"""Affichage terminal de KeyRock — effacement sécurisé du scrollback.

`rich.Console.clear()` n'émet que `\\033[2J\\033[H` : il efface l'écran
visible mais laisse intact le buffer de scrollback (historique terminal,
tmux, screen). Les tokens y resteraient lisibles.

Les fonctions de ce module purgent explicitement le scrollback
(`\\033[3J`) et utilisent le buffer alternatif pour l'affichage des
tokens, afin de satisfaire l'exigence « Zéro Persistance ».
"""

from __future__ import annotations

import contextlib
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from typing import TypeVar

from rich.align import Align
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

__all__ = [
    "SEQ_ALT_SCREEN_OFF",
    "SEQ_ALT_SCREEN_ON",
    "SEQ_EFFACER_TOUT",
    "afficher_banniere",
    "afficher_footer",
    "afficher_tokens",
    "attendre_enter",
    "avec_buffer_alterne",
    "basculer_buffer_alterne",
    "copier_vers_presse_papier",
    "ecrire_brut",
    "effacer_ecran_et_scrollback",
    "purger_presse_papier_dans",
    "vider_presse_papier",
]

SEQ_EFFACER_TOUT = "\033[3J\033[2J\033[H"
SEQ_ALT_SCREEN_OFF = "\033[?1049l"
SEQ_ALT_SCREEN_ON = "\033[?1049h"

console = Console()

T = TypeVar("T")

#: Minuteur d'effacement du presse-papier, pour un processus qui reste vivant
#: (TUI). Inutile en ligne de commande : voir `demarrer_purge_presse_papier`.
_minuteur: threading.Timer | None = None


def effacer_ecran_et_scrollback(*, cible: Console | None = None) -> None:
    """Efface l'écran visible ET le buffer de scrollback.

    Séquence émise :
      - `\\033[3J` : purge le scrollback (xterm)
      - `\\033[2J` : efface l'écran visible
      - `\\033[H`  : replace le curseur en haut à gauche
    """
    ecrire_brut(SEQ_EFFACER_TOUT, cible=cible)


def ecrire_brut(sequence: str, *, cible: Console | None = None) -> None:
    """Écrit une séquence de contrôle directement sur la sortie.

    `Console.control()` laisse passer ces codes uniquement lorsque la sortie
    est un terminal ; l'écriture directe garantit un comportement déterministe
    et verifiable dans tous les contextes (tty, pipe, tests).
    """
    c = cible or console
    c.file.write(sequence)
    c.file.flush()


def basculer_buffer_alterne(activer: bool, *, cible: Console | None = None) -> None:
    """Bascule entre le buffer normal et le buffer d'écran alternatif."""
    ecrire_brut(SEQ_ALT_SCREEN_ON if activer else SEQ_ALT_SCREEN_OFF, cible=cible)


def avec_buffer_alterne(fonction: Callable[[], T]) -> T:
    """Exécute `fonction` dans le buffer d'écran alternatif (isolé du scrollback)."""
    c = console
    basculer_buffer_alterne(True, cible=c)
    try:
        return fonction()
    finally:
        effacer_ecran_et_scrollback(cible=c)
        basculer_buffer_alterne(False, cible=c)


def copier_vers_presse_papier(texte: str, *, delai_secondes: float = 30.0) -> bool:
    """Copie `texte` dans le presse-papier et programme son effacement.

    Le presse-papier doit survivre à la fin du processus — sinon `kr c 32`
    copierait puis viderait aussitôt, et l'utilisateur ne pourrait rien
    coller. L'effacement est donc confié à un **purificateur détaché**, un
    processus séparé qui attend `delai_secondes` puis écrit une chaîne vide.

    Un minuteur local est aussi armé pour les processus qui restent vivants
    (TUI) ; il est sans effet ici, les deux mécanismes se renforçant.

    Ne bloque jamais l'appelant. Retourne `True` si la copie a réussi.
    """
    if not _module_presse_papier():
        return False
    if not _copier_brut(texte):
        return False
    if delai_secondes <= 0:
        # Cas limite : on vide immédiatement, une seule fois, sans détacher.
        _annuler_effacement()
        _copier_brut("")
        return True
    demarrer_purge_presse_papier(delai_secondes)
    _programmer_effacement(delai_secondes)
    return True


def demarrer_purge_presse_papier(delai_secondes: float = 30.0) -> bool:
    """Lance un processus détaché qui vide le presse-papier après le délai.

    Le processus est totalement détaché (nouvelle session, E/S sur
    /dev/null) pour ne jamais hériter des tubes du script appelant : sans cela
    un `kr c 32` dans un script laisserait un lecteur en attente de la fin.

    Retourne `True` si le purificateur a pu être lancé.
    """
    if delai_secondes <= 0:
        return vider_presse_papier()
    try:
        subprocess.Popen(  # noqa: S603 — python + script interne, aucun input utilisateur
            [sys.executable, "-c", _SCRIPT_PURGE, repr(float(delai_secondes))],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            close_fds=True,
        )
    except (OSError, ValueError):
        return False
    return True


