"""对话附件:把用户上传的文件变成 LLM 能读的东西。

两条去处,按类型分流(**不是**同一条路):
  图片 → 保留为 base64 data URL,作为多模态 content 直接给模型看
  文档 → 现在就抽成纯文本,后续当普通文本拼进 prompt

分流在此一处收口:调用方(text_revise agent)只拿到 (文本块, 图片列表),
对"这是 PDF 还是 docx"零感知 —— 加一种文档格式 = 在 _EXTRACTORS 里加一行。

视频不在此列:它要先抽帧/转写才有文本,是一条独立链路(需要视觉或 ASR provider),
不能靠"加个解析器"糊过去。故显式拒绝,不静默当二进制塞给模型。
"""
from __future__ import annotations

import base64
import io
from collections.abc import Callable

import structlog

logger = structlog.get_logger()

# 单份附件的字节上限。大文件抽出的文本会挤爆上下文,也让一次请求贵得没道理。
MAX_BYTES = 20 * 1024 * 1024

# 抽出文本的字符上限(单份)。整本书塞进去既超窗又稀释用户真正的要求。
MAX_TEXT_CHARS = 20000

IMAGE_MIMES = frozenset({"image/png", "image/jpeg", "image/jpg", "image/webp", "image/gif"})

# 明确不支持的类型:与"未知类型"分开报错 —— 前者是能力边界(要另做一条链路),
# 后者可能只是缺个解析器。混成一个错误会让用户以为视频"迟早能支持"。
VIDEO_MIMES = frozenset({"video/mp4", "video/quicktime", "video/x-msvideo", "video/webm"})


class UnsupportedAttachment(ValueError):
    """该类型不支持。detail 直接给用户看,故要说清"为什么"和"能做什么"。"""


class AttachmentTooLarge(ValueError):
    pass


def _extract_txt(data: bytes) -> str:
    for enc in ("utf-8", "gb18030", "utf-16"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    # 兜底:替换非法字节而不是抛 —— 用户传来的剧本片段常有混合编码,
    # 丢几个字符仍可用,整份拒绝则什么也做不成。
    return data.decode("utf-8", errors="replace")


def _extract_pdf(data: bytes) -> str:
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(data))
    return "\n".join((page.extract_text() or "") for page in reader.pages)


def _extract_docx(data: bytes) -> str:
    import docx
    doc = docx.Document(io.BytesIO(data))
    return "\n".join(p.text for p in doc.paragraphs)


# mime → 抽文本函数。加一种文档格式在此加一行(扩展点,规范 5)。
_EXTRACTORS: dict[str, Callable[[bytes], str]] = {
    "text/plain": _extract_txt,
    "text/markdown": _extract_txt,
    "application/json": _extract_txt,
    "application/pdf": _extract_pdf,
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": _extract_docx,
}


def is_image(mime: str) -> bool:
    return (mime or "").lower() in IMAGE_MIMES


def to_data_url(data: bytes, mime: str) -> str:
    """图片转 data URL。不落盘 —— 对话附件是一次性的读物,存下来就得管生命周期。"""
    return f"data:{mime};base64,{base64.b64encode(data).decode()}"


def extract_text(data: bytes, mime: str, filename: str = "") -> str:
    """把文档抽成纯文本。不支持的类型显式抛,不返回空串。

    返回空串会让上层拿着"空附件"去调模型,用户以为 AI 读了他的文件,实际什么也没读到。
    """
    if len(data) > MAX_BYTES:
        raise AttachmentTooLarge(
            f"文件超过 {MAX_BYTES // 1024 // 1024}MB，请压缩或截取需要的部分")
    mime = (mime or "").lower()
    if mime in VIDEO_MIMES or mime.startswith("video/"):
        raise UnsupportedAttachment(
            "暂不支持视频：视频要先抽帧或转写台词才能读，是另一条链路。"
            "可以先截图上传，或把台词整理成文本")
    fn = _EXTRACTORS.get(mime)
    if fn is None:
        raise UnsupportedAttachment(
            f"不支持的文件类型（{mime or filename or '未知'}）。"
            "支持图片、txt / md / json、PDF、Word(.docx)")
    try:
        text = fn(data)
    except UnsupportedAttachment:
        raise
    except Exception as e:  # noqa: BLE001 — 解析失败要如实报,不能当成"没内容"
        logger.warning("attachment extract failed", mime=mime, filename=filename, error=str(e))
        raise UnsupportedAttachment(f"文件解析失败（{filename or mime}），请确认它没有损坏或加密")
    text = (text or "").strip()
    if not text:
        raise UnsupportedAttachment(
            f"没能从「{filename or mime}」里读出文字 —— 可能是扫描件或纯图片 PDF，"
            "可以改为截图上传让助手看图")
    return text[:MAX_TEXT_CHARS]
