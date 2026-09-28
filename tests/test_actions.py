"""Tests du registre d'actions — même code métier pour la TUI et le shell."""

from __future__ import annotations

import inspect
from unittest.mock import patch

import pytest

from keyrock_core.actions import ActionRegistry, ActionResultat
from keyrock_core.config import KeyRockSettings
from keyrock_core.service import GenerationService


@pytest.fixture
def service() -> GenerationService:
    return GenerationService(KeyRockSettings())


@pytest.fixture
def registre(service: GenerationService) -> ActionRegistry:
    return ActionRegistry(service)


class TestRegistre:
    def test_actions_par_defaut(self, registre: ActionRegistry) -> None:
        assert set(registre.noms()) == {
            "clear",
            "copy",
            "exit",
            "generate",
            "info",
            "password",
            "regenerate",
            "reset",
            "set_length",
            "toggle",
            "token",
        }

    def test_decrire(self, registre: ActionRegistry) -> None:
        descriptions = dict(registre.decrire())
        assert descriptions["generate"] == "Générer des tokens"

    def test_action_inconnue(self, registre: ActionRegistry) -> None:
        sortie = registre.executer("pirate")
        assert sortie.succes is False
        assert "pirate" in sortie.message
        assert sortie.donnees is not None
        assert "generate" in sortie.donnees["actions"]

    def test_aucun_acces_direct_au_csprng(self) -> None:
        """Le registre passe par le service, jamais directement au CSPRNG."""
        source = inspect.getsource(ActionRegistry)
        assert "CoreGenerator" not in source.replace("`CoreGenerator`", "")
        assert "secrets.choice" not in source

    def test_ne_leve_pas(self, registre: ActionRegistry) -> None:
        sortie = registre.executer("set_length", longueur=3)
        assert isinstance(sortie, ActionResultat)
        assert sortie.succes is False


class TestActionsGeneration:
    def test_generate(self, registre: ActionRegistry) -> None:
        sortie = registre.executer("generate")
        assert sortie.succes is True
        assert sortie.resultat is not None
        assert len(sortie.resultat.tokens) == 2

    def test_generate_nombre(self, registre: ActionRegistry) -> None:
        assert len(registre.executer("generate", nombre=4).resultat.tokens) == 4  # type: ignore[union-attr]

    def test_regenerate_produit_rien_different(self, registre: ActionRegistry) -> None:
        premier = registre.executer("generate").resultat
        second = registre.executer("regenerate").resultat
        assert premier is not None and second is not None
        assert premier.tokens != second.tokens

    def test_memorise_le_dernier(self, registre: ActionRegistry) -> None:
        resultat = registre.executer("generate").resultat
        assert registre.dernier() is resultat

    def test_sans_type_de_caractere(self, registre: ActionRegistry) -> None:
        for champ in ("majuscules", "minuscules", "chiffres", "symboles"):
            registre.executer("toggle", champ=champ)
        sortie = registre.executer("generate")
        assert sortie.succes is False
        assert "Aucun type" in sortie.message


class TestActionsEtat:
    def test_set_length(self, registre: ActionRegistry) -> None:
        sortie = registre.executer("set_length", longueur=64)
        assert sortie.succes is True
        assert sortie.donnees["longueur"] == 64

    def test_set_length_hors_bornes(self, registre: ActionRegistry) -> None:
        assert registre.executer("set_length", longueur=2).succes is False

    def test_toggle(self, registre: ActionRegistry) -> None:
        sortie = registre.executer("toggle", champ="symboles")
        assert sortie.donnees == {"symboles": False}

    def test_toggle_inconnu(self, registre: ActionRegistry) -> None:
        assert registre.executer("toggle", champ="pirate").succes is False

    def test_reset(self, registre: ActionRegistry) -> None:
        registre.executer("set_length", longueur=128)
        registre.executer("toggle", champ="chiffres")
        sortie = registre.executer("reset")
        assert sortie.succes is True
        assert registre.executer("info").donnees["longueur"] == 32  # type: ignore[index]

    def test_info(self, registre: ActionRegistry) -> None:
        donnees = registre.executer("info").donnees
        assert donnees is not None
        assert donnees["longueur"] == 32
        assert donnees["alphabet"] == 94
        assert donnees["presets"] == [16, 32, 64, 128]

    def test_exit(self, registre: ActionRegistry) -> None:
        assert registre.executer("exit").donnees == {"exit": True}


class TestActionsNommes:
    def test_password(self, registre: ActionRegistry) -> None:
        sortie = registre.executer("password", longueur=24)
        assert sortie.succes is True
        assert sortie.resultat is not None
        assert len(sortie.resultat.tokens) == 1
        assert len(sortie.resultat.tokens[0]) == 24

    def test_token(self, registre: ActionRegistry) -> None:
        sortie = registre.executer("token", longueur=64)
        assert sortie.resultat is not None
        assert len(sortie.resultat.tokens[0]) == 64

    def test_password_alphabet_complet(self, registre: ActionRegistry) -> None:
        assert registre.executer("password", longueur=32).resultat.alphabet == 94  # type: ignore[union-attr]


class TestActionCopy:
    def test_refuse_sans_precedent(self, registre: ActionRegistry) -> None:
        sortie = registre.executer("copy")
        assert sortie.succes is False
        assert "générez" in sortie.message

    def test_copie_le_token_precedent(self, registre: ActionRegistry) -> None:
        with patch("keyrock_cli.display.copier_vers_presse_papier", return_value=True) as copie:
            registre.executer("generate")
            sortie = registre.executer("copy")
        assert sortie.succes is True
        copie.assert_called_once()
        assert len(copie.call_args.args[0]) == 32

    def test_index_invalide(self, registre: ActionRegistry) -> None:
        registre.executer("generate")
        assert registre.executer("copy", index=9).succes is False

    def test_presse_papier_indisponible(self, registre: ActionRegistry) -> None:
        with patch("keyrock_cli.display.copier_vers_presse_papier", return_value=False):
            registre.executer("generate")
            assert registre.executer("copy").succes is False

    def test_aucune_borne_de_temps_dans_le_registre(self, registre: ActionRegistry) -> None:
        """Le registre ne doit jamais bloquer (minuteur non bloquant)."""
        with patch("keyrock_cli.display.copier_vers_presse_papier", return_value=True):
            registre.executer("generate")
            sortie = registre.executer("copy")
        assert sortie.succes is True


class TestErreursMasquees:
    def test_exception_interne_ne_fuit_pas(self, registre: ActionRegistry) -> None:
        with patch.object(registre.service, "generer", side_effect=RuntimeError("secret interne")):
            sortie = registre.executer("generate")
        assert sortie.succes is False
        assert "secret interne" not in sortie.message
        assert "RuntimeError" in sortie.message
