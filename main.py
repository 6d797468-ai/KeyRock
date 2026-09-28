"""Point d'entrée historique de KeyRock.

L'application vit désormais dans le package `keyrock_cli`. Ce module est
conservé comme lanceur de compatibilité (`python main.py`).
"""

from __future__ import annotations

import sys

from keyrock_cli.app import main

__all__ = ["main"]


if __name__ == "__main__":
    sys.exit(main())
