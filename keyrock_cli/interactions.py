"""Interactions clavier de la CLI KeyRock (bornes de longueur, validations).

La lecture des réponses est faite ici, et non via `rich.prompt.Prompt.ask` :
sur un flux d'entrée épuisé (Ctrl+D, pipe clos), `rich` renvoie silencieusement
la valeur par défaut, ce qui provoquerait une boucle infinie de génération.
`lire_reponse` lève `EOFError`, ce qui permet une sortie propre.
"""

from __future__ import annotations

from typing import cast

from rich.console import Console

from keyrock_cli.display import console, effacer_ecran_et_scrollback
from keyrock_core.generator import (
    LONGEUR_MAX,
    LONGEUR_MIN,
    CoreGenerator,
    GenerationOptions,
)

__all__ = [
    "PRESETS_LONGUEUR",
    "choisir_longueur",
    "confirmer",
    "demander_choix",
    "demander_entier_borne",
    "lire_reponse",
    "vers_generation_options",
]

ESSAIS_MAX = 20


def lire_reponse(invite: str, *, console_cible: Console | None = None) -> str:
    """Affiche `invite` et lit une ligne. Lève `EOFError` si le flux est épuisé."""
    (console_cible or console).print(invite, end="", markup=True, emoji=True, soft_wrap=True)
    return input()


def demander_choix(
    invite: str,
    choix_valides: list[str],
    defaut: str,
    *,
    console_cible: Console | None = None,
) -> str:
    """Demande un choix parmi `choix_valides`. Lève `EOFError` sur flux épuisé.

    Une réponse vide valide le choix par défaut (Entrée).
    """
    c = console_cible or console
    suffixe = "/".join(choix_valides)
    for _ in range(ESSAIS_MAX):
        reponse = lire_reponse(f"{invite} [{suffixe}] ({defaut}) ", console_cible=c).strip()
        if not reponse:
            return defaut
        if reponse in choix_valides:
            return reponse
        c.print(f"[red]Choix invalide : {reponse!r}. Réponses possibles : {suffixe}.[/red]")
    raise EOFError("Trop de réponses invalides : abandon.")


def demander_entier_borne(
    invite: str,
    minimum: int = LONGEUR_MIN,
    maximum: int = LONGEUR_MAX,
    *,
    console_cible: Console | None = None,
) -> int | None:
    """Demande un entier dans [minimum, maximum]. Retourne `None` si l'utilisateur abandonne."""
    c = console_cible or console
    for _ in range(ESSAIS_MAX):
        try:
            brute = lire_reponse(f"{invite} [{minimum}-{maximum}] ", console_cible=c).strip()
        except (EOFError, KeyboardInterrupt):
            return None
        try:
            valeur = int(brute)
        except ValueError:
            c.print(f"[red]Saisie invalide : {brute!r}. Un entier est attendu.[/red]")
            continue
        if minimum <= valeur <= maximum:
            return valeur
        c.print(
            f"[red]Valeur hors bornes : {minimum} ≤ longueur ≤ {maximum} (reçu : {valeur}).[/red]"
        )
    return None


def confirmer(message: str, *, console_cible: Console | None = None) -> bool:
    """Invite oui/non. Retourne `False` sur annulation (Ctrl+C / Ctrl+D)."""
    c = console_cible or console
    try:
        reponse = demander_choix(
            f"\n[bold cyan]>[/bold cyan] {message}", ["o", "n"], "n", console_cible=c
        )
    except (EOFError, KeyboardInterrupt):
        return False
    return reponse == "o"


def vers_generation_options(options: dict[str, object]) -> GenerationOptions:
    """Convertit le dictionnaire d'état de la CLI en `GenerationOptions` immuable."""
    return GenerationOptions(
        longueur=cast(int, options["longueur"]),
        majuscules=bool(options["maj"]),
        minuscules=bool(options["min"]),
        chiffres=bool(options["chiffres"]),
        symboles=bool(options["symboles"]),
    )


PRESETS_LONGUEUR: dict[str, int] = {
    "1": 16,
    "2": 32,
    "3": 64,
    "4": 0,
}

LIBELLES_LONGUEUR: dict[str, str] = {
    "1": "16 caractères (Standard)",
    "2": "32 caractères (Recommandé)",
    "3": "64 caractères (Haute sécurité)",
    "4": "Longueur personnalisée",
}


def choisir_longueur(
    options: dict[str, object],
    *,
    console_cible: Console | None = None,
) -> dict[str, object]:
    """Affiche le menu de longueur et met à jour `options` (bornes 8..1024)."""
    c = console_cible or console
    effacer_ecran_et_scrollback(cible=c)

    c.print("[bold yellow]Longueur du token :[/bold yellow]")
    c.print(f"  [dim]Bornes autorisées : {LONGEUR_MIN} à {LONGEUR_MAX} caractères.[/dim]")
    for cle, libelle in LIBELLES_LONGUEUR.items():
        c.print(f"  [bold cyan]{cle}[/bold cyan] - {libelle}")

    try:
        choix = demander_choix(
            "\n[bold cyan]>[/bold cyan] Choix", ["1", "2", "3", "4"], "2", console_cible=c
        )
    except (EOFError, KeyboardInterrupt):
        return options

    if choix != "4":
        options["longueur"] = PRESETS_LONGUEUR[choix]
        return options

    longueur = demander_entier_borne(
        "Entrez la longueur souhaitée", LONGEUR_MIN, LONGEUR_MAX, console_cible=c
    )
    if longueur is None:
        return options

    options["longueur"] = longueur
    avertir_si_entropie_faible(options, console_cible=c)
    return options


def avertir_si_entropie_faible(
    options: dict[str, object], *, console_cible: Console | None = None
) -> float | None:
    """Affiche un avertissement si la configuration ne satisfait pas le seuil NIST."""
    c = console_cible or console
    if not any(bool(options[cle]) for cle in ("maj", "min", "chiffres", "symboles")):
        return None
    entropie = CoreGenerator.calculer_entropie(vers_generation_options(options))
    if entropie < 80:
        c.print(
            f"[bold yellow]⚠ Entropie estimée : {entropie} bits — sous le seuil "
            "recommandé de 80 bits (NIST SP 800-63B).[/bold yellow]"
        )
    else:
        c.print(f"[dim]Entropie estimée : {entropie} bits.[/dim]")
    return entropie
