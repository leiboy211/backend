import os
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


BACKEND_ENV_PATH = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    app_env: str = "local"

    model_config = SettingsConfigDict(
        env_file=None if os.getenv("APP_ENV", "").strip().lower() == "production" else str(BACKEND_ENV_PATH),
        case_sensitive=False,
        protected_namespaces=("settings_",),
    )

    frontend_url: str = "http://localhost:5173"
    backend_url: str = "http://localhost:8000"
    database_url: str
    database_sslmode: str | None = None
    database_statement_timeout_ms: int = 60000
    database_pool_size: int = 5
    database_max_overflow: int = 10
    database_pool_timeout: int = 30
    database_pool_recycle: int = 300
    jwt_secret: str
    jwt_issuer: str = "devpath"

    github_client_id: str
    github_client_secret: str
    github_redirect_uri: str

    hf_token: str | None = None
    hf_space_url: str | None = None
    hf_endpoint_url: str = "https://router.huggingface.co/hf-inference"
    flan_t5_model: str | None = None
    model_alias: str | None = None

    @field_validator("flan_t5_model", "hf_token", "hf_endpoint_url", mode="before")
    @classmethod
    def clean_env_strings(cls, v: str | None) -> str | None:
        if not v or not isinstance(v, str):
            return v
        cleaned = v.strip().strip('"').strip("'")
        if "=" in cleaned:
            cleaned = cleaned.split("=", 1)[1].strip().strip('"').strip("'")
        return cleaned
    use_llm_refiner: bool | None = None
    llm_refiner_provider: str = "groq"
    llm_refiner_api_key: str | None = None
    llm_refiner_api_key_2: str | None = None
    llm_refiner_base_url: str = "https://api.groq.com/openai/v1"
    llm_refiner_model: str = "llama-3.1-8b-instant"
    admin_usernames: str | None = None
    admin_login_username: str | None = None
    admin_login_password: str | None = None
    faculty_login_username: str | None = None
    faculty_login_password: str | None = None

settings = Settings()
