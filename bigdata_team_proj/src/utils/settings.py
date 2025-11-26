from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    # Google Gemini
    GOOGLE_API_KEY: str | None = None
    GEMINI_MODEL_NAME: str = "gemini-2.5-flash"

    # DART / NAVER
    DART_API_KEY: str
    NAVER_CLIENT_ID: str
    NAVER_CLIENT_SECRET: str

    # Search
    ELASTICSEARCH_HOST: str = "http://localhost:9200"
    ELASTICSEARCH_INDEX: str = "company_corpus"

    # Vector DB
    VECTOR_DB_DIR: str = "./data/vectorstore"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
    )

settings = Settings()
