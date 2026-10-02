from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BASE_DIR / ".env", extra="ignore")

    ollama_base_url: str = "http://localhost:11434"
    llm_model: str = "qwen3:8b"
    whisper_model: str = "mlx-community/whisper-large-v3-turbo"
    data_dir: Path = BASE_DIR / "data"
    # The login cookie is only sent over https. Plain-http local use (scripts/start.sh) turns this off.
    cookie_secure: bool = True
    session_days: int = 30
    invite_days: int = 7

    # Where the AI work is done: on this Mac (ollama / local mlx-whisper) or by a cloud service that speaks the
    # OpenAI API (Gemini, OpenAI, Groq, OpenRouter …). Changed on the settings page.
    llm_backend: str = "ollama"  # ollama | cloud
    cloud_base_url: str = ""
    cloud_api_key: str = ""
    cloud_model: str = ""
    stt_backend: str = "local"  # local | cloud
    stt_base_url: str = ""
    stt_api_key: str = ""
    stt_model: str = ""

    @property
    def active_llm_model(self) -> str:
        """The model answers come from now (part of the cache key, so another model never reuses old answers)."""
        return self.cloud_model if self.llm_backend == "cloud" else self.llm_model

    @property
    def app_db_url(self) -> str:
        return f"sqlite:///{self.data_dir / 'app.sqlite'}"

    @property
    def dict_db_path(self) -> Path:
        return self.data_dir / "dict.sqlite"


settings = Settings()
