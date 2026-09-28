"""Tests de la CLI (interactions, bornes, orchestration)."""

from __future__ import annotations

import io
from unittest.mock import patch

import pytest
from rich.console import Console

from keyrock_cli import display, interactions
from keyrock_cli.app import ART_KEYROCK, CREDITS, KeyRockCLI
from keyrock_cli.display import SEQ_EFFACER_TOUT

SORTIE_ALTERNATIF = display.SEQ_ALT_SCREEN_OFF

Entrees = list[str | BaseException]


class Saisir:
    """Simule la saisie clavier en interceptant l'`input` utilisé par la CLI."""

    def __init__(self, entrees: Entrees | None = None) -> None:
        self.entrees: list[str | BaseException] = list(entrees or [])
        self._patcher: object = None

    def __enter__(self) -> Saisir:
        self._patcher = patch("builtins.input", self._lire)
        self._patcher.start()
        return self

    def __exit__(self, *_args: object) -> None:
        self._patcher.stop()

    def _lire(self, _invite: str = "") -> str:
        if not self.entrees:
            raise EOFError
        entree = self.entrees.pop(0)
        if isinstance(entree, BaseException):
            raise entree
        return entree


class Simulation:
    """Construit des objets `Saisir` à partir d'une liste de réponses."""

    def __call__(self, entrees: Entrees) -> Saisir:
        return Saisir(entrees)


@pytest.fixture
def saisir() -> Simulation:
    """Fournit une fabrique de saisie simulée."""
    return Simulation()


def creer_console_memoire() -> tuple[Console, io.StringIO]:
    tampon = io.StringIO()
    return Console(file=tampon, force_terminal=True, width=100), tampon


@pytest.fixture
def console_memoire() -> tuple[Console, io.StringIO]:
    return creer_console_memoire()


@pytest.fixture
def cli(console_memoire: tuple[Console, io.StringIO]) -> KeyRockCLI:
    console, _ = console_memoire
    return KeyRockCLI(console_cible=console)


class TestEtatInitial:
    def test_options_par_defaut(self, cli: KeyRockCLI) -> None:
        assert cli.options == {
            "maj": True,
            "min": True,
            "chiffres": True,
            "symboles": True,
            "longueur": 32,
        }

    def test_art_preserve(self) -> None:
        assert "█" in ART_KEYROCK
        assert "▒████" in ART_KEYROCK

    def test_credits_sous_l_art(self) -> None:
        assert [texte for texte, _ in CREDITS] == [
            "KEYROCK",
            "Générateur de Clés & Tokens Cryptographiques",
            "Créé pour le compte de Vextra Agency",
            "Auteur : Nawfel Reghai",
        ]


class TestBasculeOptions:
    @pytest.mark.parametrize(
        ("choix", "cle"),
        [("1", "maj"), ("2", "min"), ("3", "chiffres"), ("4", "symboles")],
    )
    def test_bascule(self, cli: KeyRockCLI, choix: str, cle: str) -> None:
        avant = cli.options[cle]
        cli.traiter_choix(choix)
        assert cli.options[cle] is not avant

    def test_quitter_leve_systemexit(self, cli: KeyRockCLI) -> None:
        with pytest.raises(SystemExit) as exc:
            cli.traiter_choix("0")
        assert exc.value.code == 0


class TestConversionOptions:
    def test_conversion_dict_vers_dataclass(self) -> None:
        options = interactions.vers_generation_options(
            {"maj": True, "min": False, "chiffres": True, "symboles": False, "longueur": 64}
        )
        assert options.longueur == 64
        assert options.majuscules is True
        assert options.minuscules is False

    def test_avertissement_entropie_faible(self) -> None:
        console, tampon = creer_console_memoire()
        options = {
            "maj": False,
            "min": False,
            "chiffres": True,
            "symboles": False,
            "longueur": 8,
        }
        resultat = interactions.avertir_si_entropie_faible(options, console_cible=console)
        assert resultat is not None and resultat < 80
        assert "sous le seuil" in tampon.getvalue()

    def test_avertissement_entropie_suffisante(self) -> None:
        console, _ = creer_console_memoire()
        options = {
            "maj": True,
            "min": True,
            "chiffres": True,
            "symboles": True,
            "longueur": 32,
        }
        resultat = interactions.avertir_si_entropie_faible(options, console_cible=console)
        assert resultat is not None and resultat >= 80

    def test_aucune_alerte_sans_type_de_caractere(self) -> None:
        console, _ = creer_console_memoire()
        options = {
            "maj": False,
            "min": False,
            "chiffres": False,
            "symboles": False,
            "longueur": 32,
        }
        assert interactions.avertir_si_entropie_faible(options, console_cible=console) is None


