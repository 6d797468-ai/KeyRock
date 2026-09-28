"""Tests des contrôles de santé : `/health` doit vérifier, pas constant."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from keyrock_api.sante import RapportSante, verifier_sante
from keyrock_core.config import KeyRockSettings


@pytest.fixture
def client() -> TestClient:
    return TestClient(_application(), raise_server_exceptions=False)


def _application() -> Any:
    from keyrock_api.main import creer_application

    return creer_application()


@contextmanager
def _client_avec(config: KeyRockSettings) -> Iterator[TestClient]:
    """Client dont `/health` lit la configuration fournie.

    `verifier_sante(get_settings())` est évalué à chaque appel, donc substituer
    `get_settings` pendant la requête suffit : le test couvre réellement la
    route, sans contourner la logique de contrôle.
    """
    with patch("keyrock_api.main.get_settings", return_value=config):
        yield TestClient(_application(), raise_server_exceptions=False)


def _controle(rapport: RapportSante, nom: str) -> Any:
    return next(controle for controle in rapport.controles if controle.nom == nom)


class TestRapportSante:
    def test_configuration_saine_est_ok(self) -> None:
        rapport = verifier_sante(KeyRockSettings())
        assert rapport.statut == "ok"
        assert rapport.disponible is True

    def test_les_controles_publies_sont_explicitement_listes(self) -> None:
        """Un contrôle manquant doit être conspicuous, pas oublié en silence.

        La clé de signature (étape 1 du plan) n'est pas encore vérifiée : elle
        est volontairement absente plutôt que couverte par un `ok` mensonger.
        """
        noms = {controle.nom for controle in verifier_sante(KeyRockSettings()).controles}
        assert noms == {"entropie_atteignable", "proxies_de_confiance"}


class TestEntropieAtteignable:
    def test_seuil_raisonnable_passe(self) -> None:
        rapport = verifier_sante(KeyRockSettings(token_min_entropy=80))
        assert _controle(rapport, "entropie_atteignable").ok is True

    def test_seuil_inatteignable_bloque(self) -> None:
        """Une configuration qui ne peut rien produire doit le signaler.

        Aucune longueur admise n'atteint le seuil : toute requête recevra un
        422. Répondre « ok » ferait croire le conteneur sain.
        """
        settings = KeyRockSettings(
            token_min_length=8, token_max_length=16, token_min_entropy=20_000
        )
        rapport = verifier_sante(settings)
        controle = _controle(rapport, "entropie_atteignable")
        assert controle.ok is False
        assert controle.bloquant is True
        assert rapport.statut == "ko"
        assert rapport.disponible is False

    def test_la_borne_haute_seule_peut_sauver(self) -> None:
        """Le contrôle doit regarder la borne haute, pas seulement la basse."""
        settings = KeyRockSettings(token_min_length=8, token_max_length=64, token_min_entropy=400)
        assert _controle(verifier_sante(settings), "entropie_atteignable").ok is True

    def test_bornes_etroites_avec_seuil_haut_bloquent(self) -> None:
        settings = KeyRockSettings(token_min_length=8, token_max_length=8, token_min_entropy=400)
        assert _controle(verifier_sante(settings), "entropie_atteignable").ok is False


class TestProxiesDeConfiance:
    def test_rien_declare_est_sain(self) -> None:
        controle = _controle(
            verifier_sante(KeyRockSettings(trusted_proxies="")), "proxies_de_confiance"
        )
        assert controle.ok is True
        assert controle.bloquant is False

    def test_reseau_valide_est_sain(self) -> None:
        rapport = verifier_sante(KeyRockSettings(trusted_proxies="172.20.0.10/32"))
        assert _controle(rapport, "proxies_de_confiance").ok is True

    def test_reseau_invalide_avertit_sans_bloquer(self) -> None:
        """Une faute de frappe désactive la confiance : il faut le signaler.

        Non bloquant : le service reste sûr et disponible, seulement moins fin.
        Le rendre bloquant déclencherait une boucle de redémarrage sur une
        configuration par ailleurs fonctionnelle.
        """
        rapport = verifier_sante(KeyRockSettings(trusted_proxies="172.20.0.10/32,pas-un-cidr"))
        controle = _controle(rapport, "proxies_de_confiance")
        assert controle.ok is False
        assert controle.bloquant is False
        assert rapport.statut == "degraded"
        assert rapport.disponible is True

    def test_detail_ne_reprend_pas_la_valeur_rejetee(self) -> None:
        """/health est public : la valeur de configuration n'y est pas exposée."""
        rapport = verifier_sante(KeyRockSettings(trusted_proxies="valeur-interne-invalide"))
        assert "valeur-interne-invalide" not in _controle(rapport, "proxies_de_confiance").detail

    @pytest.mark.parametrize(
        "declare", ["n'importe quoi", "999.999.999.999/8", "172.20.0.10/99", "   "]
    )
    def test_declarations_invalides(self, declare: str) -> None:
        rapport = verifier_sante(KeyRockSettings(trusted_proxies=declare))
        rapport_controle = _controle(rapport, "proxies_de_confiance")
        # Une déclaration vide est saine (aucune confiance voulue) ; une
        # déclaration non vide et illisible est un avertissement.
        attendu = declare.strip() == ""
        assert rapport_controle.ok is attendu
        assert rapport.disponible is True


