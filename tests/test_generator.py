"""Tests unitaires du noyau de génération (CSPRNG, entropie, bornes)."""

from __future__ import annotations

import inspect
import math
import string
from unittest.mock import patch

import pytest

from keyrock_core.generator import (
    ENTROPIE_MIN,
    LONGEUR_MAX,
    LONGEUR_MIN,
    AlphabetVideError,
    CoreGenerator,
    EntropieInsuffisanteError,
    GenerationOptions,
    LongueurHorsBornesError,
    libelle_composition,
)


class TestAlphabet:
    def test_alphabet_complet(self) -> None:
        alphabet = CoreGenerator.construire_alphabet(True, True, True, True)
        assert alphabet == (
            string.ascii_uppercase + string.ascii_lowercase + string.digits + string.punctuation
        )

    @pytest.mark.parametrize(
        ("maj", "min_", "chiffres", "symboles", "attendu"),
        [
            (True, False, False, False, string.ascii_uppercase),
            (False, True, False, False, string.ascii_lowercase),
            (False, False, True, False, string.digits),
            (False, False, False, True, string.punctuation),
        ],
    )
    def test_alphabet_partiel(
        self, maj: bool, min_: bool, chiffres: bool, symboles: bool, attendu: str
    ) -> None:
        obtenu = CoreGenerator.construire_alphabet(maj, min_, chiffres, symboles)
        assert obtenu == attendu

    def test_alphabet_vide_leve_valueerror(self) -> None:
        with pytest.raises(ValueError, match="alphabet vide"):
            CoreGenerator.construire_alphabet(False, False, False, False)

    def test_generer_alphabet_vide_leve_valueerror(self) -> None:
        with pytest.raises(ValueError, match="alphabet vide"):
            CoreGenerator.generer(32, False, False, False, False)


class TestEntropie:
    def test_formule_nist(self) -> None:
        alphabet = string.ascii_lowercase
        attendu = math.log2(len(alphabet))
        assert CoreGenerator.calculer_entropie_par_caractere(alphabet) == pytest.approx(attendu)

    def test_entropie_texte_vide(self) -> None:
        assert CoreGenerator.calculer_entropie_par_caractere("") == 0.0

    def test_entropie_alphabet_de_1_caractere(self) -> None:
        assert CoreGenerator.calculer_entropie_par_caractere("a") == 0.0

    def test_entropie_totale_longueur_fois_log2(self) -> None:
        options = GenerationOptions(
            longueur=16, majuscules=True, minuscules=True, chiffres=False, symboles=False
        )
        taille = len(string.ascii_uppercase) + len(string.ascii_lowercase)
        assert CoreGenerator.calculer_entropie(options) == pytest.approx(
            16 * math.log2(taille), abs=0.01
        )

    @pytest.mark.parametrize("longueur", [13, 16, 32, 64, 128, LONGEUR_MAX])
    def test_entropie_suffisante_avec_alphabet_complet(self, longueur: int) -> None:
        options = GenerationOptions(longueur=longueur)
        assert CoreGenerator.calculer_entropie(options) >= ENTROPIE_MIN

    @pytest.mark.parametrize("longueur", [LONGEUR_MIN, 10, 12])
    def test_longueur_courte_rejetee_par_l_entropie(self, longueur: int) -> None:
        """Avec l'alphabet complet, < 13 caractères reste sous 80 bits."""
        options = GenerationOptions(longueur=longueur)
        assert CoreGenerator.calculer_entropie(options) < ENTROPIE_MIN
        with pytest.raises(EntropieInsuffisanteError) as echec:
            CoreGenerator.valider_entropie(options)
        # Le message nomme la longueur à atteindre : c'est la correction, pas
        # un constat. « 52 bits < 80 bits » seul laisse le client deviner.
        assert "13 caractères" in str(echec.value)

    def test_entropie_insuffisante_rejetee(self) -> None:
        options = _options_chiffres_seulement(LONGEUR_MIN)
        assert CoreGenerator.calculer_entropie(options) < ENTROPIE_MIN
        with pytest.raises(EntropieInsuffisanteError, match="25 caractères"):
            CoreGenerator.valider_entropie(options)

    def test_seuil_personnalise(self) -> None:
        options = _options_chiffres_seulement(8)
        assert CoreGenerator.valider_entropie(options, seuil=1.0) > 1.0


