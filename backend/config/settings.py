"""Configuration management using Pydantic."""
import json
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings

from .paths import CONFIG_DIR


class LLMApiConfig(BaseModel):
    """LLM API configuration."""
    key: Optional[str] = None
    base_url: Optional[str] = None
    timeout: int = 60


class ChatLLMConfig(BaseModel):
    """Chat LLM configuration."""
    model: str = "gpt-3.5-turbo"
    provider: str = "openai"
    temperature: float = 0.7
    api: LLMApiConfig = Field(default_factory=LLMApiConfig)


class SystemConfig(BaseModel):
    """System configuration."""
    debug: bool = False
    log_level: str = "INFO"


class Settings(BaseSettings):
    """Global application settings."""
    chat_llm: ChatLLMConfig = Field(default_factory=ChatLLMConfig)
    system: SystemConfig = Field(default_factory=SystemConfig)
    app_name: str = "Kaiwu"

    @classmethod
    def load_from_file(cls, config_path: Optional[Path] = None) -> "Settings":
        """Load settings from JSON config file.
        
        If the config file doesn't exist, creates it with default values.
        """
        if config_path is None:
            config_path = CONFIG_DIR / "config.json"
        
        if not config_path.exists():
            # Create default config
            default_settings = cls()
            config_path.parent.mkdir(parents=True, exist_ok=True)
            config_path.write_text(
                json.dumps(default_settings.model_dump(), indent=2, ensure_ascii=False),
                encoding="utf-8"
            )
            return default_settings
        
        config_data = json.loads(config_path.read_text(encoding="utf-8"))
        return cls.model_validate(config_data)
