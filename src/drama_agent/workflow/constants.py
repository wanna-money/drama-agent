"""创作域枚举与常量:镜头类型/运镜/参考帧角色的合法取值(接口契约),及镜头时长边界。

与 db/enums.py(持久化/任务状态)分开:这里是"领域词汇",那里是"生命周期状态"。
这些是硬约束(下游代码/视频 API 依赖其字面值),模型只能从中选取,不能自由发明。
具体选哪个、镜头多长(≤ 上限)仍是模型的创作决策。
"""
from enum import Enum


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


SHOT_TYPE_DESC: dict[str, str] = {
    ShotType.ELS.value: "Extreme Long Shot - vast environment",
    ShotType.LS.value: "Long Shot - full body visible",
    ShotType.MS.value: "Medium Shot - waist up",
    ShotType.CU.value: "Close-Up - face fills frame",
    ShotType.ECU.value: "Extreme Close-Up - eyes/hands detail",
}
