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
    SCRIPT_START = "script_start"
    SCRIPT_RESUME = "script_resume"


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
