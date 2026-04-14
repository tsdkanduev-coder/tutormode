# GigaChat Branch Notes

This branch intentionally follows the working `Giga Cowork` integration instead
of the generic public OpenAI-compatible path.

## Source of truth

The implementation choices here are derived from:

- `/Users/tsevdnkanduev/Documents/Giga Cowork/openclaude/src/services/api/providerConfig.ts`
- `/Users/tsevdnkanduev/Documents/Giga Cowork/openclaude/src/services/api/gigachatShim.ts`
- `/Users/tsevdnkanduev/Documents/Giga Cowork/openclaude/src/services/api/openaiShim.test.ts`

## What we copy first

Phase 1 in DeepTutor mirrors the parts already proven in Giga Cowork:

- Arena base URL: `https://gigachat.sberdevices.ru/v2`
- Token exchange URL: `https://gigachat.sberdevices.ru/v1/token`
- Credential precedence:
  - explicit profile/API key as bearer token
  - `GIGACHAT_ACCESS_TOKEN`
  - `GIGACHAT_USERNAME` + `GIGACHAT_PASSWORD`
  - fallback `OPENAI_API_KEY`
- token cache with `exp` handling
- default `User-Agent: GigaArena`

## What is not fully ported yet

Giga Cowork does more than auth. It also adapts tool calling:

- request tools are nested under `tools[].functions.specifications[]`
- `tool_config.mode` is used instead of plain OpenAI `tool_choice`
- tool state is carried with `tool_state_id` / `functions_state_id`
- responses are converted back into the caller's internal format

That transport/message shim is the next slice to port if we want full
TutorBot tool support on GigaChat. The current branch only lays down the
auth + provider wiring foundation for chat paths that can already speak
OpenAI-style requests.

## Practical implication

For now, keep embeddings/RAG on OpenAI in this branch. Giga Cowork proves the
Arena chat/tool loop, but it does not provide the same ready-made reference for
DeepTutor's embedding path.
