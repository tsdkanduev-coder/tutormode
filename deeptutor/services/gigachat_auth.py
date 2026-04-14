"""GigaChat Arena auth helpers modeled on the working Giga Cowork shim."""

from __future__ import annotations

from dataclasses import dataclass
import base64
import os
import threading
import time
from typing import Mapping

import httpx

from deeptutor.logging import get_logger

logger = get_logger("GigaChatAuth")

DEFAULT_GIGACHAT_ARENA_BASE_URL = "https://gigachat.sberdevices.ru/v2"
DEFAULT_GIGACHAT_ARENA_AUTH_URL = "https://gigachat.sberdevices.ru/v1/token"
DEFAULT_GIGACHAT_USER_AGENT = "GigaArena"


@dataclass(slots=True)
class ResolvedGigachatArenaCredentials:
    access_token: str | None = None
    username: str | None = None
    password: str | None = None
    auth_url: str = DEFAULT_GIGACHAT_ARENA_AUTH_URL
    user_agent: str = DEFAULT_GIGACHAT_USER_AGENT
    source: str = "none"


@dataclass(slots=True)
class _CachedGigachatArenaToken:
    cache_key: str
    token: str
    expires_at_ms: int | None = None


_TOKEN_CACHE: _CachedGigachatArenaToken | None = None
_TOKEN_CACHE_LOCK = threading.Lock()


