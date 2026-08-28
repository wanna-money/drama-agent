from datetime import datetime
from sqlalchemy import String, Text, DateTime, JSON, Integer, UniqueConstraint, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from drama_agent.db.enums import LifecycleStatus


class Base(DeclarativeBase):
    pass


class Project(Base):
    """剧集元信息(剧名/类型)。单集流水线的输入与状态下沉到 Episode。
    status 不落库,按各集状态聚合派生(见 episode_service.aggregate_project_status)。"""
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    title: Mapped[str] = mapped_column(String(255))
    genre: Mapped[str] = mapped_column(String(100), default="drama")
    # 作品级「小说改编 → 分集切分」。见 specs/2026-08-25-novel-adaptation-episode-split-design.md
    source_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 切分依据二选一(接口层校验恰好一个非空)
    target_episodes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    target_seconds_per_episode: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # 分集剧本草稿:[{index,title,screenplay}]
    adapted_draft: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # AdaptationStatus 取值(见 db/enums.py)
    adaptation_status: Mapped[str] = mapped_column(
        String(20), default="none", server_default="none")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class Episode(Base):
    """一集 = 一条独立流水线(剧本→分镜→prompt→视频)。
    id 承载 LangGraph thread_id;迁移时沿用原 project_id 字符串以保 thread 不失联。
    模型配置(llm/video/resolution)是集级属性,每集独立设置。"""
    __tablename__ = "episodes"
    __table_args__ = (
        UniqueConstraint("project_id", "episode_number", name="uq_episode_number"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(36), index=True)
    episode_number: Mapped[int] = mapped_column(Integer, default=1)
    title: Mapped[str] = mapped_column(String(255))
    # 复用剧本来源(可空 — 从故事开始时没有源剧本;记下血统但之后互不影响)
    script_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    # 从故事开始时的原始故事文本(原在 Script.source_text)
    raw_input: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 目标时长(秒),驱动剧本篇幅与分镜总时长
    target_seconds: Mapped[int] = mapped_column(Integer, default=120, server_default="120")
    # AI 改写版本树(从 Script 搬来)
    screenplay_versions: Mapped[list | None] = mapped_column(JSON, nullable=True)
    screenplay_version_current: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0"
    )
    status: Mapped[str] = mapped_column(String(50), default=LifecycleStatus.CREATED)
    # 不给硬编码模型名默认值:默认模型的权威是 provider 注册表的 effective_default("llm")
    # (规范 4),由接口层/runner 解析后写入。空串 = 未指定,runner 起跑时兜底解析。
    llm_model: Mapped[str] = mapped_column(String(100), default="")
    video_provider: Mapped[str] = mapped_column(String(50), default="seedance")
    video_model: Mapped[str] = mapped_column(String(100), default="")
    resolution: Mapped[str] = mapped_column(String(20), default="768P")
    use_keyframes: Mapped[bool] = mapped_column(default=False)
    keyframe_image_model: Mapped[str] = mapped_column(String(100), default="")
    state_snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class Script(Base):
    """全局剧本库的只读复用素材。没有 graph run —— 只由「某集剧本通过后存入」产生。"""
    __tablename__ = "scripts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    title: Mapped[str] = mapped_column(String(255))
    genre: Mapped[str] = mapped_column(String(100), default="drama")
    source_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    story_analysis: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class VideoArtifact(Base):
    __tablename__ = "video_artifacts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    episode_id: Mapped[str] = mapped_column(String(36), index=True)
    project_id: Mapped[str] = mapped_column(String(36), index=True)  # 冗余列,便于按项目聚合
    shot_id: Mapped[str] = mapped_column(String(100), index=True)
    parent_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    provider: Mapped[str] = mapped_column(String(50))
    model: Mapped[str] = mapped_column(String(100), default="")
    resolution: Mapped[str] = mapped_column(String(20), default="")
    duration: Mapped[int] = mapped_column(default=5)
    action: Mapped[str] = mapped_column(String(50), default="generate")
    task_id: Mapped[str] = mapped_column(String(128), default="")
    video_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    local_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    prompt_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 生成时用的参考图(RefImage 列表序列化);rerun/regenerate 据此重放,避免重跑丢角色/首帧。
    references_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # 生成时用的音色参考(RefAudio 列表序列化);与 references_json 对称,rerun/regenerate 保音色一致。
    audio_refs_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (UniqueConstraint("episode_id", "kind", "dedup_key", name="uq_job_dedup"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    episode_id: Mapped[str] = mapped_column(String(36), index=True)
    project_id: Mapped[str] = mapped_column(String(36), index=True)  # 冗余列
    kind: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), index=True, default="queued")
    owner: Mapped[str | None] = mapped_column(String(64), nullable=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    dedup_key: Mapped[str] = mapped_column(String(128), default="")
    payload_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class Event(Base):
    __tablename__ = "events"
    __table_args__ = (UniqueConstraint("episode_id", "seq", name="uq_event_seq"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    episode_id: Mapped[str] = mapped_column(String(36), index=True)
    project_id: Mapped[str] = mapped_column(String(36), index=True)  # 冗余列
    seq: Mapped[int] = mapped_column(Integer)
    type: Mapped[str] = mapped_column(String(30))
    payload_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class UsageRecord(Base):
    """一次 LLM/图像/视频调用的用量记录(只存用量,金额查询时按 Cost 估算)。"""
    __tablename__ = "usage_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    entity_id: Mapped[str] = mapped_column(String(36), index=True)   # episode.id 或 script.id
    project_id: Mapped[str] = mapped_column(String(36), index=True)  # 冗余,便于按项目聚合
    is_script: Mapped[bool] = mapped_column(default=False)
    node: Mapped[str] = mapped_column(String(64), default="")        # 节点名(来自 contextvar)
    kind: Mapped[str] = mapped_column(String(20))                    # UsageKind 值
    provider: Mapped[str] = mapped_column(String(64), default="")
    model: Mapped[str] = mapped_column(String(128), default="")
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    video_seconds: Mapped[int] = mapped_column(Integer, default=0)
    calls: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class CustomProvider(Base):
    """全部 provider(界面管理)。api_key 明文存;列表接口只回掩码。
    内置 provider 由 provider/seed.py 幂等种入(builtin=True,可改凭证/模型但不可删);
    界面新建的 builtin=False。model 声明内联在 models_json(随 provider 整体增删)。"""
    __tablename__ = "custom_providers"
    __table_args__ = (UniqueConstraint("provider_id", name="uq_custom_provider_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    provider_id: Mapped[str] = mapped_column(String(64), index=True)  # registry 里的 provider id
    label: Mapped[str] = mapped_column(String(255))
    protocol: Mapped[str] = mapped_column(String(50))
    kind: Mapped[str] = mapped_column(String(20))  # "llm" | "video" | "image"
    base_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    api_key: Mapped[str | None] = mapped_column(Text, nullable=True)  # 明文
    models_json: Mapped[list] = mapped_column(JSON, default=list)
    enabled: Mapped[bool] = mapped_column(default=True)
    builtin: Mapped[bool] = mapped_column(default=False)  # 种子内置=True,界面新建=False
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class Asset(Base):
    """全局共享素材库。文件走 AssetStorage 工厂(本地/CFS)存;表存元数据 + 存储 key。
    分类固定枚举(见 db.enums.AssetCategory)。创作时引用=拷贝素材图进剧集参考。"""
    __tablename__ = "assets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    category: Mapped[str] = mapped_column(String(20), index=True)   # AssetCategory 值
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    storage_key: Mapped[str] = mapped_column(String(512))          # AssetStorage 内相对 key
    mime: Mapped[str | None] = mapped_column(String(100), nullable=True)
    size_bytes: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )



class Character(Base):
    """项目级角色 —— 角色身份的**唯一权威**。跨该项目剧集共享;与全局素材库(Asset)解耦。

    description 与 appearance 是两种东西,同一行上的两列(不是两张表):
      description —— 人手写的备注(外貌/性格/设定,角色页那个输入框)
      appearance  —— AI 抽出的外貌描述,喂给视频/图片模型
    两者是同一行上的两列,**不要再拆出按名字关联的第二张表** —— 那样同一角色的描述会
    两处漂移,且改名后双双失联。
    """
    __tablename__ = "characters"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(36), index=True)
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    appearance: Mapped[str | None] = mapped_column(Text, nullable=True)
    voice_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class Look(Base):
    """角色的一套造型(服饰),持有正/侧/背/面部特写四视图的存储 key(front 必填,其余可选)。"""
    __tablename__ = "looks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    character_id: Mapped[str] = mapped_column(String(36), index=True)
    name: Mapped[str] = mapped_column(String(255), default="默认造型")
    is_default: Mapped[bool] = mapped_column(default=False)
    front_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    side_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    back_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    face_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )
