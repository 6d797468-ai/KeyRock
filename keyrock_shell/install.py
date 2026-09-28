"""Intégration shell — installation réversible et idempotente du bloc KEYROCK.

Principes :
  - on ne réécrit JAMAIS un fichier shell arbitrairement : seul un bloc délimité
    `# >>> KEYROCK >>>` … `# <<< KEYROCK <<<` est ajouté ou retiré ;
  - l'opération est idempotente : deux `install-shell` ne dupliquent rien ;
  - la TUI ne dépend jamais de ce bloc (elle fonctionne sans shell configuré).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

__all__ = [
    "DEBUT_BLOC",
    "FIN_BLOC",
    "candidats_rc",
    "contenu_bloc",
    "desinstaller_shell",
    "installer_shell",
    "resoudre_repertoire",
]

DEBUT_BLOC = "# >>> KEYROCK >>>"
FIN_BLOC = "# <<< KEYROCK <<<"

# Le bloc est volontairement POSIX : une seule ligne, une seule source, aucune
# dépendance à bash/zsh-specific. La complétion est facultative (test -f).
# `@SHELL@` est remplacé, pas formaté : `${XDG_CONFIG_HOME:-...}` contient des
# accolades que `str.format` interpréterait.
MODELE_COMPLETION = (
    'XDG="${XDG_CONFIG_HOME:-$HOME/.config}/keyrock/shell/keyrock.@SHELL@"\n'
    '[ -r "$XDG" ] && . "$XDG"'
)


def contenu_bloc(shell: str) -> str:
    """Contenu du bloc KEYROCK pour le shell donné (idempotent, réversible)."""
    lignes = [
        DEBUT_BLOC,
        "# Bloc géré par KeyRock. Ne pas éditer à la main.",
        "# `kr install-shell` / `kr uninstall-shell` le gèrent de façon idempotente.",
        'export PATH="$HOME/.local/bin:$PATH"',
    ]
    if shell in ("bash", "zsh"):
        lignes.append(MODELE_COMPLETION.replace("@SHELL@", shell))
    lignes.append(FIN_BLOC)
    return "\n".join(lignes)


CONTENU_BLOC = contenu_bloc("bash")

SHELLS = ("bash", "zsh", "fish")


def _shell_courant() -> str:
    nom = Path(os.environ.get("SHELL", "")).name
    return nom if nom in SHELLS else "bash"


def resoudre_repertoire() -> Path:
    """Répertoire de configuration KeyRock (créé à la demande)."""
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    chemin = Path(base).expanduser() / "keyrock"
    chemin.mkdir(parents=True, exist_ok=True)
    return chemin


def candidats_rc() -> list[Path]:
    """Fichiers de profil ciblés, selon le shell courant."""
    maison = Path.home()
    if _shell_courant() == "zsh":
        return [maison / ".zshrc"]
    if _shell_courant() == "fish":
        return [maison / ".config" / "fish" / "config.fish"]
    return [maison / ".bashrc", maison / ".bash_profile"]


def _commande_rechargement() -> str:
    return "source ~/.zshrc" if _shell_courant() == "zsh" else "source ~/.bashrc"


def _lire(chemin: Path) -> str:
    try:
        return chemin.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""


def _ecrire(chemin: Path, contenu: str) -> None:
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_text(contenu, encoding="utf-8")


def _bloc_present(contenu: str) -> bool:
    return DEBUT_BLOC in contenu and FIN_BLOC in contenu


def _retirer_bloc(contenu: str) -> str:
    if not _bloc_present(contenu):
        return contenu
    debut = contenu.index(DEBUT_BLOC)
    fin = contenu.index(FIN_BLOC, debut) + len(FIN_BLOC)
    reste = contenu[:debut] + contenu[fin:]
    return reste.strip("\n") + "\n"


def installer_shell() -> tuple[int, str]:
    """Ajoute le bloc KEYROCK aux profils. Idempotent. Retourne (code, message)."""
    if _shell_courant() == "fish":
        return 1, (
            "Le support fish n'est pas encore géré. Utilisez bash ou zsh, "
            "ou ajoutez manuellement :\n  set -gx PATH $HOME/.local/bin $PATH"
        )
    _ecrire_fichier_completion()
    modifies: list[str] = []
    deja: list[str] = []
    for chemin in candidats_rc():
        if _shell_courant() == "zsh" and chemin.name != ".zshrc":
            continue
        contenu = _lire(chemin)
        if _bloc_present(contenu):
            deja.append(str(chemin))
            continue
        base = contenu if contenu.endswith("\n") or not contenu else contenu + "\n"
        _ecrire(chemin, f"{base}\n{contenu_bloc(_shell_courant())}\n")
        modifies.append(str(chemin))
    lignes = [
        f"Shell détecté : {_shell_courant()}.",
        f"Complétion : {resoudre_repertoire() / 'shell'}",
    ]
    if modifies:
        lignes.append("Bloc KEYROCK ajouté à : " + ", ".join(modifies))
        lignes.append(f"Rechargez : {_commande_rechargement()}")
    elif deja:
        lignes.append("Déjà installé (aucun changement) : " + ", ".join(deja))
    else:
        lignes.append("Aucun profil modifié (fichiers absents ou en lecture seule).")
    return 0, "\n".join(lignes)


def desinstaller_shell() -> tuple[int, str]:
    """Retire le bloc KEYROCK. Idempotent. Retourne (code, message)."""
    supprimes: list[str] = []
    absents: list[str] = []
    for chemin in candidats_rc():
        contenu = _lire(chemin)
        if not _bloc_present(contenu):
            absents.append(str(chemin))
            continue
        _ecrire(chemin, _retirer_bloc(contenu))
        supprimes.append(str(chemin))
    lignes = [f"Shell détecté : {_shell_courant()}."]
    if supprimes:
        lignes.append("Bloc KEYROCK retiré de : " + ", ".join(supprimes))
        lignes.append(f"Rechargez : {_commande_rechargement()}")
    else:
        lignes.append("Aucun bloc KEYROCK trouvé — rien à faire.")
    return 0, "\n".join(lignes)


def _ecrire_fichier_completion() -> None:
    """Écrit les complétions bash/zsh dans le répertoire de config KeyRock."""
    dossier = resoudre_repertoire() / "shell"
    dossier.mkdir(parents=True, exist_ok=True)
    (dossier / "keyrock.bash").write_text(
        "# Complétions KeyRock — générées par `kr install-shell`.\n"
        "_kr_completion() {\n"
        '    local cur="${COMP_WORDS[COMP_CWORD]}"\n'
        '    COMPREPLY=( $(compgen -W "--help --json --no-color --count --composition '
        'gen copy password token regen info config tui 8 16 24 32 64 128" '
        '-- "$cur") )\n'
        "}\n"
        "complete -F _kr_completion kr\n",
        encoding="utf-8",
    )
    (dossier / "keyrock.zsh").write_text(
        "# Complétions KeyRock — générées par `kr install-shell`.\n"
        "#compdef kr\n"
        "_kr() {\n"
        "    _arguments '1: :((gen copy password token regen info config tui help))' \\\n"
        "        '--json' '--no-color' '--count[Nombre de tokens]:N:' \\\n"
        "        '--composition[alpha|alnum|ascii]:c:'\n"
        "}\n"
        "compdef _kr kr\n",
        encoding="utf-8",
    )


def installer() -> int:  # pragma: no cover - point d'entrée `python -m keyrock_shell`
    code, message = installer_shell()
    print(message, file=sys.stderr if code else sys.stdout)
    return code
