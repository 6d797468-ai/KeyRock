"""Configuration centralisée de KeyRock (variables d'environnement)."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ENTROPIE_MIN_NIST = 80
LONGEUR_MIN = 8
LONGEUR_MAX = 1024


class KeyRockSettings(BaseSettings):
    """Paramètres applicatifs injectés depuis l'environnement ou un fichier .env."""

    model_config = SettingsConfigDict(
        env_prefix="KEYROCK_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    api_host: str = "0.0.0.0"  # noqa: S104 — binding public requis en conteneur
    api_port: int = Field(default=8000, ge=1, le=65535)
    log_level: str = "INFO"
    token_min_length: int = Field(default=LONGEUR_MIN, ge=LONGEUR_MIN, le=LONGEUR_MAX)
    token_max_length: int = Field(default=LONGEUR_MAX, ge=LONGEUR_MIN, le=LONGEUR_MAX)
    token_min_entropy: int = Field(default=ENTROPIE_MIN_NIST, ge=0)
    rate_limit_per_minute: int = Field(default=60, ge=1)
    cors_allow_origins: list[str] = Field(default_factory=list)

    @field_validator("log_level")
    @classmethod
    def _valider_niveau_log(cls, valeur: str) -> str:
        normalise = valeur.strip().upper()
        autorises = {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG", "NOTSET"}
        if normalise not in autorises:
            raise ValueError(f"Niveau de log invalide: {valeur!r}")
        return normalise

    @field_validator("token_max_length")
    @classmethod
    def _valider_bornes(cls, valeur: int, info: object) -> int:
        donnees = getattr(info, "data", None)
        if isinstance(donnees, dict):
            minimum = donnees.get("token_min_length", LONGEUR_MIN)
            if valeur < minimum:
                raise ValueError("token_max_length doit être >= token_min_length")
        return valeur


@lru_cache(maxsize=1)
def get_settings() -> KeyRockSettings:
    """Retourne une instance unique des paramètres (cachée pour le process)."""
    return KeyRockSettings()


def recharger_settings() -> KeyRockSettings:
    """Invalide le cache et recharge la configuration (utile pour les tests)."""
    get_settings.cache_clear()
    return get_settings()
