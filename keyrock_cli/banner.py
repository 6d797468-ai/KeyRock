"""Bannière KeyRock — art ASCII d'origine + crédits.

L'art est repris caractère pour caractère de `logo-favicon/ascii-art.txt`
(20 lignes, 52 colonnes max). Seul le padding de fin de ligne a été retiré ;
la géométrie du dessin n'a pas été touchée.
"""

from __future__ import annotations

__all__ = ["ART_KEYROCK", "CREDITS"]

ART_KEYROCK = """
                                        █
                                    ██ ▒████
                                 ████  ▓░░░▒██
                                 ▒██  ▓▒░░░░▒█ █
                              ███▓░  ▓░░░░░░░█ ██
                              █░░▓░ █▒░░░░░░░█ ▓░█
                             █▒░░█ ▓▒░░░░░░░░█ ▓ ░█
                             █░░▒█ █░░░░░░░░▒█ ▓  ▓
                             █░▒█  ▓▒░░░░░░▒▒▒ ▓░ ▒░
                            ███░ ░▓  ░░▒▒░░  ▓▓  ░▒█
                              ░░░░ █▓▓▓  ▓▓▓█ ░░▒▓░
                               █▓▒   ▓ ▓▓ ▓   ▒▓█
                                 ▒█▓ █ ▓▓ █ ▓█▒
                                     █ ▒▓ █
                                     █ ▒▓ █
                                     █ ▒▓   ██
                                     █ ▒▓ █
                                     █ ▒▓   ██
                                     █ ▒▓░█
                                       ██
"""

NOM_OUTIL = "KEYROCK"
SIGNATURE = "Générateur de Clés & Tokens Cryptographiques"
MENTION_AGENCE = "Créé pour le compte de Vextra Agency"
MENTION_AUTEUR = "Auteur : Nawfel Reghai"

#: (texte, style rich) — affichés sous l'art, dans cet ordre.
CREDITS: tuple[tuple[str, str], ...] = (
    (NOM_OUTIL, "bold cyan"),
    (SIGNATURE, "italic white"),
    (MENTION_AGENCE, "bold red"),
    (MENTION_AUTEUR, "dim white"),
)
