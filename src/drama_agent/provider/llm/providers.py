"""内置 LLM provider 声明。base_url 锁死官方地址(唯一真相),凭证走各自 settings 字段。

内置 provider 的 base_url 是官方地址、不可在 UI 覆盖(见 api/providers.py update_provider);
用户只能改 api_key。新增内置 LLM provider = 在此加一条声明(+ 若为新协议在 protocols 登记)。
用户自定义(可自填 base_url)走 config.CUSTOM_PROVIDERS。
"""
from __future__ import annotations

from drama_agent.config import settings
from drama_agent.provider.base import Model, Provider

# 内置 LLM provider 的官方 base_url(锁死,UI 只读)。
DEEPSEEK_BASE_URL = "https://api.deepseek.com"


def builtin_llm_providers() -> list[Provider]:
    """构建内置 LLM provider 列表。

    base_url 用官方常量(不再取 settings.drama_base_url,内置一律连官网);
    api_key 用 settings 的真实值(已从 .env 读入),provider.resolve_credential()
    对普通字符串原样返回。
    """
    return [
        Provider(
            id="drama", label="DeepSeek", protocol="openai-compat",
            base_url=DEEPSEEK_BASE_URL,
            api_key=settings.drama_api_key or None,
            models=[
                Model(id="deepseek-v4-flash", label="DeepSeek V4 Flash", provider="drama", kind="llm"),
                Model(id="deepseek-v4-pro", label="DeepSeek V4 Pro", provider="drama", kind="llm"),
            ],
        ),
    ]
