"""跑图时携带当前调用归属(entity/项目/节点),供服务层记账读取。不污染节点函数签名。"""
from contextvars import ContextVar

_ctx: ContextVar[dict | None] = ContextVar("usage_ctx", default=None)


def set_usage_context(*, entity_id: str, project_id: str, is_script: bool, node: str) -> None:
    _ctx.set({"entity_id": entity_id, "project_id": project_id,
              "is_script": is_script, "node": node})


def current_usage_context() -> dict | None:
    return _ctx.get()
