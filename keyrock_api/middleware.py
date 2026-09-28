"""Middleware API : rate limiting, en-têtes de sécurité, logs structurés.

Règle absolue : aucun token généré n'apparaît jamais dans les logs.
Seules des métadonnées (longueur, entropie, taille d'alphabet, durée,
identifiant de requête) sont journalisées.
"""

from __future__ import annotations

import ipaddress
import json
import logging
import sys
import threading
import time
import uuid
from collections import deque
from collections.abc import Awaitable, Callable, Iterable
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

__all__ = [
    "CORRELATION_ID_HEADER",
    "JournalisationMetadonnees",
    "RateLimiterMiddleware",
    "SecurityHeadersMiddleware",
    "configure_logging",
    "gerer_erreurs",
    "obtenir_request_id",
    "parse_reseau",
    "resoudre_ip_client",
]

CORRELATION_ID_HEADER = "X-Request-ID"

_CHAMPS_RESERVES = frozenset(
    set(vars(logging.LogRecord("", 0, "", 0, "", None, None))) | {"message", "asctime", "taskName"}
)

HEADERS_SECURITE: dict[str, str] = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "X-XSS-Protection": "0",
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
    "Permissions-Policy": "geolocation=(), microphone=(), camera=()",
    "Cache-Control": "no-store, no-cache, must-revalidate, private",
    "Pragma": "no-cache",
}

logger = logging.getLogger("keyrock.api")


def parse_reseau(brut: str) -> tuple[str, ...]:
    """Normalise une liste de réseaux de confiance (CIDR ou IP seule).

    Toute entrée invalide est ignorée silencieusement : un réseau mal saisi
    doit dégrader vers « aucune confiance », jamais vers « tout est fiable ».
    """
    valides: list[str] = []
    for morceau in brut.replace(";", ",").split(","):
        candidat = morceau.strip()
        if not candidat:
            continue
        try:
            valides.append(str(ipaddress.ip_network(candidat, strict=False)))
        except ValueError:
            logger.warning("reseau_de_confiance_invalide_ignore", extra={"valeur": candidat})
    return tuple(valides)


def resoudre_ip_client(request: Request, proxies: Iterable[str]) -> str | None:
    """Adresse du client réel, ou `None` si elle ne peut pas être établie.

    Fonction utilitaire exposée pour les tests : la logique elle-même vit
    dans `RateLimiterMiddleware._adresse`.
    """
    limite = RateLimiterMiddleware.__new__(RateLimiterMiddleware)
    limite._proxies = tuple(ipaddress.ip_network(c, strict=False) for c in proxies)
    return limite._adresse(request)


def obtenir_request_id(request: Request) -> str:
    """Retourne l'identifiant de corrélation de la requête courante."""
    return getattr(request.state, "request_id", "") or str(uuid.uuid4())


class JournalisationMetadonnees(logging.Formatter):
    """Formatter de repli : fusionne les champs `extra` dans un rendu JSON lisible.

    Seules les métadonnées structurées sont rendues. L'application ne
    transmet jamais un token via `extra`.
    """

    def format(self, record: logging.LogRecord) -> str:
        champs = {
            cle: valeur
            for cle, valeur in vars(record).items()
            if cle not in _CHAMPS_RESERVES and not cle.startswith("_")
        }
        entree: dict[str, Any] = {
            "niveau": record.levelname,
            "logger": record.name,
            "evenement": record.getMessage(),
        }
        if record.exc_info:
            entree["type_exception"] = record.exc_info[0].__name__ if record.exc_info[0] else None
        entree.update(champs)
        return json.dumps(entree, ensure_ascii=False, default=str)


def configure_logging(niveau: str = "INFO") -> None:
    """Configure un logging structuré JSON si structlog est disponible.

    Repli sur le logging stdlib si structlog n'est pas installé.
    Les tokens ne sont jamais passés aux loggers par l'application.
    """
    racine = logging.getLogger()
    racine.setLevel(getattr(logging, niveau.upper(), logging.INFO))
    try:
        import structlog
    except ImportError:  # pragma: no cover - dépend de l'environnement
        gestionnaire = logging.StreamHandler(sys.stderr)
        gestionnaire.setFormatter(JournalisationMetadonnees())
        racine.handlers = [gestionnaire]
        return

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, niveau.upper(), logging.INFO)
        ),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


