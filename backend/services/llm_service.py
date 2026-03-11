"""LLM 服务工厂模块

提供 LLM 实例的创建和管理。
"""

from typing import Optional

from ..config.paths import CONFIG_DIR
from ..config.settings import Settings
from ..providers.openai_llm import OpenaiLlm


def get_llm(settings: Optional[Settings] = None) -> OpenaiLlm:
    """获取 LLM 实例
    
    根据配置创建 OpenAI 兼容的 LLM 实例。
    
    Args:
        settings: 配置对象，如果为 None 则从配置文件加载
        
    Returns:
        OpenaiLlm 实例
        
    Raises:
        ValueError: 如果 API Key 未配置
    """
    if settings is None:
        settings = Settings.load_from_file(CONFIG_DIR / "config.json")
    
    llm_config = settings.chat_llm
    api_config = llm_config.api
    
    if not api_config.key:
        raise ValueError("API Key 未配置，请在 config/config.json 中设置 chat_llm.api.key")
    
    return OpenaiLlm(
        model=llm_config.model,
        api_key=api_config.key,
        base_url=api_config.base_url,
        timeout=api_config.timeout
    )
