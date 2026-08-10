"""
Provider-neutral LLM client for chat completion calls.
Supports Groq and MiniMax behind one small interface so agents do not need
provider-specific API code.
"""

import logging
import os
from typing import Dict, List

import anthropic
from groq import Groq

logger = logging.getLogger(__name__)

_groq_client = None
_minimax_client = None
_minimax_client_config = None

DEFAULT_GROQ_MODEL = "llama-3.3-70b-versatile"
DEFAULT_MINIMAX_MODEL = "MiniMax-M3"
DEFAULT_MINIMAX_ANTHROPIC_BASE_URL = "https://api.minimaxi.com/anthropic"


def get_provider() -> str:
    """Return selected LLM provider. Defaults to Groq for backward compatibility."""
    return os.environ.get("LLM_PROVIDER", "groq").strip().lower() or "groq"


def provider_label() -> str:
    provider = get_provider()
    if provider == "minimax":
        return f"MiniMax · {get_model_name()}"
    return f"Groq · {get_model_name()}"


def get_model_name() -> str:
    provider = get_provider()
    if provider == "minimax":
        return os.environ.get("MINIMAX_MODEL", DEFAULT_MINIMAX_MODEL)
    return os.environ.get("GROQ_MODEL", DEFAULT_GROQ_MODEL)


def has_required_api_key() -> bool:
    provider = get_provider()
    if provider == "minimax":
        return bool(os.environ.get("MINIMAX_API_KEY"))
    return bool(os.environ.get("GROQ_API_KEY"))


def required_key_name() -> str:
    provider = get_provider()
    if provider == "minimax":
        return "MINIMAX_API_KEY"
    return "GROQ_API_KEY"


def chat_completion(messages: List[Dict[str, str]], max_tokens: int) -> str:
    """
    Run a non-streaming chat completion and return the assistant text content.
    """
    provider = get_provider()
    if provider == "minimax":
        return _minimax_chat_completion(messages, max_tokens)
    if provider == "groq":
        return _groq_chat_completion(messages, max_tokens)
    raise ValueError(f"Unsupported LLM_PROVIDER: {provider}")


def _groq_chat_completion(messages: List[Dict[str, str]], max_tokens: int) -> str:
    global _groq_client
    if not os.environ.get("GROQ_API_KEY"):
        raise ValueError("GROQ_API_KEY is required for Groq provider.")
    if _groq_client is None:
        _groq_client = Groq(api_key=os.environ["GROQ_API_KEY"])

    response = _groq_client.chat.completions.create(
        model=get_model_name(),
        max_tokens=max_tokens,
        messages=messages,
    )
    return response.choices[0].message.content.strip()


def _minimax_chat_completion(messages: List[Dict[str, str]], max_tokens: int) -> str:
    global _minimax_client, _minimax_client_config
    api_key = os.environ.get("MINIMAX_API_KEY")
    if not api_key:
        raise ValueError("MINIMAX_API_KEY is required for MiniMax provider.")

    base_url = os.environ.get(
        "ANTHROPIC_BASE_URL",
        os.environ.get("MINIMAX_ANTHROPIC_BASE_URL", DEFAULT_MINIMAX_ANTHROPIC_BASE_URL),
    )
    client_config = (api_key, base_url)
    if _minimax_client is None or _minimax_client_config != client_config:
        _minimax_client = anthropic.Anthropic(api_key=api_key, base_url=base_url)
        _minimax_client_config = client_config

    system_prompt, anthropic_messages = _to_anthropic_messages(messages)
    request = {
        "model": get_model_name(),
        "max_tokens": max_tokens,
        "messages": anthropic_messages,
    }
    if system_prompt:
        request["system"] = system_prompt

    try:
        response = _minimax_client.messages.create(**request)
    except Exception as e:
        logger.error("MiniMax Anthropic SDK request failed: %s", e)
        raise ValueError(f"MiniMax Anthropic SDK request failed: {e}") from e

    text_blocks = []
    for block in response.content:
        if getattr(block, "type", None) == "text":
            text_blocks.append(block.text)
    if text_blocks:
        return "\n".join(text_blocks).strip()

    raise ValueError(f"MiniMax response did not contain text content: {response}")


def _to_anthropic_messages(messages: List[Dict[str, str]]) -> tuple[str, List[Dict[str, object]]]:
    """
    Convert OpenAI/Groq-style messages into Anthropic Messages format.
    System messages are passed via the top-level system argument.
    """
    system_parts = []
    converted = []
    for message in messages:
        role = message.get("role", "user")
        content = message.get("content", "")
        if role == "system":
            if content:
                system_parts.append(str(content))
            continue
        if role not in {"user", "assistant"}:
            role = "user"
        converted.append(
            {
                "role": role,
                "content": [
                    {
                        "type": "text",
                        "text": str(content),
                    }
                ],
            }
        )
    return "\n\n".join(system_parts), converted
