"""keyrock_cli — Interface terminal interactive de KeyRock."""

from __future__ import annotations

from keyrock_cli.app import ART_KEYROCK, CREDITS, KeyRockCLI, main
from keyrock_cli.banner import (
    ART_KEYROCK as ART_BANNIERE,
)
from keyrock_cli.banner import (
    CREDITS as CREDITS_BANNIERE,
)
from keyrock_cli.display import (
    SEQ_ALT_SCREEN_OFF,
    SEQ_ALT_SCREEN_ON,
    SEQ_EFFACER_TOUT,
    afficher_banniere,
    afficher_footer,
    afficher_tokens,
    attendre_enter,
    avec_buffer_alterne,
    basculer_buffer_alterne,
    copier_vers_presse_papier,
    ecrire_brut,
    effacer_ecran_et_scrollback,
    vider_presse_papier,
)
from keyrock_cli.interactions import (
    PRESETS_LONGUEUR,
    choisir_longueur,
    confirmer,
    demander_choix,
    demander_entier_borne,
    vers_generation_options,
)

__all__ = [
    "ART_BANNIERE",
    "ART_KEYROCK",
    "CREDITS",
    "CREDITS_BANNIERE",
    "PRESETS_LONGUEUR",
    "SEQ_ALT_SCREEN_OFF",
    "SEQ_ALT_SCREEN_ON",
    "SEQ_EFFACER_TOUT",
    "KeyRockCLI",
    "afficher_banniere",
    "afficher_footer",
    "afficher_tokens",
    "attendre_enter",
    "avec_buffer_alterne",
    "basculer_buffer_alterne",
    "choisir_longueur",
    "confirmer",
    "copier_vers_presse_papier",
    "demander_choix",
    "demander_entier_borne",
    "ecrire_brut",
    "effacer_ecran_et_scrollback",
    "main",
    "vers_generation_options",
    "vider_presse_papier",
]

__version__ = "1.0.0"