class TestGenerationOptions:
    def test_immuable(self) -> None:
        options = GenerationOptions()
        with pytest.raises(AttributeError):
            options.longueur = 64  # type: ignore[misc]

    @pytest.mark.parametrize("longueur", [LONGEUR_MIN - 1, 0, -1, LONGEUR_MAX + 1, 999_999_999])
    def test_longueur_hors_bornes(self, longueur: int) -> None:
        with pytest.raises(LongueurHorsBornesError, match="longueur"):
            GenerationOptions(longueur=longueur)

    def test_erreurs_du_noyau_sont_des_valueerror(self) -> None:
        """Compatibilité : `ValueError` reste attrapable par le code appelant."""
        for erreur in (LongueurHorsBornesError, EntropieInsuffisanteError, AlphabetVideError):
            assert issubclass(erreur, ValueError)
            assert erreur.code.isupper()

    @pytest.mark.parametrize("longueur", [LONGEUR_MIN, 32, LONGEUR_MAX])
    def test_longueur_dans_bornes(self, longueur: int) -> None:
        assert GenerationOptions(longueur=longueur).longueur == longueur

    def test_longueur_non_entier(self) -> None:
        with pytest.raises(TypeError):
            GenerationOptions(longueur="32")  # type: ignore[arg-type]

    def test_bool_refuse(self) -> None:
        with pytest.raises(TypeError):
            GenerationOptions(longueur=True)  # type: ignore[arg-type]


class TestGeneration:
    def test_longueur_respectee(self) -> None:
        assert len(CoreGenerator.generer(48, True, True, True, True)) == 48

    def test_caracteres_limites_a_lalphabet(self) -> None:
        alphabet = string.ascii_uppercase + string.digits
        token = CoreGenerator.generer(256, True, False, True, False)
        assert set(token) <= set(alphabet)

    def test_utilise_secrets_choice_et_non_random(self) -> None:
        source = inspect.getsource(CoreGenerator.generer_avec_options)
        assert "secrets.choice" in source
        assert "random" not in source

    def test_secrets_choice_effectivement_appele(self) -> None:
        with patch("secrets.choice", side_effect=lambda seq: seq[0]) as mocke:
            CoreGenerator.generer_avec_options(GenerationOptions(longueur=32))
        assert mocke.call_count == 32

    def test_tokens_independants(self) -> None:
        tokens = CoreGenerator.generer_plusieurs(GenerationOptions(longueur=32), nombre=50)
        assert len(tokens) == 50
        assert len(set(tokens)) == 50

    def test_nombre_invalide(self) -> None:
        for nombre in (0, -1, True, "2"):
            with pytest.raises(ValueError):
                CoreGenerator.generer_plusieurs(GenerationOptions(), nombre=nombre)  # type: ignore[arg-type]

    def test_generer_plusieurs_entre_8_et_1024(self) -> None:
        tokens = CoreGenerator.generer_plusieurs(GenerationOptions(longueur=LONGEUR_MAX), nombre=2)
        assert all(len(token) == LONGEUR_MAX for token in tokens)

    def test_seuil_entropie_personnalise_bloque(self) -> None:
        options = _options_chiffres_seulement(8)
        with pytest.raises(EntropieInsuffisanteError):
            CoreGenerator.generer_avec_options(options)
        assert len(CoreGenerator.generer_avec_options(options, seuil_entropie=0.0)) == 8


