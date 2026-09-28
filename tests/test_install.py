"""Tests de l'intégration shell — idempotence, réversibilité, non-destructivité."""

from __future__ import annotations

from pathlib import Path

import pytest

from keyrock_shell import install


@pytest.fixture
def maison(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Redirige HOME et XDG_CONFIG_HOME, et force bash comme shell courant."""
    faux = tmp_path / "home"
    faux.mkdir()
    monkeypatch.setenv("HOME", str(faux))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(faux / ".config"))
    monkeypatch.setenv("SHELL", "/bin/bash")
    return faux


class TestDetectionShell:
    def test_bash(self, maison: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SHELL", "/bin/bash")
        assert install._shell_courant() == "bash"
        assert install.candidats_rc()[0].name == ".bashrc"

    def test_zsh(self, maison: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SHELL", "/usr/bin/zsh")
        assert install._shell_courant() == "zsh"
        assert install.candidats_rc() == [Path.home() / ".zshrc"]

    def test_inconnu_retombe_sur_bash(self, maison: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SHELL", "/bin/fish")
        assert install._shell_courant() in {"zsh", "fish"}

    def test_repertoire_cree(self, maison: Path) -> None:
        assert install.resoudre_repertoire().is_dir()


class TestInstallation:
    def test_ajoute_le_bloc(self, maison: Path) -> None:
        code, message = install.installer_shell()
        contenu = (maison / ".bashrc").read_text(encoding="utf-8")
        assert code == 0
        assert install.DEBUT_BLOC in contenu
        assert install.FIN_BLOC in contenu
        assert "ajouté" in message

    def test_idempotent(self, maison: Path) -> None:
        install.installer_shell()
        premier = (maison / ".bashrc").read_text(encoding="utf-8")
        install.installer_shell()
        assert (maison / ".bashrc").read_text(encoding="utf-8") == premier
        assert premier.count(install.DEBUT_BLOC) == 1

    def test_preserve_le_contenu_existant(self, maison: Path) -> None:
        rc = maison / ".bashrc"
        rc.write_text("# commentaire existant\nexport FOO=1\n", encoding="utf-8")
        install.installer_shell()
        contenu = rc.read_text(encoding="utf-8")
        assert "# commentaire existant" in contenu
        assert "export FOO=1" in contenu

    def test_une_seule_modification_par_fichier(self, maison: Path) -> None:
        rc = maison / ".bashrc"
        rc.write_text("a=1\n", encoding="utf-8")
        for _ in range(5):
            install.installer_shell()
        assert rc.read_text(encoding="utf-8").count(install.DEBUT_BLOC) == 1

    def test_ecrit_les_completions(self, maison: Path) -> None:
        install.installer_shell()
        dossier = install.resoudre_repertoire() / "shell"
        assert (dossier / "keyrock.bash").is_file()
        assert (dossier / "keyrock.zsh").is_file()

    def test_le_bloc_charge_la_completion(self, maison: Path) -> None:
        """Les complétions ne servent à rien si le bloc ne les source pas."""
        rc = maison / ".bashrc"
        rc.write_text("", encoding="utf-8")
        install.installer_shell()
        bloc = rc.read_text(encoding="utf-8")
        assert install.DEBUT_BLOC in bloc
        assert "keyrock.bash" in bloc
        assert ".bashrc" not in bloc.split(install.DEBUT_BLOC)[1].split('"$XDG"')[0]

    def test_completion_absence_ne_casse_pas_le_bloc(self, maison: Path) -> None:
        """`[ -r ] && .` doit rester sans erreur si le fichier n'existe pas."""
        rc = maison / ".bashrc"
        rc.write_text("", encoding="utf-8")
        install.installer_shell()
        ligne = next(ln for ln in rc.read_text(encoding="utf-8").splitlines() if "-r" in ln)
        assert ligne.startswith("[ -r ")
        assert ligne.endswith('&& . "$XDG"')

    def test_zsh_source_la_completion_zsh(
        self, maison: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SHELL", "/bin/zsh")
        install.installer_shell()
        bloc = (maison / ".zshrc").read_text(encoding="utf-8")
        assert "keyrock.zsh" in bloc
        assert "keyrock.bash" not in bloc

    def test_fish_refuse(self, maison: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SHELL", "/usr/bin/fish")
        code, message = install.installer_shell()
        assert code == 1
        assert "fish" in message
        assert not (maison / ".bashrc").exists()


class TestDesinstallation:
    def test_retire_le_bloc(self, maison: Path) -> None:
        install.installer_shell()
        code, message = install.desinstaller_shell()
        contenu = (maison / ".bashrc").read_text(encoding="utf-8")
        assert code == 0
        assert install.DEBUT_BLOC not in contenu
        assert "retiré" in message

    def test_idempotent(self, maison: Path) -> None:
        install.installer_shell()
        install.desinstaller_shell()
        avant = (maison / ".bashrc").read_text(encoding="utf-8")
        install.desinstaller_shell()
        assert (maison / ".bashrc").read_text(encoding="utf-8") == avant

    def test_preserve_le_contenu_existant(self, maison: Path) -> None:
        rc = maison / ".bashrc"
        rc.write_text("# avant\n", encoding="utf-8")
        install.installer_shell()
        install.desinstaller_shell()
        contenu = rc.read_text(encoding="utf-8")
        assert "# avant" in contenu
        assert install.DEBUT_BLOC not in contenu

    def test_sans_bloc(self, maison: Path) -> None:
        code, message = install.desinstaller_shell()
        assert code == 0
        assert "rien à faire" in message

    def test_cycle_complet(self, maison: Path) -> None:
        rc = maison / ".bashrc"
        rc.write_text("# original\n", encoding="utf-8")
        install.installer_shell()
        install.desinstaller_shell()
        assert rc.read_text(encoding="utf-8").strip() == "# original"


class TestSecurite:
    def test_aucun_secret_ecrit(self, maison: Path) -> None:
        install.installer_shell()
        contenu = (maison / ".bashrc").read_text(encoding="utf-8")
        assert "KEY=" not in contenu
        assert "TOKEN=" not in contenu

    def test_bloc_bien_delimite(self, maison: Path) -> None:
        install.installer_shell()
        contenu = (maison / ".bashrc").read_text(encoding="utf-8")
        assert contenu.index(install.DEBUT_BLOC) < contenu.index(install.FIN_BLOC)
