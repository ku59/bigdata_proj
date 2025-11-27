from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    # Google Gemini
    GOOGLE_API_KEY: str
    GEMINI_MODEL_NAME: str = "gemini-2.5-flash"

    # DART / NAVER
    DART_API_KEY: str = "dd86489dc31f8aadc2a245bcdd92586dc9a5fd2a"
    NAVER_CLIENT_ID: str
    NAVER_CLIENT_SECRET: str

    # Search
    ELASTICSEARCH_HOST: str = "http://localhost:9200"
    ELASTICSEARCH_INDEX: str = "company_corpus"

    # Vector DB
    VECTOR_DB_DIR: str = "./data/vectorstore"

    # Resolve .env path relative to project root (bigdata_team_proj/.env)
    _ENV_PATH = Path(__file__).resolve().parents[2] / ".env"
    model_config = SettingsConfigDict(
        env_file=_ENV_PATH,
        env_file_encoding="utf-8",
    )

settings = Settings()
