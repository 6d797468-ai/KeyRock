"""Dispatcher `kr` — interface « shell-first » de KeyRock.

Usage :

    kr                 → ouvre la TUI
    kr 32              → 2 tokens de 32 caractères
    kr gen 64          → forme explicite de kr 64
    kr c 32            → génère et copie (presse-papier purgé à la sortie)
    kr p 24            → mot de passe
    kr t 64            → token
    kr r 32            → régénération
    kr info | config   → état
    kr help            → aide
    kr gen 32 --json   → sortie machine-readable

Règle de sécurité : aucun secret n'est accepté en argument. Seuls des entiers
et des noms de commandes sont parsés ; tout argument ressemblant à une valeur
secrète est refusé explicitement.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from keyrock_core.actions import ActionRegistry
from keyrock_core.config import get_settings
from keyrock_core.service import GenerationResultat, GenerationService

__all__ = [
    "CODE_AIDE",
    "CODE_ERREUR",
    "CODE_ERREUR_USAGE",
    "CODE_OK",
    "COMMANDES",
    "Reponse",
    "main",
    "refuser_secret",
    "router",
]

CODE_OK = 0
CODE_AIDE = 0
CODE_ERREUR = 1
CODE_ERREUR_USAGE = 2

#: `kr 32` — une suite de chiffres est TOUJOURS une longueur ; les bornes 8-1024
#: produisent ensuite le bon message d'erreur (pas de faux positif "secret").
RE_LONGUEUR = re.compile(r"^\d{1,10}$")
COMMANDES: dict[str, str] = {
    "g": "gen",
    "gen": "gen",
    "generate": "gen",
    "générer": "gen",
    "c": "copy",
    "copy": "copy",
    "copier": "copy",
    "p": "password",
    "pass": "password",
    "password": "password",
    "mdp": "password",
    "t": "token",
    "tok": "token",
    "token": "token",
    "r": "regen",
    "regen": "regen",
    "regenerate": "regen",
    "i": "info",
    "info": "info",
    "config": "info",
    "h": "help",
    "help": "help",
    "aide": "help",
    "tui": "tui",
    "ui": "tui",
    "install-shell": "install-shell",
    "uninstall-shell": "uninstall-shell",
}

COMPOSITIONS_NOMMEES: dict[str, dict[str, bool]] = {
    "alpha": {"majuscules": True, "minuscules": True, "chiffres": False, "symboles": False},
    "alnum": {"majuscules": True, "minuscules": True, "chiffres": True, "symboles": False},
    "ascii": {"majuscules": True, "minuscules": True, "chiffres": True, "symboles": True},
}

LIBELLES_COMPOSITION = {
    "majuscules": "Majuscules (A-Z)",
    "minuscules": "Minuscules (a-z)",
    "chiffres": "Chiffres (0-9)",
    "symboles": "Symboles",
}

AIDE: tuple[tuple[str, str], ...] = (
    ("kr", "ouvre l'interface interactive"),
    ("kr 32", "2 tokens de 32 caractères"),
    ("kr gen 64", "forme explicite de kr 64"),
    ("kr c 32", "génère puis copie (presse-papier purgé)"),
    ("kr p 24", "mot de passe"),
    ("kr t 64", "token"),
    ("kr r 32", "régénération"),
    ("kr info", "état et configuration"),
    ("kr help", "cette aide"),
    ("kr gen 32 --json", "sortie machine-readable"),
)


@dataclass(frozen=True, slots=True)
class Reponse:
    """Réponse normalisée du dispatcher, consommée par `main`."""

    code: int = CODE_OK
    mode: str = "gen"
    resultat: GenerationResultat | None = None
    donnees: dict[str, Any] | None = None
    erreur: str | None = None
    texte: str | None = None

    def en_json(self) -> dict[str, Any]:
        charge: dict[str, Any] = {"mode": self.mode}
        if self.resultat is not None:
            charge.update(self.resultat.en_json())
        if self.donnees:
            charge.update(self.donnees)
        if self.erreur:
            charge["erreur"] = self.erreur
        return charge


def refuser_secret(argument: str) -> bool:
    """Vrai si l'argument n'est ni une longueur, ni une commande, ni une composition.

    Règle volontairement stricte (fail closed) : tout ce qui n'est pas
    explicitement reconnu est refusé. Un seul message couvre le cas « commande
    mal orthographiée » et le cas « secret » — distinguer les deux fournirait un
    oracle inutile à qui devine des secrets.
    """
    if RE_LONGUEUR.match(argument):
        return False
    return argument.lower() not in COMMANDES and argument.lower() not in COMPOSITIONS_NOMMEES


def construire_parser() -> argparse.ArgumentParser:
    """Construit le parseur d'arguments de `kr`."""
    parser = argparse.ArgumentParser(
        prog="kr",
        description="KeyRock — générateur de tokens cryptographiques (CSPRNG).",
        epilog="Exemples : kr | kr 32 | kr c 32 | kr p 24 | kr gen 64 --json | kr info",
        add_help=False,
    )
    parser.add_argument("arguments", nargs="*", metavar="COMMANDE")
    parser.add_argument("--json", action="store_true", help="sortie machine-readable")
    parser.add_argument("--no-color", action="store_true", help="désactive les couleurs")
    parser.add_argument("--count", "-n", type=int, default=2, help="nombre de tokens")
    parser.add_argument("--composition", "-C", default=None, help="alpha | alnum | ascii")
    parser.add_argument("--help", "-h", action="store_true", help="affiche cette aide")
    return parser


