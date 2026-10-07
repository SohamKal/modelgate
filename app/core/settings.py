"""Validated startup settings. Secrets are distinct from model configuration."""

from typing import Literal, Self

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.domain.contracts import Release


class MissingProviderSettings(ValueError):
    """Carry setting names, never their values, through Pydantic validation."""

    def __init__(self, names: list[str], provider: str) -> None:
        self.names = tuple(names)
        super().__init__(f"Missing required {provider} settings: " + ", ".join(names) + ".")


class MissingOpenAISettings(MissingProviderSettings):
    def __init__(self, names: list[str]) -> None:
        super().__init__(names, "OpenAI")


class MissingGroqSettings(MissingProviderSettings):
    def __init__(self, names: list[str]) -> None:
        super().__init__(names, "Groq")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="MODELGATE_",
        env_file=".env",
        extra="ignore",
        frozen=True,
        hide_input_in_errors=True,
        populate_by_name=True,
    )
    client_api_key: SecretStr
    stable_release: Literal["fake", "openai-a", "openai-b", "groq-a", "groq-b"] = "fake"
    verification_provider: Literal["openai", "groq"] = "openai"
    max_request_bytes: int = Field(default=65536, ge=1, le=65536)
    max_output_tokens: int = Field(default=1024, ge=200, le=4096)
    serving_deadline_seconds: float = Field(default=10, gt=0, le=60)
    serving_concurrency: int = Field(default=20, ge=1, le=128)
    openai_api_key: SecretStr | None = Field(default=None, validation_alias="OPENAI_API_KEY")
    openai_model_a: str | None = Field(default=None, validation_alias="OPENAI_MODEL_A")
    openai_model_b: str | None = Field(default=None, validation_alias="OPENAI_MODEL_B")
    openai_a_supports_temperature: bool = False
    openai_b_supports_temperature: bool = False
    groq_api_key: SecretStr | None = Field(default=None, validation_alias="GROQ_API_KEY")
    groq_model_a: str | None = Field(default=None, validation_alias="GROQ_MODEL_A")
    groq_model_b: str | None = Field(default=None, validation_alias="GROQ_MODEL_B")
    groq_a_supports_temperature: bool = False
    groq_b_supports_temperature: bool = False

    @field_validator("client_api_key")
    @classmethod
    def validate_client_key(cls, value: SecretStr) -> SecretStr:
        raw = value.get_secret_value()
        if len(raw) < 16 or raw.strip() != raw:
            raise ValueError("The gateway key must contain at least 16 characters without padding.")
        return value

    @field_validator("openai_model_a", "openai_model_b", "groq_model_a", "groq_model_b")
    @classmethod
    def validate_model(cls, value: str | None) -> str | None:
        if value == "":
            return None  # Empty placeholders in .env.example are optional for fake serving.
        if value is not None and (not value or len(value) > 128 or value.strip() != value):
            raise ValueError("Model identifiers must be nonempty and at most 128 characters.")
        return value

    @model_validator(mode="after")
    def require_provider_configuration(self) -> Self:
        for key in (self.openai_api_key, self.groq_api_key):
            if key and key.get_secret_value() == self.client_api_key.get_secret_value():
                raise ValueError("Gateway and provider credentials must be different.")
        if self.stable_release.startswith("openai-"):
            required = {
                "OPENAI_API_KEY": bool(
                    self.openai_api_key and self.openai_api_key.get_secret_value().strip()
                ),
                "OPENAI_MODEL_A": bool(self.openai_model_a),
                "OPENAI_MODEL_B": bool(self.openai_model_b),
            }
            missing = [name for name, present in required.items() if not present]
            if missing:
                raise MissingOpenAISettings(missing)
            if self.openai_model_a == self.openai_model_b:
                raise ValueError(
                    "Use distinct model identifiers for the two OpenAI configurations."
                )
        if self.stable_release.startswith("groq-"):
            required = {
                "GROQ_API_KEY": bool(
                    self.groq_api_key and self.groq_api_key.get_secret_value().strip()
                ),
                "GROQ_MODEL_A": bool(self.groq_model_a),
                "GROQ_MODEL_B": bool(self.groq_model_b),
            }
            missing = [name for name, present in required.items() if not present]
            if missing:
                raise MissingGroqSettings(missing)
            if self.groq_model_a == self.groq_model_b:
                raise ValueError("Use distinct model identifiers for the two Groq configurations.")
        return self

    def active_release(self) -> Release:
        if self.stable_release == "fake":
            return Release(name="fake", provider="fake", model="fake-v1", supports_temperature=True)
        if self.stable_release in {"groq-a", "groq-b"}:
            is_a = self.stable_release == "groq-a"
            model = self.groq_model_a if is_a else self.groq_model_b
            assert model is not None
            return Release(
                name=self.stable_release,
                provider="groq",
                model=model,
                supports_temperature=(
                    self.groq_a_supports_temperature if is_a else self.groq_b_supports_temperature
                ),
            )
        is_a = self.stable_release == "openai-a"
        model = self.openai_model_a if is_a else self.openai_model_b
        assert model is not None
        return Release(
            name=self.stable_release,
            provider="openai",
            model=model,
            supports_temperature=(
                self.openai_a_supports_temperature if is_a else self.openai_b_supports_temperature
            ),
        )