class TestLongueurMinimaleEffective:
    """Le minimum publié doit être le minimum *atteignable*.

    Régression directe du contrat faux : `/api/v1/meta` annonçait
    `longueur_min = 8`, valeur que le seuil de 80 bits rejette pour tout
    alphabet. Un client obéissant au contrat recevait un 422.
    """

    @pytest.mark.parametrize(
        ("maj", "min_", "chiffres", "symboles", "attendu"),
        [
            (True, True, True, True, 13),  # ascii, 94 caractères
            (True, True, True, False, 14),  # alnum, 62
            (True, True, False, False, 15),  # alpha, 52
            (False, False, True, False, 25),  # num, 10
        ],
    )
    def test_minimum_connu_par_alphabet(
        self, maj: bool, min_: bool, chiffres: bool, symboles: bool, attendu: int
    ) -> None:
        minimum = CoreGenerator.longueur_min_effective(maj, min_, chiffres, symboles)
        assert minimum == attendu

    @pytest.mark.parametrize(
        ("maj", "min_", "chiffres", "symboles"),
        [
            (a, b, c, d)
            for a in (True, False)
            for b in (True, False)
            for c in (True, False)
            for d in (True, False)
            if a or b or c or d
        ],
    )
    def test_le_minimum_annonce_est_toujours_atteignable(
        self, maj: bool, min_: bool, chiffres: bool, symboles: bool
    ) -> None:
        """Propriété centrale : le minimum annoncé passe la validation.

        C'est exactement l'invariant violé par l'ancien contrat.
        """
        minimum = CoreGenerator.longueur_min_effective(maj, min_, chiffres, symboles)
        options = GenerationOptions(
            longueur=minimum,
            majuscules=maj,
            minuscules=min_,
            chiffres=chiffres,
            symboles=symboles,
        )
        assert CoreGenerator.calculer_entropie(options) >= ENTROPIE_MIN
        assert CoreGenerator.valider_entropie(options) >= ENTROPIE_MIN

    def test_un_caractere_de_moins_echoue(self) -> None:
        options = GenerationOptions(longueur=12)
        with pytest.raises(EntropieInsuffisanteError):
            CoreGenerator.valider_entropie(options)

    def test_seuil_personnalise_change_le_minimum(self) -> None:
        """Le minimum dépend du seuil : il ne peut pas être une constante."""
        complet = CoreGenerator.longueur_min_effective(seuil=80.0)
        exigeant = CoreGenerator.longueur_min_effective(seuil=128.0)
        assert exigeant > complet

    def test_minimum_jamais_sous_la_borne_de_saisie(self) -> None:
        """Un seuil très bas ne doit pas annoncer une longueur hors bornes."""
        assert CoreGenerator.longueur_min_effective(seuil=0.0) == LONGEUR_MIN

    def test_alphabet_vide_refuse(self) -> None:
        with pytest.raises(AlphabetVideError):
            CoreGenerator.longueur_min_effective(False, False, False, False)


class TestTableDesAlphabets:
    def test_les_quinze_combinaisons_sont_publiees(self) -> None:
        table = CoreGenerator.decrire_alphabets()
        assert len(table) == 15
        assert "num" in table
        assert "maj+min+num+sym" in table

    def test_les_compositions_nommees_sont_repertoriees(self) -> None:
        table = CoreGenerator.decrire_alphabets()
        noms = {entree["nom"] for entree in table.values()}
        assert {"alpha", "alnum", "ascii"} <= noms

    def test_libelles_canoniques(self) -> None:
        assert libelle_composition(True, True, True, True) == "maj+min+num+sym"
        assert libelle_composition(False, False, True, False) == "num"
        assert libelle_composition(True, False, False, False) == "maj"

    def test_table_sans_drift_avec_la_fonction(self) -> None:
        """La table doit être dérivée, jamais recopiée.

        Une table recopiée diverge — c'est exactement ce qui a produit le
        contrat faux corrigé ici.
        """
        for entree in CoreGenerator.decrire_alphabets().values():
            attendu = max(LONGEUR_MIN, math.ceil(ENTROPIE_MIN / entree["entropie_par_caractere"]))
            assert entree["longueur_min"] == attendu

    def test_donnees_coherentes(self) -> None:
        for entree in CoreGenerator.decrire_alphabets().values():
            assert round(math.log2(entree["alphabet"]), 2) == entree["entropie_par_caractere"]


class TestSecurite:
    def test_aucun_log_dans_le_noyau(self) -> None:
        source = inspect.getsource(CoreGenerator)
        assert "logging" not in source
        assert "print(" not in source

    def test_generation_non_deterministe(self) -> None:
        options = GenerationOptions(longueur=64)
        premier = CoreGenerator.generer_avec_options(options)
        assert premier != CoreGenerator.generer_avec_options(options)


def _options_chiffres_seulement(longueur: int) -> GenerationOptions:
    return GenerationOptions(
        longueur=longueur,
        majuscules=False,
        minuscules=False,
        chiffres=True,
        symboles=False,
    )
