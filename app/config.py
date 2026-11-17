from pydantic import SecretStr
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    APP_NAME: str = "KagazAstra"
    APP_ENV: str = "development"
    PORT: int = 8000
    MONGODB_URL: str = "mongodb://localhost:27017"
    DATABASE_NAME: str = "kagazastra_db"
    SECRET_KEY: str = "supersecretkey_kagazastra_2026"
    
    ADMIN_EMAIL: str = ""
    ADMIN_PASSWORD: SecretStr = SecretStr("")
    SESSION_COOKIE_SECURE: bool = False

    # ==========================================
    # GROQ AI CONFIGURATION (Naya aur Active)
    # ==========================================
    GROQ_API_KEY: SecretStr = SecretStr("")
    GROQ_API_KEY_BACKUP: SecretStr = SecretStr("")

    # ==========================================
    # OLLAMA AI CONFIGURATION (Purana - Backup ke liye)
    # ==========================================
    OLLAMA_BASE_URL: str = "https://ollama.com"
    OLLAMA_MODEL: str = "gemma4:31b"
    OLLAMA_TIMEOUT_SECONDS: int = 300
    OLLAMA_API_KEY: SecretStr = SecretStr("")

    class Config:
        env_file = ".env"
        extra = "ignore"

settings = Settings()