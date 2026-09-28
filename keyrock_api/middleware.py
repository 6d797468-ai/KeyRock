"""Middleware API : rate limiting, en-têtes de sécurité, logs structurés.

Règle absolue : aucun token généré n'apparaît jamais dans les logs.
Seules des métadonnées (longueur, entropie, taille d'alphabet, durée,
identifiant de requête) sont journalisées.
"""

from __future__ import annotations

import json
import logging
import sys
import time
import uuid
from collections import defaultdict, deque
from collections.abc import Awaitable, Callable
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
    """Rate limiting en mémoire (fenêtre glissante), par IP.

    Aucun état n'est persisté sur disque : compteur volatile uniquement.
    """

    def __init__(self, app: Any, max_requetes: int = 60, fenetre_secondes: int = 60) -> None:
        super().__init__(app)
        self.max_requetes = max(1, max_requetes)
        self.fenetre_secondes = max(1, fenetre_secondes)
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def _autorise(self, cle: str) -> tuple[bool, int]:
        maintenant = time.monotonic()
        horodatages = self._hits[cle]
        while horodatages and horodatages[0] <= maintenant - self.fenetre_secondes:
            horodatages.popleft()
        if len(horodatages) >= self.max_requetes:
            restant = int(self.fenetre_secondes - (maintenant - horodatages[0]))
            return False, max(restant, 1)
        horodatages.append(maintenant)
        return True, 0

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        client = request.client.host if request.client else "inconnu"
        autorise, retry_apres = self._autorise(client)
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
        reponse.headers["X-RateLimit-Remaining"] = str(
            max(0, self.max_requetes - len(self._hits[client]))
        )
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