class TestRouteHealth:
    def test_sante_normale(self, client: TestClient) -> None:
        reponse = client.get("/health")
        assert reponse.status_code == 200
        corps = reponse.json()
        assert corps["status"] == "ok"
        assert corps["version"]
        assert {controle["nom"] for controle in corps["controles"]} == {
            "entropie_atteignable",
            "proxies_de_confiance",
        }

    def test_health_degrade_reste_en_200(self) -> None:
        """Un avertissement ne doit pas faire tomber la sonde.

        Un 503 ici ferait redémarrer le conteneur en boucle sur une
        configuration qui fonctionne.
        """
        with _client_avec(KeyRockSettings(trusted_proxies="pas-un-cidr")) as client:
            reponse = client.get("/health")
        assert reponse.status_code == 200
        assert reponse.json()["status"] == "degraded"

    def test_health_bloquant_renvoie_503(self) -> None:
        """Un contrôle bloquant échoué doit sortir en 503, pas en 200 « ok »."""
        config = KeyRockSettings(token_min_length=8, token_max_length=8, token_min_entropy=20_000)
        with _client_avec(config) as client:
            reponse = client.get("/health")
        assert reponse.status_code == 503
        assert reponse.json()["status"] == "ko"

    def test_health_bloquant_garde_les_en_tetes_de_securite(self) -> None:
        """Le 503 est une réponse comme une autre : elle reste durcie."""
        config = KeyRockSettings(token_min_length=8, token_max_length=8, token_min_entropy=20_000)
        with _client_avec(config) as client:
            entetes = client.get("/health").headers
        assert entetes["X-Content-Type-Options"] == "nosniff"
        assert entetes["Cache-Control"].startswith("no-store")

    def test_health_bloquant_empêche_de_servir(self) -> None:
        """Une configuration en panne ne doit pas laisser passer la génération.

        Le contrôle signale l'indisponibilité ; il ne pretend pas interdire
        l'usage. Ce test verrouille le statut, pas une politique d'accès.
        """
        config = KeyRockSettings(token_min_length=8, token_max_length=8, token_min_entropy=20_000)
        with _client_avec(config) as client:
            assert client.get("/health").status_code == 503
            # La génération échoue bien, et pour la raison annoncée.
            reponse = client.post("/api/v1/generate", json={"longueur": 8})
        assert reponse.status_code == 422
        assert reponse.json()["error"]["code"] == "ENTROPIE_INSUFFISANTE"

    def test_health_ne_publie_que_des_metadonnees(self, client: TestClient) -> None:
        corps = client.get("/health").json()
        assert set(corps) == {"status", "version", "controles"}
        for controle in corps["controles"]:
            assert set(controle) == {"nom", "ok", "bloquant", "detail"}
