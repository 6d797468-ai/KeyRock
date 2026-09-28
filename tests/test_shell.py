"""Tests du dispatcher `kr` — grammaire, garde-fous, sorties."""

from __future__ import annotations

import json

import pytest

from keyrock_core.actions import ActionRegistry
from keyrock_core.config import KeyRockSettings
from keyrock_core.service import GenerationService
from keyrock_shell import cli
from keyrock_shell.cli import (
    CODE_ERREUR,
    CODE_ERREUR_USAGE,
    CODE_OK,
    COMMANDES,
    refuser_secret,
    router,
)


@pytest.fixture
def service() -> GenerationService:
    return GenerationService(KeyRockSettings())


@pytest.fixture
def registre(service: GenerationService) -> ActionRegistry:
    return ActionRegistry(service)


def executer(registre: ActionRegistry, service: GenerationService, argv: list[str], **kw: object):
    return router(argv, service, registre, **kw)  # type: ignore[arg-type]


class TestGardeFouSecret:
    @pytest.mark.parametrize(
        "argument",
        ["MonSuperSecret", "P4ssw0rd", "abc123", "hunter2xyz", "a1b2c3d4e5"],
    )
    def test_secret_refuse(self, argument: str) -> None:
        assert refuser_secret(argument) is True

    @pytest.mark.parametrize("argument", ["8", "16", "32", "1024", "gen", "copy", "info"])
    def test_longueur_ou_commande_acceptee(self, argument: str) -> None:
        assert refuser_secret(argument) is False

    def test_chiffres_pures_sont_des_longueurs(self) -> None:
        """Pas de faux positif : `kr 123456` doit donner une erreur de bornes."""
        assert refuser_secret("123456") is False

    def test_router_refuse_un_secret(
        self, service: GenerationService, registre: ActionRegistry
    ) -> None:
        reponse = executer(registre, service, ["MonSuperSecret123"])
        assert reponse.code == CODE_ERREUR
        assert reponse.erreur is not None
        assert "jamais un secret" in reponse.erreur

    def test_le_secret_refuse_ne_reparait_jamais(
        self, service: GenerationService, registre: ActionRegistry
    ) -> None:
        """Le message de refus ne doit pas rejouer la valeur refusée.

        Un secret qui ressort dans le terminal part dans l'historique du shell,
        les journaux de CI et les rapports de bug. Le refus doit être muet.
        """
        secret = "P4ssw0rdTresSecret"
        reponse = executer(registre, service, ["32", secret])
        assert reponse.code == CODE_ERREUR
        assert secret not in (reponse.erreur or "")
        assert "P4ssw0rd" not in (reponse.erreur or "")

    def test_secret_refuse_meme_en_position_secondaire(
        self, service: GenerationService, registre: ActionRegistry
    ) -> None:
        reponse = executer(registre, service, ["gen", "32", "MonSuperSecret1"])
        assert reponse.code == CODE_ERREUR
        assert reponse.resultat is None


