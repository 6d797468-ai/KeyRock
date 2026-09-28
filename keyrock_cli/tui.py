"""TUI Textual — interface interactive (souris + clavier) de KeyRock.

Trois modes de fonctionnement, choisis automatiquement :

  * terminal interactif complet  → TUI Textual (souris + clavier)
  * terminal sans souris         → TUI clavier (clavier seul, focus visible)
  * sortie non interactive       → le dispatcher `kr` bascule sur le CLI

Le mode dégradé est celui de `keyrock_cli.app.KeyRockCLI` (Rich), ce qui évite
de casser les environnements sans prise en charge du pointeur.

Cette couche ne fait **aucune** logique métier : tout passe par `ActionRegistry`.
"""

from __future__ import annotations

import contextlib
import os
import shutil
import sys
from typing import Any, ClassVar

from rich.console import Console

from keyrock_core.actions import ActionRegistry
from keyrock_core.service import LONGUEURS_PRESETS, GenerationService

__all__ = ["MODE_CLEAVIER", "MODE_SOURIS", "detecter_mode", "lancer_tui"]

MODE_SOURIS = "souris"
MODE_CLEAVIER = "clavier"


def terminal_supporte_souris() -> bool:
    """Vrai si la sortie est un TTY exposant les séquences de souris."""
    if not sys.stdout.isatty():
        return False
    if sys.platform == "win32":
        return False
    # TERM valide : les terminaux « dumb » n'ont pas de souris.
    return "dumb" not in os.environ.get("TERM", "")


def detecter_mode() -> str:
    return MODE_SOURIS if terminal_supporte_souris() else MODE_CLEAVIER


def _largeur_utile() -> int:
    return max(60, min(100, shutil.get_terminal_size((80, 24)).columns - 4))


