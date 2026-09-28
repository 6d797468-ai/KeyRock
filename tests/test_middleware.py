"""Tests du middleware API (sécurité, rate limiting, logs structurés)."""

from __future__ import annotations

import asyncio
import json
import logging
import sys
import time
from typing import Any

import pytest
from fastapi.testclient import TestClient
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import PlainTextResponse
from starlette.routing import Route

from keyrock_api.middleware import (
    HEADERS_SECURITE,
    JournalisationMetadonnees,
    RateLimiterMiddleware,
    SecurityHeadersMiddleware,
    configure_logging,
    parse_reseau,
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


class TestContournementParEnTeteProxy:
    """Régression du P0 : `X-Forwarded-For` ne doit jamais être pris pour
    l'adresse du client tant que le pair n'est pas un proxy déclaré."""

    def test_xff_ignore_quand_aucun_proxy_nest_declare(self) -> None:
        limiteur = RateLimiterMiddleware(creer_app(), max_requetes=1, fenetre_secondes=60)
        faux = Request(
            {
                "type": "http",
                "method": "GET",
                "path": "/t",
                "headers": [(b"x-forwarded-for", b"10.0.0.7")],
                "client": ("203.0.113.9", 4321),
            }
        )
        # Le pair est le client : l'en-tete est ignore, l'adresse socket gagne.
        assert limiteur._adresse(faux) == "203.0.113.9"

    def test_quota_ne_depend_pas_du_xff(self) -> None:
        client = client_avec(Middleware(RateLimiterMiddleware, max_requetes=3, fenetre_secondes=60))
        codes = [
            client.get("/t", headers={"X-Forwarded-For": f"10.0.{i}.{i}"}).status_code
            for i in range(8)
        ]
        assert codes.count(200) == 3
        assert codes.count(429) == 5

    def test_proxy_declare_lit_le_xff(self) -> None:
        limiteur = RateLimiterMiddleware(
            creer_app(), max_requetes=5, proxies_de_confiance=("172.20.0.0/16",)
        )
        faux = Request(
            {
                "type": "http",
                "method": "GET",
                "path": "/t",
                "headers": [(b"x-forwarded-for", b"203.0.113.5")],
                "client": ("172.20.0.3", 40000),
            }
        )
        assert limiteur._adresse(faux) == "203.0.113.5"

    def test_entrees_prependues_par_un_attaquant_sont_ignorees(self) -> None:
        """L'attaquant qui prepend des adresses ne doit pas passer devant."""
        limiteur = RateLimiterMiddleware(
            creer_app(), max_requetes=5, proxies_de_confiance=("172.20.0.0/16",)
        )
        faux = Request(
            {
                "type": "http",
                "method": "GET",
                "path": "/t",
                "headers": [(b"x-forwarded-for", b"10.66.66.66, 203.0.113.5, 172.20.0.3")],
                "client": ("172.20.0.9", 40000),
            }
        )
        # Parcours depuis la droite : le premier non-proxy est le vrai client.
        assert limiteur._adresse(faux) == "203.0.113.5"

    def test_proxy_sans_xff_replique_sur_le_pair(self) -> None:
        """Repli sûr : tout le trafic tombe dans un seul seau, donc reste quota."""
        limiteur = RateLimiterMiddleware(
            creer_app(), max_requetes=5, proxies_de_confiance=("172.20.0.0/16",)
        )
        faux = Request(
            {
                "type": "http",
                "method": "GET",
                "path": "/t",
                "headers": [],
                "client": ("172.20.0.3", 40000),
            }
        )
        assert limiteur._adresse(faux) == "172.20.0.3"

    def test_absence_totale_de_client_donne_403_pas_500(self) -> None:
        """Fail-closed sur le seul cas réellement indéterminable.

        Appelé directement sur `dispatch` : un `TestClient` présente toujours un
        pair, la branche ne serait pas atteignable par HTTP.
        """
        limiteur = RateLimiterMiddleware(creer_app(), max_requetes=5)
        faux = Request(
            {"type": "http", "method": "GET", "path": "/t", "headers": [], "client": None}
        )

        async def jamais_appele(_request: Any) -> PlainTextResponse:
            raise AssertionError("la requete ne doit pas atteindre l'application")

        reponse = asyncio.run(limiteur.dispatch(faux, jamais_appele))
        assert reponse.status_code == 403
        assert json.loads(reponse.body)["error"]["code"] == "ADRESSE_INDETERMINEE"


class TestBornitudeMemoire:
    def test_empreinte_bornee(self) -> None:
        limiteur = RateLimiterMiddleware(creer_app(), max_requetes=5, max_clients_suivis=16)
        for i in range(2000):
            limiteur._autorise(f"10.0.{i // 256}.{i % 256}")
        assert len(limiteur._hits) <= 16

    def test_lecture_ne_cree_pas_dentree(self) -> None:
        limiteur = RateLimiterMiddleware(creer_app(), max_requetes=5)
        limiteur._autorise("connue")
        avant = dict(limiteur._hits)
        limiteur._hits.get("jamais-vue")
        assert limiteur._hits == avant


class TestParseReseau:
    def test_normalise_les_cidr(self) -> None:
        assert parse_reseau("172.20.0.0/16") == ("172.20.0.0/16",)

    def test_accepte_ip_seule(self) -> None:
        assert parse_reseau("10.1.2.3") == ("10.1.2.3/32",)

    def test_ignore_les_entrees_invalides(self) -> None:
        assert parse_reseau("172.20.0.0/16, pas-un-reseau, 10.0.0.1") == (
            "172.20.0.0/16",
            "10.0.0.1/32",
        )

    def test_chaine_vide_ne_confie_a_personne(self) -> None:
        assert parse_reseau("") == ()


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
