"""未来实现:向量检索走 Postgres pgvector + embedding(已接的 OpenAI 兼容端点)。

本期占位,证明 KnowledgeStore 接口可扩展到 RAG;当前统一用 ConstantKnowledgeStore。
"""


class PgVectorKnowledgeStore:
    def retrieve(
        self, kind: str, key: str | None = None, query: str | None = None, k: int = 3
    ) -> list[str]:
        raise NotImplementedError(
            "pgvector-backed retrieval not implemented; using ConstantKnowledgeStore for now"
        )
