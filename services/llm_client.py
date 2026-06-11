import os
import requests
import logging
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("IssueForge.LlmClient")


class LlmClient:
    """
    Lightweight, zero-dependency LLM client supporting Gemini, OpenAI, and Anthropic.
    """

    @staticmethod
    def generate(prompt: str) -> str:
        # 1. Try Gemini API
        gemini_key = os.getenv("GEMINI_API_KEY")
        if gemini_key:
            models = ["gemini-2.5-flash", "gemini-2.5-flash-lite"]
            for model in models:
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={gemini_key}"
                headers = {"Content-Type": "application/json"}
                payload = {
                    "contents": [
                        {
                            "parts": [
                                {"text": prompt}
                            ]
                        }
                    ],
                    "generationConfig": {
                        "temperature": 0.2,
                    }
                }
                try:
                    response = requests.post(url, json=payload, headers=headers, timeout=120)
                    if response.status_code == 200:
                        data = response.json()
                        # Parse response content
                        return data["candidates"][0]["content"]["parts"][0]["text"].strip()
                    else:
                        logger.error(f"Gemini API returned status code {response.status_code} for model {model}: {response.text}")
                except Exception as e:
                    logger.error(f"Error calling Gemini API for model {model}: {e}")

        # 2. Try OpenAI API
        openai_key = os.getenv("OPENAI_API_KEY")
        if openai_key:
            url = "https://api.openai.com/v1/chat/completions"
            headers = {
                "Authorization": f"Bearer {openai_key}",
                "Content-Type": "application/json"
            }
            payload = {
                "model": "gpt-4o-mini",
                "messages": [
                    {"role": "user", "content": prompt}
                ],
                "temperature": 0.2
            }
            try:
                response = requests.post(url, json=payload, headers=headers, timeout=60)
                if response.status_code == 200:
                    data = response.json()
                    return data["choices"][0]["message"]["content"].strip()
                else:
                    logger.error(f"OpenAI API returned status code {response.status_code}: {response.text}")
            except Exception as e:
                logger.error(f"Error calling OpenAI API: {e}")

        # 3. Try Anthropic API
        anthropic_key = os.getenv("ANTHROPIC_API_KEY")
        if anthropic_key:
            url = "https://api.anthropic.com/v1/messages"
            headers = {
                "x-api-key": anthropic_key,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json"
            }
            payload = {
                "model": "claude-3-5-sonnet-20241022",
                "max_tokens": 4000,
                "messages": [
                    {"role": "user", "content": prompt}
                ]
            }
            try:
                response = requests.post(url, json=payload, headers=headers, timeout=60)
                if response.status_code == 200:
                    data = response.json()
                    return data["content"][0]["text"].strip()
                else:
                    logger.error(f"Anthropic API returned status code {response.status_code}: {response.text}")
            except Exception as e:
                logger.error(f"Error calling Anthropic API: {e}")

        # Fallback if no keys or all APIs failed
        logger.warning("No LLM API keys configured or all API requests failed.")
        return ""
