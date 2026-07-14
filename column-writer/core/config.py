import os
from pathlib import Path
from pydantic_settings import BaseSettings
from dotenv import load_dotenv

load_dotenv()


class Settings(BaseSettings):
    llm_api_key: str = ""
    llm_base_url: str = "https://api.openai.com/v1"
    llm_model_id: str = "gpt-4"
    llm_timeout: int = 180

    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-4"

    tavily_api_key: str = ""
    serpapi_api_key: str = ""

    max_depth: int = 3
    approval_threshold: int = 75
    revision_threshold: int = 60
    enable_parallel: bool = False
    enable_search: bool = True
    enable_review: bool = True
    max_revisions: int = 2

    host: str = "0.0.0.0"
    port: int = 8000
    cors_origins: str = ""
    log_level: str = "INFO"

    unsplash_access_key: str = ""
    unsplash_secret_key: str = ""
    vite_api_base_url: str = ""
    amap_api_key: str = ""
    vite_amap_web_key: str = ""

    word_count_level_1: int = 600
    word_count_level_2: int = 400
    word_count_level_3: int = 200
    word_count_tolerance: float = 0.1

    class Config:
        env_file = ".env"
        case_sensitive = False
        extra = "ignore"


_settings = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
        if _settings.openai_api_key and not _settings.llm_api_key:
            _settings.llm_api_key = _settings.openai_api_key
        if _settings.openai_base_url and _settings.llm_base_url == "https://api.openai.com/v1":
            _settings.llm_base_url = _settings.openai_base_url
        if _settings.openai_model and _settings.llm_model_id == "gpt-4":
            _settings.llm_model_id = _settings.openai_model
    return _settings


def get_word_count(level: int) -> int:
    settings = get_settings()
    word_counts = {
        1: settings.word_count_level_1,
        2: settings.word_count_level_2,
        3: settings.word_count_level_3
    }
    return word_counts.get(level, 400)
