"""各 protocol 用到的**功能键**及其官方默认路径。

前端「自定义接入路径」表单据此渲染:选了哪个 protocol,就只显示它认的那几个键,
placeholder 是官方默认值 —— 用户看得见"不填走什么"。后端校验也据此拒绝无效键
(打错键名会静默失效:配了却不生效,比报错更难查)。

这里是路径词表的**唯一真相**:新增 protocol 时在此登记一行,前端与校验自动跟上。
"""
from __future__ import annotations

# protocol key → {功能键: 官方默认相对路径}
# 路径里的 {task_id} 是占位符(部分网关用路径段而非 query 参数传任务 id)。
PROTOCOL_OPS: dict[str, dict[str, str]] = {
    # —— llm ——
    "openai-compat": {"chat": "/chat/completions"},
    "openai-responses": {"responses": "/responses"},
    # —— image ——
    "openai-image": {
        "image_generate": "/images/generations",
        "image_edit": "/images/edits",
    },
    "doubao-image": {"image_generate": "/images/generations"},
    # —— video ——
    "seedance": {
        "video_submit": "/contents/generations/tasks",
        "video_query": "/contents/generations/tasks/{task_id}",
    },
    "minimax": {
        "video_submit": "/v2/video_generation",
        "video_query": "/v2/query/video_generation/{task_id}",
    },
}

# 语义字段 → 说明(前端 response_map 表单渲染 + 后端校验用)。
# 值为空表示"该字段无官方默认路径,不声明即不取"。
RESPONSE_FIELDS: dict[str, str] = {
    "task_id": "提交响应里的任务 id",
    "status": "查询响应里的状态字段",
    "video_url": "成片地址",
    "last_frame_url": "尾帧地址",
    "error": "错误信息",
    "seed": "实际使用的 seed",
    "duration": "实际生成时长(秒);提交 -1 时靠它拿到真实值",
    "status_succeeded": "该网关表示「成功」的状态词",
    "status_failed": "该网关表示「失败」的状态词",
}


def ops_of(protocol: str) -> dict[str, str]:
    """该 protocol 认的功能键 → 官方默认路径;未登记的 protocol 返回空(= 不支持自定义)。"""
    return PROTOCOL_OPS.get(protocol, {})
