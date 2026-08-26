import os
from pathlib import Path

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
