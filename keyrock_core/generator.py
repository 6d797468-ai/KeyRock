"""Moteur de génération de tokens cryptographiques (CSPRNG)."""

from __future__ import annotations

import math
import secrets
import string
from dataclasses import dataclass
from typing import TypedDict

LONGEUR_MIN = 8
LONGEUR_MAX = 1024
ENTROPIE_MIN = 80.0

# Source unique de vérité des compositions nommées. Partagée par l'API
# (`/api/v1/meta`) et par la CLI (`keyrock_shell/cli.py`) : deux listes
# divergentes ont déjà produit un contrat d'entropie faux.
COMPOSITIONS_NOMMEES: dict[str, dict[str, bool]] = {
    "alpha": {"majuscules": True, "minuscules": True, "chiffres": False, "symboles": False},
    "alnum": {"majuscules": True, "minuscules": True, "chiffres": True, "symboles": False},
    "ascii": {"majuscules": True, "minuscules": True, "chiffres": True, "symboles": True},
}

# Abréviations des quatre classes de caractères, dans l'ordre canonique.
CLASSES: tuple[tuple[str, str], ...] = (
    ("maj", "majuscules"),
    ("min", "minuscules"),
    ("num", "chiffres"),
    ("sym", "symboles"),
)


class LongueurHorsBornesError(ValueError):
    """Longueur demandée hors de `[LONGEUR_MIN, LONGEUR_MAX]`."""

    code = "LONGUEUR_HORS_BORNES"


class EntropieInsuffisanteError(ValueError):
    """Entropie inférieure au seuil exigé.

    Distincte de `LongueurHorsBornesError` parce que les deux erreurs
    appellent une correction différente : ici il faut augmenter la longueur
    ou élargir l'alphabet, alors que là un simple dépassement de borne suffit.
    Confondre les deux envoie le client dans la mauvaise direction.
    """

    code = "ENTROPIE_INSUFFISANTE"


class AlphabetVideError(ValueError):
    """Aucune classe de caractères activée : alphabet vide."""

    code = "ALPHABET_VIDE"


class DescriptionAlphabet(TypedDict):
    """Données publiées pour une combinaison de classes.

    `TypedDict` et non modèle Pydantic : le noyau ne doit pas connaître les
    modèles de l'API, mais la description doit rester typée de bout en bout.
    Un `dict[str, object]` perd l'information et casse la vérification.
    """

    nom: str | None
    alphabet: int
    entropie_par_caractere: float
    longueur_min: int


__all__ = [
    "CLASSES",
    "COMPOSITIONS_NOMMEES",
    "ENTROPIE_MIN",
    "LONGEUR_MAX",
    "LONGEUR_MIN",
    "AlphabetVideError",
    "CoreGenerator",
    "DescriptionAlphabet",
    "EntropieInsuffisanteError",
    "GenerationOptions",
    "LongueurHorsBornesError",
    "libelle_composition",
]


@dataclass(frozen=True, slots=True)
class GenerationOptions:
    """Jeu de caractères et longueur demandés pour une génération."""

    longueur: int = 32
    majuscules: bool = True
    minuscules: bool = True
    chiffres: bool = True
    symboles: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.longueur, int) or isinstance(self.longueur, bool):
            raise TypeError("longueur doit être un entier")
        if not LONGEUR_MIN <= self.longueur <= LONGEUR_MAX:
            raise LongueurHorsBornesError(
                f"longueur doit être comprise entre {LONGEUR_MIN} et {LONGEUR_MAX} "
                f"(reçu: {self.longueur})"
            )


def libelle_composition(majuscules: bool, minuscules: bool, chiffres: bool, symboles: bool) -> str:
    """Libellé canonique d'une combinaison de classes, ex. `maj+min+num+sym`."""
    retenues = {
        "majuscules": majuscules,
        "minuscules": minuscules,
        "chiffres": chiffres,
        "symboles": symboles,
    }
    return "+".join(abrege for abrege, cle in CLASSES if retenues[cle])