def _trimmed(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _resolve_env(env: Mapping[str, str] | None = None) -> Mapping[str, str]:
    return env or os.environ


def normalize_gigachat_base_url(base_url: str | None) -> str:
    """Normalize the configured base URL to the Arena contour root (`.../v2`)."""
    base = _trimmed(base_url) or DEFAULT_GIGACHAT_ARENA_BASE_URL
    base = base.rstrip("/")
    if base.lower().endswith("/chat/completions"):
        return base[: -len("/chat/completions")]
    if base.lower().endswith("/v2"):
        return base
    return f"{base}/v2"


def resolve_gigachat_auth_url(
    base_url: str | None,
    env: Mapping[str, str] | None = None,
) -> str:
    """Resolve the token exchange URL using the same fallback order as Giga Cowork."""
    resolved_env = _resolve_env(env)
    explicit = _trimmed(resolved_env.get("GIGACHAT_AUTH_URL"))
    if explicit:
        return explicit

    base = _trimmed(base_url)
    if not base:
        return DEFAULT_GIGACHAT_ARENA_AUTH_URL

    try:
        parsed = httpx.URL(base)
        if parsed.scheme and parsed.host:
            return str(parsed.copy_with(path="/v1/token", query=None, fragment=None))
    except Exception:
        pass
    return DEFAULT_GIGACHAT_ARENA_AUTH_URL


def resolve_gigachat_credentials(
    *,
    base_url: str | None,
    api_key: str | None = None,
    env: Mapping[str, str] | None = None,
) -> ResolvedGigachatArenaCredentials:
    """Resolve GigaChat credentials using the Giga Cowork precedence order."""
    resolved_env = _resolve_env(env)
    auth_url = resolve_gigachat_auth_url(base_url, resolved_env)
    user_agent = _trimmed(resolved_env.get("GIGACHAT_USER_AGENT")) or DEFAULT_GIGACHAT_USER_AGENT

    explicit_api_key = _trimmed(api_key)
    if explicit_api_key and explicit_api_key != "SUA_CHAVE":
        return ResolvedGigachatArenaCredentials(
            access_token=explicit_api_key,
            auth_url=auth_url,
            user_agent=user_agent,
            source="profile_api_key",
        )

    explicit_token = _trimmed(resolved_env.get("GIGACHAT_ACCESS_TOKEN"))
    if explicit_token and explicit_token != "SUA_CHAVE":
        return ResolvedGigachatArenaCredentials(
            access_token=explicit_token,
            auth_url=auth_url,
            user_agent=user_agent,
            source="gigachat_access_token",
        )

    username = _trimmed(resolved_env.get("GIGACHAT_USERNAME")) or _trimmed(
        resolved_env.get("GIGACHAT_USER")
    )
    password = _trimmed(resolved_env.get("GIGACHAT_PASSWORD"))
    if username and password:
        return ResolvedGigachatArenaCredentials(
            username=username,
            password=password,
            auth_url=auth_url,
            user_agent=user_agent,
            source="gigachat_basic",
        )

    openai_api_key = _trimmed(resolved_env.get("OPENAI_API_KEY"))
    if openai_api_key and openai_api_key != "SUA_CHAVE":
        return ResolvedGigachatArenaCredentials(
            access_token=openai_api_key,
            auth_url=auth_url,
            user_agent=user_agent,
            source="openai_api_key",
        )

    return ResolvedGigachatArenaCredentials(
        auth_url=auth_url,
        user_agent=user_agent,
        source="none",
    )


def _get_cached_token(cache_key: str) -> str | None:
    now = int(time.time() * 1000)
    with _TOKEN_CACHE_LOCK:
        cached = _TOKEN_CACHE
        if cached is None or cached.cache_key != cache_key:
            return None
        if cached.expires_at_ms is not None and cached.expires_at_ms <= now + 30_000:
            return None
        return cached.token


def _set_cached_token(cache_key: str, token: str, exp: int | None) -> None:
    expires_at_ms = exp * 1000 - 60_000 if isinstance(exp, int) else None
    with _TOKEN_CACHE_LOCK:
        global _TOKEN_CACHE
        _TOKEN_CACHE = _CachedGigachatArenaToken(
            cache_key=cache_key,
            token=token,
            expires_at_ms=expires_at_ms,
        )


def _token_exchange_headers(
    credentials: ResolvedGigachatArenaCredentials,
    default_headers: Mapping[str, str] | None,
) -> dict[str, str]:
    headers = {str(k): str(v) for k, v in (default_headers or {}).items()}
    headers["Accept"] = "application/json"
    headers["User-Agent"] = credentials.user_agent
    return headers


def _build_basic_auth(username: str, password: str) -> str:
    raw = f"{username}:{password}".encode("utf-8")
    return base64.b64encode(raw).decode("ascii")


def resolve_gigachat_access_token_sync(
    *,
    base_url: str | None,
    api_key: str | None = None,
    default_headers: Mapping[str, str] | None = None,
    env: Mapping[str, str] | None = None,
) -> str:
    """Synchronously resolve an Arena access token for provider initialization."""
    credentials = resolve_gigachat_credentials(base_url=base_url, api_key=api_key, env=env)
    if credentials.access_token:
        return credentials.access_token

    if not credentials.username or not credentials.password:
        raise ValueError(
            "GigaChat auth requires api_key/access token or GIGACHAT_USERNAME/GIGACHAT_PASSWORD."
        )

    cache_key = f"{credentials.auth_url}|{credentials.username}|{credentials.password}"
    cached = _get_cached_token(cache_key)
    if cached:
        return cached

    headers = _token_exchange_headers(credentials, default_headers)
    headers["Authorization"] = f"Basic {_build_basic_auth(credentials.username, credentials.password)}"

    with httpx.Client(timeout=30.0) as client:
        response = client.post(credentials.auth_url, headers=headers)
        if response.status_code >= 400:
            raise ValueError(
                f"GigaChat token exchange failed with {response.status_code}: {response.text}"
            )
        data = response.json()

    token = data.get("tok")
    if not token:
        raise ValueError("GigaChat token exchange succeeded but response did not contain `tok`.")

    exp = data.get("exp")
    _set_cached_token(cache_key, token, exp if isinstance(exp, int) else None)
    logger.info("Resolved GigaChat access token via basic auth")
    return token


async def resolve_gigachat_access_token(
    *,
    base_url: str | None,
    api_key: str | None = None,
    default_headers: Mapping[str, str] | None = None,
    env: Mapping[str, str] | None = None,
) -> str:
    """Asynchronously resolve an Arena access token for request-time use."""
    credentials = resolve_gigachat_credentials(base_url=base_url, api_key=api_key, env=env)
    if credentials.access_token:
        return credentials.access_token

    if not credentials.username or not credentials.password:
        raise ValueError(
            "GigaChat auth requires api_key/access token or GIGACHAT_USERNAME/GIGACHAT_PASSWORD."
        )

    cache_key = f"{credentials.auth_url}|{credentials.username}|{credentials.password}"
    cached = _get_cached_token(cache_key)
    if cached:
        return cached

    headers = _token_exchange_headers(credentials, default_headers)
    headers["Authorization"] = f"Basic {_build_basic_auth(credentials.username, credentials.password)}"

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(credentials.auth_url, headers=headers)
        if response.status_code >= 400:
            raise ValueError(
                f"GigaChat token exchange failed with {response.status_code}: {response.text}"
            )
        data = response.json()

    token = data.get("tok")
    if not token:
        raise ValueError("GigaChat token exchange succeeded but response did not contain `tok`.")

    exp = data.get("exp")
    _set_cached_token(cache_key, token, exp if isinstance(exp, int) else None)
    logger.info("Resolved GigaChat access token via basic auth")
    return token


__all__ = [
    "DEFAULT_GIGACHAT_ARENA_AUTH_URL",
    "DEFAULT_GIGACHAT_ARENA_BASE_URL",
    "DEFAULT_GIGACHAT_USER_AGENT",
    "ResolvedGigachatArenaCredentials",
    "normalize_gigachat_base_url",
    "resolve_gigachat_access_token",
    "resolve_gigachat_access_token_sync",
    "resolve_gigachat_auth_url",
    "resolve_gigachat_credentials",
]
