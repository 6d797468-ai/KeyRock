"""Tests de l'API REST KeyRock (TestClient FastAPI)."""

from __future__ import annotations

import string

import pytest
from fastapi.testclient import TestClient

from keyrock_api.main import creer_application
from keyrock_core.config import get_settings
from keyrock_core.generator import LONGEUR_MAX, LONGEUR_MIN


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(creer_application(), raise_server_exceptions=False)


class TestSante:
    def test_health(self, client: TestClient) -> None:
        reponse = client.get("/health")
        assert reponse.status_code == 200
        assert reponse.json()["status"] == "ok"

    def test_meta_expose_les_bornes(self, client: TestClient) -> None:
        corps = client.get("/api/v1/meta").json()
        assert corps["longueur_min"] == LONGEUR_MIN
        assert corps["longueur_max"] == LONGEUR_MAX
        assert corps["entropie_min"] == 80


class TestGenerate:
    def test_generation_par_defaut(self, client: TestClient) -> None:
        reponse = client.post("/api/v1/generate", json={})
        assert reponse.status_code == 200
        corps = reponse.json()
        assert len(corps["token1"]) == 32
        assert len(corps["token2"]) == 32
        assert corps["token1"] != corps["token2"]
        assert corps["entropie_bits"] >= 80
        assert corps["alphabet"] == len(
            string.ascii_uppercase + string.ascii_lowercase + string.digits + string.punctuation
        )

    def test_parametres_explicites(self, client: TestClient) -> None:
        reponse = client.post(
            "/api/v1/generate",
            json={
                "longueur": 64,
                "majuscules": True,
                "minuscules": True,
                "chiffres": True,
                "symboles": True,
            },
        )
        assert reponse.status_code == 200
        assert len(reponse.json()["token1"]) == 64

    def test_chiffres_seulement_avec_suffisance(self, client: TestClient) -> None:
        reponse = client.post(
            "/api/v1/generate",
            json={
                "longueur": 32,
                "majuscules": False,
                "minuscules": False,
                "chiffres": True,
                "symboles": False,
            },
        )
        assert reponse.status_code == 200
        assert set(reponse.json()["token1"]) <= set(string.digits)

    def test_nombre_personnalise(self, client: TestClient) -> None:
        reponse = client.post("/api/v1/generate", json={"nombre": 3})
        assert reponse.status_code == 200
        corps = reponse.json()
        assert corps["token2"] is not None
        assert corps["token1"] != corps["token2"]

    def test_entete_no_store(self, client: TestClient) -> None:
        entetes = client.post("/api/v1/generate", json={}).headers
        assert "no-store" in entetes["Cache-Control"]

    def test_en_tetes_securite(self, client: TestClient) -> None:
        entetes = client.get("/health").headers
        assert entetes["X-Content-Type-Options"] == "nosniff"
        assert entetes["X-Frame-Options"] == "DENY"
        assert entetes["Referrer-Policy"] == "no-referrer"
        assert "X-Request-ID" in entetes


class TestValidation:
    @pytest.mark.parametrize("longueur", [LONGEUR_MIN - 1, 0, -5, LONGEUR_MAX + 1])
    def test_longueur_hors_bornes(self, client: TestClient, longueur: int) -> None:
        reponse = client.post("/api/v1/generate", json={"longueur": longueur})
        assert reponse.status_code == 422
        assert reponse.json()["error"]["code"] in {"REQUETE_INVALIDE", "ENTROPIE_INSUFFISANTE"}

    def test_alphabet_vide_rejete(self, client: TestClient) -> None:
        reponse = client.post(
            "/api/v1/generate",
            json={
                "longueur": 32,
                "majuscules": False,
                "minuscules": False,
                "chiffres": False,
                "symboles": False,
            },
        )
        assert reponse.status_code == 422
        assert "type de caractère" in reponse.json()["error"]["message"]

    def test_entropie_insuffisante_rejetee(self, client: TestClient) -> None:
        reponse = client.post(
            "/api/v1/generate",
            json={
                "longueur": 8,
                "majuscules": False,
                "minuscules": False,
                "chiffres": True,
                "symboles": False,
            },
        )
        assert reponse.status_code == 422
        assert reponse.json()["error"]["code"] in {"REQUETE_INVALIDE", "ENTROPIE_INSUFFISANTE"}

    def test_champ_inconnu_rejete(self, client: TestClient) -> None:
        reponse = client.post("/api/v1/generate", json={"pirate": True})
        assert reponse.status_code == 422

    def test_type_incorrect_rejete(self, client: TestClient) -> None:
        reponse = client.post("/api/v1/generate", json={"longueur": "beaucoup"})
        assert reponse.status_code == 422
        assert reponse.json()["error"]["code"] == "REQUETE_INVALIDE"

    def test_nombre_hors_bornes(self, client: TestClient) -> None:
        assert client.post("/api/v1/generate", json={"nombre": 0}).status_code == 422
        assert client.post("/api/v1/generate", json={"nombre": 99}).status_code == 422

    def test_aucune_stack_trace_exposee(self, client: TestClient) -> None:
        reponse = client.post(
            "/api/v1/generate",
            json={
                "longueur": 1,
                "majuscules": False,
                "minuscules": False,
                "chiffres": False,
                "symboles": False,
            },
        )
        corps = reponse.text
        assert reponse.status_code == 422
        assert "Traceback" not in corps
        assert "keyrock_core" not in corps


class TestRateLimiter:
    def test_quota_depasse(self) -> None:
        application = creer_application()
        application.user_middleware.clear()
        from keyrock_api.middleware import RateLimiterMiddleware

        application.add_middleware(RateLimiterMiddleware, max_requetes=3, fenetre_secondes=60)
        client = TestClient(application, raise_server_exceptions=False)
        codes = [client.get("/health").status_code for _ in range(5)]
        assert codes[:3] == [200, 200, 200]
        assert codes[3:] == [429, 429]
        assert "Retry-After" in client.get("/health").headers

    def test_la_limite_suivant_une_variable_d_environnement(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """KEYROCK_RATE_LIMIT_PER_MINUTE doit réellement changer la limite.

        Sans ce test, une variable d'env mal câblée laisse le middleware sur
        sa valeur par défaut sans que rien ne le signale.
        """
        monkeypatch.setenv("KEYROCK_RATE_LIMIT_PER_MINUTE", "4")
        get_settings.cache_clear()
        application = creer_application()
        application.user_middleware.clear()
        from keyrock_api.middleware import RateLimiterMiddleware

        application.add_middleware(
            RateLimiterMiddleware, max_requetes=get_settings().rate_limit_per_minute
        )
        client = TestClient(application, raise_server_exceptions=False)
        codes = [client.get("/health").status_code for _ in range(5)]
        assert codes == [200, 200, 200, 200, 429]
        get_settings.cache_clear()


class TestZeroPersistance:
    def test_aucun_token_dans_les_logs(
        self, client: TestClient, caplog: pytest.LogCaptureFixture
    ) -> None:
        import logging

        with caplog.at_level(logging.DEBUG):
            reponse = client.post("/api/v1/generate", json={"longueur": 48})
        token = reponse.json()["token1"]
        assert token not in caplog.text
        for enregistrement in caplog.records:
            assert token not in str(enregistrement.__dict__)
