"""文本对话式改写(中立端点,不落库)+ 对话附件解析。

服务所有**不在流水线里**的文本:故事原文(剧本的 / 作品的小说)与剧本库里的剧本正文。
剧集里在审的剧本走 workflow.py 的 `/episodes/{id}/screenplay/revise` —— 那条路要落
版本树并写回图状态,与此处"只回结果、由前端确认后覆盖"的语义不同,但**用的是同一个
agent**(text_revise_service),规则与决策口径因此一致。

不在这里落库:AI 改写用户手写的东西必须先让他过目(原文没有版本树,改坏了无从回退)。
传 text 而不是 script_id —— 原文可能还没落库(新建剧本的表单里就要能用),且同一份
能力对剧本原文、作品小说、剧本正文三者通用。
"""
from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel

from drama_agent import provider as provider_pkg
from drama_agent.services import attachment_service as att
from drama_agent.services import text_revise_service as svc


router = APIRouter(prefix="/api/story-text", tags=["story-text"])


class ChatMessage(BaseModel):
    role: str        # "user" | "assistant"
    content: str


class Attachment(BaseModel):
    """一份已解析的附件。前端上传时就分好了流,此处只是原样带回来。

    图片带 data_url(多模态直给模型看),文档带 text(已抽好的正文)——
    两者不会同时非空,分流的权威在 attachment_service。
    """
    filename: str = ""
    text: str | None = None       # 文档抽出的正文
    data_url: str | None = None   # 图片 data URL


class ReviseIn(BaseModel):
    kind: svc.TextKind          # story | screenplay(非法值由 pydantic 拦成 422)
    text: str = ""             # 当前文本;可空(只有想法时让 AI 从零撰写)
    messages: list[ChatMessage]
    attachments: list[Attachment] = []
    model: str | None = None


def _model_or_422(explicit: str | None) -> str:
    if explicit:
        return explicit
    dm = provider_pkg.provider_registry.effective_default("llm")
    if dm is None:
        raise HTTPException(500, "未配置可用的文本模型，请先到「模型管理」配置")
    return dm.id


@router.post("/attachments")
async def parse_attachment(file: UploadFile = File(...)):
    """解析一份对话附件:图片回 data_url,文档回抽好的 text。

    在这里解析而不是把原文件传给 revise:附件是**一次性读物**,不落盘就没有生命周期
    要管;而前端拿到解析结果后可以在多轮对话里复用它,不必每轮重传原文件。
    """
    data = await file.read()
    mime = (file.content_type or "").lower()
    fn = file.filename or "upload"
    if att.is_image(mime):
        if len(data) > att.MAX_BYTES:
            raise HTTPException(422, f"图片超过 {att.MAX_BYTES // 1024 // 1024}MB")
        return {"filename": fn, "data_url": att.to_data_url(data, mime), "text": None}
    try:
        text = att.extract_text(data, mime, fn)
    except att.AttachmentTooLarge as e:
        raise HTTPException(422, str(e))
    except att.UnsupportedAttachment as e:
        # 能力边界与解析失败都是 422 且 detail 可读:前端直接展示,用户据此换个方式
        raise HTTPException(422, str(e))
    return {"filename": fn, "text": text, "data_url": None}


@router.post("/revise")
async def revise(body: ReviseIn):
    """跑一轮改写决策。action=ask 只回复;action=apply 带 text(由前端预览后落库)。"""
    if not body.messages:
        raise HTTPException(422, "请说明想怎么改")
    # 附件分两路进模型:文档正文作参考材料拼进 prompt,图片走多模态 content。
    # 带上文件名 —— 用户常说"按第二份文档改",没有名字模型无从对应。
    doc_texts = [
        f"《{a.filename}》\n{a.text}" if a.filename else str(a.text)
        for a in body.attachments if (a.text or "").strip()
    ]
    images = [str(a.data_url) for a in body.attachments if (a.data_url or "").strip()]
    result = await svc.turn(
        body.kind, body.text, [m.model_dump() for m in body.messages],
        _model_or_422(body.model),
        doc_texts=doc_texts or None, images=images or None,
    )
    return result
