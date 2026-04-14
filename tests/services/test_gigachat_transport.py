"""Tests for the GigaChat Arena transport conversion logic."""

from __future__ import annotations

import pytest

from deeptutor.services.gigachat_transport import parse_gigachat_response, post_gigachat_request


def test_parse_gigachat_response_maps_tool_call_and_state() -> None:
    payload = {
        "model": "GigaChat-3-Ultra",
        "messages": [
            {
                "role": "assistant",
                "tool_state_id": "state-123",
                "content": [
                    {
                        "function_call": {
                            "name": "Bash",
                            "arguments": {"command": "pwd"},
                        }
                    }
                ],
            }
        ],
        "finish_reason": "function_call",
        "usage": {
            "prompt_tokens": 8,
            "completion_tokens": 3,
            "total_tokens": 11,
        },
    }

    result = parse_gigachat_response(payload)

    assert result.finish_reason == "tool_calls"
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0].name == "Bash"
    assert result.tool_calls[0].arguments == {"command": "pwd"}
    assert result.tool_calls[0].tool_state_id == "state-123"


@pytest.mark.asyncio
async def test_post_gigachat_request_serializes_tool_results(monkeypatch) -> None:
    captured: dict[str, object] = {}

    async def _fake_token(**_kwargs):
        return "gigachat-token"

    class _FakeResponse:
        status_code = 200
        headers = {"Content-Type": "application/json"}

        def raise_for_status(self) -> None:
            return None

        def json(self):
            return {"messages": [{"role": "assistant", "content": [{"text": "done"}]}]}

    class _FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, json=None, headers=None):
            captured["url"] = url
            captured["json"] = json
            captured["headers"] = headers
            return _FakeResponse()

    monkeypatch.setattr(
        "deeptutor.services.gigachat_transport.resolve_gigachat_access_token",
        _fake_token,
    )
    monkeypatch.setattr("deeptutor.services.gigachat_transport.httpx.AsyncClient", _FakeClient)

    await post_gigachat_request(
        messages=[
            {"role": "system", "content": "system prompt"},
            {"role": "user", "content": "read the file"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {
                            "name": "Read",
                            "arguments": "{\"file_path\":\"/tmp/README.md\"}",
                            "provider_specific_fields": {
                                "gigachat": {"tool_state_id": "state-123"}
                            },
                        },
                    }
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "call_1",
                "name": "Read",
                "content": "README contents here",
            },
        ],
        tools=[
            {
                "type": "function",
                "function": {
                    "name": "Read",
                    "description": "Read a file",
                    "parameters": {
                        "type": "object",
                        "properties": {"file_path": {"type": "string"}},
                    },
                },
            }
        ],
        tool_choice="auto",
        model="GigaChat-3-Ultra",
        api_key="gigachat-token",
        base_url="https://gigachat.sberdevices.ru/v2",
        max_tokens=64,
    )

    assert captured["url"] == "https://gigachat.sberdevices.ru/v2/chat/completions"
    payload = captured["json"]
    assert payload["tool_config"] == {"mode": "auto"}
    assert payload["messages"] == [
        {"role": "system", "content": [{"text": "system prompt"}]},
        {"role": "user", "content": [{"text": "read the file"}]},
        {
            "role": "assistant",
            "content": [
                {
                    "function_call": {
                        "name": "Read",
                        "arguments": {"file_path": "/tmp/README.md"},
                    }
                }
            ],
            "tool_state_id": "state-123",
        },
        {
            "role": "tool",
            "name": "Read",
            "functions_state_id": "state-123",
            "content": [
                {
                    "function_result": {
                        "result": {"content": "README contents here"},
                    }
                }
            ],
        },
    ]
