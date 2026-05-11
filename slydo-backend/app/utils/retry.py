"""
重试装饰器 — 指数退避重试

用法：
    @retry(max_attempts=3, delay=2, exceptions=(aiohttp.ClientError,))
    async def fetch_data(url):
        ...
"""
from __future__ import annotations

import asyncio
import functools
import logging
from typing import Any, Callable, TypeVar

logger = logging.getLogger(__name__)

F = TypeVar("F", bound=Callable[..., Any])


def retry(
    max_attempts: int = 3,
    delay: float = 2.0,
    backoff: float = 2.0,
    exceptions: tuple[type[Exception], ...] = (Exception,),
    on_retry: Callable[[Exception, int], None] | None = None,
) -> Callable[[F], F]:
    """
    异步函数重试装饰器。

    参数：
        max_attempts: 最大重试次数（默认 3）
        delay: 首次重试间隔秒数（默认 2）
        backoff: 退避系数（默认 2，即 2s → 4s → 8s）
        exceptions: 捕获的异常类型元组（默认所有 Exception）
        on_retry: 每次重试前的回调函数（接收异常和尝试次数）

    示例：
        @retry(max_attempts=3, delay=1, exceptions=(TimeoutError,))
        async def call_api():
            ...
    """
    def decorator(func: F) -> F:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            last_exception = None
            for attempt in range(1, max_attempts + 1):
                try:
                    return await func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    if attempt < max_attempts:
                        wait = delay * (backoff ** (attempt - 1))
                        logger.warning(
                            "%s 第 %d/%d 次失败: %s，%s 后重试...",
                            func.__name__, attempt, max_attempts, e, f"{wait:.1f}s",
                        )
                        if on_retry:
                            on_retry(e, attempt)
                        await asyncio.sleep(wait)
                    else:
                        logger.error(
                            "%s 重试 %d 次后仍失败: %s",
                            func.__name__, max_attempts, e,
                        )
            raise last_exception  # type: ignore[misc]
        return wrapper  # type: ignore[return-value]
    return decorator
