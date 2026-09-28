"""Tests de la configuration par environnement."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from keyrock_core.config import (
    ENTROPIE_MIN_NIST,
    LONGEUR_MAX,
    LONGEUR_MIN,
    KeyRockSettings,
    get_settings,
    recharger_settings,
)


class TestValeursParDefaut:
    def test_defauts(self) -> None:
        parametres = KeyRockSettings()
        assert parametres.api_host == "0.0.0.0"  # noqa: S104
        assert parametres.api_port == 8000
        assert parametres.log_level == "INFO"
        assert parametres.token_min_length == LONGEUR_MIN
        assert parametres.token_max_length == LONGEUR_MAX
        assert parametres.token_min_entropy == ENTROPIE_MIN_NIST

    def test_lectura_du_prefixe_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("KEYROCK_API_PORT", "9999")
        monkeypatch.setenv("KEYROCK_LOG_LEVEL", "debug")
        parametres = KeyRockSettings()
        assert parametres.api_port == 9999
        assert parametres.log_level == "DEBUG"


class TestValidation:
    def test_port_hors_bornes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("KEYROCK_API_PORT", "70000")
        with pytest.raises(ValidationError):
            KeyRockSettings()

    @pytest.mark.parametrize("niveau", ["TRACE", "bavard", ""])
    def test_niveau_log_invalide(self, niveau: str) -> None:
        with pytest.raises(ValidationError):
            KeyRockSettings(log_level=niveau)

    def test_max_inferieur_au_min(self) -> None:
        with pytest.raises(ValidationError):
            KeyRockSettings(token_min_length=64, token_max_length=32)


class TestCache:
    def test_rechargement(self, monkeypatch: pytest.MonkeyPatch) -> None:
        assert recharger_settings().api_port == 8000
        monkeypatch.setenv("KEYROCK_API_PORT", "9100")
        assert recharger_settings().api_port == 9100

    def test_cache_partage(self) -> None:
        assert get_settings() is get_settings()
