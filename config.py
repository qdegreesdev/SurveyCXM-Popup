import os
from pydantic_settings import BaseSettings
from dotenv import load_dotenv

load_dotenv(override=True)

class Settings(BaseSettings):
    # ── MySQL (matches your existing naming convention) ─────────
    survey_db_host: str = "localhost"
    survey_db_port: int = 3306
    survey_db_name: str = "surveycxm"
    survey_db_user: str = "root"
    survey_db_password: str = ""

    # ── OpenAI ──────────────────────────────────────────────────────
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    
    # ── Server ──────────────────────────────────────────────────────
    base_url: str = ""

    # ── CORS Origins ────────────────────────────────────────────────
    cors_origins: str = "http://localhost:5173,http://localhost:3000,http://127.0.0.1:5173"

    # ── Dev flag: use mock data when DB not configured ───────────────
    use_mock_data: bool = False
    
    # ── Environment ─────────────────────────────────────────────────
    environment: str = "local"

    # ── Security ────────────────────────────────────────────────────
    admin_secret: str = "change_me"

    @property
    def cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    class Config:
        env_file = ".env"
        extra = "ignore"

settings = Settings()
