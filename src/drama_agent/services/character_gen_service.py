"""角色四视图 AI 生成:一张 sheet 文生图(复用 asset_gen_service)+ Pillow 裁四张。

单次生成保证四视图一致;不需要参考图条件生成(现图片栈不支持,已绕开)。
"""
from __future__ import annotations

from io import BytesIO

from PIL import Image

from drama_agent.services import asset_gen_service

_WHITE_CUTOFF = 240   # 灰度 ≥ 此值视为白底
_ROW_SAMPLE = 200     # 采样行数上限(加速)


def _sheet_prompt(character_desc: str, look_desc: str) -> str:
    return (
        f"角色四视图 character turnaround sheet。角色:{character_desc}。造型/服饰:{look_desc}。"
        "从左到右均匀排四个:正面全身、侧面(profile)全身、背面全身、面部特写(face close-up),"
        "四个视图为同一角色同一造型,保持一致的五官/发型/妆容/服装/气质;"
        "面部特写清晰展示五官、肌肤纹理、妆容与发丝细节;"
        "纯白背景,居中,无文字,无水印,无边框。"
    )


class CropFailed(ValueError):
    """自动识别四视图分界失败。调用方据此引导人工裁切,而不是拿一份猜出来的切法。"""


def crop_four_views(sheet: bytes) -> tuple[bytes, bytes, bytes, bytes]:
    """按白底竖向空隙切成 front/side/back/face。

    找不到恰好三条内部空隙 → 抛 CropFailed。**不要加等分兜底**:等分线与真实人物位置
    不符时会把相邻视图切进同一张图,而错切与正切在返回值里无法区分,调用方与用户都
    无从判断这次切得对不对。宁可显式失败、转人工裁切。
    """
    img = Image.open(BytesIO(sheet)).convert("RGB")
    w, h = img.size
    gray = img.convert("L")
    data = gray.tobytes()   # 行主序、每字节 0..255;索引得 int(避开 PixelAccess 的宽松类型)
    step = max(1, h // _ROW_SAMPLE)
    is_gap = []
    for x in range(w):
        ink = 0
        for y in range(0, h, step):
            if data[y * w + x] < _WHITE_CUTOFF:
                ink += 1
                break  # 该列有墨即非空隙
        is_gap.append(ink == 0)
    # 收集空隙区间
    runs = []
    start = None
    for x in range(w):
        if is_gap[x] and start is None:
            start = x
        elif not is_gap[x] and start is not None:
            runs.append((start, x))
            start = None
    if start is not None:
        runs.append((start, w))
    internal = sorted(((s, e) for s, e in runs if s > 0 and e < w),
                      key=lambda r: r[1] - r[0], reverse=True)
    cuts = sorted((s + e) // 2 for s, e in internal[:3])
    if len(cuts) != 3:
        raise CropFailed(
            f"未能自动识别四视图分界(只找到 {len(cuts)} 条留白间隔,需要 3 条):"
            "请确认图为纯白背景、四个视图横向排列且彼此之间留白清晰,或改用手动裁切"
        )
    bounds = [(0, cuts[0]), (cuts[0], cuts[1]), (cuts[1], cuts[2]), (cuts[2], w)]
    out = []
    for x0, x1 in bounds:
        buf = BytesIO()
        img.crop((x0, 0, max(x1, x0 + 1), h)).save(buf, format="PNG")
        out.append(buf.getvalue())
    return out[0], out[1], out[2], out[3]


async def generate_four_view_sheet(
    character_desc: str, look_desc: str, model_id: str, size: str = "2048x576"
) -> tuple[bytes, tuple[bytes, bytes, bytes, bytes] | None]:
    """返回 (原始 sheet, 四视图) —— 裁切失败时后者为 None 而非抛错。

    sheet 原图必须一并回传:裁切失败时前端要拿它做人工裁切,只回裁切结果就把原图丢了。
    """
    prompt = _sheet_prompt(character_desc, look_desc)
    images = await asset_gen_service.generate_image(model_id, prompt, size=size, n=1)
    if not images:
        raise ValueError("图片模型未返回结果")
    sheet = images[0]
    try:
        return sheet, crop_four_views(sheet)
    except CropFailed:
        return sheet, None
