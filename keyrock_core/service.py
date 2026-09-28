"""Service de génération — couche métier unique, partagée par la TUI, le shell et l'API.

`CoreGenerator` reste le seul à appeler `secrets` : ce service ne fait que
orchestrer, valider et rapporter. Il ne connaît ni le terminal, ni le
presse-papier, ni le format de sortie.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, replace

from keyrock_core.config import KeyRockSettings, get_settings
from keyrock_core.generator import (
    ENTROPIE_MIN,
    LONGEUR_MAX,
    LONGEUR_MIN,
    CoreGenerator,
    GenerationOptions,
)

__all__ = [
    "ENTROPIE_MIN",
    "LONGEUR_MAX",
    "LONGEUR_MIN",
    "GenerationResultat",
    "GenerationService",
    "OptionsState",
]

LONGUEURS_PRESETS: tuple[int, ...] = (16, 32, 64, 128)


class OptionsState:
    """État de génération modifiable (longueur + composition de l'alphabet).

    `GenerationOptions` reste immuable : la TUI manipule cet objet mutable et
    n'obtient un `GenerationOptions` figé qu'au moment de générer.
    """

    __slots__ = ("_options",)

    def __init__(self, options: GenerationOptions | None = None) -> None:
        self._options = options or GenerationOptions()

    @property
    def options(self) -> GenerationOptions:
        return self._options

    @property
    def longueur(self) -> int:
        return self._options.longueur

    def set_longueur(self, longueur: int) -> None:
        self._options = replace(self._options, longueur=longueur)

    def basculer(self, champ: str) -> bool:
        """Bascule `majuscules`/`minuscules`/`chiffres`/`symboles`. Retourne la valeur."""
        if champ not in {"majuscules", "minuscules", "chiffres", "symboles"}:
            raise ValueError(f"Champ de composition inconnu : {champ!r}")
        nouvelle = not getattr(self._options, champ)
        self._options = replace(self._options, **{champ: nouvelle})
        return nouvelle

    def definir(self, champ: str, valeur: bool) -> None:
        if champ not in {"majuscules", "minuscules", "chiffres", "symboles"}:
            raise ValueError(f"Champ de composition inconnu : {champ!r}")
        self._options = replace(self._options, **{champ: bool(valeur)})

    def a_un_type_de_caractere(self) -> bool:
        o = self._options
        return bool(o.majuscules or o.minuscules or o.chiffres or o.symboles)

    def composition(self) -> dict[str, bool]:
        o = self._options
        return {
            "majuscules": o.majuscules,
            "minuscules": o.minuscules,
            "chiffres": o.chiffres,
            "symboles": o.symboles,
        }

    def reinitialiser(self) -> None:
        self._options = GenerationOptions()

    def copie(self) -> OptionsState:
        return OptionsState(self._options)


@dataclass(frozen=True, slots=True)
class GenerationResultat:
    """Résultat d'une génération. Ne contient que des métadonnées + les tokens."""

    tokens: tuple[str, ...]
    longueur: int
    entropie_bits: float
    alphabet: int
    duree_ms: float
    composition: dict[str, bool]

    @property
    def token1(self) -> str:
        return self.tokens[0]

    @property
    def token2(self) -> str | None:
        return self.tokens[1] if len(self.tokens) > 1 else None

    def en_json(self) -> dict[str, object]:
        """Représentation machine-readable (tokens inclus, c'est la demande)."""
        return {
            "token1": self.token1,
            "token2": self.token2,
            "tokens": list(self.tokens),
            "longueur": self.longueur,
            "entropie_bits": self.entropie_bits,
            "alphabet": self.alphabet,
            "duree_ms": self.duree_ms,
            "composition": dict(self.composition),
        }

    def sans_tokens(self) -> dict[str, object]:
        """Métadonnées seules — pour les logs (principe zéro persistance)."""
        return {
            "longueur": self.longueur,
            "entropie_bits": self.entropie_bits,
            "alphabet": self.alphabet,
            "nombre": len(self.tokens),
            "duree_ms": self.duree_ms,
        }


class GenerationService:
    """Point d'entrée métier unique : TUI, shell et API passent tous par ici."""

    def __init__(self, settings: KeyRockSettings | None = None) -> None:
        self.settings = settings or get_settings()
        self.etat = OptionsState(
            GenerationOptions(
                longueur=32,
                majuscules=True,
                minuscules=True,
                chiffres=True,
                symboles=True,
            )
        )

    # -- Lecture -----------------------------------------------------------
    def longueur(self) -> int:
        return self.etat.longueur

    def composition(self) -> dict[str, bool]:
        return self.etat.composition()

    def alphabet(self) -> str:
        o = self.etat.options
        return CoreGenerator.construire_alphabet(o.majuscules, o.minuscules, o.chiffres, o.symboles)

    def entropie(self) -> float:
        return CoreGenerator.calculer_entropie(self.etat.options)

    # -- Écriture ----------------------------------------------------------
    def set_longueur(self, longueur: int) -> None:
        """Applique les bornes 8..1024 et le seuil d'entropie configuré."""
        if not LONGEUR_MIN <= longueur <= LONGEUR_MAX:
            raise ValueError(
                f"longueur doit être comprise entre {LONGEUR_MIN} et {LONGEUR_MAX} "
                f"(reçu : {longueur})"
            )
        candidat = replace(self.etat.options, longueur=longueur)
        entropie = CoreGenerator.calculer_entropie(candidat)
        if entropie < self.settings.token_min_entropy:
            raise ValueError(
                f"Entropie insuffisante : {entropie} bits < "
                f"{self.settings.token_min_entropy} bits. Augmentez la longueur ou "
                "activez plus de types de caractères."
            )
        self.etat.set_longueur(longueur)

    def basculer(self, champ: str) -> bool:
        return self.etat.basculer(champ)

    def definir(self, champ: str, valeur: bool) -> None:
        self.etat.definir(champ, valeur)

    def reinitialiser(self) -> None:
        self.etat = OptionsState(
            GenerationOptions(
                longueur=32,
                majuscules=True,
                minuscules=True,
                chiffres=True,
                symboles=True,
            )
        )

    # -- Génération --------------------------------------------------------
    def generer(self, nombre: int = 2) -> GenerationResultat:
        """Génère `nombre` tokens. Lève `ValueError` si la configuration est invalide."""
        if not isinstance(nombre, int) or isinstance(nombre, bool) or nombre < 1:
            raise ValueError("nombre doit être un entier >= 1")
        if not self.etat.a_un_type_de_caractere():
            raise ValueError(
                "Aucun type de caractère sélectionné : activez au moins une "
                "catégorie avant de générer."
            )
        options = self.etat.options
        debut = time.perf_counter()
        tokens = CoreGenerator.generer_plusieurs(
            options, nombre=nombre, seuil_entropie=self.settings.token_min_entropy
        )
        duree_ms = round((time.perf_counter() - debut) * 1000, 2)
        return GenerationResultat(
            tokens=tuple(tokens),
            longueur=options.longueur,
            entropie_bits=CoreGenerator.calculer_entropie(options),
            alphabet=len(self.alphabet()),
            duree_ms=duree_ms,
            composition=self.composition(),
        )

    def generer_avec(
        self,
        longueur: int,
        *,
        nombre: int = 2,
        composition: dict[str, bool] | None = None,
    ) -> GenerationResultat:
        """Génération ponctuelle sans toucher à l'état courant de la session."""
        sauvegarde = self.etat.copie()
        try:
            if composition is not None:
                for champ, valeur in composition.items():
                    self.definir(champ, valeur)
            self.set_longueur(longueur)
            return self.generer(nombre)
        finally:
            self.etat = sauvegarde
