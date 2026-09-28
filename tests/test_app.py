"""Tests de l'application FastAPI (montage, cycle de vie, OpenAPI)."""

from __future__ import annotations

from keyrock_api.main import VERSION, creer_application


class TestApplication:
    def test_titre_et_version(self) -> None:
        application = creer_application()
        assert application.title == "KeyRock API"
        assert application.version == VERSION

    def test_openapi_genere_automatiquement(self) -> None:
        schema = creer_application().openapi()
        assert "/api/v1/generate" in schema["paths"]
        assert "post" in schema["paths"]["/api/v1/generate"]
        assert "/health" in schema["paths"]

    def test_middlewares_enregistres(self) -> None:
        noms = {m.cls.__name__ for m in creer_application().user_middleware}
        assert "SecurityHeadersMiddleware" in noms
        assert "RateLimiterMiddleware" in noms