class RateLimiterMiddleware(BaseHTTPMiddleware):
    """Rate limiting en mémoire (fenêtre glissante), par IP réelle.

    Trois propriétés que cette classe garantit explicitement :

    1. **L'adresse utilisée est la socket, pas un en-têtearbitrable.** Un
       `X-Forwarded-For` n'est lu que si le pair est un reverse proxy
       explicitement déclaré. Aucune confiance n'est accordée par défaut.
    2. **L'empreinte mémoire est bornée.** Un attaquant ne peut pas créer une
       entrée par requête en faisant tourner des adresses.
    3. **Jamais de contournement par repli.** Un client dont l'adresse n'est pas
       déterminable est refusé (403). Un client réel dont l'en-tête a été
       écarté retombe sur le pair, ce qui le **mutualise** volontairement : il
       reste soumis au quota, mais ne peut pas obtenir un quota illimité en
       forgeant des en-têtes.

    Aucun état n'est persisté sur disque : compteur volatile uniquement.
    """

    def __init__(
        self,
        app: Any,
        max_requetes: int = 60,
        fenetre_secondes: int = 60,
        proxies_de_confiance: Iterable[str] = (),
        max_clients_suivis: int = 10_000,
    ) -> None:
        super().__init__(app)
        self.max_requetes = max(1, max_requetes)
        self.fenetre_secondes = max(1, fenetre_secondes)
        self.max_clients_suivis = max(16, max_clients_suivis)
        self._proxies = tuple(ipaddress.ip_network(c, strict=False) for c in proxies_de_confiance)
        # dict et non defaultdict : `get` ne crée pas d'entrée, donc une
        # simple lecture ne consomme pas de mémoire.
        self._hits: dict[str, deque[float]] = {}
        self._dernier_acces: dict[str, float] = {}
        self._verrou = threading.Lock()

    # -- Résolution de l'adresse -----------------------------------------
    def _est_proxy_de_confiance(self, adresse: str) -> bool:
        try:
            ip = ipaddress.ip_address(adresse)
        except ValueError:
            return False
        return any(ip in reseau for reseau in self._proxies)

    def _adresse(self, request: Request) -> str | None:
        """Adresse du client réel, ou `None` si elle ne peut pas être établie.

        Trois cas, du plus fiable au plus dégradé :

        * pair **non** déclaré proxy → le pair EST le client, l'en-tête est ignoré ;
        * pair déclaré proxy et `X-Forwarded-For` exploitable → premier
          encounteré en remontant depuis la droite, ce qui neutralise les
          entrées prépendues par un attaquant ;
        * pair déclaré proxy sans en-tête exploitable → on retombe sur le pair.

        Le dernier cas est un repli **sûr**, pas un trou : tout le trafic ainsi
        attribué au pair partage un seul seau, donc reste soumis au quota. Il se
        produit quand Traefik est joint via un port publié (trafic « hairpin » :
        le pair est alors la passerelle Docker) ou quand l'API est publiee
        directement. Refuser (403) casserait le trafic légitime sans apporter de
        sécurité supplémentaire.
        """
        pair = request.client.host if request.client else None
        if not pair:
            return None
        if not self._est_proxy_de_confiance(pair):
            return pair
        brut = request.headers.get("x-forwarded-for", "")
        for candidat in reversed([part.strip() for part in brut.split(",") if part.strip()]):
            if not self._est_proxy_de_confiance(candidat):
                return candidat
        return pair

    # -- Comptage ----------------------------------------------------------
    def _purger(self, maintenant: float) -> None:
        """Retire les entrées sans requête ni expirées. Appelé sous verrou."""
        expire = maintenant - self.fenetre_secondes
        for cle in [
            c
            for c, horodatages in self._hits.items()
            if not horodatages or horodatages[-1] <= expire
        ]:
            del self._hits[cle]
            self._dernier_acces.pop(cle, None)
        if len(self._hits) < self.max_clients_suivis:
            return
        # Bornitude mémoire : éviction des entrées les moins récemment
        # utilisées. Ce n'est PAS une frontière de sécurité (un attaquant
        # peut encore évincer un client légitime) — c'est un garde-fou
        # contre l'épuisement de la mémoire.
        cibles = sorted(self._dernier_acces, key=self._dernier_acces.get)  # type: ignore[arg-type]
        for cle in cibles[: len(self._hits) - self.max_clients_suivis + 1]:
            self._hits.pop(cle, None)
            self._dernier_acces.pop(cle, None)

    def _autorise(self, cle: str) -> tuple[bool, int, int]:
        """Retourne (autorisé, retry_apres, restantes). Appelé sous verrou."""
        maintenant = time.monotonic()
        self._purger(maintenant)
        horodatages = self._hits.get(cle)
        if horodatages is None:
            horodatages = deque()
            self._hits[cle] = horodatages
        expire = maintenant - self.fenetre_secondes
        while horodatages and horodatages[0] <= expire:
            horodatages.popleft()
        if len(horodatages) >= self.max_requetes:
            restant = int(self.fenetre_secondes - (maintenant - horodatages[0]))
            self._dernier_acces[cle] = maintenant
            return False, max(restant, 1), 0
        horodatages.append(maintenant)
        self._dernier_acces[cle] = maintenant
        # Solde reflecti l'etat APRES la requete courante, comme attendu par
        # les en-tetes de quota usuels.
        return True, 0, max(0, self.max_requetes - len(horodatages))

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        client = self._adresse(request)
        if client is None:
            # Fail-closed : ni pair ni en-tête exploitable. On `return` et non
            # `raise` : un middleware s'exécute hors de la chaîne d'exception
            # handlers, un `raise` deviendrait un 500.
            logger.warning("adresse_client_indeterminee", extra={"path": request.url.path})
            return JSONResponse(
                status_code=403,
                content={
                    "error": {
                        "code": "ADRESSE_INDETERMINEE",
                        "message": ("Adresse client non déterminable. Requête refusée."),
                    }
                },
            )
        with self._verrou:
            autorise, retry_apres, restantes = self._autorise(client)
        if not autorise:
            logger.warning(
                "rate_limit_exceeded", extra={"client": client, "path": request.url.path}
            )
            return JSONResponse(
                status_code=429,
                content={
                    "error": {
                        "code": "RATE_LIMIT_EXCEEDED",
                        "message": ("Trop de requêtes. Réessayez plus tard."),
                    }
                },
                headers={"Retry-After": str(retry_apres)},
            )
        reponse = await call_next(request)
        reponse.headers["X-RateLimit-Limit"] = str(self.max_requetes)
        reponse.headers["X-RateLimit-Remaining"] = str(restantes)
        return reponse


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Injecte les en-têtes de sécurité et l'identifiant de corrélation."""

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request_id = request.headers.get(CORRELATION_ID_HEADER) or str(uuid.uuid4())
        request.state.request_id = request_id
        debut = time.perf_counter()
        try:
            reponse = await call_next(request)
        except Exception:
            logger.exception(
                "requete_en_erreur",
                extra={
                    "request_id": request_id,
                    "path": request.url.path,
                    "methode": request.method,
                },
            )
            raise
        duree_ms = round((time.perf_counter() - debut) * 1000, 2)
        for cle, valeur in HEADERS_SECURITE.items():
            reponse.headers[cle] = valeur
        reponse.headers[CORRELATION_ID_HEADER] = request_id
        # Journalisation des métadonnées uniquement — jamais du corps de réponse.
        logger.info(
            "requete",
            extra={
                "request_id": request_id,
                "methode": request.method,
                "chemin": request.url.path,
                "statut": reponse.status_code,
                "duree_ms": duree_ms,
            },
        )
        return reponse


async def gerer_erreurs(request: Request, exc: Exception) -> JSONResponse:
    """Handler global : JSON standardisé, sans stack trace exposée."""
    request_id = obtenir_request_id(request)
    code = "ERREUR_INTERNE"
    message = "Une erreur interne est survenue."
    statut = 500
    if isinstance(exc, ValueError):
        code = "REQUETE_INVALIDE"
        message = str(exc)
        statut = 422
    logger.error(
        "exception_non_geree",
        extra={
            "request_id": request_id,
            "type_exception": type(exc).__name__,
            "chemin": request.url.path,
        },
    )
    return JSONResponse(
        status_code=statut,
        content={
            "error": {"code": code, "message": message},
            "request_id": request_id,
        },
    )
