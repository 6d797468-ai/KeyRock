"""keyrock_shell — interface « shell-first » de KeyRock (exécutable `kr`).

keyrock_core   (métier, CSPRNG)
     ↓
keyrock_shell  (dispatcher kr, scripts)
     ↓
keyrock_cli    (TUI)
"""

from __future__ import annotations

from keyrock_shell.cli import (
    CODE_AIDE,
    CODE_ERREUR,
    CODE_ERREUR_USAGE,
    CODE_OK,
    COMMANDES,
    Reponse,
    main,
    refuser_secret,
    router,
)
from keyrock_shell.install import (
    DEBUT_BLOC,
    FIN_BLOC,
    desinstaller_shell,
    installer_shell,
)

__all__ = [
    "CODE_AIDE",
    "CODE_ERREUR",
    "CODE_ERREUR_USAGE",
    "CODE_OK",
    "COMMANDES",
    "DEBUT_BLOC",
    "FIN_BLOC",
    "Reponse",
    "desinstaller_shell",
    "installer_shell",
    "main",
    "refuser_secret",
    "router",
]

__version__ = "1.0.0"