def _analyser(argv: Sequence[str]) -> tuple[list[str], argparse.Namespace, list[str]]:
    """Découpe l'argv. Retourne (positionnels, options, options inconnues)."""
    parser = construire_parser()
    namespace, inconnues = parser.parse_known_args(list(argv))
    # argparse place les positionnels connus dans `namespace.arguments` ; seul ce
    # qui ressemble à une option non reconnue reste dans `inconnues`.
    return list(namespace.arguments), namespace, [a for a in inconnues if a.startswith("-")]


def _longueur(brute: str | None, defaut: int) -> int:
    if brute is None:
        return defaut
    if not RE_LONGUEUR.match(brute):
        raise ValueError(f"Longueur invalide : {brute!r}. Attendu : un entier (8-1024).")
    return int(brute)


def _composition_positonnelle(reste: Sequence[str], composition: str | None) -> str | None:
    """`kr gen 32 alpha` : la composition peut être positionnelle ou via --composition."""
    if composition is not None:
        return composition
    for argument in reste[1:]:
        if argument.lower() in COMPOSITIONS_NOMMEES:
            return argument
    return None


def _composition(nom: str | None) -> dict[str, bool] | None:
    if nom is None:
        return None
    table = COMPOSITIONS_NOMMEES.get(nom.lower())
    if table is None:
        raise ValueError(f"Composition inconnue : {nom!r}. Attendu : alpha, alnum, ascii.")
    return dict(table)


def router(
    argv: Sequence[str],
    service: GenerationService,
    registre: ActionRegistry,
    *,
    nombre: int = 2,
    composition: str | None = None,
) -> Reponse:
    """Interprète les arguments. Ne lève jamais : retourne toujours une `Reponse`."""
    arguments = list(argv)
    try:
        return _router(arguments, service, registre, nombre, composition)
    except ValueError as exc:
        return Reponse(code=CODE_ERREUR, mode="erreur", erreur=str(exc))


def _router(
    arguments: list[str],
    service: GenerationService,
    registre: ActionRegistry,
    nombre: int,
    composition: str | None,
) -> Reponse:
    for argument in arguments:
        if not argument.startswith("-") and refuser_secret(argument):
            # Message volontairement générique et SANS rejeu de la valeur : un
            # secret ne doit jamais repartir vers le terminal, l'historique du
            # shell, les journaux de CI ou un rapport de bug.
            return Reponse(
                code=CODE_ERREUR,
                mode="erreur",
                erreur=(
                    "Argument refusé. KeyRock n'accepte en ligne de commande que des "
                    "longueurs, des commandes et des compositions connues — jamais un "
                    "secret. L'argument n'a pas été utilisé. Voir `kr help`."
                ),
            )

    if not arguments:
        return Reponse(mode="tui")

    premier = arguments[0].lower()
    reste = arguments[1:]

    if premier in {"-h", "--help", "h", "help", "aide"}:
        return Reponse(mode="aide")

    # `kr c 32` et `kr 32 c` sont tous deux acceptés.
    if premier in {"c", "copy", "copier"}:
        return _generer(
            service,
            registre,
            _longueur(reste[0] if reste else None, 32),
            nombre,
            composition,
            mode="copy",
        )
    if len(arguments) >= 2 and reste[0].lower() in {"c", "copy", "copier"}:
        return _generer(service, registre, _longueur(premier, 32), nombre, composition, mode="copy")

    if premier in COMMANDES:
        commande = COMMANDES[premier]
    elif RE_LONGUEUR.match(premier):
        return _generer(service, registre, int(premier), nombre, composition, mode="gen")
    else:
        return Reponse(
            code=CODE_ERREUR_USAGE, mode="erreur", erreur=f"Commande inconnue : {premier!r}"
        )

    if commande == "tui":
        return Reponse(mode="tui")
    if commande == "help":
        return Reponse(mode="aide")
    if commande == "info":
        return Reponse(mode="info", donnees=dict(registre.executer("info").donnees or {}))
    if commande in {"install-shell", "uninstall-shell"}:
        from keyrock_shell.install import (
            desinstaller_shell,
            installer_shell,
        )

        code, texte = installer_shell() if commande == "install-shell" else desinstaller_shell()
        return Reponse(code=code, mode=commande, texte=texte)
    if commande == "gen":
        return _generer(
            service,
            registre,
            _longueur(reste[0] if reste else None, 32),
            nombre,
            _composition_positonnelle(reste, composition),
            "gen",
        )
    if commande in {"password", "token"}:
        defaut = 24 if commande == "password" else 64
        composition_finale = _composition_positonnelle(reste, composition) or "ascii"
        return _generer(
            service,
            registre,
            _longueur(reste[0] if reste else None, defaut),
            1,
            composition_finale,
            commande,
        )
    if commande == "regen":
        if reste:
            service.set_longueur(_longueur(reste[0], service.longueur()))
        return _generer(
            service,
            registre,
            service.longueur(),
            nombre,
            _composition_positonnelle(reste, composition),
            "regen",
        )
    return Reponse(code=CODE_ERREUR_USAGE, mode="erreur", erreur=f"Commande inconnue : {premier!r}")


