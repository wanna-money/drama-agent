"""Dify 知识库检索:POST /v1/datasets/{id}/retrieve。

只负责"查 dify":命中→返回 chunks;dataset 未配 / 命中空 / HTTP 失败→返回 []。
降级(回落常量)由 KnowledgeRegistry 统一处理(CLAUDE.md 规范 4/6),本类不自兜。
"""
import httpx
import structlog

logger = structlog.get_logger()


class DifyKnowledgeStore:
    def __init__(self, base_url: str, api_key: str, dataset_ids: dict[str, str],
                 timeout: int = 10):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.dataset_ids = dataset_ids or {}
        self.timeout = timeout

    def retrieve(
        self, kind: str, key: str | None = None, query: str | None = None, k: int = 3
    ) -> list[str]:
        dataset_id = self.dataset_ids.get(kind)
        if not dataset_id:
            return []
        text = (query or key or kind)[:250]
        try:
            data = self._post(dataset_id, text, k)
            records = data.get("records") or []
            chunks = [(r.get("segment") or {}).get("content", "") for r in records]
            return [c for c in chunks if c][:k]
        except Exception as e:  # noqa: BLE001 — 失败返回空,由 registry 兜底
            logger.warning("dify retrieve failed", kind=kind, error=str(e))
            return []

    def _post(self, dataset_id: str, query: str, k: int) -> dict:
        url = f"{self.base_url}/v1/datasets/{dataset_id}/retrieve"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        body = {"query": query, "retrieval_model": {"top_k": k}}
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.post(url, headers=headers, json=body)
            resp.raise_for_status()
            return resp.json()
