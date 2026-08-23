import pytest


def test_is_retryable_status():
    from drama_agent.services.retry import is_retryable_status
    for c in (429, 529, 500, 502, 503, 504):
        assert is_retryable_status(c) is True
    for c in (400, 401, 403, 404, 422):
        assert is_retryable_status(c) is False


@pytest.mark.asyncio
async def test_llm_retry_retries_then_succeeds():
    from drama_agent.services.retry import llm_retry
    import httpx
    calls = 0

    @llm_retry
    async def flaky():
        nonlocal calls
        calls += 1
        if calls < 3:
            raise httpx.HTTPStatusError(
                "rate", request=httpx.Request("GET", "http://x"),
                response=httpx.Response(429))
        return "ok"

    result = await flaky()
    assert result == "ok" and calls == 3


@pytest.mark.asyncio
async def test_llm_retry_does_not_retry_4xx():
    from drama_agent.services.retry import llm_retry
    import httpx
    calls = 0

    @llm_retry
    async def bad():
        nonlocal calls
        calls += 1
        raise httpx.HTTPStatusError(
            "bad", request=httpx.Request("GET", "http://x"),
            response=httpx.Response(400))

    with pytest.raises(httpx.HTTPStatusError):
        await bad()
    assert calls == 1
