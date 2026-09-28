"""Modèles Pydantic de l'API KeyRock (requêtes / réponses)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from keyrock_core.generator import (
    COMPOSITIONS_NOMMEES,
    ENTROPIE_MIN,
    LONGEUR_MAX,
    LONGEUR_MIN,
    AlphabetVideError,
    CoreGenerator,
    GenerationOptions,
    LongueurHorsBornesError,
)

__all__ = [
    "COMPOSITIONS_NOMMEES",
    "ENTROPIE_MIN",
    "LONGEUR_MAX",
    "LONGEUR_MIN",
    "AlphabetMinimum",
    "ErrorDetail",
    "ErrorResponse",
    "GenerateRequest",
    "GenerateResponse",
    "HealthResponse",
    "MetaResponse",
    "SanteControle",
]


class GenerateRequest(BaseModel):
    """Paramètres de génération d'une paire de tokens."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": {
                "longueur": 32,
                "majuscules": True,
                "minuscules": True,
                "chiffres": True,
                "symboles": True,
                "nombre": 2,
            }
        },
    )

    longueur: int = Field(
        default=32,
        ge=LONGEUR_MIN,
        le=LONGEUR_MAX,
        description="Longueur du token, en caractères.",
    )
    majuscules: bool = Field(default=True, description="Inclure A-Z.")
    minuscules: bool = Field(default=True, description="Inclure a-z.")
    chiffres: bool = Field(default=True, description="Inclure 0-9.")
    symboles: bool = Field(default=True, description="Inclure la ponctuation ASCII.")
    nombre: int = Field(default=2, ge=1, le=16, description="Nombre de tokens à renvoyer.")
    seuil_entropie: float = Field(
        default=ENTROPIE_MIN,
        ge=0,
        le=4096,
        description="Entropie minimale requise, en bits (fail-fast serveur).",
    )

    @field_validator("longueur")
    @classmethod
    def _verifier_longueur(cls, valeur: int) -> int:
        if not LONGEUR_MIN <= valeur <= LONGEUR_MAX:
            raise LongueurHorsBornesError(
                f"longueur doit être comprise entre {LONGEUR_MIN} et {LONGEUR_MAX} (reçu: {valeur})"
            )
        return valeur

    @model_validator(mode="after")
    def _verifier_alphabet_et_entropie(self) -> GenerateRequest:
        if not any((self.majuscules, self.minuscules, self.chiffres, self.symboles)):
            raise AlphabetVideError(
                "au moins un type de caractère doit être activé "
                "(majuscules, minuscules, chiffres, symboles)"
            )
        # `valider_entropie` lève `EntropieInsuffisanteError`, qui porte le
        # minimum exact à atteindre dans son message. La borne de longueur et
        # le seuil d'entropie sont deux échecs distincts, avec deux codes et
        # deux corrections distinctes : augmenter la longueur ne dispense pas
        # d'élargir l'alphabet, ni l'inverse.
        CoreGenerator.valider_entropie(self.vers_options(), self.seuil_entropie)
        return self

    def vers_options(self) -> GenerationOptions:
        """Construit l'objet métier immuable correspondant à la requête."""
        return GenerationOptions(
            longueur=self.longueur,
            majuscules=self.majuscules,
            minuscules=self.minuscules,
            chiffres=self.chiffres,
            symboles=self.symboles,
        )


class GenerateResponse(BaseModel):
    """Réponse de `/api/v1/generate`.

    Les tokens sont renvoyés en clair (usage immédiat) et ne sont
    **jamais** journalisés ni persistés (principe « Zéro Persistance »).
    """

    model_config = ConfigDict(extra="forbid")

    token1: str = Field(description="Premier token généré.")
    token2: str | None = Field(default=None, description="Second token généré.")
    longueur: int
    entropie_bits: float
    alphabet: int = Field(description="Taille de l'alphabet utilisé.")


class HealthResponse(BaseModel):
    """État de santé effectif, pas une constante."""

    status: str = Field(description="`ok`, `degraded` ou `ko`.")
    version: str
    controles: list[SanteControle] = Field(
        default_factory=list, description="Détail de chaque contrôle effectué."
    )


class SanteControle(BaseModel):
    """Un contrôle nommé et son résultat."""

    model_config = ConfigDict(extra="forbid")

    nom: str
    ok: bool
    bloquant: bool = Field(
        description="Vrai si l'échec de ce contrôle rend le service indisponible."
    )
    detail: str


class AlphabetMinimum(BaseModel):
    """Longueur minimale réelle pour une combinaison de classes de caractères."""

    model_config = ConfigDict(extra="forbid")

    nom: str | None = Field(
        default=None, description="Nom de composition si elle existe, ex. `alnum`."
    )
    alphabet: int = Field(description="Nombre de caractères distincts disponibles.")
    entropie_par_caractere: float = Field(description="log2(|alphabet|), en bits.")
    longueur_min: int = Field(
        description="Longueur minimale atteignant `entropie_min` avec cet alphabet."
    )


class MetaResponse(BaseModel):
    nom: str
    version: str
    description: str
    longueur_min: int = Field(
        description=(
            "Borne de saisie inférieure. Ce n'est PAS une longueur utilisable : "
            "consulter `longueur_min_par_alphabet` pour le minimum réel."
        )
    )
    longueur_max: int
    entropie_min: float = Field(description="Seuil d'entropie appliqué par défaut, en bits.")
    longueur_min_par_alphabet: dict[str, AlphabetMinimum] = Field(
        description=(
            "Longueur minimale effective, par combinaison de classes. Clé = libellé "
            "canonique (`maj+min+num+sym`). C'est ce tableau qu'un client doit "
            "consulter avant d'envoyer une longueur."
        )
    )
    persistance: str = "aucune (zéro persistance)"


class ErrorDetail(BaseModel):
    code: str
    message: str
    champ: str | None = None


class ErrorResponse(BaseModel):
    error: ErrorDetail
    # Jamais de stack trace ni de repr(token) ici.
    request_id: str | None = None


def alphabet_pour(requete: GenerateRequest) -> str:
    return CoreGenerator.construire_alphabet(
        requete.majuscules, requete.minuscules, requete.chiffres, requete.symboles
    )
