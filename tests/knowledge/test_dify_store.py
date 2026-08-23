from unittest.mock import MagicMock, patch
import httpx


def _make_store(dataset_ids=None):
    from drama_agent.knowledge.dify_store import DifyKnowledgeStore
    return DifyKnowledgeStore(
        base_url="https://dify.example.com",
        api_key="k",
        dataset_ids=dataset_ids if dataset_ids is not None else {"prompt_template": "ds-1"},
        timeout=5,
    )


_DIFY_OK = {
    "query": {"content": "CU"},
    "records": [
        {"segment": {"content": "chunk-1"}, "score": 0.9},
        {"segment": {"content": "chunk-2"}, "score": 0.8},
        {"segment": {"content": "chunk-3"}, "score": 0.7},
    ],
}


def test_retrieve_parses_segment_content_and_limits_k():
    store = _make_store()
    with patch.object(store, "_post", new=MagicMock(return_value=_DIFY_OK)) as post:
        out = store.retrieve("prompt_template", key="CU", k=2)
    assert out == ["chunk-1", "chunk-2"]
    # 调用了正确 dataset 的 retrieve
    args, kwargs = post.call_args
    assert args[0] == "ds-1"


def test_unconfigured_kind_returns_empty():
    store = _make_store(dataset_ids={})  # 无任何 dataset 映射 → dify 不自兜,返回空
    assert store.retrieve("prompt_template", key="CU", k=2) == []


def test_http_failure_returns_empty():
    store = _make_store()

    def boom(*a, **k):
        raise httpx.ConnectError("down")

    with patch.object(store, "_post", new=boom):
        assert store.retrieve("prompt_template", key="CU", k=2) == []


def test_screenplay_guide_returns_empty_when_no_dataset():
    store = _make_store(dataset_ids={"prompt_template": "ds-1"})  # screenplay_guide 未配
    assert store.retrieve("screenplay_guide") == []


def test_dify_retrieve_is_sync_and_returns_list():
    from drama_agent.knowledge.dify_store import DifyKnowledgeStore
    store = DifyKnowledgeStore("http://dify.local", "k", {"prompt_guide": "ds1"}, timeout=5)
    fake_resp = MagicMock()
    fake_resp.json.return_value = {"records": [{"segment": {"content": "CHUNK_A"}}]}
    fake_resp.raise_for_status = MagicMock()
    fake_client = MagicMock()
    fake_client.__enter__.return_value.post.return_value = fake_resp
    with patch("drama_agent.knowledge.dify_store.httpx.Client", return_value=fake_client):
        out = store.retrieve("prompt_guide", key="minimax")
    assert out == ["CHUNK_A"]  # sync list, not a coroutine


def test_dify_returns_empty_on_error():
    from drama_agent.knowledge.dify_store import DifyKnowledgeStore
    store = DifyKnowledgeStore("http://dify.local", "k", {"prompt_guide": "ds1"}, timeout=5)
    fake_client = MagicMock()
    fake_client.__enter__.return_value.post.side_effect = RuntimeError("boom")
    with patch("drama_agent.knowledge.dify_store.httpx.Client", return_value=fake_client):
        assert store.retrieve("prompt_guide", key="minimax") == []


def test_dify_no_dataset_returns_empty():
    from drama_agent.knowledge.dify_store import DifyKnowledgeStore
    store = DifyKnowledgeStore("http://dify.local", "k", {}, timeout=5)
    assert store.retrieve("prompt_guide", key="minimax") == []