class TestBornesLongueur:
    @pytest.mark.parametrize("valeur", [8, 32, 1024])
    def test_valeurs_valides(self, valeur: int, saisir: Simulation) -> None:
        with saisir([str(valeur)]):
            console, _ = creer_console_memoire()
            obtenu = interactions.demander_entier_borne("Longueur", 8, 1024, console_cible=console)
        assert obtenu == valeur

    @pytest.mark.parametrize("valeur", [7, 0, -1, 1025, 999_999_999])
    def test_valeurs_rejetees_puis_boucle(self, valeur: int, saisir: Simulation) -> None:
        with saisir([str(valeur), "32"]):
            console, tampon = creer_console_memoire()
            resultat = interactions.demander_entier_borne(
                "Longueur", 8, 1024, console_cible=console
            )
        assert resultat == 32
        assert "hors bornes" in tampon.getvalue()

    def test_abandon_retourne_none(self, saisir: Simulation) -> None:
        with saisir([KeyboardInterrupt()]):
            console, _ = creer_console_memoire()
            obtenu = interactions.demander_entier_borne("Longueur", 8, 1024, console_cible=console)
        assert obtenu is None


class TestFinDeFlux:
    """Regression : sur flux épuisé, `rich.Prompt.ask` renvoyait la valeur par
    défaut, ce qui bouclait indéfiniment sur la génération de tokens."""

    def test_lire_reponse_leve_eof(self, saisir: Simulation) -> None:
        with saisir([]), pytest.raises(EOFError):
            interactions.lire_reponse("> ")

    def test_reponse_vide_valide_le_defaut(self, saisir: Simulation) -> None:
        with saisir([""]):
            console, _ = creer_console_memoire()
            obtenu = interactions.demander_choix("> ", ["a", "b"], "b", console_cible=console)
        assert obtenu == "b"

    def test_choix_invalide_redemande(self, saisir: Simulation) -> None:
        with saisir(["z", "1"]):
            console, tampon = creer_console_memoire()
            obtenu = interactions.demander_choix("> ", ["0", "1"], "0", console_cible=console)
        assert obtenu == "1"
        assert "Choix invalide" in tampon.getvalue()

    def test_trop_de_reponses_invalides_abandonne(self, saisir: Simulation) -> None:
        with saisir(["x"] * 30), pytest.raises(EOFError):
            interactions.demander_choix("> ", ["0", "1"], "0")

    def test_menu_principal_quitte_sur_eof(self, cli: KeyRockCLI, saisir: Simulation) -> None:
        console, tampon = creer_console_memoire()
        cli.console = console
        with saisir([]):
            cli.menu_principal()  # ne doit pas boucler
        assert tampon.getvalue().count("TOKEN 1") == 0
        assert "Arrêt manuel" in tampon.getvalue()


class TestGenerationCLI:
    @pytest.fixture(autouse=True)
    def _sans_presse_papier(self) -> None:
        with (
            patch("builtins.input", lambda *a, **k: ""),
            patch("keyrock_cli.app.confirmer", return_value=False),
        ):
            yield

    def test_refus_sans_type_de_caractere(
        self, cli: KeyRockCLI, console_memoire: tuple[Console, io.StringIO]
    ) -> None:
        cli.options.update({"maj": False, "min": False, "chiffres": False, "symboles": False})
        cli.executer_generation()
        assert "au moins un type" in console_memoire[1].getvalue()

    def test_refus_entropie_insuffisante(
        self, cli: KeyRockCLI, console_memoire: tuple[Console, io.StringIO]
    ) -> None:
        cli.options.update(
            {"maj": False, "min": False, "chiffres": True, "symboles": False, "longueur": 8}
        )
        cli.executer_generation()
        assert "Génération impossible" in console_memoire[1].getvalue()

    def test_generation_reussie_puis_purge(
        self, cli: KeyRockCLI, console_memoire: tuple[Console, io.StringIO]
    ) -> None:
        cli.executer_generation()
        sortie = console_memoire[1].getvalue()
        assert "TOKEN 1" in sortie and "TOKEN 2" in sortie
        assert sortie.rindex(SEQ_EFFACER_TOUT) > sortie.index("TOKEN 2")
        assert SORTIE_ALTERNATIF in sortie

    def test_longueur_inchangee_apres_generation(self, cli: KeyRockCLI) -> None:
        cli.executer_generation()
        assert cli.options["longueur"] == 32

    def test_copie_clipboard_proposee(self, cli: KeyRockCLI) -> None:
        with (
            patch("keyrock_cli.app.confirmer", return_value=True),
            patch("keyrock_cli.app.copier_vers_presse_papier", return_value=True) as copie,
        ):
            cli.executer_generation()
        copie.assert_called_once()
        assert len(copie.call_args.args[0]) == 32

    def test_copie_indisponible_signalee(
        self, cli: KeyRockCLI, console_memoire: tuple[Console, io.StringIO]
    ) -> None:
        with (
            patch("keyrock_cli.app.confirmer", return_value=True),
            patch("keyrock_cli.app.copier_vers_presse_papier", return_value=False),
        ):
            cli.executer_generation()
        assert "Presse-papier indisponible" in console_memoire[1].getvalue()

    def test_erreur_inattendue_masquee(
        self, cli: KeyRockCLI, console_memoire: tuple[Console, io.StringIO]
    ) -> None:
        with patch(
            "keyrock_core.generator.CoreGenerator.generer_plusieurs",
            side_effect=RuntimeError("fuite"),
        ):
            cli.executer_generation()
        sortie = console_memoire[1].getvalue()
        assert "Erreur interne" in sortie
        assert "fuite" not in sortie
        assert "Traceback" not in sortie