#: Programme exécuté par le processus détaché : attend, puis vide.
#: Importé paresseusement pour ne charger pyperclip que si besoin.
_SCRIPT_PURGE = (
    "import sys,time;time.sleep(float(sys.argv[1]));"
    "\ntry:\n import pyperclip;pyperclip.copy('')\nexcept Exception:pass\n"
)


def purger_presse_papier_dans(delai_secondes: float) -> None:
    """Point d'entrée testable du purificateur détaché (sans détachement)."""
    time.sleep(max(0.0, delai_secondes))
    _copier_brut("")


def vider_presse_papier() -> bool:
    """Vide le presse-papier immédiatement et annule l'effacement programmé."""
    _annuler_effacement()
    return _module_presse_papier() is not None and _copier_brut("")


def _module_presse_papier() -> object | None:
    try:
        import pyperclip
    except ImportError:
        return None
    return pyperclip


def _copier_brut(texte: str) -> bool:
    pyperclip = _module_presse_papier()
    if pyperclip is None:
        return False
    try:
        pyperclip.copy(texte)  # type: ignore[attr-defined]
    except Exception:
        return False
    return True


def _programmer_effacement(delai_secondes: float) -> None:
    """Efface le presse-papier après `delai_secondes` sans bloquer l'appelant.

    Arme aussi le purgeur détaché : le minuteur local meurt avec le processus,
    alors qu'un jeton collé depuis `kr c 32` doit être purgé même après la
    sortie de `kr`.
    """
    _annuler_effacement()
    if delai_secondes <= 0:
        _copier_brut("")
        return
    global _minuteur
    _minuteur = threading.Timer(delai_secondes, _copier_brut, args=("",))
    _minuteur.daemon = True
    _minuteur.start()


def _annuler_effacement() -> None:
    global _minuteur
    if _minuteur is not None:
        _minuteur.cancel()
        _minuteur = None


def afficher_banniere(
    logo: str, *, credits: tuple[tuple[str, str], ...] = (), cible: Console | None = None
) -> None:
    """Affiche la bannière KeyRock : art ASCII puis crédits (écran purgé au préalable)."""
    c = cible or console
    effacer_ecran_et_scrollback(cible=c)

    art = Text.from_markup(f"[bold cyan]{logo}[/bold cyan]")
    art.justify = "center"

    layout = Table.grid(padding=(0, 1))
    layout.add_column(justify="center", width=c.width - 4)
    layout.add_row(art)
    for texte, style in credits:
        ligne = Text(texte, style=style, justify="center")
        layout.add_row(ligne)

    c.print(Panel(layout, border_style="cyan", padding=(1, 2)))


def afficher_footer(*, cible: Console | None = None) -> None:
    """Affiche la mention d'auteur en pied d'écran."""
    c = cible or console
    footer = Text("\n© 2026 KeyRock - Développé par Nawfel Reghai", style="dim", justify="center")
    c.print(footer)


def afficher_tokens(
    tokens: list[str],
    longueur: int,
    entropie: float | None = None,
    *,
    cible: Console | None = None,
) -> None:
    """Affiche les tokens dans le buffer alternatif (jamais dans le scrollback)."""
    c = cible or console
    basculer_buffer_alterne(True, cible=c)
    try:
        effacer_ecran_et_scrollback(cible=c)

        result_text = Text()
        couleurs = ["bold green", "bold cyan", "bold magenta", "bold yellow"]
        for index, token in enumerate(tokens):
            couleur = couleurs[index % len(couleurs)]
            result_text.append(f"🟢 TOKEN {index + 1} :\n", style=couleur)
            result_text.append(f"{token}\n", style="white")
            if index != len(tokens) - 1:
                result_text.append("\n")

        titre = f"[bold]CLÉS GÉNÉRÉES (L: {longueur}"
        if entropie is not None:
            titre += f" | {entropie} bits"
        titre += ")[/bold]"

        c.print(
            Panel(
                Align.center(result_text),
                title=titre,
                border_style="green",
                padding=(1, 4),
            )
        )
        c.print(
            Text(
                "⚠ Ces tokens seront effacés de l'écran et du scrollback à la fin de l'affichage.",
                style="bold yellow",
                justify="center",
            )
        )
        afficher_footer(cible=c)
    finally:
        effacer_ecran_et_scrollback(cible=c)
        basculer_buffer_alterne(False, cible=c)


def attendre_enter(
    message: str = "\nAppuyez sur Entrée pour revenir au menu",
    *,
    cible: Console | None = None,
) -> None:
    """Attend une validation utilisateur, puis purge l'écran et le scrollback."""
    with contextlib.suppress(EOFError, KeyboardInterrupt):
        input(message)
    effacer_ecran_et_scrollback(cible=cible)


def quitter_terminal(console_cible: Console | None = None) -> None:
    """Affiche le message de fermeture puis quitte proprement."""
    c = console_cible or console
    effacer_ecran_et_scrollback(cible=c)
    c.print("[bold green]Fermeture de KeyRock. À bientôt ![/bold green]")
    sys.stdout.flush()
    raise SystemExit(0)