def _generer(
    service: GenerationService,
    registre: ActionRegistry,
    longueur: int,
    nombre: int,
    composition: str | None,
    mode: str,
) -> Reponse:
    table = _composition(composition)
    resultat = service.generer_avec(longueur, nombre=max(1, nombre), composition=table)
    registre.memoriser(resultat)
    return Reponse(mode=mode, resultat=resultat)


def _console(no_color: bool) -> Console:
    return Console(no_color=no_color, highlight=False)


def _aide(console: Console) -> None:
    grille = Table.grid(padding=(0, 2))
    for exemple, description in AIDE:
        grille.add_row(Text(exemple, style="bold cyan"), description)
    console.print(Panel(grille, title="[bold]KeyRock — kr[/bold]", border_style="cyan"))


def _afficher_resultat(console: Console, resultat: GenerationResultat, titre: str) -> None:
    corps = Text()
    couleurs = ("bold green", "bold cyan", "bold magenta", "bold yellow")
    for index, token in enumerate(resultat.tokens):
        corps.append(f"TOKEN {index + 1}\n", style=couleurs[index % len(couleurs)])
        corps.append(f"{token}\n", style="white")
        if index != len(resultat.tokens) - 1:
            corps.append("\n")
    console.print(
        Panel(
            corps,
            title=(
                f"[bold]{titre} — {resultat.longueur} car. | {resultat.entropie_bits} bits[/bold]"
            ),
            border_style="green",
            padding=(1, 3),
        )
    )


def _afficher_info(console: Console, donnees: dict[str, Any]) -> None:
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_row("Longueur", f"[bold yellow]{donnees['longueur']}[/]")
    table.add_row("Entropie", f"{donnees['entropie_bits']} bits")
    table.add_row("Alphabet", f"{donnees['alphabet']} caractères")
    table.add_row("", "")
    for champ, libelle in LIBELLES_COMPOSITION.items():
        actif = bool(donnees["composition"][champ])
        table.add_row(libelle, "[bold green]✓[/]" if actif else "[bold red]✗[/]")
    table.add_row("", "")
    table.add_row("Presets", ", ".join(str(p) for p in donnees["presets"]))
    console.print(Panel(table, title="[bold]keyrock info[/bold]", border_style="blue"))


def main(argv: Sequence[str] | None = None) -> int:
    arguments, options, inconnues = _analyser(list(argv) if argv is not None else sys.argv[1:])
    console = _console(options.no_color or not sys.stdout.isatty())

    if options.help:
        _aide(console)
        return CODE_AIDE

    if inconnues:
        message = f"Option inconnue : {inconnues[0]!r}. Utilisez `kr help`."
        if options.json:
            print(json.dumps({"erreur": message}, ensure_ascii=False))
        else:
            console.print(f"[bold red]✗[/bold red] {message}")
        return CODE_ERREUR_USAGE

    service = GenerationService(get_settings())
    registre = ActionRegistry(service)

    if options.help:
        _aide(console)
        return CODE_AIDE

    reponse = router(
        arguments,
        service,
        registre,
        nombre=options.count,
        composition=options.composition,
    )

    if reponse.erreur is not None:
        if options.json:
            print(json.dumps({"erreur": reponse.erreur}, ensure_ascii=False))
        else:
            console.print(f"[bold red]✗[/bold red] {reponse.erreur}")
        return reponse.code

    if options.json:
        print(json.dumps(reponse.en_json(), ensure_ascii=False, sort_keys=True))
        return CODE_OK

    if reponse.texte is not None:
        console.print(reponse.texte)
        return reponse.code
    if reponse.mode == "tui":
        from keyrock_cli.tui import lancer_tui

        return lancer_tui(service, registre, console=console)
    if reponse.mode == "aide":
        _aide(console)
        return CODE_AIDE
    if reponse.mode == "info":
        _afficher_info(console, reponse.donnees or {})
        return CODE_OK
    if reponse.resultat is not None:
        if reponse.mode == "copy":
            from keyrock_cli.display import copier_vers_presse_papier

            # Ne surtout pas vider ici : le token doit rester collable après la
            # sortie de `kr`. L'effacement est confié au processus détaché.
            if copier_vers_presse_papier(reponse.resultat.token1, delai_secondes=30.0):
                console.print("[dim]Presse-papier purgé automatiquement après 30 s.[/dim]")
            else:
                console.print("[bold red]Presse-papier indisponible.[/bold red]")
        _afficher_resultat(console, reponse.resultat, reponse.mode.upper())
    return CODE_OK


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
