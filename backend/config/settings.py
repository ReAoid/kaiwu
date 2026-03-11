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
    def load_from_file(cls, config_path: Optional[Path] = None, secrets_path: Optional[Path] = None) -> "Settings":
        """Load settings from config.json and secrets.json.
        
        config.json: General settings (can be committed to git)
        secrets.json: Sensitive settings like API keys (should not be committed)
        
        secrets.json takes precedence over config.json for overlapping keys.
        """
        if config_path is None:
            config_path = CONFIG_DIR / "config.json"
        if secrets_path is None:
            secrets_path = CONFIG_DIR / "secrets.json"
        
        config_data = {}
        
        # Load general config
        if config_path.exists():
            config_data = json.loads(config_path.read_text(encoding="utf-8"))
        
        # Load and merge secrets (takes precedence)
        if secrets_path.exists():
            secrets_data = json.loads(secrets_path.read_text(encoding="utf-8"))
            config_data = cls._deep_merge(config_data, secrets_data)
        
        if not config_data:
            # No config files exist, create defaults
            default_settings = cls()
            config_path.parent.mkdir(parents=True, exist_ok=True)
            config_path.write_text(
                json.dumps(default_settings.model_dump(exclude={"chat_llm"}), indent=2, ensure_ascii=False),
                encoding="utf-8"
            )
            return default_settings
        
        return cls.model_validate(config_data)
    
    @staticmethod
    def _deep_merge(base: dict, override: dict) -> dict:
        """Deep merge two dictionaries, override takes precedence."""
        result = base.copy()
        for key, value in override.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = Settings._deep_merge(result[key], value)
            else:
                result[key] = value
        return result
