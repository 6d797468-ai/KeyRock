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

    def test_meta_publie_le_minimum_effectif_par_alphabet(self, client: TestClient) -> None:
        corps = client.get("/api/v1/meta").json()
        table = corps["longueur_min_par_alphabet"]
        assert table["maj+min+num+sym"]["longueur_min"] == 13
        assert table["maj+min+num"]["longueur_min"] == 14
        assert table["maj+min"]["longueur_min"] == 15
        assert table["num"]["longueur_min"] == 25

    def test_minimum_publie_est_toujours_accepté(self, client: TestClient) -> None:
        """Boucle fermée sur le contrat : ce que `meta` annonce, `generate` l'accepte.

        C'est l'invariant violé avant correction : `meta` annonçait 8, `generate`
        refusait 8. Le test lit le contrat puis l'exerce, pour que le contrat ne
        puisse plus mentir en silence.
        """
        table = client.get("/api/v1/meta").json()["longueur_min_par_alphabet"]
        drapeaux = {
            "maj+min+num+sym": (True, True, True, True),
            "maj+min+num": (True, True, True, False),
            "maj+min": (True, True, False, False),
            "num": (False, False, True, False),
        }
        for libelle, (maj, min_, chiffres, symboles) in drapeaux.items():
            reponse = client.post(
                "/api/v1/generate",
                json={
                    "longueur": table[libelle]["longueur_min"],
                    "majuscules": maj,
                    "minuscules": min_,
                    "chiffres": chiffres,
                    "symboles": symboles,
                },
            )
            assert reponse.status_code == 200, f"{libelle} : {reponse.text}"
            assert reponse.json()["entropie_bits"] >= 80


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
        """Hors bornes = code propre, et un message dans la langue de l'API.

        Régression : le message venait directement de Pydantic, en anglais,
        au milieu d'un corps de réponse francophone.
        """
        reponse = client.post("/api/v1/generate", json={"longueur": longueur})
        assert reponse.status_code == 422
        erreur = reponse.json()["error"]
        assert erreur["code"] == "LONGUEUR_HORS_BORNES"
        assert erreur["champ"] == "body.longueur"
        assert f"entre {LONGEUR_MIN} et {LONGEUR_MAX}" in erreur["message"]

    @pytest.mark.parametrize(
        ("corps", "code_attendu"),
        [
            ({"longueur": 8}, "ENTROPIE_INSUFFISANTE"),
            (
                {"longueur": 24, "majuscules": False, "minuscules": False, "symboles": False},
                "ENTROPIE_INSUFFISANTE",
            ),
            (
                {
                    "majuscules": False,
                    "minuscules": False,
                    "chiffres": False,
                    "symboles": False,
                },
                "ALPHABET_VIDE",
            ),
        ],
    )
    def test_echecs_distinguets(
        self, client: TestClient, corps: dict[str, object], code_attendu: str
    ) -> None:
        """Bornes, entropie et alphabet vide sont trois échecs, trois codes.

        Les confondre envoie le client vers la mauvaise correction :
        `LONGUEUR_HORS_BORNES` et `ENTROPIE_INSUFFISANTE` ne se réparent pas
        de la même façon.
        """
        reponse = client.post("/api/v1/generate", json=corps)
        assert reponse.status_code == 422
        assert reponse.json()["error"]["code"] == code_attendu

    def test_erreur_entropie_nomme_la_longueur_requise(self, client: TestClient) -> None:
        """Le message doit porter la correction, pas seulement le constat."""
        reponse = client.post("/api/v1/generate", json={"longueur": 8})
        message = reponse.json()["error"]["message"]
        assert "13 caractères" in message

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
