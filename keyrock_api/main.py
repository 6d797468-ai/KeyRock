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
)
from keyrock_api.models import (
    ENTROPIE_MIN,
    LONGEUR_MAX,
    LONGEUR_MIN,
    ErrorResponse,
    GenerateRequest,
    GenerateResponse,
    HealthResponse,
    MetaResponse,
    alphabet_pour,
)
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
    application.add_middleware(RateLimiterMiddleware, max_requetes=settings.rate_limit_per_minute)
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

    @application.get("/health", response_model=HealthResponse, tags=["système"])
    async def health() -> HealthResponse:
        """Sonde de vivacité pour Docker HEALTHCHECK et Traefik."""
        return HealthResponse(status="ok", version=VERSION)

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
            # Aucune fuite de token : l'erreur ne contient que des métadonnées.
            logger.warning(
                "generation_refusee",
                extra={
                    "request_id": obtenir_request_id(request),
                    "longueur": requete.longueur,
                    "raison": "entropie_insuffisante",
                },
            )
            return JSONResponse(
                status_code=422,
                content={
                    "error": {"code": "ENTROPIE_INSUFFISANTE", "message": str(exc)},
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
            "code": "REQUETE_INVALIDE",
            "message": _message_sanitisee(item),
            "champ": ".".join(str(partie) for partie in item.get("loc", ())),
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


def _message_sanitisee(erreur: dict[str, Any]) -> str:
    """Ne conserve que les messages de nos propres validateurs.

    Les messages natifs de Pydantic (types, chemins de classes) sont
    remplacés par un texte générique pour ne rien divulguer.
    """
    type_erreur = erreur.get("type", "")
    types_natifs = {
        "value_error",
        "too_short",
        "too_long",
        "greater_than_equal",
        "less_than_equal",
    }
    if type_erreur in types_natifs:
        return str(erreur.get("msg", "Paramètres invalides.")).removeprefix("Value error, ")
    return "Paramètres de requête invalides."


app = creer_application()
