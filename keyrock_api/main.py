"""Application FastAPI KeyRock — génération de tokens via REST.

Principe « Zéro Persistance » : aucun token n'est journalisé, mis en cache
ou écrit sur disque, y compris dans les erreurs.
"""

from __future__ import annotations

import logging
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from keyrock_api.middleware import (
    RateLimiterMiddleware,
    SecurityHeadersMiddleware,
    configure_logging,
    gerer_erreurs,
    obtenir_request_id,
    parse_reseau,
)
from keyrock_api.models import (
    ENTROPIE_MIN,
    LONGEUR_MAX,
    LONGEUR_MIN,
    AlphabetMinimum,
    ErrorResponse,
    GenerateRequest,
    GenerateResponse,
    HealthResponse,
    MetaResponse,
    SanteControle,
    alphabet_pour,
)
from keyrock_api.sante import verifier_sante
from keyrock_core.config import get_settings
from keyrock_core.generator import CoreGenerator

__all__ = ["VERSION", "app", "creer_application"]

VERSION = "1.0.0"

logger = logging.getLogger("keyrock.api")


@asynccontextmanager
async def cycle_de_vie(application: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(settings.log_level)
    logger.info(
        "demarrage_api",
        extra={"version": VERSION, "hote": settings.api_host, "port": settings.api_port},
    )
    yield
    logger.info("arret_api", extra={"version": VERSION})


def creer_application() -> FastAPI:
    settings = get_settings()

    application = FastAPI(
        title="KeyRock API",
        version=VERSION,
        description=(
            "Générateur de clés & tokens cryptographiques (CSPRNG). "
            "Zéro persistance : aucun token n'est journalisé ni stocké."
        ),
        lifespan=cycle_de_vie,
        docs_url="/docs",
        redoc_url=None,
    )

    # L'ordre compte : SecurityHeaders est le plus externe (ajoute les
    # en-têtes à toutes les réponses, y compris celles du rate limiter).
    application.add_middleware(
        RateLimiterMiddleware,
        max_requetes=settings.rate_limit_per_minute,
        proxies_de_confiance=parse_reseau(settings.trusted_proxies),
        max_clients_suivis=settings.max_tracked_clients,
    )
    application.add_middleware(SecurityHeadersMiddleware)
    if settings.cors_allow_origins:
        application.add_middleware(
            CORSMiddleware,
            allow_origins=list(settings.cors_allow_origins),
            allow_methods=["GET", "POST"],
            allow_headers=["Content-Type", "X-Request-ID"],
            allow_credentials=False,
        )

    application.add_exception_handler(ValueError, gerer_erreurs)
    application.add_exception_handler(Exception, gerer_erreurs)
    application.add_exception_handler(RequestValidationError, _valider_entree)

    @application.get(
        "/health",
        response_model=HealthResponse,
        tags=["système"],
        responses={503: {"model": HealthResponse, "description": "Configuration bloquante"}},
    )
    async def health() -> JSONResponse | HealthResponse:
        """Sonde de vivacité : vérifie que la configuration permet de servir.

        Répond 503 si un contrôle bloquant échoue, pour que le HEALTHCHECK
        Docker et Traefik Cessent de considérer sain un service qui ne peut
        rien produire. Un avertissement reste en 200 : le traiter comme
        bloquant provoquerait une boucle de redémarrage.
        """
        rapport = verifier_sante(get_settings())
        reponse = HealthResponse(
            status=rapport.statut,
            version=VERSION,
            controles=[
                SanteControle(
                    nom=controle.nom,
                    ok=controle.ok,
                    bloquant=controle.bloquant,
                    detail=controle.detail,
                )
                for controle in rapport.controles
            ],
        )
        if not rapport.disponible:
            logger.error("sante_bloquante", extra={"controles": rapport.statut})
            return JSONResponse(status_code=503, content=reponse.model_dump())
        if rapport.statut == "degraded":
            logger.warning("sante_avertissement")
        return reponse

    @application.get("/api/v1/meta", response_model=MetaResponse, tags=["système"])
    async def meta() -> MetaResponse:
        """Métadonnées de l'API (aucune donnée sensible)."""
        return MetaResponse(
            nom="KeyRock",
            version=VERSION,
            description="Générateur de tokens cryptographiques — usage unique Vextra Agency",
            longueur_min=LONGEUR_MIN,
            longueur_max=LONGEUR_MAX,
            entropie_min=ENTROPIE_MIN,
            longueur_min_par_alphabet={
                libelle: AlphabetMinimum(**donnees)
                for libelle, donnees in CoreGenerator.decrire_alphabets(ENTROPIE_MIN).items()
            },
        )

    @application.post(
        "/api/v1/generate",
        response_model=GenerateResponse,
        tags=["génération"],
        responses={
            422: {"model": ErrorResponse, "description": "Paramètres ou entropie invalides"},
            429: {"model": ErrorResponse, "description": "Quota de requêtes dépassé"},
        },
    )
    async def generer(
        requete: GenerateRequest, request: Request, response: Response
    ) -> GenerateResponse | JSONResponse:
        """Génère `nombre` tokens independants via le CSPRNG."""
        debut = time.perf_counter()
        options = requete.vers_options()
        try:
            tokens = CoreGenerator.generer_plusieurs(
                options, nombre=requete.nombre, seuil_entropie=requete.seuil_entropie
            )
        except ValueError as exc:
            # Filet de sécurité, non atteignable par le chemin validé : le
            # modèle `GenerateRequest` a déjà appliqué les mêmes bornes et le
            # même seuil. Conservé pour qu'un relâchement futur du validateur
            # reste en échec fermé plutôt qu'en émission silencieuse. Le code
            # vient de l'exception, jamais d'une constante : c'est ce qui
            # avait produit ici un `ENTROPIE_INSUFFISANTE` codé en dur pour
            # toute erreur, longueur comprise.
            logger.warning(
                "generation_refusee",
                extra={
                    "request_id": obtenir_request_id(request),
                    "longueur": requete.longueur,
                    "raison": getattr(exc, "code", "REQUETE_INVALIDE"),
                },
            )
            return JSONResponse(
                status_code=422,
                content={
                    "error": {
                        "code": getattr(exc, "code", "REQUETE_INVALIDE"),
                        "message": str(exc),
                    },
                    "request_id": obtenir_request_id(request),
                },
            )

        entropie = CoreGenerator.calculer_entropie(options)
        taille_alphabet = len(alphabet_pour(requete))
        duree_ms = round((time.perf_counter() - debut) * 1000, 2)
        # Métadonnées uniquement : jamais les tokens.
        logger.info(
            "tokens_generes",
            extra={
                "request_id": obtenir_request_id(request),
                "nombre": requete.nombre,
                "longueur": requete.longueur,
                "entropie_bits": entropie,
                "alphabet": taille_alphabet,
                "duree_ms": duree_ms,
            },
        )

        reponse = GenerateResponse(
            token1=tokens[0],
            token2=tokens[1] if len(tokens) > 1 else None,
            longueur=requete.longueur,
            entropie_bits=entropie,
            alphabet=taille_alphabet,
        )
        response.headers["Cache-Control"] = "no-store"
        return reponse

    return application


async def _valider_entree(request: Request, exc: Exception) -> JSONResponse:
    """Handler Pydantic : 422 uniformisé, sans exposer la structure interne."""
    erreurs = exc.errors() if isinstance(exc, RequestValidationError) else []
    details = [
        {
            "code": _code_erreur(item),
            "message": _message_sanitisee(item),
            "champ": _champ(item),
        }
        for item in erreurs
    ]
    return JSONResponse(
        status_code=422,
        content={
            "error": (
                details[0]
                if len(details) == 1
                else {
                    "code": "REQUETE_INVALIDE",
                    "message": "Paramètres de requête invalides.",
                }
            ),
            "request_id": obtenir_request_id(request),
        },
    )


def _champ(erreur: dict[str, Any]) -> str | None:
    """Champ fautif, ou `None` quand l'erreur porte sur une combinaison.

    Un validateur de modèle est localisé à `body` seulement : désigner `body`
    comme champ fautif est trompeur, car aucun champ précis n'est en cause —
    c'est leur combinaison. Le client doit donc lire le message.
    """
    chemin = [str(partie) for partie in erreur.get("loc", ())]
    if len(chemin) <= 1:
        return None
    return ".".join(chemin)


def _code_erreur(erreur: dict[str, Any]) -> str:
    """Code machine lisible, propagé par nos propres validateurs.

    Pydantic conserve l'exception d'origine dans `ctx["error"` : nos classes
    d'erreur du noyau y transportent leur `code`, ce qui permet de distinguer
    « longueur hors bornes » de « entropie insuffisante » — deux échecs qui
    n'appellent pas la même correction côté client.
    """
    origine = erreur.get("ctx", {}).get("error")
    code = getattr(origine, "code", None)
    if isinstance(code, str):
        return code
    type_erreur = erreur.get("type", "")
    if type_erreur in {"greater_than_equal", "less_than_equal"}:
        return "LONGUEUR_HORS_BORNES"
    return "REQUETE_INVALIDE"


def _message_sanitisee(erreur: dict[str, Any]) -> str:
    """Ne conserve que les messages de nos propres validateurs.

    Les messages natifs de Pydantic (types, chemins de classes) sont
    remplacés par un texte générique pour ne rien divulguer — sauf pour les
    bornes de longueur, traduites ici pour que la réponse reste dans la langue
    du reste de l'API. Aucun autre type natif n'est traduit : le repli
    générique est le comportement sûr.
    """
    type_erreur = erreur.get("type", "")
    if type_erreur in {"greater_than_equal", "less_than_equal"}:
        return f"longueur doit être comprise entre {LONGEUR_MIN} et {LONGEUR_MAX}"
    if type_erreur == "value_error":
        return str(erreur.get("msg", "Paramètres invalides.")).removeprefix("Value error, ")
    return "Paramètres de requête invalides."


app = creer_application()
