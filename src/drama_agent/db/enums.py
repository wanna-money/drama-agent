from enum import Enum


class LifecycleStatus(str, Enum):
    CREATED = "created"
    QUEUED = "queued"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"


class JobKind(str, Enum):
    START = "start"
    RESUME = "resume"
    ADAPT = "adapt"          # 作品级:小说改编+分集切分(job 的 episode_id 列载 project_id)


class AdaptationStatus(str, Enum):
    """作品级改编阶段状态。与「各集聚合出的 Project 展示态」正交,互不覆盖。"""
    NONE = "none"
    ADAPTING = "adapting"
    DRAFT_READY = "draft_ready"
    FAILED = "failed"
    COMMITTED = "committed"


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class EventType(str, Enum):
    STAGE_CHANGE = "stage_change"
    PAUSED = "paused"
    COMPLETED = "completed"
    ERROR = "error"


class AssetCategory(str, Enum):
    """全局素材库分类(固定枚举)。"""
    CHARACTER = "character"      # 人物
    BACKGROUND = "background"    # 背景
    PROP = "prop"               # 道具
    COSTUME = "costume"         # 服饰


class ReferenceType(str, Enum):
    """参考图用途分类(固定枚举)。

    是接口契约:前端按此分组展示、下游节点按此过滤取图。**不要退回自由字符串** ——
    历史上 ref_type 只在请求体里存在、既不落库也不下发,前端只能按
    "名字是否出现在 story_analysis.characters" 反猜类型,导致从素材库选的
    角色参考图被判成背景图。类型的唯一权威在 services/reference_service。
    """
    CHARACTER = "character"      # 角色参考图,key 是角色名
    BACKGROUND = "background"    # 背景参考图,key 是场景地点


class ImageType(str, Enum):
    """项目图片的存储分类(固定枚举)。决定 uploads/{project_id}/{type}/ 子目录与访问 URL 段。

    UPLOADABLE 是客户端允许上传的取值;KEYFRAME 由关键帧节点生成,不接受上传但必须可读取。
    """
    CHARACTER = "character"
    BACKGROUND = "background"
    REFERENCE = "reference"
    KEYFRAME = "keyframe"


# 客户端可上传的图片类型(keyframe 是系统产物,不在其中)
UPLOADABLE_IMAGE_TYPES: frozenset[str] = frozenset(
    {ImageType.CHARACTER.value, ImageType.BACKGROUND.value, ImageType.REFERENCE.value}
)
# 可通过 URL 读取的图片类型 = 可上传的 + 系统生成的关键帧
SERVABLE_IMAGE_TYPES: frozenset[str] = frozenset(t.value for t in ImageType)


class CharacterView(str, Enum):
    """角色 Look 的四视图(固定枚举)。"""
    FRONT = "front"
    SIDE = "side"
    BACK = "back"
    FACE = "face"


class Genre(str, Enum):
    """短剧故事类型(固定枚举)。用于建项目时的类型选择,并作为 story_analyzer 的软引导上下文。"""
    DRAMA = "drama"
    ROMANCE = "romance"
    THRILLER = "thriller"
    COMEDY = "comedy"
    ACTION = "action"
    FANTASY = "fantasy"


GENRE_LABELS: dict[str, str] = {
    Genre.DRAMA.value: "剧情",
    Genre.ROMANCE.value: "爱情",
    Genre.THRILLER.value: "悬疑",
    Genre.COMEDY.value: "喜剧",
    Genre.ACTION.value: "动作",
    Genre.FANTASY.value: "奇幻",
}


class UsageKind(str, Enum):
    """用量记录类型(固定枚举)。"""
    LLM = "llm"
    IMAGE = "image"
    VIDEO = "video"
