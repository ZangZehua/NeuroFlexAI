from __future__ import annotations

import httpx
from openai import OpenAI

from .config import Settings


def create_openai_client(settings: Settings) -> OpenAI:
    """Create a consistently configured client.

    httpx keeps ``trust_env=True`` by default, so HTTPS_PROXY/HTTP_PROXY loaded
    from .env are honored without duplicating proxy configuration here.
    """
    timeout = httpx.Timeout(
        settings.openai_timeout,
        connect=settings.openai_connect_timeout,
    )
    return OpenAI(
        api_key=settings.api_key,
        base_url=settings.base_url,
        timeout=timeout,
        max_retries=settings.openai_max_retries,
    )


def create_chat_client(settings: Settings) -> OpenAI:
    settings.require_api_key()
    return create_openai_client(settings)
