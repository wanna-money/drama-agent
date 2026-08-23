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

    # MiniMax H3 视频 (v2, api.minimaxi.com) — 与文本模型独立
    minimax_video_api_key: str = ""
    minimax_video_base_url: str = "https://api.minimaxi.com"

    # GLM (Zhipu)
    glm_api_key: str = ""
    glm_base_url: str = "https://open.bigmodel.cn/api/paas/v4"

    ark_api_key: str = ""
    openai_api_key: str = ""
    # 素材库存储(工厂):开发本地目录 / 生产 CFS(预留)
    asset_storage_backend: str = "local"      # local | cfs
    asset_local_dir: str = "./data/assets"    # local backend 的素材根目录
    seedance_endpoint_id: str = ""
    seedance_2_5_endpoint_id: str = ""       # Seedance 2.5 Ark 接入点(独立于 2.0)

    # Provider 适配层:用户自定义 provider/model 声明(新增或覆盖内置)。
    # .env 以 JSON 写:CUSTOM_PROVIDERS='[{"id":...,"protocol":"openai-compat",...}]'
    custom_providers: list[dict] = Field(default=[])

    # Job worker（后台任务运行时）
    worker_poll_interval: float = 2.0
    job_heartbeat_timeout: int = 120
    worker_instance_id: str = ""  # 空则运行时用 hostname+pid

    # Dify 知识库（外部检索源;空 base_url 则知识走常量兜底）
    dify_base_url: str = ""            # 自部署填自己的 host（如 https://dify.mycorp.com）
    dify_api_key: str = ""            # 知识库 API Key（服务端保存）
    dify_dataset_ids: dict = Field(default={})   # {kind: dataset_id}
    knowledge_retrieve_timeout: int = 10

    # 知识后端声明式接入(Provider 化);空则由 build_default_registry 从上面 dify_* 派生。
    # .env 以 JSON 写:KNOWLEDGE_BACKENDS='[{"id":"biz","type":"dify","kinds":[...],"config":{...}}]'
    knowledge_backends: list[dict] = Field(default=[])

    app_host: str = "0.0.0.0"
    app_port: int = 8888
    debug: bool = True
    db_echo: bool = False   # SQLAlchemy 是否回显 SQL(与 debug 解耦,默认关,避免刷屏)

    data_dir: str = "./data"
    upload_dir: str = "./data/uploads"
    output_dir: str = "./data/outputs"

    database_url: str = "sqlite+aiosqlite:///./data/drama_agent.db"
    langgraph_db_path: str = "./data/langgraph_checkpoints.db"

    cors_origins: list[str] = ["http://localhost:5173", "http://localhost:3000"]


settings = Settings()