class CoreGenerator:
    """Moteur de génération isolé, intégrable facilement dans une API (FastAPI, etc.)."""

    @staticmethod
    def construire_alphabet(
        majuscules: bool = True,
        minuscules: bool = True,
        chiffres: bool = True,
        symboles: bool = True,
    ) -> str:
        """Assemble l'alphabet retenu. Lève `AlphabetVideError` si vide."""
        alphabet = ""
        if majuscules:
            alphabet += string.ascii_uppercase
        if minuscules:
            alphabet += string.ascii_lowercase
        if chiffres:
            alphabet += string.digits
        if symboles:
            alphabet += string.punctuation
        if not alphabet:
            raise AlphabetVideError(
                "Aucun type de caractère sélectionné : alphabet vide, génération impossible."
            )
        return alphabet

    @staticmethod
    def calculer_entropie_par_caractere(alphabet: str) -> float:
        """Entropie d'un caractère unique: log2(|alphabet|). 0.0 si alphabet vide."""
        taille = len(set(alphabet))
        if taille <= 1:
            return 0.0
        return math.log2(taille)

    @staticmethod
    def calculer_entropie(options: GenerationOptions) -> float:
        """Entropie totale du token: longueur * log2(|alphabet|), en bits."""
        alphabet = CoreGenerator.construire_alphabet(
            options.majuscules,
            options.minuscules,
            options.chiffres,
            options.symboles,
        )
        return round(options.longueur * CoreGenerator.calculer_entropie_par_caractere(alphabet), 2)

    @staticmethod
    def valider_entropie(options: GenerationOptions, seuil: float = ENTROPIE_MIN) -> float:
        """Valide qu'un jeu d'options atteint le seuil d'entropie (NIST SP 800-63B)."""
        entropie = CoreGenerator.calculer_entropie(options)
        if entropie < seuil:
            minimum = CoreGenerator.longueur_min_effective(
                options.majuscules,
                options.minuscules,
                options.chiffres,
                options.symboles,
                seuil=seuil,
            )
            raise EntropieInsuffisanteError(
                f"entropie insuffisante : {entropie} bits < seuil requis de {seuil} bits. "
                f"Augmentez la longueur à {minimum} caractères au minimum, ou activez "
                "plus de types de caractères."
            )
        return entropie

    @staticmethod
    def longueur_min_effective(
        majuscules: bool = True,
        minuscules: bool = True,
        chiffres: bool = True,
        symboles: bool = True,
        seuil: float = ENTROPIE_MIN,
    ) -> int:
        """Longueur minimale atteignant `seuil` bits pour cet alphabet.

        C'est la longueur que l'API doit annoncer, **pas** `LONGEUR_MIN`.
        `LONGEUR_MIN` est une borne de saisie, jamais une valeur atteignable :
        avec l'alphabet complet, 8 caractères ne donnent que 52 bits, et la
        borne est rejetée par le seuil d'entropie. Publier `LONGEUR_MIN` comme
        minimum fait donc recevoir un 422 à un client qui a suivi le contrat.
        """
        alphabet = CoreGenerator.construire_alphabet(majuscules, minuscules, chiffres, symboles)
        par_caractere = CoreGenerator.calculer_entropie_par_caractere(alphabet)
        if par_caractere <= 0:
            raise AlphabetVideError("alphabet vide : aucune longueur ne peut atteindre le seuil")
        return max(LONGEUR_MIN, math.ceil(seuil / par_caractere))

    @staticmethod
    def decrire_alphabets(seuil: float = ENTROPIE_MIN) -> dict[str, DescriptionAlphabet]:
        """Longueur minimale effective pour les 15 combinaisons de classes.

        Les 15 sont publiées, pas une sélection : le bug corrigé ici venait
        précisément d'un contrat partiel. Un client lit l'entrée correspondant
        aux quatre drapeaux qu'il envoie et connaît son minimum réel.

        Les clés sont les libellés canoniques produits par `libelle_composition`.
        """
        noms = {
            libelle_composition(
                majuscules=drapeaux["majuscules"],
                minuscules=drapeaux["minuscules"],
                chiffres=drapeaux["chiffres"],
                symboles=drapeaux["symboles"],
            ): nom
            for nom, drapeaux in COMPOSITIONS_NOMMEES.items()
        }
        table: dict[str, DescriptionAlphabet] = {}
        for masque in range(1, 16):
            drapeaux: dict[str, bool] = {
                cle: bool(masque >> index & 1) for index, (_, cle) in enumerate(CLASSES)
            }
            libelle = libelle_composition(
                majuscules=drapeaux["majuscules"],
                minuscules=drapeaux["minuscules"],
                chiffres=drapeaux["chiffres"],
                symboles=drapeaux["symboles"],
            )
            alphabet = CoreGenerator.construire_alphabet(
                majuscules=drapeaux["majuscules"],
                minuscules=drapeaux["minuscules"],
                chiffres=drapeaux["chiffres"],
                symboles=drapeaux["symboles"],
            )
            table[libelle] = DescriptionAlphabet(
                nom=noms.get(libelle),
                alphabet=len(set(alphabet)),
                entropie_par_caractere=round(
                    CoreGenerator.calculer_entropie_par_caractere(alphabet), 2
                ),
                longueur_min=CoreGenerator.longueur_min_effective(
                    majuscules=drapeaux["majuscules"],
                    minuscules=drapeaux["minuscules"],
                    chiffres=drapeaux["chiffres"],
                    symboles=drapeaux["symboles"],
                    seuil=seuil,
                ),
            )
        return table

    @staticmethod
    def generer(
        longueur: int = 32,
        maj: bool = True,
        min_: bool = True,
        chiffres: bool = True,
        symboles: bool = True,
        *,
        seuil_entropie: float = ENTROPIE_MIN,
    ) -> str:
        """Génère un token via `secrets.choice()` (CSPRNG).

        Lève `ValueError` si l'alphabet est vide, la longueur hors bornes,
        ou l'entropie sous le seuil.
        """
        options = GenerationOptions(
            longueur=longueur,
            majuscules=maj,
            minuscules=min_,
            chiffres=chiffres,
            symboles=symboles,
        )
        return CoreGenerator.generer_avec_options(options, seuil_entropie=seuil_entropie)

    @staticmethod
    def generer_avec_options(
        options: GenerationOptions, *, seuil_entropie: float = ENTROPIE_MIN
    ) -> str:
        """Variante acceptant une instance `GenerationOptions` immuable."""
        alphabet = CoreGenerator.construire_alphabet(
            options.majuscules,
            options.minuscules,
            options.chiffres,
            options.symboles,
        )
        CoreGenerator.valider_entropie(options, seuil_entropie)
        return "".join(secrets.choice(alphabet) for _ in range(options.longueur))

    @staticmethod
    def generer_plusieurs(
        options: GenerationOptions, nombre: int = 2, *, seuil_entropie: float = ENTROPIE_MIN
    ) -> list[str]:
        """Génère `nombre` tokens indépendants à partir d'un même jeu d'options."""
        if not isinstance(nombre, int) or isinstance(nombre, bool) or nombre < 1:
            raise ValueError("nombre doit être un entier >= 1")
        return [
            CoreGenerator.generer_avec_options(options, seuil_entropie=seuil_entropie)
            for _ in range(nombre)
        ]
