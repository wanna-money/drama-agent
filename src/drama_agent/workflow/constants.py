"""创作域枚举与常量:镜头类型/运镜/参考帧角色的合法取值(接口契约),及镜头时长边界。

与 db/enums.py(持久化/任务状态)分开:这里是"领域词汇",那里是"生命周期状态"。
这些是硬约束(下游代码/视频 API 依赖其字面值),模型只能从中选取,不能自由发明。
具体选哪个、镜头多长(≤ 上限)仍是模型的创作决策。
"""
from enum import Enum

from drama_agent.db.enums import VisualStyle


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


# 镜头时长边界(秒)。MAX_SHOT_DURATION 是叙事层单镜上限(剪辑判断:一个镜头该
# 有多长,不随模型能力放宽);叙事层没有下限 —— 冲击/爆发类镜头可以短至 1 秒,
# 这正是本模块要保护的表达空间(见 generation_duration_for)。
MAX_SHOT_DURATION = 10
DEFAULT_SHOT_DURATION = 5


def generation_duration_for(narrative_seconds: int, model_ref: str = "") -> int:
    """这一镜提交给视频模型生成任务的时长(秒)。

    只看模型能力下限,不看叙事意图 —— 叙事时长(ShotDict.duration_seconds)可以
    短于模型下限,那正是要解决的问题:生成时长必须够模型下限才能提交任务,
    差额部分由 video_generator 生成后裁剪补上(见 services.video_trim)。

    model_ref 解析不到能力(空串、未知 provider、自定义 provider 未声明
    min_duration)时原样返回 narrative_seconds —— 没有约束就不需要抬高。
    """
    if not model_ref:
        return narrative_seconds
    from drama_agent import provider as provider_pkg
    try:
        _p, m = provider_pkg.provider_registry.resolve_model(model_ref)
    except ValueError:
        return narrative_seconds
    if m.min_duration and narrative_seconds < m.min_duration:
        return m.min_duration
    return narrative_seconds


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
