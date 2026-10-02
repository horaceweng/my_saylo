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
    # When the cloud service fails (unreachable, timeout, 429, 5xx, unusable answers), do the work on this Mac instead.
    fallback_local: bool = True

    # This Mac has 16 GB: only one heavy local model may be in memory at a time (see services/compute.py).
    # Ollama frees its model this many seconds after the last request; local whisper is dropped after the same idle time.
    local_keep_alive_seconds: int = 60

    # Limits. A request to the LLM, and a media job as a whole (audio length x factor + extra seconds).
    llm_request_seconds: int = 120
    media_time_factor: float = 3.0
    media_time_extra_seconds: int = 600

    # Daily quotas per user (admins are exempt). A day ends at midnight in `quota_timezone`.
    quota_timezone: str = "Asia/Taipei"
    quota_media_per_day: int = 5
    quota_audio_minutes_per_day: int = 90
    quota_ai_requests_per_day: int = 300
    max_upload_mb: int = 100
    max_media_minutes: int = 90

    # New media and books are refused while the volume holding `data/` has less free space than this (GB).
    min_free_disk_gb: float = 20

    # In-memory rate limits (per minute): logins/sign-ups per IP, other API calls per user.
    rate_limit_auth_per_minute: int = 10
    rate_limit_api_per_minute: int = 120

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
