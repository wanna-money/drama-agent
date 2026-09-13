"""角色四视图 AI 生成:一张 sheet 文生图(复用 asset_gen_service)+ Pillow 裁四张。

单次生成保证四视图一致;不需要参考图条件生成(现图片栈不支持,已绕开)。
"""
from __future__ import annotations

from io import BytesIO

from PIL import Image

from drama_agent.services import asset_gen_service
from drama_agent.workflow.constants import VISUAL_STYLE_PHRASE

_WHITE_CUTOFF = 240   # 灰度 ≥ 此值视为白底
_ROW_SAMPLE = 200     # 采样行数上限(加速)


def _sheet_prompt(character_desc: str, look_desc: str, visual_style: str = "") -> str:
    """四视图拼图的 prompt。

    "**单行横排 + 视图之间留白**"这两句是自动裁切的前提:crop_four_views 靠竖向纯白空隙
    定位分界,模型一旦排成 2x2 网格或让人物彼此紧贴,就只剩 1 条空隙、裁切必然失败
    (实测在接近方形的画布上尤其容易发生)。
    """
    style_phrase = VISUAL_STYLE_PHRASE.get(visual_style, "")
    style_clause = f"整体视觉风格:{style_phrase}。" if style_phrase else ""
    return (
        f"角色四视图 character turnaround sheet。角色:{character_desc}。造型/服饰:{look_desc}。"
        f"{style_clause}"
        "严格排成**一行**(single horizontal row, 1x4 layout),从左到右依次是:"
        "正面全身、侧面(profile)全身、背面全身、面部特写(face close-up);"
        "禁止 2x2 网格或多行排列;"
        "相邻视图之间留出明显的纯白竖向间隔(clear white vertical gap between each view),"
        "人物之间不得重叠或紧贴;"
        "四个视图为同一角色同一造型,保持一致的五官/发型/妆容/服装/气质;"
        "面部特写清晰展示五官、肌肤纹理、妆容与发丝细节;"
        "纯白背景,无文字,无水印,无边框。"
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


_FALLBACK_SIZE = "1024x1024"   # 各家图片模型都支持的方图


def _resolve_model(model_id: str):
    """解析出该模型的声明(能力的唯一真相在 registry);解析不到返回 None。"""
    from drama_agent import provider as provider_pkg
    try:
        _prov, mdl = provider_pkg.provider_registry.resolve_model(model_id)
    except Exception:  # noqa: BLE001 — 解析不到不阻断,由 pick_sheet_size 兜底
        return None
    return mdl


def _aspect(res: str) -> float | None:
    """"1536x1024" → 1.5;非法格式返回 None(声明来自 DB / 界面,可能有脏数据)。"""
    parts = res.lower().split("x")
    if len(parts) != 2:
        return None
    try:
        w, h = int(parts[0]), int(parts[1])
    except ValueError:
        return None
    return w / h if h > 0 else None


_TARGET_ASPECT = 4.0   # 四个视图一字排开的天然比例


def pick_sheet_size(model) -> str:
    """四视图拼图的尺寸:在该模型**声明的** resolutions 里挑最接近 4:1 的那个。

    两点都不能省:
      · 必须取自声明 —— 硬编码 "2048x576"(3.56:1)被 gpt-image-2 拒
        (「maximum supported aspect ratio is 3:1」),而各 provider 早已声明支持哪些尺寸
        (规范 4:能力的唯一真相在 registry)。
      · 必须朝 4:1 靠 —— 只挑"最宽"时会选到 1536x1024(1.5:1),那接近方形,模型会把
        四个视图排成 2x2 或彼此紧贴,竖向留白只剩 1 条,自动裁切必然失败(实测)。
    """
    if model is None:
        return _FALLBACK_SIZE
    valid = [(r, a) for r in (model.resolutions or []) if (a := _aspect(r)) is not None]
    if valid:
        return min(valid, key=lambda ra: abs(ra[1] - _TARGET_ASPECT))[0]
    return model.default_resolution or _FALLBACK_SIZE


async def generate_four_view_sheet(
    character_desc: str, look_desc: str, model_id: str, size: str | None = None,
    prompt: str | None = None, visual_style: str = "",
) -> tuple[bytes, tuple[bytes, bytes, bytes, bytes] | None]:
    """返回 (原始 sheet, 四视图) —— 裁切失败时后者为 None 而非抛错。

    sheet 原图必须一并回传:裁切失败时前端要拿它做人工裁切,只回裁切结果就把原图丢了。

    size 缺省时按模型声明挑(见 pick_sheet_size):写死一个值会在不支持该比例的模型上
    恒被拒(实测 gpt-image-2 拒 2048x576)。

    prompt 直给时不再用 character_desc/look_desc 拼:那是给"只有描述"的调用方用的默认拼法,
    而从剧本提炼来的 prompt 已由用户过目改定,再套一层模板会覆盖掉他改的措辞。
    """
    prompt = (prompt or "").strip() or _sheet_prompt(character_desc, look_desc, visual_style)
    size = size or pick_sheet_size(_resolve_model(model_id))
    images = await asset_gen_service.generate_image(model_id, prompt, size=size, n=1)
    if not images:
        raise ValueError("图片模型未返回结果")
    sheet = images[0]
    try:
        return sheet, crop_four_views(sheet)
    except CropFailed:
        return sheet, None
