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
    CLIP = "clip"            # 散片直接生成(job 的 episode_id 列载 clip_id)


class ClipTaskType(str, Enum):
    """散片的任务类型(Seedance 2.5 的 omni_reference_task_type)。

    自由字符串会静默走成另一种任务:平台按提示词自行判定,与我们以为的不一致时
    触发异步报错,而那时错误信息指向参数不兼容、与"我选了延长"对不上。
    """

    REFERENCE = "reference"   # 参考生视频:ratio / duration 无特殊限制
    EDIT = "edit"             # 视频编辑:ratio 必须 adaptive、duration 必须 -1
    EXTEND = "extend"         # 视频延长:ratio 必须 adaptive


class AdaptationStatus(str, Enum):
    """作品级改编阶段状态。与「各集聚合出的 Project 展示态」正交,互不覆盖。

    切分产出直接落成剧本(Script),没有"草稿待确认"这个中间态 —— 剧本库就是内容的家,
    切完即可在那里逐个编辑。故只有"没跑过 / 在跑 / 跑完 / 失败"四态。
    """
    NONE = "none"
    ANALYZING = "analyzing"        # 正在抽整本小说的角色
    CAST_REVIEW = "cast_review"    # 等人工确认角色身份(切分前的唯一卡点)
    ADAPTING = "adapting"          # 角色已定,正在切分
    DONE = "done"
    FAILED = "failed"


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


class VisualStyle(str, Enum):
    """作品级视觉风格(固定枚举)。建作品时必填,决定视频/图像生成的画面基调 ——
    与 Genre 同构:取值固定,不接受自由文本,避免不同集各自"翻译"出不一致的措辞。"""
    ANIME = "anime"              # 日系动漫风
    GUOMAN = "guoman"            # 国漫风
    REALISTIC = "realistic"      # 写实风
    INK = "ink"                  # 水墨风
    CYBERPUNK = "cyberpunk"      # 赛博朋克风
    RETRO_ANIME = "retro_anime"  # 复古动画风


VISUAL_STYLE_LABELS: dict[str, str] = {
    VisualStyle.ANIME.value: "日系动漫风",
    VisualStyle.GUOMAN.value: "国漫风",
    VisualStyle.REALISTIC.value: "写实风",
    VisualStyle.INK.value: "水墨风",
    VisualStyle.CYBERPUNK.value: "赛博朋克风",
    VisualStyle.RETRO_ANIME.value: "复古动画风",
}


class UsageKind(str, Enum):
    """用量记录类型(固定枚举)。"""
    LLM = "llm"
    IMAGE = "image"
    VIDEO = "video"
