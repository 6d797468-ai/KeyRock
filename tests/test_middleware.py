"""Tests du middleware API (sécurité, rate limiting, logs structurés)."""

from __future__ import annotations

import json
import logging
import sys
import time
from typing import Any

import pytest
from fastapi.testclient import TestClient
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.responses import PlainTextResponse
from starlette.routing import Route

from keyrock_api.middleware import (
    HEADERS_SECURITE,
    JournalisationMetadonnees,
    RateLimiterMiddleware,
    SecurityHeadersMiddleware,
    configure_logging,
)


async def _ok(_request: Any) -> PlainTextResponse:
    return PlainTextResponse("ok")


def creer_app(*mw: Middleware) -> Starlette:
    return Starlette(routes=[Route("/t", _ok, methods=["GET"])], middleware=list(mw))


def client_avec(*mw: Middleware) -> TestClient:
    return TestClient(creer_app(*mw), raise_server_exceptions=False)


class TestEnTetesSecurite:
    def test_tous_les_entetes_sont_presents(self) -> None:
        client = client_avec(Middleware(SecurityHeadersMiddleware))
        entetes = client.get("/t").headers
        for cle in HEADERS_SECURITE:
            assert entetes[cle] == HEADERS_SECURITE[cle], cle

    def test_id_de_correlation_genere(self) -> None:
        client = client_avec(Middleware(SecurityHeadersMiddleware))
        assert client.get("/t").headers["X-Request-ID"]

    def test_id_de_correlation_propage(self) -> None:
        client = client_avec(Middleware(SecurityHeadersMiddleware))
        reponse = client.get("/t", headers={"X-Request-ID": "trace-42"})
        assert reponse.headers["X-Request-ID"] == "trace-42"


class TestRateLimiter:
    def test_entetes_de_quota(self) -> None:
        client = client_avec(Middleware(RateLimiterMiddleware, max_requetes=5, fenetre_secondes=60))
        entetes = client.get("/t").headers
        assert entetes["X-RateLimit-Limit"] == "5"
        assert entetes["X-RateLimit-Remaining"] == "4"

    def test_retry_apres_renseigne(self) -> None:
        client = client_avec(Middleware(RateLimiterMiddleware, max_requetes=1, fenetre_secondes=30))
        assert client.get("/t").status_code == 200
        reponse = client.get("/t")
        assert reponse.status_code == 429
        assert 1 <= int(reponse.headers["Retry-After"]) <= 30

    def test_fenetre_glissante(self) -> None:
        limiteur = RateLimiterMiddleware(creer_app(), max_requetes=2, fenetre_secondes=1)
        assert limiteur._autorise("ip")[0] is True
        assert limiteur._autorise("ip")[0] is True
        assert limiteur._autorise("ip")[0] is False
        time.sleep(1.05)
        assert limiteur._autorise("ip")[0] is True

    def test_cles_independantes_par_ip(self) -> None:
        limiteur = RateLimiterMiddleware(creer_app(), max_requetes=1, fenetre_secondes=60)
        assert limiteur._autorise("a")[0] is True
        assert limiteur._autorise("b")[0] is True
        assert limiteur._autorise("a")[0] is False

    def test_parametres_incoherents_corriges(self) -> None:
        limiteur = RateLimiterMiddleware(creer_app(), max_requetes=0, fenetre_secondes=0)
        assert limiteur.max_requetes == 1
        assert limiteur.fenetre_secondes == 1


class TestJournalisation:
    def test_formateur_agregue_les_metadonnees(self) -> None:
        enregistrement = logging.LogRecord(
            "keyrock.api", logging.INFO, "f.py", 1, "tokens", None, None
        )
        enregistrement.longueur = 32  # type: ignore[attr-defined]
        enregistrement.request_id = "abc"  # type: ignore[attr-defined]
        rendu = json.loads(JournalisationMetadonnees().format(enregistrement))
        assert rendu["evenement"] == "tokens"
        assert rendu["longueur"] == 32
        assert rendu["request_id"] == "abc"
        assert "msg" not in rendu

    def test_configure_logging_sans_structlog(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setitem(__import__("sys").modules, "structlog", None)
        assert configure_logging("DEBUG") is None
        assert logging.getLogger().level == logging.DEBUG

    def test_type_exception_non_expose(self) -> None:
        try:
            raise ValueError("secret interne")
        except ValueError:
            enregistrement = logging.LogRecord(
                "k", logging.ERROR, "f.py", 1, "boom", None, sys.exc_info()
            )
        rendu = json.loads(JournalisationMetadonnees().format(enregistrement))
        assert rendu["type_exception"] == "ValueError"
        assert "secret interne" not in json.dumps(rendu)