# ---------------------------------------------------------------------------
# TUI Textual
# ---------------------------------------------------------------------------
def _construire_app(service: GenerationService, registre: ActionRegistry) -> Any:
    from textual.app import App, ComposeResult
    from textual.binding import Binding
    from textual.containers import Horizontal, Vertical, VerticalScroll
    from textual.widgets import Button, Checkbox, Footer, Header, Static

    class KeyRockTUI(App[None]):
        """TUI KeyRock : souris + clavier, même moteur métier que le CLI."""

        CSS: ClassVar[str] = """
        Screen { align: center top; overflow-y: auto; }
        #banneau { height: auto; margin: 1 0; }
        #titre { text-align: center; color: cyan; text-style: bold; }
        #signature { text-align: center; color: white; }
        #credits { text-align: center; color: red; }
        #longueur { height: auto; margin: 1 0; }
        #presets Button { margin: 0 1; min-width: 12; }
        #actions Button { margin: 0 1; min-width: 20; }
        #resultat { height: auto; margin: 1 0; padding: 1 2; border: round green; }
        #message { height: 3; margin: 1 0; color: yellow; }
        #composition { height: auto; margin: 1 0; }
        Checkbox { margin: 0 2 0 0; }
        """

        BINDINGS: ClassVar[list[Binding | tuple[str, str] | tuple[str, str, str]]] = [
            ("q", "quitter", "Quitter"),
            ("g", "generer", "Générer"),
            ("c", "copier", "Copier"),
            ("r", "reset", "Réinitialiser"),
            ("escape", "reset", "Réinitialiser"),
        ]

        def __init__(self) -> None:
            super().__init__()
            self.service = service
            self.registre = registre
            #: Derniers textes affichés (lisibles par les tests, sans scraper l'écran).
            self.texte_longueur = ""
            self.texte_resultat = ""
            self.texte_message = ""

        # -- Composition de l'écran ---------------------------------------
        def compose(self) -> ComposeResult:
            from keyrock_cli.banner import ART_KEYROCK, CREDITS

            yield Header(show_clock=False)
            with VerticalScroll(id="panneau"):
                # markup=False : un token peut contenir « [ » et « ] ».
                yield Static(ART_KEYROCK.strip("\n"), id="banneau", markup=False)
                for indice, (texte, _style) in enumerate(CREDITS):
                    style = "signature" if indice == 0 else "credits"
                    yield Static(texte, id=f"{style}-{indice}", markup=False)
                yield Static("", id="longueur", markup=False)
                with Horizontal(id="presets"):
                    for preset in (*LONGUEURS_PRESETS, "perso"):
                        libelle = "Personnalisé" if preset == "perso" else str(preset)
                        yield Button(libelle, id=f"preset-{preset}", variant="primary")
                with Vertical(id="composition"):
                    for champ, libelle in (
                        ("majuscules", "Majuscules"),
                        ("minuscules", "Minuscules"),
                        ("chiffres", "Chiffres"),
                        ("symboles", "Symboles"),
                    ):
                        yield Checkbox(libelle, value=service.composition()[champ], id=champ)
                with Horizontal(id="actions"):
                    yield Button("🔑 GÉNÉRER", id="generer", variant="success")
                    yield Button("📋 COPIER", id="copier", variant="warning")
                    yield Button("↻ RESET", id="reset")
                    yield Button("✕ QUITTER", id="quitter", variant="error")
                yield Static("", id="message", markup=False)
                yield Static("", id="resultat", markup=False)
            yield Footer()

        # -- Rafraîchissement ---------------------------------------------
        def _maj_longueur(self) -> None:
            self.texte_longueur = (
                f"LONGUEUR : {self.service.longueur()}  (entropie {self.service.entropie()} bits)"
            )
            self.query_one("#longueur", Static).update(self.texte_longueur)

        def _maj_resultat(self, texte: str) -> None:
            self.texte_resultat = texte
            self.query_one("#resultat", Static).update(texte)
            self._maj_longueur()

        def _maj_message(self, texte: str) -> None:
            self.texte_message = texte
            self.query_one("#message", Static).update(texte)

        def on_mount(self) -> None:
            self._maj_longueur()

        # -- Actions (uniquement via le registre) --------------------------
        def _appliquer(self, resultat: Any) -> None:
            if not resultat.succes:
                self._maj_message(f"✗ {resultat.message}")
                self._maj_longueur()
                return
            if resultat.resultat is None:
                self._maj_resultat(resultat.message)
                return
            corps = "\n".join(
                f"TOKEN {i + 1}\n{token}" for i, token in enumerate(resultat.resultat.tokens)
            )
            entete = (
                f"{resultat.resultat.longueur} car. | "
                f"{resultat.resultat.entropie_bits} bits | {resultat.message}"
            )
            self._maj_resultat(f"{entete}\n{corps}")
            self._maj_message("")

        def action_generer(self) -> None:
            self._appliquer(self.registre.executer("generate"))

        def action_copier(self) -> None:
            dernier = self.registre.dernier()
            if dernier is not None:
                self.registre.memoriser(dernier)
            self._appliquer(self.registre.executer("copy"))

        def action_reset(self) -> None:
            self.service.reinitialiser()
            composition = self.service.composition()
            for champ in ("majuscules", "minuscules", "chiffres", "symboles"):
                with contextlib.suppress(Exception):
                    self.query_one(f"#{champ}", Checkbox).value = composition[champ]
            self._appliquer(self.registre.executer("reset"))

        def action_quitter(self) -> None:
            self.exit()

        # -- Souris : un clic sur un Button -------------------------------
        def on_button_pressed(self, event: Button.Pressed) -> None:
            identifiant = event.button.id or ""
            if identifiant.startswith("preset-"):
                self._preset(identifiant.removeprefix("preset-"))
                return
            if identifiant == "generer":
                self.action_generer()
            elif identifiant == "copier":
                self.action_copier()
            elif identifiant == "reset":
                self.action_reset()
            elif identifiant == "quitter":
                self.action_quitter()

        def _preset(self, valeur: str) -> None:
            if valeur == "perso":
                from keyrock_cli.interactions import demander_entier_borne

                longueur = demander_entier_borne(
                    "Longueur souhaitée", 8, 1024, console_cible=self.console_rich
                )
                if longueur is None:
                    return
            else:
                longueur = int(valeur)
            sortie = self.registre.executer("set_length", longueur=longueur)
            if not sortie.succes:
                self._maj_message(f"✗ {sortie.message}")
                return
            self._maj_longueur()

        def on_checkbox_changed(self, event: Checkbox.Changed) -> None:
            if event.value is None:
                return
            self.registre.executer("toggle", champ=event.checkbox.id or "")

        @property
        def console_rich(self) -> Console:
            return Console()

    return KeyRockTUI()


def lancer_tui(
    service: GenerationService,
    registre: ActionRegistry,
    *,
    console: Console | None = None,
    forcer: str | None = None,
) -> int:
    """Lance la TUI adaptée au terminal. Retourne le code de sortie."""
    mode = forcer or detecter_mode()
    if mode == MODE_CLEAVIER:
        from keyrock_cli.app import KeyRockCLI

        # Reprise de l'état courant du service dans la TUI clavier.
        application = KeyRockCLI(console_cible=console)
        application.service = service  # type: ignore[attr-defined]
        try:
            application.menu_principal()
        except KeyboardInterrupt:  # pragma: no cover - dépend du terminal
            return 130
        return 0

    try:
        app = _construire_app(service, registre)
    except ImportError:
        if console is not None:
            console.print("[bold red]Textual absent : bascule en mode clavier.[/bold red]")
        return lancer_tui(service, registre, console=console, forcer=MODE_CLEAVIER)
    app.run()
    return 0
