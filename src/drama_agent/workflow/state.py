from typing import TypedDict


class CharacterProfile(TypedDict):
    name: str
    appearance: str          # detailed visual description for prompts
    personality: str
    reference_image_url: str | None   # uploaded or extracted frame


class ShotDict(TypedDict):
    shot_id: str
    scene_number: int
    shot_number: int
    shot_type: str           # ShotType enum value (workflow/constants.py)
    camera_movement: str     # CameraMovement enum value (workflow/constants.py)
    # 光影是逐镜声明、而非交给模型每镜自由发挥:后者会让同一场戏的光线在镜间乱跳。
    # 值域见 constants.Lighting / ColorTemp;prompt_engineer 查 *_PHRASE 表写进 prompt。
    lighting: str
    color_temp: str
    duration_seconds: int
    # 镜内节拍(可选)。有它 = 这一镜由多个短促节拍(<下限秒,如击中/爆炸)合并而成,
    # 自然语言按顺序描述各节拍占多久、发生什么;None = 单一连续动作,无需合并。
    # 不结构化成 {seconds, action}——那还得再拼回自然语言,不如让 LLM 直接写。
    beats: list[str] | None
    description: str
    characters: list[str]
    dialogue: str
    action: str
    location: str


class PromptDict(TypedDict):
    shot_id: str
    prompt_text: str
    negative_prompt: str
    reference_image_url: str | None
    reference_role: str | None        # ReferenceRole enum value (workflow/constants.py)
    approved: bool
    edited_prompt: str | None
    edited_negative_prompt: str | None
    keyframe_url: str | None


class ReferenceDict(TypedDict):
    """背景参考图条目。角色形象不走这里 —— 见 services/reference_service 模块注释。

    历史数据里可能仍有 ref_type=character 的条目(读时兼容,不丢用户数据),
    但界面与下游都不再消费它们。
    """
    key: str                 # 场景地点(background);历史条目可能是角色名
    ref_type: str            # ReferenceType enum value (db/enums.py)
    image_url: str           # 空串 = 已列出但尚未上传(占位)
    # 生成该图用的 prompt(从分镜提炼后可人工改)。必须存下来:背景图很少一次满意,
    # 重生成时用户要改的正是它 —— 不存则每次重新提炼的结果都不同,用户无从迭代。
    prompt: str

class VideoDict(TypedDict):
    shot_id: str
    task_id: str             # provider task ID
    status: str              # queued/running/succeeded/failed
    video_url: str | None
    last_frame_url: str | None
    local_path: str | None
    error: str | None


class StoryAnalysis(TypedDict):
    title: str
    genre: str
    setting: str
    themes: list[str]
    characters: list[CharacterProfile]
    plot_summary: str
    scene_count_estimate: int
    tone: str


class DramaState(TypedDict):
    project_id: str          # 归属项目(角色跨集共享、存储顶层目录用)
    episode_id: str          # 本集 = LangGraph thread 身份
    episode_number: int
    title: str
    story_id: str | None     # 本集拍的那段原文(集的锚点;raw_input 取自它)
    script_id: str | None    # 起始剧本方案(null = 从故事开始,方案由流水线产出)
    raw_input: str
    genre: str
    # 作品级视觉风格(VisualStyle 枚举值)。只有 project 一层来源,没有 story/script
    # 级覆盖 —— 与 genre 的四跳兜底链不同,直接查 Project.visual_style 即可。
    visual_style: str

    story_analysis: StoryAnalysis | None

    # 本集阵容:角色名 → Character.id。由 cast_review 确认后写入,下游一律按 id 取角色
    # (改名不断链)。不落独立表 —— 身份在作品级 Character,这里只是本集的解析结果。
    cast: dict[str, str]
    # 待人工确认的角色身份(名单外的新名字)。cast_resolve 写、cast_review 消费;
    # 确认后清空。必须在状态里(而非只在 interrupt 载荷里)前端才读得到。
    cast_pending: list[dict]

    screenplay: str
    screenplay_approved: bool
    screenplay_revision_notes: str

    shots: list[ShotDict]
    target_seconds: int              # 集级目标时长(秒),驱动分镜总时长收敛
    storyboard_approved: bool        # 分镜是否已通过审核
    storyboard_revision_notes: str   # 分镜被打回时的人工意见(重生成参考)
    duration_over_target: bool       # 压到每镜下限仍超目标(前端据此提示退回重做)

    prompts: list[PromptDict]
    prompts_approved: bool
    prompt_revision_notes: str

    use_keyframes: bool
    keyframe_image_model: str
    keyframes_approved: bool

    videos: list[VideoDict]
    # 背景参考图清单(唯一真相,带 ref_type)。**角色形象不在这里** —— 走造型(Look),
    # 由 subject_ref_service 下发。旧的 character_references 已废弃(读时兼容升级)。
    references: list[ReferenceDict]

    look_assignments: dict[str, dict[str, str]]
    look_assignments_approved: bool

    current_stage: str
    error: str | None
    llm_model: str
    video_model: str
    video_provider: str
    resolution: str
    aspect_ratio: str
    assembled_video_path: str | None
