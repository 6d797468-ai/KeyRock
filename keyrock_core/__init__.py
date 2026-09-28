"""keyrock_core — Logique métier isolée de KeyRock.

Ce package ne dépend d'aucune interface utilisateur : il est importable
depuis la CLI comme depuis l'API REST.
"""

from __future__ import annotations

from keyrock_core.actions import Action, ActionRegistry, ActionResultat
from keyrock_core.config import KeyRockSettings, get_settings, recharger_settings
from keyrock_core.generator import (
    ENTROPIE_MIN,
    LONGEUR_MAX,
    LONGEUR_MIN,
    CoreGenerator,
    GenerationOptions,
)
from keyrock_core.service import (
    GenerationResultat,
    GenerationService,
    OptionsState,
)

__all__ = [
    "ENTROPIE_MIN",
    "LONGEUR_MAX",
    "LONGEUR_MIN",
    "Action",
    "ActionRegistry",
    "ActionResultat",
    "CoreGenerator",
    "GenerationOptions",
    "GenerationResultat",
    "GenerationService",
    "KeyRockSettings",
    "OptionsState",
    "get_settings",
    "recharger_settings",
]

__version__ = "1.0.0"
