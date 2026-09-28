"""Modèles Pydantic de l'API KeyRock (requêtes / réponses)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

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
    "ErrorDetail",
    "ErrorResponse",
    "GenerateRequest",
    "GenerateResponse",
    "HealthResponse",
    "MetaResponse",
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
            raise ValueError(f"longueur doit être comprise entre {LONGEUR_MIN} et {LONGEUR_MAX}")
        return valeur

    @model_validator(mode="after")
    def _verifier_alphabet_et_entropie(self) -> GenerateRequest:
        if not any((self.majuscules, self.minuscules, self.chiffres, self.symboles)):
            raise ValueError(
                "au moins un type de caractère doit être activé "
                "(majuscules, minuscules, chiffres, symboles)"
            )
        entropie = CoreGenerator.calculer_entropie(self.vers_options())
        if entropie < self.seuil_entropie:
            raise ValueError(
                f"entropie insuffisante : {entropie} bits < {self.seuil_entropie} bits "
                "requis ; augmentez la longueur ou activez plus de types de caractères"
            )
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
    status: str
    version: str


class MetaResponse(BaseModel):
    nom: str
    version: str
    description: str
    longueur_min: int
    longueur_max: int
    entropie_min: float
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
