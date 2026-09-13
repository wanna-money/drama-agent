"""创作域枚举与常量:镜头类型/运镜/参考帧角色的合法取值(接口契约),及镜头时长边界。

与 db/enums.py(持久化/任务状态)分开:这里是"领域词汇",那里是"生命周期状态"。
这些是硬约束(下游代码/视频 API 依赖其字面值),模型只能从中选取,不能自由发明。
具体选哪个、镜头多长(≤ 上限)仍是模型的创作决策。
"""
import logging
from enum import Enum

from drama_agent.db.enums import VisualStyle

logger = logging.getLogger(__name__)


class ShotType(str, Enum):
    ELS = "ELS"   # Extreme Long Shot
    LS = "LS"     # Long Shot
    MS = "MS"     # Medium Shot
    CU = "CU"     # Close-Up
    ECU = "ECU"   # Extreme Close-Up


class CameraMovement(str, Enum):
    STATIC = "static"
    PAN = "pan"
    TILT = "tilt"
    DOLLY = "dolly"
    ZOOM = "zoom"
    TRACKING = "tracking"
    CRANE = "crane"


class Lighting(str, Enum):
    """光照方案。分镜逐镜声明,prompt 据此写死光影 ——
    不声明则每镜由模型自由发挥,同一场戏的光线在镜间乱跳(视觉漂移的主因之一)。"""
    HIGH_KEY = "high_key"           # 明亮少影
    LOW_KEY = "low_key"             # 大光比重阴影
    NATURAL = "natural"             # 自然环境光
    GOLDEN_HOUR = "golden_hour"     # 日落前暖阳
    BLUE_HOUR = "blue_hour"         # 日落后冷调天光
    TUNGSTEN = "tungsten"           # 室内钨丝暖光
    NEON = "neon"                   # 霓虹/彩色光溢
    SILHOUETTE = "silhouette"       # 逆光剪影
    RIM_LIT = "rim_lit"             # 轮廓光
    OVERCAST = "overcast"           # 阴天柔光


class ColorTemp(str, Enum):
    """色温倾向。与 Lighting 分开:同一光照方案可走暖可走冷(如 neon 既有暖也有冷)。"""
    WARM = "warm"
    NEUTRAL = "neutral"
    COOL = "cool"
    MIXED = "mixed"        # 冷暖对撞(常用于人物内外境反差)


class ReferenceRole(str, Enum):
    FIRST_FRAME = "first_frame"
    LAST_FRAME = "last_frame"
    SUBJECT_REFERENCE = "subject_reference"
    REFERENCE_IMAGE = "reference_image"
    REFERENCE_VIDEO = "reference_video"
    REFERENCE_AUDIO = "reference_audio"


# 镜头时长边界(秒)。具体时长由模型按剧情节奏决定,代码只兜上下限。
MAX_SHOT_DURATION = 10
MIN_SHOT_DURATION = 5
DEFAULT_SHOT_DURATION = 5

# 短集(≤ SHORT_EPISODE_SECONDS)放宽单镜下限:5s 下限下 30 秒只容得 6 个镜头,
# 一条完整的起承转合装不进去。放宽到 3s 让短集能有 10 镜的叙事密度。
# 只对短集放宽 —— 常规集用 3s 镜头会把节奏切得过碎,且视频模型对极短镜头的表现更差。
SHORT_EPISODE_SECONDS = 30
SHORT_EPISODE_MIN_SHOT_DURATION = 3


def _narrative_shot_bounds(target_seconds: int) -> tuple[int, int]:
    """纯叙事区间(不看模型能力):短集放宽下限到 3s,常规集 5s 起,上限恒为 10s。"""
    lo = (SHORT_EPISODE_MIN_SHOT_DURATION
          if target_seconds <= SHORT_EPISODE_SECONDS else MIN_SHOT_DURATION)
    return lo, MAX_SHOT_DURATION


