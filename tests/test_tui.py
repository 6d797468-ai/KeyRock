"""Tests de la TUI Textual — pilotage par le clavier et par des clics simulés.

Textual s'exécute ici sans terminal réel (`run_test`), ce qui permet de vérifier
que la souris et le clavier déclenchent exactement le même code métier.
"""

from __future__ import annotations

from typing import Any

import pytest

from keyrock_core.actions import ActionRegistry
from keyrock_core.config import KeyRockSettings
from keyrock_core.service import GenerationService

textual = pytest.importorskip("textual")

#: Taille de terminal simulée (la bannière ASCII occupe 20 lignes).
TAILLE_TERMINAL = (120, 60)


@pytest.fixture
def service() -> GenerationService:
    return GenerationService(KeyRockSettings())


@pytest.fixture
def registre(service: GenerationService) -> ActionRegistry:
    return ActionRegistry(service)


@pytest.fixture
def app(service: GenerationService, registre: ActionRegistry) -> Any:
    from keyrock_cli.tui import _construire_app

    return _construire_app(service, registre)


class TestModeDetecte:
    def test_pipe_means_clavier(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from keyrock_cli import tui

        monkeypatch.setattr(tui.sys.stdout, "isatty", lambda: False, raising=False)
        assert tui.detecter_mode() == tui.MODE_CLEAVIER

    def test_terminal_dumb_means_clavier(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from keyrock_cli import tui

        monkeypatch.setattr(tui.sys.stdout, "isatty", lambda: True, raising=False)
        monkeypatch.setenv("TERM", "dumb")
        assert tui.detecter_mode() == tui.MODE_CLEAVIER

    def test_terminal_plein_means_souris(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from keyrock_cli import tui

        monkeypatch.setattr(tui.sys.stdout, "isatty", lambda: True, raising=False)
        monkeypatch.setenv("TERM", "xterm-256color")
        monkeypatch.setattr(tui.sys, "platform", "linux")
        assert tui.detecter_mode() == tui.MODE_SOURIS

    def test_largeur_bornee(self) -> None:
        from keyrock_cli.tui import _largeur_utile

        assert 60 <= _largeur_utile() <= 100


class TestClicSouris:
    def test_clic_generer(self, app: Any) -> None:
        import asyncio

        async def scenario() -> None:
            async with app.run_test(size=TAILLE_TERMINAL) as pilote:
                await pilote.click("#generer")
                await pilote.pause()
                contenu = pilote.app.texte_resultat
                assert "TOKEN 1" in contenu
                assert "TOKEN 2" in contenu

        asyncio.run(scenario())

    def test_clic_preset_change_la_longueur(self, app: Any, service: GenerationService) -> None:
        import asyncio

        async def scenario() -> None:
            async with app.run_test(size=TAILLE_TERMINAL) as pilote:
                await pilote.click("#preset-64")
                await pilote.pause()
                assert service.longueur() == 64
                assert "64" in pilote.app.texte_longueur

        asyncio.run(scenario())

    def test_case_a_cocher_avec_la_souris(self, app: Any, service: GenerationService) -> None:
        import asyncio

        async def scenario() -> None:
            async with app.run_test(size=TAILLE_TERMINAL) as pilote:
                await pilote.click("#symboles")
                await pilote.pause()
                assert service.composition()["symboles"] is False

        asyncio.run(scenario())

    def test_clic_reset(self, app: Any, service: GenerationService) -> None:
        import asyncio

        async def scenario() -> None:
            async with app.run_test(size=TAILLE_TERMINAL) as pilote:
                await pilote.click("#preset-128")
                await pilote.pause()
                await pilote.click("#reset")
                await pilote.pause()
                assert service.longueur() == 32

        asyncio.run(scenario())


class TestClavier:
    def test_touche_g_generer(self, app: Any) -> None:
        import asyncio

        async def scenario() -> None:
            async with app.run_test(size=TAILLE_TERMINAL) as pilote:
                await pilote.press("g")
                await pilote.pause()
                assert "TOKEN 1" in pilote.app.texte_resultat

        asyncio.run(scenario())

    def test_tab_puis_entree_sur_un_bouton(self, app: Any) -> None:
        import asyncio

        async def scenario() -> None:
            async with app.run_test(size=TAILLE_TERMINAL) as pilote:
                bouton = pilote.app.query_one("#generer")
                bouton.focus()
                await pilote.press("enter")
                await pilote.pause()
                assert "TOKEN 1" in pilote.app.texte_resultat

        asyncio.run(scenario())

    def test_touche_q_quitte(self, app: Any) -> None:
        import asyncio

        async def scenario() -> None:
            async with app.run_test(size=TAILLE_TERMINAL) as pilote:
                await pilote.press("q")
                await pilote.pause()
                assert pilote.app._exit is True

        asyncio.run(scenario())


class TestPariteSourisClavier:
    def test_meme_resultat_metier(self, app: Any) -> None:
        """Souris et clavier appellent le même `ActionRegistry`."""
        import asyncio

        async def scenario() -> None:
            async with app.run_test(size=TAILLE_TERMINAL) as pilote:
                await pilote.click("#preset-32")
                await pilote.pause()
                await pilote.press("g")
                await pilote.pause()
                par_clavier = pilote.app.texte_resultat
                await pilote.click("#generer")
                await pilote.pause()
                par_souris = pilote.app.texte_resultat
            assert par_clavier.startswith("32 car.")
            assert par_souris.startswith("32 car.")

        asyncio.run(scenario())


class TestAucunSecretJournalise:
    def test_aucune_import_de_secrets_dans_la_tui(self) -> None:
        import inspect

        from keyrock_cli import tui

        assert "secrets" not in inspect.getsource(tui)
        assert "CoreGenerator" not in inspect.getsource(tui)
        assert "random" not in inspect.getsource(tui)

    def test_ord_charger_texte_n_est_pas_requis(self) -> None:
        """La TUI ne doit dépendre d'aucun fichier externe."""
        import inspect

        from keyrock_cli import tui

        source = inspect.getsource(tui)
        assert "open(" not in source
        assert "Path(" not in source
