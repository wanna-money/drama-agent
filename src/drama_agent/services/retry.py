"""HTTP 调用重试策略：429/529/5xx/超时/连接错指数退避，其余 4xx 不重试。"""
import httpx
from tenacity import (
    retry, stop_after_attempt, wait_exponential_jitter, retry_if_exception,
)

_RETRYABLE_CODES = {429, 529, 500, 502, 503, 504}


def is_retryable_status(code: int) -> bool:
    return code in _RETRYABLE_CODES


def _is_retryable_exc(exc: BaseException) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        return is_retryable_status(exc.response.status_code)
    if isinstance(exc, (httpx.TimeoutException, httpx.ConnectError, httpx.ReadError)):
        return True
    try:
        import openai
        if isinstance(exc, openai.APIStatusError):
            return is_retryable_status(getattr(exc, "status_code", 0))
        if isinstance(exc, (openai.APITimeoutError, openai.APIConnectionError)):
            return True
    except ImportError:
        pass
    return False


def _build(max_attempts: int = 4):
    return retry(
        retry=retry_if_exception(_is_retryable_exc),
        stop=stop_after_attempt(max_attempts),
        wait=wait_exponential_jitter(initial=0.05, max=30),
        reraise=True,
    )


llm_retry = _build()
video_api_retry = _build()
