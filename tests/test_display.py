"""Tests du module d'affichage (sécurité du scrollback, presse-papier)."""

from __future__ import annotations

import io
import sys
import types
from unittest.mock import patch

import pytest
from rich.console import Console

from keyrock_cli import display
from keyrock_cli.banner import CREDITS

ENTREE_SCREEN = "\033[2J"
EFFACER_SCROLLBACK = "\033[3J"
ENTREE_ALTERNATIF = display.SEQ_ALT_SCREEN_ON
SORTIE_ALTERNATIF = display.SEQ_ALT_SCREEN_OFF

COPIES: list[str] = []


class PyperclipFaux(types.ModuleType):
    @staticmethod
    def copy(texte: str) -> None:
        COPIES.append(texte)


class PyperclipCasse(types.ModuleType):
    @staticmethod
    def copy(_texte: str) -> None:
        raise RuntimeError("pas de serveur d'affichage")


def creer_console_memoire() -> tuple[Console, io.StringIO]:
    tampon = io.StringIO()
    return (
        Console(file=tampon, force_terminal=True, width=100, legacy_windows=False),
        tampon,
    )


class TestSequenceEffacement:
    def test_sequence_combinee(self) -> None:
        assert f"{EFFACER_SCROLLBACK}{ENTREE_SCREEN}\033[H" == display.SEQ_EFFACER_TOUT

    def test_console_clear_de_rich_ne_purge_pas_le_scrollback(self) -> None:
        """Finding d'origine : `Console.clear()` n'émet que `\\033[2J\\033[H`."""
        tampon = io.StringIO()
        Console(file=tampon, force_terminal=True).clear()
        sortie = tampon.getvalue()
        assert ENTREE_SCREEN in sortie
        assert EFFACER_SCROLLBACK not in sortie

    def test_effacement_emise_bien_le_code(self) -> None:
        console, tampon = creer_console_memoire()
        display.effacer_ecran_et_scrollback(cible=console)
        assert display.SEQ_EFFACER_TOUT in tampon.getvalue()

    def test_console_par_defaut_sans_argument(self) -> None:
        console, tampon = creer_console_memoire()
        with patch.object(display, "console", console):
            display.effacer_ecran_et_scrollback()
        assert display.SEQ_EFFACER_TOUT in tampon.getvalue()


