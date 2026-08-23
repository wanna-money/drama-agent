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
    duration_seconds: int
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
    raw_input: str
    genre: str

    story_analysis: StoryAnalysis | None

    screenplay: str
    screenplay_approved: bool
    screenplay_revision_notes: str

    shots: list[ShotDict]

    prompts: list[PromptDict]
    prompts_approved: bool
    prompt_revision_notes: str

    use_keyframes: bool
    keyframe_image_model: str
    keyframes_approved: bool

    videos: list[VideoDict]
    character_references: dict[str, str]   # name -> image_url

    look_assignments: dict[str, dict[str, str]]
    look_assignments_approved: bool

    current_stage: str
    error: str | None
    llm_model: str
    video_model: str
    video_provider: str
    resolution: str
    assembled_video_path: str | None