class TestRoutage:
    @pytest.mark.parametrize("argv", [[], ["tui"], ["ui"]])
    def test_tui(
        self, service: GenerationService, registre: ActionRegistry, argv: list[str]
    ) -> None:
        assert executer(registre, service, argv).mode == "tui"

    @pytest.mark.parametrize("argv", [["help"], ["h"], ["aide"], ["-h"], ["--help"]])
    def test_aide(
        self, service: GenerationService, registre: ActionRegistry, argv: list[str]
    ) -> None:
        assert executer(registre, service, argv).mode == "aide"

    def test_commande_inconnue(self, service: GenerationService, registre: ActionRegistry) -> None:
        """Fail-closed : une commande inconnue est refusée comme le serait un secret.

        Même code et même message que pour un secret : distinguer les deux
        fournirait un oracle à qui devine des secrets.
        """
        reponse = executer(registre, service, ["bogus"])
        assert reponse.code == CODE_ERREUR
        assert "refusé" in (reponse.erreur or "")

    def test_longueur_hors_bornes(
        self, service: GenerationService, registre: ActionRegistry
    ) -> None:
        """Une longueur hors bornes est une faute de frappe, pas un secret."""
        reponse = executer(registre, service, ["99999"])
        assert reponse.code == CODE_ERREUR
        assert "entre 8 et 1024" in (reponse.erreur or "")

    @pytest.mark.parametrize("commande", ["info", "config", "i"])
    def test_info(
        self, service: GenerationService, registre: ActionRegistry, commande: str
    ) -> None:
        reponse = executer(registre, service, [commande])
        assert reponse.mode == "info"
        assert reponse.donnees["longueur"] == 32  # type: ignore[index]

    def test_toutes_les_commandes_sont_connues(self) -> None:
        assert set(COMMANDES.values()) <= {
            "gen",
            "copy",
            "password",
            "token",
            "regen",
            "info",
            "help",
            "tui",
            "install-shell",
            "uninstall-shell",
        }


class TestGeneration:
    def test_kr_32(self, service: GenerationService, registre: ActionRegistry) -> None:
        reponse = executer(registre, service, ["32"])
        assert reponse.code == CODE_OK
        assert reponse.resultat is not None
        assert len(reponse.resultat.token1) == 32
        assert reponse.resultat.token2 is not None

    def test_kr_gen_64(self, service: GenerationService, registre: ActionRegistry) -> None:
        reponse = executer(registre, service, ["gen", "64"])
        assert reponse.resultat is not None
        assert reponse.resultat.longueur == 64

    def test_kr_g_64(self, service: GenerationService, registre: ActionRegistry) -> None:
        assert executer(registre, service, ["g", "64"]).resultat.longueur == 64  # type: ignore[union-attr]

    def test_kr_c_32(self, service: GenerationService, registre: ActionRegistry) -> None:
        reponse = executer(registre, service, ["c", "32"])
        assert reponse.mode == "copy"
        assert reponse.resultat is not None

    def test_kr_32_c(self, service: GenerationService, registre: ActionRegistry) -> None:
        assert executer(registre, service, ["32", "c"]).mode == "copy"

    def test_kr_p_24(self, service: GenerationService, registre: ActionRegistry) -> None:
        reponse = executer(registre, service, ["p", "24"])
        assert reponse.mode == "password"
        assert len(reponse.resultat.tokens) == 1  # type: ignore[union-attr]
        assert len(reponse.resultat.tokens[0]) == 24  # type: ignore[union-attr]

    def test_kr_t_64(self, service: GenerationService, registre: ActionRegistry) -> None:
        reponse = executer(registre, service, ["t", "64"])
        assert reponse.mode == "token"
        assert len(reponse.resultat.tokens[0]) == 64  # type: ignore[union-attr]

    def test_kr_r_32(self, service: GenerationService, registre: ActionRegistry) -> None:
        assert executer(registre, service, ["r", "32"]).mode == "regen"

    def test_nombre_personnalise(
        self, service: GenerationService, registre: ActionRegistry
    ) -> None:
        reponse = executer(registre, service, ["32"], nombre=5)
        assert reponse.resultat is not None
        assert len(reponse.resultat.tokens) == 5

    def test_tokens_independants(
        self, service: GenerationService, registre: ActionRegistry
    ) -> None:
        resultat = executer(registre, service, ["64"], nombre=20).resultat
        assert resultat is not None
        assert len(set(resultat.tokens)) == 20

    def test_registre_memorise(self, service: GenerationService, registre: ActionRegistry) -> None:
        reponse = executer(registre, service, ["32"])
        assert registre.dernier() is reponse.resultat

    def test_entropie_insuffisante(
        self, service: GenerationService, registre: ActionRegistry
    ) -> None:
        reponse = executer(registre, service, ["4"])
        assert reponse.code == CODE_ERREUR
        assert "8 et 1024" in (reponse.erreur or "")

    def test_longueur_non_numerique(
        self, service: GenerationService, registre: ActionRegistry
    ) -> None:
        reponse = executer(registre, service, ["alpha"])
        assert reponse.code == CODE_ERREUR_USAGE


