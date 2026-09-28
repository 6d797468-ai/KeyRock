"""Tests du service de génération (façade métier partagée)."""

from __future__ import annotations

import pytest

from keyrock_core.config import KeyRockSettings
from keyrock_core.generator import (
    LONGEUR_MAX,
    LONGEUR_MIN,
    EntropieInsuffisanteError,
)
from keyrock_core.service import (
    GenerationResultat,
    GenerationService,
    OptionsState,
)


@pytest.fixture
def service() -> GenerationService:
    return GenerationService(KeyRockSettings())


class TestOptionsState:
    def test_defauts(self) -> None:
        etat = OptionsState()
        assert etat.longueur == 32
        assert all(etat.composition().values())

    def test_immuabilite_du_resultat(self) -> None:
        etat = OptionsState()
        with pytest.raises(AttributeError):
            etat.options.longueur = 64  # type: ignore[misc]

    def test_set_longueur(self) -> None:
        etat = OptionsState()
        etat.set_longueur(64)
        assert etat.longueur == 64

    def test_basculer_aller_retour(self) -> None:
        etat = OptionsState()
        assert etat.basculer("symboles") is False
        assert etat.basculer("symboles") is True

    def test_basculer_champ_inconnu(self) -> None:
        with pytest.raises(ValueError, match="inconnu"):
            OptionsState().basculer("pirate")

    def test_definir_champ_inconnu(self) -> None:
        with pytest.raises(ValueError, match="inconnu"):
            OptionsState().definir("pirate", True)

    def test_copie_independante(self) -> None:
        etat = OptionsState()
        copie = etat.copie()
        etat.set_longueur(128)
        assert copie.longueur == 32


class TestServiceLecture:
    def test_longueur_par_defaut(self, service: GenerationService) -> None:
        assert service.longueur() == 32

    def test_alphabet_complet(self, service: GenerationService) -> None:
        assert len(service.alphabet()) == 94

    def test_entropie_par_defaut(self, service: GenerationService) -> None:
        assert service.entropie() >= 80

    def test_composition(self, service: GenerationService) -> None:
        assert set(service.composition()) == {
            "majuscules",
            "minuscules",
            "chiffres",
            "symboles",
        }


class TestServiceEcriture:
    @pytest.mark.parametrize("longueur", [16, 32, 64, 128, LONGEUR_MAX])
    def test_longueurs_valides(self, service: GenerationService, longueur: int) -> None:
        service.set_longueur(longueur)
        assert service.longueur() == longueur

    @pytest.mark.parametrize("longueur", [LONGEUR_MIN - 1, 0, -5, LONGEUR_MAX + 1])
    def test_longueurs_hors_bornes(self, service: GenerationService, longueur: int) -> None:
        with pytest.raises(ValueError, match="8 et 1024"):
            service.set_longueur(longueur)

    def test_entropie_insuffisante_refusee(self, service: GenerationService) -> None:
        service.definir("majuscules", False)
        service.definir("minuscules", False)
        service.definir("symboles", False)
        with pytest.raises(EntropieInsuffisanteError):
            service.set_longueur(8)

    def test_basculer(self, service: GenerationService) -> None:
        assert service.basculer("symboles") is False
        assert service.composition()["symboles"] is False

    def test_reinitialiser(self, service: GenerationService) -> None:
        service.set_longueur(128)
        service.basculer("chiffres")
        service.reinitialiser()
        assert service.longueur() == 32
        assert all(service.composition().values())


class TestGeneration:
    def test_deux_tokens_par_defaut(self, service: GenerationService) -> None:
        resultat = service.generer()
        assert len(resultat.tokens) == 2
        assert resultat.token1 != resultat.token2
        assert len(resultat.token1) == 32

    def test_nombre_custom(self, service: GenerationService) -> None:
        assert len(service.generer(5).tokens) == 5

    @pytest.mark.parametrize("nombre", [0, -1, True, "2"])
    def test_nombre_invalide(self, service: GenerationService, nombre: object) -> None:
        with pytest.raises(ValueError, match="nombre"):
            service.generer(nombre)  # type: ignore[arg-type]

    def test_sans_type_de_caractere(self, service: GenerationService) -> None:
        for champ in ("majuscules", "minuscules", "chiffres", "symboles"):
            service.definir(champ, False)
        with pytest.raises(ValueError, match="Aucun type de caractère"):
            service.generer()

    def test_metadonnees(self, service: GenerationService) -> None:
        resultat = service.generer()
        assert resultat.longueur == 32
        assert resultat.alphabet == 94
        assert resultat.entropie_bits >= 80
        assert resultat.duree_ms >= 0

    def test_en_json_inclut_les_tokens(self, service: GenerationService) -> None:
        charge = service.generer().en_json()
        assert charge["token1"] == charge["tokens"][0]
        assert charge["token2"] == charge["tokens"][1]

    def test_sans_tokens_exclut_les_tokens(self, service: GenerationService) -> None:
        resultat = service.generer()
        charge = resultat.sans_tokens()
        assert "tokens" not in charge
        for valeur in charge.values():
            assert resultat.token1 not in str(valeur)

    def test_token2_none_si_un_seul(self, service: GenerationService) -> None:
        assert service.generer(1).token2 is None

    def test_generer_avec_ne_mute_pas_l_etat(self, service: GenerationService) -> None:
        service.set_longueur(32)
        service.generer_avec(128, nombre=1)
        assert service.longueur() == 32

    def test_generer_avec_restaure_apres_echec(self, service: GenerationService) -> None:
        service.set_longueur(64)
        with pytest.raises(ValueError):
            service.generer_avec(4, nombre=1)
        assert service.longueur() == 64

    def test_generer_avec_composition(self, service: GenerationService) -> None:
        resultat = service.generer_avec(
            32,
            nombre=1,
            composition={
                "chiffres": True,
                "symboles": False,
                "majuscules": False,
                "minuscules": False,
            },
        )
        assert resultat.token1.isdigit()
        assert resultat.alphabet == 10

    def test_csprng_non_deterministe(self, service: GenerationService) -> None:
        assert service.generer(1).token1 != service.generer(1).token1

    def test_resultat_immuable(self, service: GenerationService) -> None:
        resultat = service.generer(1)
        assert isinstance(resultat, GenerationResultat)
        with pytest.raises(AttributeError):
            resultat.longueur = 99  # type: ignore[misc]


class TestSeuilConfigurable:
    def test_seuil_personnalise_est_respecte(self) -> None:
        # 32 caractères « tout alphabet » = 209.75 bits : un seuil de 300 doit refuser.
        service = GenerationService(KeyRockSettings(token_min_entropy=300))
        with pytest.raises(ValueError, match="300"):
            service.set_longueur(32)

    def test_seuil_bas_autorise_les_courtes_longueurs(self) -> None:
        service = GenerationService(KeyRockSettings(token_min_entropy=10, token_min_length=8))
        service.set_longueur(8)
        assert service.longueur() == 8
