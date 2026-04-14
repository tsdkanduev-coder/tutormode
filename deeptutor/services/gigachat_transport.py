"""GigaChat Arena transport helpers modeled on the working Giga Cowork shim."""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import os
from typing import Any, AsyncGenerator, Iterable, Mapping

import httpx

from deeptutor.logging import get_logger
from deeptutor.services.gigachat_auth import (
    DEFAULT_GIGACHAT_USER_AGENT,
    normalize_gigachat_base_url,
    resolve_gigachat_access_token,
)

logger = get_logger("GigaChatTransport")


@dataclass(slots=True)
class GigachatToolCall:
    id: str
    name: str
    arguments: dict[str, Any]
    tool_state_id: str | None = None


@dataclass(slots=True)
class GigachatResponse:
    content: str | None = None
    tool_calls: list[GigachatToolCall] = field(default_factory=list)
    finish_reason: str = "stop"
    usage: dict[str, int] = field(default_factory=dict)
    raw_payload: dict[str, Any] = field(default_factory=dict)


def _content_to_text_parts(content: Any) -> list[dict[str, Any]]:
    if isinstance(content, str):
        return [{"text": content}]
    if isinstance(content, list):
        parts: list[dict[str, Any]] = []
        for item in content:
            if isinstance(item, dict):
                if item.get("type") in {"text", "input_text", "output_text"} and item.get("text"):
                    parts.append({"text": str(item["text"])})
                    continue
                text = item.get("text")
                if isinstance(text, str) and text:
                    parts.append({"text": text})
                    continue
            elif item is not None:
                parts.append({"text": str(item)})
        return parts or [{"text": ""}]
    if content is None:
        return [{"text": ""}]
    return [{"text": str(content)}]


