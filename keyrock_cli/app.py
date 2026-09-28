"""Application CLI KeyRock — interface terminal (TUI)."""

from __future__ import annotations

import logging
import sys

from rich.align import Align
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from keyrock_cli.banner import ART_KEYROCK, CREDITS
from keyrock_cli.display import (
    afficher_banniere,
    afficher_footer,
    afficher_tokens,
    attendre_enter,
    console,
    copier_vers_presse_papier,
    effacer_ecran_et_scrollback,
    vider_presse_papier,
)
from keyrock_cli.interactions import (
    choisir_longueur,
    confirmer,
    demander_choix,
    vers_generation_options,
)
from keyrock_core.generator import LONGEUR_MAX, LONGEUR_MIN, CoreGenerator

logger = logging.getLogger("keyrock.cli")

__all__ = ["ART_KEYROCK", "CREDITS", "KeyRockCLI", "main"]


class KeyRockCLI:
    """Gestionnaire de l'interface utilisateur en ligne de commande pour KeyRock."""

    def __init__(self, console_cible: Console | None = None) -> None:
        self.console = console_cible or console
        self.options: dict[str, object] = {
            "maj": True,
            "min": True,
            "chiffres": True,
            "symboles": True,
            "longueur": 32,
        }

    # ------------------------------------------------------------------
    # Affichage
    # ------------------------------------------------------------------
    def afficher_banniere(self) -> None:
        """Bannière — art ASCII d'origine + crédits, écran et scrollback purgés."""
        afficher_banniere(ART_KEYROCK, credits=CREDITS, cible=self.console)

    def afficher_footer(self) -> None:
        afficher_footer(cible=self.console)

    def afficher_configuration(self) -> None:
        table = Table(show_header=False, box=None, padding=(0, 2))

        def statut(actif: object) -> str:
            return "[bold green]✓ ACTIVÉ[/]" if actif else "[bold red]✗ DÉSACTIVÉ[/]"

        table.add_row("1.", "Majuscules (A-Z)", statut(self.options["maj"]))
        table.add_row("2.", "Minuscules (a-z)", statut(self.options["min"]))
        table.add_row("3.", "Chiffres (0-9)", statut(self.options["chiffres"]))
        table.add_row("4.", "Symboles (@, #, $)", statut(self.options["symboles"]))
        table.add_row("", "", "")
        table.add_row(
            "5.",
            "Longueur du Token",
            f"[bold yellow]{self.options['longueur']} caractères[/]"
            f" [dim]({LONGEUR_MIN}-{LONGEUR_MAX})[/dim]",
        )

        self.console.print(
            Panel(
                Align.center(table),
                title="[bold]Configuration Actuelle[/bold]",
                border_style="blue",
                padding=(1, 2),
            )
        )

    def afficher_menu_actions(self) -> None:
        actions = Table.grid(padding=(0, 2))
        actions.add_row("[bold cyan]1-5[/bold cyan]", "Modifier un paramètre")
        actions.add_row("[bold green]6[/bold green]", "⚡ GÉNÉRER LES CLÉS")
        actions.add_row("[bold red]0[/bold red]", "Quitter KeyRock")
        self.console.print(Align.center(actions))

    # ------------------------------------------------------------------
    # Boucle principale
    # ------------------------------------------------------------------
    def menu_principal(self) -> None:
        while True:
            self.afficher_banniere()
            self.afficher_configuration()
            self.afficher_menu_actions()
            self.afficher_footer()

            try:
                choix = demander_choix(
                    "\n[bold cyan]>[/bold cyan] Choix",
                    ["0", "1", "2", "3", "4", "5", "6"],
                    "6",
                    console_cible=self.console,
                )
            except (EOFError, KeyboardInterrupt):
                effacer_ecran_et_scrollback(cible=self.console)
                self.console.print("\n\n[bold red]Arrêt manuel du script.[/bold red]")
                return
            self.traiter_choix(choix)

    def traiter_choix(self, choix: str) -> None:
        if choix == "1":
            self.options["maj"] = not self.options["maj"]
        elif choix == "2":
            self.options["min"] = not self.options["min"]
        elif choix == "3":
            self.options["chiffres"] = not self.options["chiffres"]
        elif choix == "4":
            self.options["symboles"] = not self.options["symboles"]
        elif choix == "5":
            self.afficher_banniere()
            choisir_longueur(self.options, console_cible=self.console)
        elif choix == "6":
            self.executer_generation()
        elif choix == "0":
            effacer_ecran_et_scrollback(cible=self.console)
            self.console.print("[bold green]Fermeture de KeyRock. À bientôt ![/bold green]")
            self.console.file.flush()
            raise SystemExit(0)

    # ------------------------------------------------------------------
    # Génération
    # ------------------------------------------------------------------
    def executer_generation(self) -> None:
        if not any(bool(self.options[cle]) for cle in ("maj", "min", "chiffres", "symboles")):
            self.console.print(
                "\n[bold red]❌ Erreur : vous devez sélectionner au moins un type "
                "de caractère.[/bold red]"
            )
            attendre_enter(cible=self.console)
            return

        options = vers_generation_options(self.options)

        # Les tokens ne sont jamais journalisés : seuls des métadonnées le sont.
        try:
            tokens = CoreGenerator.generer_plusieurs(options, nombre=2)
            entropie = CoreGenerator.calculer_entropie(options)
        except ValueError as exc:
            self.console.print(f"\n[bold red]❌ Génération impossible :[/bold red] {exc}")
            attendre_enter(cible=self.console)
            return
        except Exception:
            logger.exception("Échec inattendu de la génération")
            self.console.print(
                "\n[bold red]❌ Erreur interne de génération (détails dans les logs "
                "structurés, aucun token journalisé).[/bold red]"
            )
            attendre_enter(cible=self.console)
            return

        afficher_tokens(tokens, options.longueur, entropie, cible=self.console)
        self._proposer_copie(tokens)
        attendre_enter(cible=self.console)
        vider_presse_papier()
        effacer_ecran_et_scrollback(cible=self.console)

    def _proposer_copie(self, tokens: list[str]) -> None:
        """Propose la copie dans le presse-papier avec effacement automatique."""
        if not confirmer(
            "Copier le TOKEN 1 dans le presse-papier ? (o/n)", console_cible=self.console
        ):
            return
        if copier_vers_presse_papier(tokens[0], delai_secondes=30.0):
            self.console.print(
                "[dim]Presse-papier copié — il sera vidé automatiquement dans 30 s "
                "à la sortie de l'écran.[/dim]"
            )
        else:
            self.console.print("[bold red]Presse-papier indisponible sur ce système.[/bold red]")


def main() -> int:
    logging.basicConfig(
        level=logging.INFO, format="%(levelname)s %(name)s: %(message)s", stream=sys.stderr
    )
    app = KeyRockCLI()
    try:
        app.menu_principal()
    except KeyboardInterrupt:
        effacer_ecran_et_scrollback()
        console.print("\n\n[bold red]Arrêt manuel du script.[/bold red]")
    except EOFError:
        effacer_ecran_et_scrollback()
        console.print("\n\n[bold red]Fin d'entrée (Ctrl+D).[/bold red]")
    except Exception:
        logger.exception("Erreur inattendue dans la boucle principale")
        effacer_ecran_et_scrollback()
        console.print(
            "\n[bold red]Une erreur inattendue est survenue. "
            "Aucun token n'a été journalisé.[/bold red]"
        )
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
