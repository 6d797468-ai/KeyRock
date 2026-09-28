"""Moteur de génération de tokens cryptographiques (CSPRNG)."""

from __future__ import annotations

import math
import secrets
import string
from dataclasses import dataclass

LONGEUR_MIN = 8
LONGEUR_MAX = 1024
ENTROPIE_MIN = 80.0

__all__ = [
    "ENTROPIE_MIN",
    "LONGEUR_MAX",
    "LONGEUR_MIN",
    "CoreGenerator",
    "GenerationOptions",
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
            raise ValueError(
                f"longueur doit être comprise entre {LONGEUR_MIN} et {LONGEUR_MAX} "
                f"(reçu: {self.longueur})"
            )


class CoreGenerator:
    """Moteur de génération isolé, intégrable facilement dans une API (FastAPI, etc.)."""

    @staticmethod
    def construire_alphabet(
        majuscules: bool = True,
        minuscules: bool = True,
        chiffres: bool = True,
        symboles: bool = True,
    ) -> str:
        """Assemble l'alphabet retenu. Lève `ValueError` si l'alphabet est vide."""
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
            raise ValueError(
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
            raise ValueError(
                f"Entropie insuffisante: {entropie} bits < seuil requis de {seuil} bits. "
                "Augmentez la longueur ou activez plus de types de caractères."
            )
        return entropie

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