def shot_duration_bounds(target_seconds: int, model_ref: str = "") -> tuple[int, int]:
    """该集单镜时长的 [下限, 上限](秒)。**边界的唯一权威**,prompt 与收敛都必须走它
    (各自算一遍必然分叉:一边按 3s 收敛、另一边告诉模型下限是 5s)。

    两个约束求交:
      · 叙事约束(本模块):短集放宽到 3s、常规集 5s 起 —— 3s 镜头会把常规集切碎;
        上限 10s 是"一个镜头该有多长"的剪辑判断,不随模型能力放宽。
      · 模型能力(`Model.min_duration`/`max_duration`):平台收不下的值,给了也白给。
        三个内置模型下限都是 4 秒 —— 短集放宽到的 3 秒会被平台原样拒掉。

    模型区间比叙事上限宽时(如 Seedance 2.5 的 30s)**以叙事上限为准**——
    能力允许不等于该用,一集 120 秒塞几个 30 秒长镜会毁掉节奏。
    模型解析不到(未声明 model_ref、自定义 provider 未声明能力)时退回纯叙事区间。
    """
    lo, hi = _narrative_shot_bounds(target_seconds)
    if not model_ref:
        return lo, hi
    from drama_agent import provider as provider_pkg
    try:
        _p, m = provider_pkg.provider_registry.resolve_model(model_ref)
    except ValueError:
        return lo, hi
    if m.min_duration:
        lo = max(lo, m.min_duration)
    if m.max_duration:
        hi = min(hi, m.max_duration)
    if lo > hi:
        logger.warning(
            "shot_duration_bounds: narrative and model ranges don't overlap, "
            "using model floor (target_seconds=%s, model_ref=%s, narrative_hi=%s, model_lo=%s)",
            target_seconds, model_ref, hi, lo,
        )
        hi = lo
    return lo, hi


def min_shot_duration(target_seconds: int) -> int:
    """该集的单镜下限(不看模型能力)。仍对外保留 —— 部分调用点(如收敛函数的兜底)
    只需要叙事下限;需要模型能力时用 `shot_duration_bounds`。"""
    return _narrative_shot_bounds(target_seconds)[0]


SHOT_TYPE_DESC: dict[str, str] = {
    ShotType.ELS.value: "Extreme Long Shot - vast environment",
    ShotType.LS.value: "Long Shot - full body visible",
    ShotType.MS.value: "Medium Shot - waist up",
    ShotType.CU.value: "Close-Up - face fills frame",
    ShotType.ECU.value: "Extreme Close-Up - eyes/hands detail",
}

# 枚举 → 可直接写进 video prompt 的自然语言。prompt_engineer 查表,不让 LLM 自己翻译
# ——它每次译法不同,同一 lighting 值在不同镜头会得到不同措辞,声明的一致性就白费了。
LIGHTING_PHRASE: dict[str, str] = {
    Lighting.HIGH_KEY.value: "明亮的高调光,阴影浅淡",
    Lighting.LOW_KEY.value: "低调光,大光比,阴影浓重",
    Lighting.NATURAL.value: "自然环境光",
    Lighting.GOLDEN_HOUR.value: "黄金时刻的暖金色阳光,长投影",
    Lighting.BLUE_HOUR.value: "蓝调时刻的冷调天光",
    Lighting.TUNGSTEN.value: "室内钨丝灯的暖黄光",
    Lighting.NEON.value: "霓虹灯照明,彩色光溢",
    Lighting.SILHOUETTE.value: "强逆光,主体呈剪影",
    Lighting.RIM_LIT.value: "轮廓光勾勒主体边缘",
    Lighting.OVERCAST.value: "阴天的柔和散射光,无硬阴影",
}

COLOR_TEMP_PHRASE: dict[str, str] = {
    ColorTemp.WARM.value: "暖色调(琥珀/橙红)",
    ColorTemp.NEUTRAL.value: "中性色调,白平衡准确",
    ColorTemp.COOL.value: "冷色调(青蓝)",
    ColorTemp.MIXED.value: "冷暖对撞的混合色温",
}

# 视觉风格 → 可直接写进 prompt 的中文短语。与 LIGHTING_PHRASE 同一模式:查表而非
# 让 LLM 自行翻译枚举值 —— 否则同一 visual_style 在不同镜头/不同生成路径上译法漂移,
# "全作品统一画风"这个声明在落地时就散了。
VISUAL_STYLE_PHRASE: dict[str, str] = {
    VisualStyle.ANIME.value: "日系动漫风格,赛璐璐上色,干净的线稿,大眼睛精致五官",
    VisualStyle.GUOMAN.value: "国风国漫CG渲染风格,鲜艳平涂上色,粗黑轮廓线,电影级质感",
    VisualStyle.REALISTIC.value: "写实摄影质感,自然光影,真实材质细节,电影级镜头语言",
    VisualStyle.INK.value: "水墨画风格,墨色浓淡渲染,留白构图,写意笔触",
    VisualStyle.CYBERPUNK.value: "赛博朋克风格,高对比霓虹光效,金属机械质感,未来都市氛围",
    VisualStyle.RETRO_ANIME.value: "复古动画风格,90年代赛璐璐质感,颗粒胶片感,怀旧色调",
}