class TestBufferAlternatif:
    def test_execution_et_restauration(self) -> None:
        console, tampon = creer_console_memoire()
        marqueur: list[str] = []
        with patch.object(display, "console", console):
            display.avec_buffer_alterne(lambda: marqueur.append("passe"))
        assert marqueur == ["passe"]
        sortie = tampon.getvalue()
        assert sortie.index(ENTREE_ALTERNATIF) < sortie.index(SORTIE_ALTERNATIF)

    def test_restauration_apres_exception(self) -> None:
        console, tampon = creer_console_memoire()
        with patch.object(display, "console", console), pytest.raises(ZeroDivisionError):
            display.avec_buffer_alterne(lambda: 1 // 0)
        assert SORTIE_ALTERNATIF in tampon.getvalue()

    def test_valeur_de_retour_propagee(self) -> None:
        console, _ = creer_console_memoire()
        with patch.object(display, "console", console):
            assert display.avec_buffer_alterne(lambda: 42) == 42

    def test_bascule_explicite(self) -> None:
        console, tampon = creer_console_memoire()
        display.basculer_buffer_alterne(True, cible=console)
        display.basculer_buffer_alterne(False, cible=console)
        assert tampon.getvalue() == (f"{ENTREE_ALTERNATIF}{SORTIE_ALTERNATIF}")

    def test_codes_ecrits_meme_hors_terminal(self) -> None:
        """`Console.control()` ignore ces codes hors terminal : on écrit en direct."""
        tampon = io.StringIO()
        console = Console(file=tampon, force_terminal=False, width=100)
        assert not console.is_terminal
        display.basculer_buffer_alterne(True, cible=console)
        assert tampon.getvalue() == ENTREE_ALTERNATIF


class TestAffichage:
    def test_tokens_encadres_par_le_buffer_alterne(self) -> None:
        console, tampon = creer_console_memoire()
        with patch.object(display, "console", console):
            display.afficher_tokens(["abc", "def"], 32, 104.87, cible=console)
        sortie = tampon.getvalue()
        assert "TOKEN 1" in sortie and "TOKEN 2" in sortie
        assert "104.87" in sortie
        assert sortie.index(ENTREE_ALTERNATIF) < sortie.index("abc")
        assert sortie.index(SORTIE_ALTERNATIF) > sortie.index("def")

    def test_scrollback_purge_apres_le_token(self) -> None:
        console, tampon = creer_console_memoire()
        with patch.object(display, "console", console):
            display.afficher_tokens(["secret1", "secret2"], 16, cible=console)
        sortie = tampon.getvalue()
        assert sortie.rindex(display.SEQ_EFFACER_TOUT) > sortie.index("secret1")
        assert sortie.rindex(SORTIE_ALTERNATIF) > sortie.index("secret2")

    def test_banniere_purge_en_tete(self) -> None:
        console, tampon = creer_console_memoire()
        with patch.object(display, "console", console):
            display.afficher_banniere("KEYROCK", credits=CREDITS, cible=console)
        sortie = tampon.getvalue()
        assert sortie.startswith(display.SEQ_EFFACER_TOUT)
        assert "KEYROCK" in sortie
        assert "Vextra Agency" in sortie
        assert "Nawfel Reghai" in sortie

    def test_banniere_sans_credits(self) -> None:
        console, tampon = creer_console_memoire()
        display.afficher_banniere("CLE", cible=console)
        assert "CLE" in tampon.getvalue()
        assert "Vextra Agency" not in tampon.getvalue()

    def test_footer_mentionne_auteur(self) -> None:
        console, tampon = creer_console_memoire()
        display.afficher_footer(cible=console)
        assert "Nawfel Reghai" in tampon.getvalue()

    def test_attendre_enter_purge_meme_sur_eof(self) -> None:
        console, tampon = creer_console_memoire()
        with (
            patch.object(display, "console", console),
            patch("builtins.input", side_effect=EOFError),
        ):
            display.attendre_enter()
        assert display.SEQ_EFFACER_TOUT in tampon.getvalue()

    def test_quitter_terminal_purge_puis_quitte(self) -> None:
        console, tampon = creer_console_memoire()
        with pytest.raises(SystemExit):
            display.quitter_terminal(console)
        assert tampon.getvalue().startswith(display.SEQ_EFFACER_TOUT)


class TestPressePapier:
    def test_copie_puis_vidage_automatique(self) -> None:
        COPIES.clear()
        with patch.dict(sys.modules, {"pyperclip": PyperclipFaux("pyperclip")}):
            assert display.copier_vers_presse_papier("token-secret", delai_secondes=0.0) is True
        assert COPIES == ["token-secret", ""]

    def test_pyperclip_absent(self) -> None:
        with patch.dict(sys.modules, {"pyperclip": None}):
            assert display.copier_vers_presse_papier("token", delai_secondes=0.0) is False
            assert display.vider_presse_papier() is False

    def test_echec_de_copie_rentre(self) -> None:
        with patch.dict(sys.modules, {"pyperclip": PyperclipCasse("pyperclip")}):
            assert display.copier_vers_presse_papier("token", delai_secondes=0.0) is False
            assert display.vider_presse_papier() is False

    def test_vidage_direct(self) -> None:
        COPIES.clear()
        with patch.dict(sys.modules, {"pyperclip": PyperclipFaux("pyperclip")}):
            assert display.vider_presse_papier() is True
        assert COPIES == [""]

    def test_le_purgeur_detache_est_lance(self) -> None:
        """Sans purgeur détaché, un token collé par `kr c 32` ne meurt jamais."""
        COPIES.clear()
        with (
            patch.dict(sys.modules, {"pyperclip": PyperclipFaux("pyperclip")}),
            patch.object(display.subprocess, "Popen") as popen,
        ):
            assert display.copier_vers_presse_papier("jeton", delai_secondes=30.0) is True
        popen.assert_called_once()
        # Tubes détachés, sinon un script appelant resterait en attente.
        kwargs = popen.call_args.kwargs
        assert kwargs["start_new_session"] is True
        assert kwargs["stdout"] is display.subprocess.DEVNULL
        assert kwargs["stderr"] is display.subprocess.DEVNULL
        assert kwargs["close_fds"] is True

    def test_purgeur_detache_demarre_une_session(self) -> None:
        """Le script exécuté doit attendre puis vider, et rien d'autre."""
        assert "sleep" in display._SCRIPT_PURGE
        assert "pyperclip" in display._SCRIPT_PURGE

    def test_delai_nul_vide_immediatement_sans_detacher(self) -> None:
        COPIES.clear()
        with (
            patch.dict(sys.modules, {"pyperclip": PyperclipFaux("pyperclip")}),
            patch.object(display.subprocess, "Popen") as popen,
        ):
            assert display.copier_vers_presse_papier("jeton", delai_secondes=0.0) is True
        popen.assert_not_called()
        assert COPIES == ["jeton", ""]

    def test_purgeur_dans_vide_effectivement(self) -> None:
        COPIES.clear()
        with patch.dict(sys.modules, {"pyperclip": PyperclipFaux("pyperclip")}):
            display.purger_presse_papier_dans(0.0)
        assert COPIES == [""]

    def test_echec_du_purgeur_ne_casse_pas_la_copie(self) -> None:
        COPIES.clear()
        with (
            patch.dict(sys.modules, {"pyperclip": PyperclipFaux("pyperclip")}),
            patch.object(display.subprocess, "Popen", side_effect=OSError("nope")),
        ):
            assert display.copier_vers_presse_papier("jeton", delai_secondes=30.0) is True
        assert COPIES == ["jeton"]
