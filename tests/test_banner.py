"""La bannière doit rester synchronisée avec `logo-favicon/ascii-art.txt`.

L'art ASCII d'origine est la source de vérité : le code l'embarque pour ne pas
avoir de dépendance à un fichier externe au runtime (image Docker comprise).
Ce test échoue si les deux divergent.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from keyrock_cli.banner import (
    ART_KEYROCK,
    CREDITS,
    MENTION_AGENCE,
    MENTION_AUTEUR,
    NOM_OUTIL,
    SIGNATURE,
)

FICHIER_ART = Path(__file__).resolve().parent.parent / "logo-favicon" / "ascii-art.txt"


def lignes_du_fichier() -> list[str]:
    lignes = FICHIER_ART.read_text(encoding="utf-8").split("\n")
    fin = next(i for i, ligne in enumerate(lignes) if ligne.strip() == "")
    return [ligne.rstrip() for ligne in lignes[:fin]]


def lignes_du_code() -> list[str]:
    return [ligne.rstrip() for ligne in ART_KEYROCK.strip("\n").split("\n")]


class TestArtOriginal:
    def test_fichier_present(self) -> None:
        assert FICHIER_ART.is_file()

    def test_art_identique_au_fichier(self) -> None:
        assert lignes_du_code() == lignes_du_fichier()

    def test_art_a_20_lignes(self) -> None:
        assert len(lignes_du_code()) == 20

    def test_largeur_bornee_pour_terminal_80_colonnes(self) -> None:
        assert max(len(ligne) for ligne in lignes_du_code()) <= 60

    def test_mentions_dans_le_fichier(self) -> None:
        contenu = FICHIER_ART.read_text(encoding="utf-8")
        assert NOM_OUTIL in contenu
        assert MENTION_AGENCE in contenu
        assert MENTION_AUTEUR in contenu
        assert SIGNATURE in contenu

    def test_mentions_apres_l_art(self) -> None:
        lignes = FICHIER_ART.read_text(encoding="utf-8").split("\n")
        art = lignes[: len(lignes_du_code())]
        credits = lignes[len(lignes_du_code()) :]
        assert any(NOM_OUTIL in ligne for ligne in credits)
        assert all(ligne.strip() for ligne in art)


class TestCredits:
    @pytest.mark.parametrize(
        "attendu",
        [
            "KEYROCK",
            "Générateur de Clés & Tokens Cryptographiques",
            "Créé pour le compte de Vextra Agency",
            "Auteur : Nawfel Reghai",
        ],
    )
    def test_credit_present(self, attendu: str) -> None:
        assert any(texte == attendu for texte, _ in CREDITS)

    def test_ordre_des_credits(self) -> None:
        assert CREDITS[0][0] == NOM_OUTIL
        assert CREDITS[-1][0] == MENTION_AUTEUR

    def test_chaque_credit_a_un_style(self) -> None:
        assert all(style for _, style in CREDITS)

    def test_aucun_credit_vide(self) -> None:
        assert all(texte.strip() for texte, _ in CREDITS)
