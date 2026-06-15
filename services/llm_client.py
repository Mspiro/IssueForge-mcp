import os
import requests
import logging
from dotenv import load_dotenv
from config import (
    LLM_PRIMARY_MODEL_ANTHROPIC,
    LLM_PRIMARY_MODEL_GEMINI,
    LLM_FALLBACK_MODEL_GEMINI,
    LLM_PRIMARY_MODEL_OPENAI,
    LLM_MAX_TOKENS,
    LLM_TEMPERATURE,
    LLM_TIMEOUT_ANTHROPIC,
    LLM_TIMEOUT_GEMINI,
    LLM_TIMEOUT_OPENAI,
)

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

logger = logging.getLogger("IssueForge.LlmClient")


class LlmClient:
    """
    LLM client supporting Anthropic, Gemini, and OpenAI.

    Claude is the primary provider — it produces the most reliable
    Drupal PHP code. Gemini and OpenAI are fallbacks.

    Supports system/user message separation for better generation
    quality and prompt caching on Claude.
    """

    @staticmethod
    def generate(prompt: str, system: str = None) -> str:
        """
        Generate text from a prompt.

        Args:
            prompt: The user-facing prompt (issue-specific context).
            system: Optional system prompt (reusable constraints/role).
                    Sent as a separate system message to Claude, which
                    enables Anthropic prompt caching and cleaner role
                    separation. Falls back to prepending to the prompt
                    for non-Claude providers.
        """
        # 1. Try Anthropic Claude (primary — best Drupal code generation)
        anthropic_key = os.getenv("ANTHROPIC_API_KEY")
        if anthropic_key:
            result = LlmClient._call_anthropic(anthropic_key, prompt, system)
            if result:
                return result

        # 2. Try Gemini (secondary)
        gemini_key = os.getenv("GEMINI_API_KEY")
        if gemini_key:
            result = LlmClient._call_gemini(gemini_key, prompt, system)
            if result:
                return result

        # 3. Try OpenAI (tertiary)
        openai_key = os.getenv("OPENAI_API_KEY")
        if openai_key:
            result = LlmClient._call_openai(openai_key, prompt, system)
            if result:
                return result

        logger.warning("No LLM API keys configured or all requests failed.")
        return ""

    @staticmethod
    def _call_anthropic(api_key: str, prompt: str, system: str = None) -> str:
        url = "https://api.anthropic.com/v1/messages"
        headers = {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }
        payload = {
            "model": LLM_PRIMARY_MODEL_ANTHROPIC,
            "max_tokens": LLM_MAX_TOKENS,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system:
            # Cache the system prompt — it's static across all issue calls.
            payload["system"] = [
                {
                    "type": "text",
                    "text": system,
                    "cache_control": {"type": "ephemeral"},
                }
            ]
        try:
            response = requests.post(url, json=payload, headers=headers, timeout=LLM_TIMEOUT_ANTHROPIC)
            if response.status_code == 200:
                data = response.json()
                return data["content"][0]["text"].strip()
            logger.error(
                f"Anthropic API returned {response.status_code}: {response.text}"
            )
        except Exception as e:
            logger.error(f"Error calling Anthropic API: {e}")
        return ""

    @staticmethod
    def _call_gemini(api_key: str, prompt: str, system: str = None) -> str:
        # Gemini does not natively support system prompts in this payload
        # format, so prepend system to the user message.
        full_prompt = f"{system}\n\n{prompt}" if system else prompt
        models = [LLM_PRIMARY_MODEL_GEMINI, LLM_FALLBACK_MODEL_GEMINI]
        for model in models:
            url = (
                f"https://generativelanguage.googleapis.com/v1beta/models/"
                f"{model}:generateContent?key={api_key}"
            )
            payload = {
                "contents": [{"parts": [{"text": full_prompt}]}],
                "generationConfig": {"temperature": LLM_TEMPERATURE},
            }
            try:
                response = requests.post(
                    url,
                    json=payload,
                    headers={"Content-Type": "application/json"},
                    timeout=LLM_TIMEOUT_GEMINI,
                )
                if response.status_code == 200:
                    data = response.json()
                    return data["candidates"][0]["content"]["parts"][0]["text"].strip()
                logger.error(
                    f"Gemini {model} returned {response.status_code}: {response.text}"
                )
            except Exception as e:
                logger.error(f"Error calling Gemini {model}: {e}")
        return ""

    @staticmethod
    def _call_openai(api_key: str, prompt: str, system: str = None) -> str:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        payload = {
            "model": LLM_PRIMARY_MODEL_OPENAI,
            "messages": messages,
            "temperature": LLM_TEMPERATURE,
        }
        try:
            response = requests.post(
                "https://api.openai.com/v1/chat/completions",
                json=payload,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                timeout=LLM_TIMEOUT_OPENAI,
            )
            if response.status_code == 200:
                return response.json()["choices"][0]["message"]["content"].strip()
            logger.error(
                f"OpenAI API returned {response.status_code}: {response.text}"
            )
        except Exception as e:
            logger.error(f"Error calling OpenAI API: {e}")
        return ""
