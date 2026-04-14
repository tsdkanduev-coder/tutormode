"""Tests for the GigaChat Arena auth helpers."""

from __future__ import annotations

from deeptutor.services.gigachat_auth import (
    DEFAULT_GIGACHAT_ARENA_AUTH_URL,
    DEFAULT_GIGACHAT_ARENA_BASE_URL,
    normalize_gigachat_base_url,
    resolve_gigachat_auth_url,
    resolve_gigachat_credentials,
)


def test_normalize_gigachat_base_url() -> None:
    assert normalize_gigachat_base_url(None) == DEFAULT_GIGACHAT_ARENA_BASE_URL
    assert (
        normalize_gigachat_base_url("https://gigachat.sberdevices.ru")
        == DEFAULT_GIGACHAT_ARENA_BASE_URL
    )
    assert (
        normalize_gigachat_base_url("https://gigachat.sberdevices.ru/v2/chat/completions")
        == DEFAULT_GIGACHAT_ARENA_BASE_URL
    )


def test_resolve_gigachat_auth_url_prefers_env_override() -> None:
    env = {"GIGACHAT_AUTH_URL": "https://custom.example/token"}
    assert resolve_gigachat_auth_url("https://gigachat.sberdevices.ru/v2", env) == env["GIGACHAT_AUTH_URL"]


def test_resolve_gigachat_auth_url_defaults_from_base_origin() -> None:
    assert (
        resolve_gigachat_auth_url("https://gigachat.sberdevices.ru/v2", {})
        == DEFAULT_GIGACHAT_ARENA_AUTH_URL
    )


def test_resolve_gigachat_credentials_prefers_explicit_api_key() -> None:
    creds = resolve_gigachat_credentials(
        base_url="https://gigachat.sberdevices.ru/v2",
        api_key="profile-token",
        env={"GIGACHAT_ACCESS_TOKEN": "env-token"},
    )
    assert creds.access_token == "profile-token"
    assert creds.source == "profile_api_key"


def test_resolve_gigachat_credentials_uses_basic_auth_when_present() -> None:
    creds = resolve_gigachat_credentials(
        base_url="https://gigachat.sberdevices.ru/v2",
        api_key=None,
        env={
            "GIGACHAT_USERNAME": "arena-user",
            "GIGACHAT_PASSWORD": "arena-pass",
        },
    )
    assert creds.username == "arena-user"
    assert creds.password == "arena-pass"
    assert creds.source == "gigachat_basic"


def test_resolve_gigachat_credentials_falls_back_to_none() -> None:
    creds = resolve_gigachat_credentials(
        base_url=None,
        api_key=None,
        env={},
    )
    assert creds.source == "none"
    assert creds.auth_url == DEFAULT_GIGACHAT_ARENA_AUTH_URL