def _parse_json_if_string(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except Exception:
        return value


def _stringify_arguments(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value if value is not None else {}, ensure_ascii=False)


def _parse_tool_arguments(value: Any) -> dict[str, Any]:
    parsed = _parse_json_if_string(value)
    if isinstance(parsed, dict):
        return parsed
    if isinstance(parsed, list):
        return {"items": parsed}
    if parsed is None:
        return {}
    return {"raw": parsed}


def _tool_result_to_value(content: Any) -> Any:
    if isinstance(content, str):
        parsed = _parse_json_if_string(content)
        return {"content": parsed} if isinstance(parsed, str) else parsed
    if isinstance(content, list):
        text = "\n".join(
            part.get("text", "")
            for part in content
            if isinstance(part, dict) and isinstance(part.get("text"), str)
        ).strip()
        parsed = _parse_json_if_string(text)
        return {"content": parsed} if isinstance(parsed, str) else parsed
    return content if content is not None else {}


def _extract_openai_tool_state_id(tool_call: Mapping[str, Any]) -> str | None:
    direct = tool_call.get("provider_specific_fields")
    function = tool_call.get("function") if isinstance(tool_call.get("function"), Mapping) else {}
    function_specific = function.get("provider_specific_fields") if isinstance(function, Mapping) else None

    for source in (function_specific, direct):
        if not isinstance(source, Mapping):
            continue
        for key in ("tool_state_id", "functions_state_id"):
            value = source.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        nested = source.get("gigachat")
        if isinstance(nested, Mapping):
            for key in ("tool_state_id", "functions_state_id"):
                value = nested.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
    return None


def _convert_tool_choice(tool_choice: str | Mapping[str, Any] | None) -> tuple[str, str | None]:
    if tool_choice == "none":
        return "none", None
    if isinstance(tool_choice, Mapping):
        if tool_choice.get("type") == "function":
            function = tool_choice.get("function")
            if isinstance(function, Mapping):
                name = function.get("name")
                if isinstance(name, str) and name.strip():
                    return "auto", name.strip()
        if tool_choice.get("type") == "none":
            return "none", None
    return "auto", None


def _convert_tools(
    tools: list[dict[str, Any]] | None,
    pinned_tool_name: str | None,
) -> list[dict[str, Any]]:
    if not tools:
        return []
    specifications: list[dict[str, Any]] = []
    for tool in tools:
        if not isinstance(tool, Mapping):
            continue
        function = tool.get("function") if isinstance(tool.get("function"), Mapping) else {}
        name = function.get("name")
        if not isinstance(name, str) or not name.strip():
            continue
        if pinned_tool_name and name != pinned_tool_name:
            continue
        specifications.append(
            {
                "name": name,
                "description": str(function.get("description") or ""),
                "parameters": function.get("parameters") or {"type": "object", "properties": {}},
                "return_parameters": {"type": "object", "properties": {}},
            }
        )
    if not specifications:
        return []
    return [{"functions": {"specifications": specifications}}]


def _convert_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    tool_state_by_call_id: dict[str, tuple[str, str | None]] = {}

    for raw in messages:
        role = str(raw.get("role") or "").strip()
        content = raw.get("content")

        if role == "system":
            result.append({"role": "system", "content": _content_to_text_parts(content)})
            continue

        if role == "user":
            result.append({"role": "user", "content": _content_to_text_parts(content)})
            continue

        if role == "assistant":
            tool_calls = raw.get("tool_calls")
            if content:
                result.append({"role": "assistant", "content": _content_to_text_parts(content)})
            if isinstance(tool_calls, list):
                for tool_call in tool_calls:
                    if not isinstance(tool_call, Mapping):
                        continue
                    call_id = str(tool_call.get("id") or "")
                    function = tool_call.get("function") if isinstance(tool_call.get("function"), Mapping) else {}
                    name = function.get("name")
                    if not isinstance(name, str) or not name.strip():
                        continue
                    arguments = _parse_json_if_string(function.get("arguments") or {})
                    tool_state_id = _extract_openai_tool_state_id(tool_call)
                    if call_id:
                        tool_state_by_call_id[call_id] = (name, tool_state_id)
                    payload = {
                        "role": "assistant",
                        "content": [{"function_call": {"name": name, "arguments": arguments}}],
                    }
                    if tool_state_id:
                        payload["tool_state_id"] = tool_state_id
                    result.append(payload)
            continue

        if role == "tool":
            tool_call_id = str(raw.get("tool_call_id") or "")
            tool_name = str(raw.get("name") or "")
            mapped_name, tool_state_id = tool_state_by_call_id.get(tool_call_id, (tool_name, None))
            payload = {
                "role": "tool",
                "name": mapped_name or tool_name or "unknown",
                "content": [{"function_result": {"result": _tool_result_to_value(content)}}],
            }
            if tool_state_id:
                payload["functions_state_id"] = tool_state_id
            result.append(payload)
            continue

    return result


def _extract_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    return "".join(
        str(part.get("text") or "")
        for part in content
        if isinstance(part, Mapping)
    )


def _extract_function_call(message: Mapping[str, Any] | None) -> Mapping[str, Any] | None:
    if not message:
        return None
    direct = message.get("function_call")
    if isinstance(direct, Mapping) and direct.get("name"):
        return direct
    content = message.get("content")
    if isinstance(content, list):
        for part in content:
            if isinstance(part, Mapping):
                function_call = part.get("function_call")
                if isinstance(function_call, Mapping) and function_call.get("name"):
                    return function_call
    return None


def _extract_tool_state_id(message: Mapping[str, Any] | None) -> str | None:
    if not message:
        return None
    for key in ("tool_state_id", "functions_state_id"):
        value = message.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _map_finish_reason(value: str | None) -> str:
    if value in {"function_call", "tool_calls"}:
        return "tool_calls"
    if value == "length":
        return "length"
    return "stop"


def _make_tool_call_id(name: str, arguments: dict[str, Any], tool_state_id: str | None) -> str:
    raw = json.dumps(
        {
            "name": name,
            "arguments": arguments,
            "tool_state_id": tool_state_id,
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:9]


def parse_gigachat_response(payload: Mapping[str, Any]) -> GigachatResponse:
    message: Mapping[str, Any] | None = None
    finish_reason: str | None = None

    choices = payload.get("choices")
    if isinstance(choices, list) and choices:
        first = choices[0]
        if isinstance(first, Mapping):
            msg = first.get("message")
            if isinstance(msg, Mapping):
                message = msg
            finish_reason = first.get("finish_reason") if isinstance(first.get("finish_reason"), str) else None

    if message is None:
        messages = payload.get("messages")
        if isinstance(messages, list) and messages:
            first = messages[0]
            if isinstance(first, Mapping):
                message = first
        if isinstance(payload.get("finish_reason"), str):
            finish_reason = str(payload.get("finish_reason"))

    text = _extract_text(message.get("content") if isinstance(message, Mapping) else None) or None
    function_call = _extract_function_call(message if isinstance(message, Mapping) else None)
    tool_calls: list[GigachatToolCall] = []
    if function_call and isinstance(function_call.get("name"), str):
        tool_name = str(function_call.get("name"))
        tool_args = _parse_tool_arguments(function_call.get("arguments"))
        tool_state_id = _extract_tool_state_id(message if isinstance(message, Mapping) else None)
        tool_calls.append(
            GigachatToolCall(
                id=_make_tool_call_id(tool_name, tool_args, tool_state_id),
                name=tool_name,
                arguments=tool_args,
                tool_state_id=tool_state_id,
            )
        )

    usage = payload.get("usage") if isinstance(payload.get("usage"), Mapping) else {}
    usage_dict = {
        "prompt_tokens": int(usage.get("prompt_tokens") or 0),
        "completion_tokens": int(usage.get("completion_tokens") or 0),
        "total_tokens": int(usage.get("total_tokens") or 0),
    }
    return GigachatResponse(
        content=text,
        tool_calls=tool_calls,
        finish_reason=_map_finish_reason(finish_reason),
        usage=usage_dict,
        raw_payload=dict(payload),
    )


async def post_gigachat_request(
    *,
    messages: list[dict[str, Any]],
    model: str,
    api_key: str | None,
    base_url: str | None,
    max_tokens: int = 4096,
    temperature: float | None = 0.7,
    tools: list[dict[str, Any]] | None = None,
    tool_choice: str | Mapping[str, Any] | None = None,
    stream: bool = False,
    extra_headers: Mapping[str, str] | None = None,
) -> httpx.Response:
    normalized_base = normalize_gigachat_base_url(base_url)
    chat_url = f"{normalized_base}/chat/completions"
    default_headers = {"x-session-affinity": "gigachat"}
    if extra_headers:
        default_headers.update({str(k): str(v) for k, v in extra_headers.items()})
    access_token = await resolve_gigachat_access_token(
        base_url=normalized_base,
        api_key=api_key,
        default_headers=default_headers,
    )

    mode, pinned_tool_name = _convert_tool_choice(tool_choice)
    payload: dict[str, Any] = {
        "model": model,
        "messages": _convert_messages(messages),
        "tool_config": {"mode": mode},
        "stream": stream,
        "max_tokens": max(1, max_tokens),
    }
    if temperature is not None:
        payload["temperature"] = temperature

    converted_tools = _convert_tools(tools, pinned_tool_name)
    if converted_tools and mode != "none":
        payload["tools"] = converted_tools

    timezone = os.getenv("GIGACHAT_TIMEZONE") or os.getenv("TZ")
    if timezone:
        payload["user_info"] = {"timezone": timezone}

    disable_filter = os.getenv("GIGACHAT_DISABLE_FILTER")
    if disable_filter:
        normalized = disable_filter.strip().lower()
        payload["disable_filter"] = normalized not in {"", "0", "false", "no"}

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {access_token}",
        "User-Agent": os.getenv("GIGACHAT_USER_AGENT", DEFAULT_GIGACHAT_USER_AGENT),
    }
    headers.update(default_headers)

    async with httpx.AsyncClient(timeout=httpx.Timeout(60.0, read=120.0)) as client:
        response = await client.post(chat_url, json=payload, headers=headers)
        response.raise_for_status()
        return response


async def complete_gigachat(
    *,
    messages: list[dict[str, Any]],
    model: str,
    api_key: str | None,
    base_url: str | None,
    max_tokens: int = 4096,
    temperature: float | None = 0.7,
    tools: list[dict[str, Any]] | None = None,
    tool_choice: str | Mapping[str, Any] | None = None,
    extra_headers: Mapping[str, str] | None = None,
) -> GigachatResponse:
    response = await post_gigachat_request(
        messages=messages,
        model=model,
        api_key=api_key,
        base_url=base_url,
        max_tokens=max_tokens,
        temperature=temperature,
        tools=tools,
        tool_choice=tool_choice,
        stream=False,
        extra_headers=extra_headers,
    )
    payload = response.json()
    if not isinstance(payload, Mapping):
        raise ValueError("GigaChat response is not a JSON object")
    return parse_gigachat_response(payload)


async def stream_gigachat_text(
    *,
    messages: list[dict[str, Any]],
    model: str,
    api_key: str | None,
    base_url: str | None,
    max_tokens: int = 4096,
    temperature: float | None = 0.7,
    extra_headers: Mapping[str, str] | None = None,
) -> AsyncGenerator[str, None]:
    response = await post_gigachat_request(
        messages=messages,
        model=model,
        api_key=api_key,
        base_url=base_url,
        max_tokens=max_tokens,
        temperature=temperature,
        stream=True,
        extra_headers=extra_headers,
    )
    content_type = response.headers.get("content-type", "")
    if "text/event-stream" not in content_type.lower():
        payload = response.json()
        if isinstance(payload, Mapping):
            parsed = parse_gigachat_response(payload)
            if parsed.content:
                yield parsed.content
        return

    async for line in response.aiter_lines():
        trimmed = line.strip()
        if not trimmed or trimmed == "data: [DONE]" or not trimmed.startswith("data: "):
            continue
        try:
            chunk = json.loads(trimmed[6:])
        except Exception:
            continue
        if not isinstance(chunk, Mapping):
            continue
        choices = chunk.get("choices")
        if not isinstance(choices, list) or not choices:
            continue
        first = choices[0]
        if not isinstance(first, Mapping):
            continue
        delta = first.get("delta")
        if not isinstance(delta, Mapping):
            continue
        text = _extract_text(delta.get("content"))
        if text:
            yield text


__all__ = [
    "GigachatResponse",
    "GigachatToolCall",
    "complete_gigachat",
    "parse_gigachat_response",
    "post_gigachat_request",
    "stream_gigachat_text",
]
