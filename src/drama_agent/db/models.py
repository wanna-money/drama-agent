from datetime import datetime, timezone
from sqlalchemy import String, Text, DateTime, JSON, Integer, UniqueConstraint, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from drama_agent.db.enums import ClipTaskType, LifecycleStatus, VisualStyle


class Base(DeclarativeBase):
    pass


class Project(Base):
    """剧集元信息(剧名/类型)。单集流水线的输入与状态下沉到 Episode。
    status 不落库,按各集状态聚合派生(见 episode_service.aggregate_project_status)。"""
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    title: Mapped[str] = mapped_column(String(255))
    genre: Mapped[str] = mapped_column(String(100), default="drama")
    # 作品级视觉风格(固定枚举,建作品时前端必填)。default/server_default 只是 DB 层
    # 兜底(防止漏传时插入失败,含绕过 ORM 的原始 SQL insert),真正的"必填"由
    # CreateProjectRequest 不给默认值强制。
    visual_style: Mapped[str] = mapped_column(
        String(20), default=VisualStyle.REALISTIC.value,
        server_default=VisualStyle.REALISTIC.value)
    # 作品级「小说改编 → 分集切分」。见 specs/2026-08-25-novel-adaptation-episode-split-design.md
    source_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 切分依据二选一(接口层校验恰好一个非空)
    target_episodes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    target_seconds_per_episode: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # 整本小说的角色分析结果与待确认清单(切分前的角色卡点用)。
    # 确认后角色落成 Character 实体,这两个字段只是卡点期间的中间态。
    cast_analysis: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    cast_pending: Mapped[list | None] = mapped_column(JSON, nullable=True)
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
    # 本集拍的是哪段原文 —— 集的锚点。业务上必填(由 episode_service.create 强制),
    # DB 上可空只为兼容旧行:给已有表加 NOT NULL 列在 SQLite 要重建表
    # (与 Script.story_id 同例)。
    #
    # 为什么锚点是原文而不是剧本:集是一次**制作运行**,输入是原文,剧本是它要产出
    # 或在起点被塞进去的东西。"从一段故事开跑"的集压根还没有剧本。
    story_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    # 起始剧本方案(可空:从故事开跑时没有)。**只作溯源**,不是功能依赖 ——
    # 本集实际用的正文在 screenplay_versions(建集时快照进版本 0),改源剧本不影响
    # 在制作中的集。原文/分析/阵容一律经 story_id 取。
    script_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    # 目标时长(秒),驱动剧本篇幅与分镜总时长
    target_seconds: Mapped[int] = mapped_column(Integer, default=120, server_default="120")
    # 开拍那一刻定下的入口模式("from_story" / "from_script"),开拍后不再变。
    # 不存的话只能"看当前有没有正文"现算,而从故事开跑的集在剧本产出后判据就翻转了 ——
    # 左栏的剧本四步会在流程跑到一半时凭空消失(见 episode_service.entry_mode)。
    entry_mode_at_start: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # AI 改写版本树(从 Script 搬来)
    screenplay_versions: Mapped[list | None] = mapped_column(JSON, nullable=True)
    screenplay_version_current: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0"
    )
    # 分镜版本树(与 screenplay_versions 同构):storyboard_director 每次(重新)生成
    # 追加一条,而不是覆盖 —— 否则"退回重新生成"会让上一版分镜(可能更满意、
    # 已看过)无法再对比或恢复。
    shots_versions: Mapped[list | None] = mapped_column(JSON, nullable=True)
    shots_version_current: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0"
    )
    status: Mapped[str] = mapped_column(String(50), default=LifecycleStatus.CREATED)
    # 不给硬编码模型名默认值:默认模型的权威是 provider 注册表的 effective_default("llm")
    # (规范 4),由接口层/runner 解析后写入。空串 = 未指定,runner 起跑时兜底解析。
    llm_model: Mapped[str] = mapped_column(String(100), default="")
    video_provider: Mapped[str] = mapped_column(String(50), default="seedance")
    video_model: Mapped[str] = mapped_column(String(100), default="")
    resolution: Mapped[str] = mapped_column(String(20), default="768P")
    # 画面比例。短剧默认竖屏 —— 写死 16:9 会让所有集只能出横屏,
    # 而合法取值随模型不同(权威在 provider 注册表的 Model.aspect_ratios)。
    aspect_ratio: Mapped[str] = mapped_column(String(10), default="9:16", server_default="9:16")
    use_keyframes: Mapped[bool] = mapped_column(default=False)
    keyframe_image_model: Mapped[str] = mapped_column(String(100), default="")
    state_snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class Story(Base):
    """故事原文 —— 内容的源头。用户写/粘贴的那段文本,或从更长的一段切出来的一片。

    与 Script 是 **1:N**:同一段原文可以有多个改编方案(悬疑版/温情版),它们并列存在。
    这与 Episode 的 screenplay_versions 不同 —— 那是线性历史(改坏了回退),
    表达不了"我想试两个方向"。

    自指 parent_id 承载**切分**:一本小说切出 N 个片段,每片是一条子 Story(有序,
    见 order_index)。切分与改编是两种关系,故各走一条边:
      切分 → Story.parent_id;改编 → Script.story_id
    合成一条边再用类型字段区分的话,"这条记录是切片还是方案"就得靠枚举猜,
    而两者的下游语义完全不同(片段要接着改编,方案要拿去开拍)。

    story_analysis 与 cast 住在这里而不是 Script 上:改编流程"切分前先确认角色",
    说明角色名单是原文的属性 —— 挂在每个方案上就会被复制 N 份并各自漂移。
    """
    __tablename__ = "stories"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    # 切分来源(NULL = 顶层原文)。自指,不建外键(与 Look.character_id 同例,手工级联)
    parent_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    # 在父原文里的次序(第几段);顶层为 0。列表按它排,不按创建时间 ——
    # 切分是并发入库的,创建时间不保证与剧情顺序一致。
    order_index: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    title: Mapped[str] = mapped_column(String(255))
    genre: Mapped[str] = mapped_column(String(100), default="drama")
    content: Mapped[str | None] = mapped_column(Text, nullable=True)   # 原文正文
    story_analysis: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # 角色名 → Character.id
    cast: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class Script(Base):
    """剧本 —— 一段原文的一个改编方案。成稿剧本正文住在这里。

    story_id 指向它改编自哪段原文(1:N 的 N 侧)。原文正文、story_analysis、cast 都在
    Story 上,**不在此复制** —— 复制会让同一段原文的多个方案各持一份并逐渐漂移。

    source_text / story_analysis / cast 三列为兼容旧数据保留(迁移脚本读它们),
    新代码一律经 story_id 取原文侧的对应字段;这三列不再写入。
    """
    __tablename__ = "scripts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    # 改编自哪段原文。可空只为兼容旧行(迁移后应全部非空)
    story_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    title: Mapped[str] = mapped_column(String(255))
    genre: Mapped[str] = mapped_column(String(100), default="drama")
    content: Mapped[str | None] = mapped_column(Text, nullable=True)   # 成稿剧本正文
    # ↓ 旧列:仅迁移读取,新代码不写(权威已移到 Story)
    source_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    story_analysis: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    cast: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


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
    aspect_ratio: Mapped[str] = mapped_column(String(10), default="", server_default="")
    duration: Mapped[int] = mapped_column(default=5)
    action: Mapped[str] = mapped_column(String(50), default="generate")
    # 生成时的负向提示(已折进 prompt 送出);单独存一份,rerun 才能原样重放而不双份追加
    negative_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 平台回传的实际 seed:重跑要复现同一支视频只能靠它(不存则每次都是另一支)
    seed: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # 模型实际使用的 prompt(可能被平台改写);排查"为什么长这样"看它
    revised_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    task_id: Mapped[str] = mapped_column(String(128), default="")
    video_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    local_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    prompt_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 生成时用的参考图(RefImage 列表序列化);rerun/regenerate 据此重放,避免重跑丢角色/首帧。
    references_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # 生成时用的音色参考(RefAudio 列表序列化);与 references_json 对称,rerun/regenerate 保音色一致。
    audio_refs_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Clip(Base):
    """散片 —— 一次「直接生成」请求的完整生命周期。

    与 Episode 平级(都挂 project_id),不挂任何集:它不是"一集",挂到集上会让
    "集 = 一条流水线"这个语义失效。

    为什么不复用 VideoArtifact:那张表只在**成功后**才写,是"成品记录"——
    没有 queued/running/failed,没有 error_message。而这里必须让用户看到
    "排队中 / 生成中 / 失败了,原因是 X"。两张表并存是刻意的:
    Clip 是一次请求的生命周期,VideoArtifact 是一支成品的血统。
    """
    __tablename__ = "clips"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(36), index=True)
    prompt: Mapped[str] = mapped_column(Text)
    negative_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration: Mapped[int] = mapped_column(Integer, default=5)
    resolution: Mapped[str] = mapped_column(String(20), default="")
    aspect_ratio: Mapped[str] = mapped_column(String(10), default="")
    video_provider: Mapped[str] = mapped_column(String(50), default="")
    video_model: Mapped[str] = mapped_column(String(100), default="")
    # 平台回传的实际取值(仅 supports_seed 的模型有);重跑要复现同一支视频靠它
    seed: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # RefImage / RefAudio 的**原始语义**形态(相对 URL),不是内联后的 data URI ——
    # base64 会撑爆 DB,且重放时要重新内联一次
    references_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    audio_refs_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # RefVideo 的原始语义:装的是**storage key**,不是签名后的 URL ——
    # 预签名有有效期,存下来的 URL 会在到期后腐烂成一个看着正常、实际 403 的串。
    video_refs_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # ClipTaskType:参考生成 / 视频编辑 / 视频延长
    task_type: Mapped[str] = mapped_column(
        String(20), default=ClipTaskType.REFERENCE.value)
    # 本片在公网存储里的 key —— 供它自己之后被引用为编辑/延长的输入。
    # 平台回传的 video_url 24 小时就失效,故不能拿它当长期引用。
    storage_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), index=True, default=LifecycleStatus.CREATED.value)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    task_id: Mapped[str] = mapped_column(String(100), default="")
    # Text 而非定长:平台回传的是带签名 query 的长 URL,长度无契约上限。
    # 定长列在 Postgres 上溢出会抛而非截断 —— 一支**已生成成功**的散片会在落库这一步
    # 失败并被标 failed,错误信息还指向 DB 而非真正的成因。与 VideoArtifact 同名列一致。
    video_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    local_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    revised_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 用 Python 端默认值而非 server_default=func.now():SQLite 的 CURRENT_TIMESTAMP
    # 只有秒级精度,同一秒内建的多支散片会拿到相同 created_at,list_by_project
    # 的"最新在前"就退化成按随机 UUID 排序。微秒精度才能保证创建顺序可排。
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


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
    # 自定义接入路径与响应映射(见 provider/base.py:Provider.paths / response_map)。
    # 同一 protocol 被不同网关代理时,路径与响应形态因部署而异;留空 = 走协议官方默认。
    paths_json: Mapped[dict] = mapped_column(JSON, default=dict)
    response_map_json: Mapped[dict] = mapped_column(JSON, default=dict)
    # 后端专属配置(kind="storage" 用:bucket / region / secret_id / prefix /
    # expires_days)。凭证里的 SecretKey 仍走 api_key 列 —— 它已有 $ENV 解析与列表掩码,
    # 另存一份就会有两套凭证处理。
    config_json: Mapped[dict] = mapped_column(JSON, default=dict)
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
