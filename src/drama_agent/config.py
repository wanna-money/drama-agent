from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Generic drama endpoint (DRAMA_BASE_URL / DRAMA_API_KEY / DRAMA_TEXT_MODEL)
    drama_base_url: str = ""
    drama_api_key: str = ""
    drama_text_model: str = ""

    # Kimi (Moonshot)
    kimi_api_key: str = ""
    kimi_base_url: str = "https://api.moonshot.cn/v1"

    # MiniMax
    minimax_api_key: str = ""
    minimax_base_url: str = "https://api.minimax.chat/v1"

    # GLM (Zhipu)
    glm_api_key: str = ""
    glm_base_url: str = "https://open.bigmodel.cn/api/paas/v4"

    ark_api_key: str = ""
    seedance_endpoint_id: str = ""
    dashscope_api_key: str = ""

    app_host: str = "0.0.0.0"
    app_port: int = 8000
    debug: bool = True

    data_dir: str = "./data"
    upload_dir: str = "./data/uploads"
    output_dir: str = "./data/outputs"
    chroma_dir: str = "./data/chroma"

    database_url: str = "sqlite+aiosqlite:///./data/drama_agent.db"
    langgraph_db_path: str = "./data/langgraph_checkpoints.db"

    cors_origins: list[str] = ["http://localhost:5173", "http://localhost:3000"]

    video_models: list[dict] = Field(default=[
        {"value": "seedance", "label": "Seedance 2.0", "provider": "字节跳动"},
        {"value": "bailian",  "label": "万相 2.7",     "provider": "阿里云"},
    ])

    llm_models: list[dict] = Field(default=[
        {"value": "deepseek-v3",            "label": "DeepSeek V4 Pro",       "provider": "DeepSeek"},
        {"value": "kimi-k2-0711-preview",   "label": "Kimi K2",           "provider": "Kimi"},
        {"value": "glm-4-plus-0111",        "label": "GLM 4 Plus",        "provider": "GLM"},
        {"value": "MiniMax-Text-01",        "label": "MiniMax Text-01",   "provider": "MiniMax"},
    ])


settings = Settings()
