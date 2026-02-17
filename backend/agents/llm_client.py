"""LLM Client — HTTP wrapper for Ollama API.

Provides a simple async interface for text generation and JSON extraction.
"""

from __future__ import annotations

import json
import re
from typing import Optional

import httpx
import structlog

from backend.config import Settings

logger = structlog.get_logger()


class LLMClient:
    """Async HTTP client for Ollama API.

    Handles text generation with timeout and error handling.
    """

    def __init__(self, settings: Settings) -> None:
        """Initialize the LLM client.

        Args:
            settings: Application settings containing Ollama URL and model config.
        """
        self.settings = settings
        self.base_url = settings.ollama_url
        self.timeout = settings.llm_timeout_sec

    async def generate(
        self,
        prompt: str,
        model: Optional[str] = None,
        system: Optional[str] = None,
    ) -> Optional[str]:
        """Generate text completion from Ollama.

        Args:
            prompt: The user prompt to send to the model.
            model: Optional model name override (defaults to settings.ollama_model).
            system: Optional system prompt for context.

        Returns:
            Generated text response or None if request failed.
        """
        if model is None:
            model = self.settings.ollama_model

        endpoint = f"{self.base_url}/api/generate"

        payload = {
            "model": model,
            "prompt": prompt,
            "stream": False,
        }

        if system:
            payload["system"] = system

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                logger.info(
                    "llm_request_started",
                    model=model,
                    prompt_length=len(prompt),
                )

                response = await client.post(endpoint, json=payload)
                response.raise_for_status()

                data = response.json()
                generated_text = data.get("response", "")

                logger.info(
                    "llm_request_completed",
                    model=model,
                    response_length=len(generated_text),
                )

                return generated_text

        except httpx.TimeoutException:
            logger.error(
                "llm_timeout",
                model=model,
                timeout_sec=self.timeout,
            )
            return None

        except httpx.ConnectError:
            logger.error(
                "llm_connection_error",
                url=self.base_url,
                message="Ollama service unavailable",
            )
            return None

        except Exception as exc:
            logger.error(
                "llm_unexpected_error",
                error=str(exc),
                error_type=type(exc).__name__,
            )
            return None

    async def generate_json(
        self,
        prompt: str,
        schema: Optional[dict] = None,
        model: Optional[str] = None,
    ) -> Optional[dict]:
        """Generate JSON response from Ollama.

        Args:
            prompt: The user prompt requesting JSON output.
            schema: Optional JSON schema for validation (not enforced by Ollama).
            model: Optional model name override.

        Returns:
            Parsed JSON dict or None if generation/parsing failed.

        Note:
            This method attempts to extract JSON from the model's response.
            If the model doesn't support JSON mode, it will try to parse
            JSON from the text response using extract_json().
        """
        # Add JSON instructions to the prompt
        json_prompt = f"{prompt}\n\nRespond with valid JSON only. No markdown, no extra text."

        if schema:
            json_prompt += f"\n\nJSON Schema: {json.dumps(schema)}"

        response = await self.generate(json_prompt, model=model)

        if response is None:
            return None

        # Try to extract JSON from the response
        extracted = extract_json(response)

        if extracted is None:
            logger.warning(
                "llm_json_parse_failed",
                response_preview=response[:200],
            )

        return extracted


def extract_json(text: str) -> Optional[dict]:
    """Extract JSON object from text that may contain markdown or prose.

    Args:
        text: Text potentially containing JSON.

    Returns:
        Parsed JSON dict or None if no valid JSON found.

    Examples:
        >>> extract_json('Some text {"key": "value"} more text')
        {'key': 'value'}
        >>> extract_json('```json\\n{"key": "value"}\\n```')
        {'key': 'value'}
    """
    # Try to find JSON in markdown code blocks first
    markdown_pattern = r"```(?:json)?\s*\n?(.*?)\n?```"
    markdown_match = re.search(markdown_pattern, text, re.DOTALL)

    if markdown_match:
        json_text = markdown_match.group(1).strip()
        try:
            return json.loads(json_text)
        except json.JSONDecodeError:
            pass

    # Try to find raw JSON object in the text
    json_pattern = r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}"
    json_match = re.search(json_pattern, text, re.DOTALL)

    if json_match:
        json_text = json_match.group(0)
        try:
            return json.loads(json_text)
        except json.JSONDecodeError:
            pass

    # Try parsing the entire text as JSON
    try:
        return json.loads(text.strip())
    except json.JSONDecodeError:
        pass

    return None


def extract_code_block(text: str, language: str = "python") -> Optional[str]:
    """Extract code from markdown code blocks.

    Args:
        text: Text potentially containing code blocks.
        language: Language identifier for the code block (default: python).

    Returns:
        Extracted code or None if no code block found.

    Examples:
        >>> extract_code_block('```python\\nprint("hello")\\n```')
        'print("hello")'
    """
    # Try language-specific code block first
    pattern = rf"```{language}\s*\n(.*?)\n```"
    match = re.search(pattern, text, re.DOTALL)

    if match:
        return match.group(1).strip()

    # Try generic code block
    pattern = r"```\s*\n(.*?)\n```"
    match = re.search(pattern, text, re.DOTALL)

    if match:
        return match.group(1).strip()

    return None