class TestComposition:
    def test_alpha(self, service: GenerationService, registre: ActionRegistry) -> None:
        reponse = executer(registre, service, ["gen", "32", "alpha"])
        assert reponse.resultat is not None
        assert reponse.resultat.alphabet == 52

    def test_alnum(self, service: GenerationService, registre: ActionRegistry) -> None:
        reponse = executer(registre, service, ["gen", "32", "alnum"])
        assert reponse.resultat is not None
        assert reponse.resultat.alphabet == 62

    def test_ascii_par_defaut_pour_password(
        self, service: GenerationService, registre: ActionRegistry
    ) -> None:
        reponse = executer(registre, service, ["p", "24"])
        assert reponse.resultat is not None
        assert reponse.resultat.alphabet == 94

    def test_composition_inconnue(
        self, service: GenerationService, registre: ActionRegistry
    ) -> None:
        reponse = executer(registre, service, ["gen", "32"], composition="pirate")
        assert reponse.code == CODE_ERREUR
        assert "Composition inconnue" in (reponse.erreur or "")


class TestSortieJson:
    def test_structure(self, service: GenerationService, registre: ActionRegistry) -> None:
        charge = executer(registre, service, ["32"]).en_json()
        assert charge["mode"] == "gen"
        assert charge["longueur"] == 32
        assert isinstance(charge["tokens"], list)
        json.dumps(charge)  # sérialisable tel quel

    def test_erreur_serialisee(self) -> None:
        reponse = cli.Reponse(code=CODE_ERREUR, mode="erreur", erreur="boom")
        assert json.loads(json.dumps(reponse.en_json()))["erreur"] == "boom"

    def test_main_json(
        self,
        service: GenerationService,
        registre: ActionRegistry,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        code = cli.main(["32", "--json", "--no-color"])
        charge = json.loads(capsys.readouterr().out)
        assert code == CODE_OK
        assert charge["mode"] == "gen"
        assert len(charge["token1"]) == 32

    def test_main_json_erreur(self, capsys: pytest.CaptureFixture[str]) -> None:
        code = cli.main(["MonSuperSecret123", "--json"])
        assert code == CODE_ERREUR
        assert "erreur" in json.loads(capsys.readouterr().out)

    def test_main_option_inconnue(self, capsys: pytest.CaptureFixture[str]) -> None:
        code = cli.main(["32", "--bogus", "--json"])
        assert code == CODE_ERREUR_USAGE
        assert "Option inconnue" in json.loads(capsys.readouterr().out)["erreur"]

    def test_main_help(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert cli.main(["--help"]) == CODE_OK
        assert "KeyRock" in capsys.readouterr().out


class TestMainSansTui:
    def test_aide(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert cli.main(["help"]) == CODE_OK
        sortie = capsys.readouterr().out
        assert "kr 32" in sortie
        assert "presse-papier" in sortie

    def test_genere(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert cli.main(["32", "--no-color"]) == CODE_OK
        assert "TOKEN 1" in capsys.readouterr().out

    def test_info(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert cli.main(["info", "--no-color"]) == CODE_OK
        assert "keyrock info" in capsys.readouterr().out

    def test_erreur(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert cli.main(["bogus", "--no-color"]) == CODE_ERREUR
        assert "refusé" in capsys.readouterr().out

    def test_copy_sans_presse_papier(
        self, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("keyrock_cli.display.copier_vers_presse_papier", lambda *a, **k: False)
        assert cli.main(["c", "32", "--no-color"]) == CODE_OK
        assert "indisponible" in capsys.readouterr().out
