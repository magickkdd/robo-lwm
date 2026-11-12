"""OpenAI-compatible chat completions model.

Works with any endpoint that implements the OpenAI ``/v1/chat/completions`` API
(OpenAI, vLLM, SGLang, Ollama's OpenAI endpoint, ...).
"""

import logging
import os
import time
from typing import Any, Callable

from openai import AuthenticationError, BadRequestError, NotFoundError, OpenAI, PermissionDeniedError
from pydantic import BaseModel

from minisweagent.exceptions import FormatError
from minisweagent.models import GLOBAL_MODEL_STATS
from minisweagent.models.utils.actions_toolcall import (
    BASH_TOOL,
    format_toolcall_observation_messages,
    parse_toolcall_actions,
)
from minisweagent.models.utils.openai_multimodal import expand_multimodal_content
from minisweagent.models.utils.retry import retry

logger = logging.getLogger("openai_model")


class OpenAIModelConfig(BaseModel):
    model_name: str
    """Model identifier understood by the endpoint, e.g. `gpt-4o` or `Qwen/Qwen2.5-7B-Instruct`."""
    base_url: str | None = None
    """API base URL. Falls back to `OPENAI_BASE_URL`."""
    api_key: str | None = None
    """API key. Falls back to `OPENAI_API_KEY`, then a dummy value for local servers."""
    model_kwargs: dict[str, Any] = {}
    """Extra arguments forwarded to `chat.completions.create`."""
    observation_template: str = (
        "{% if output.exception_info %}<exception>{{output.exception_info}}</exception>\n{% endif %}"
        "<returncode>{{output.returncode}}</returncode>\n<output>\n{{output.output}}</output>"
    )
    """Template used to render the observation after executing an action."""
    format_error_template: str = "{{ error }}"
    """Template used when the model's output is not in the expected format."""
    multimodal_regex: str = ""
    """Regex to extract multimodal content. Empty string disables multimodal processing."""
    price_input: float = 0.0
    """USD per 1M prompt tokens, for cost tracking. 0 disables cost accumulation."""
    price_output: float = 0.0
    """USD per 1M completion tokens, for cost tracking. 0 disables cost accumulation."""
    request_timeout: float = 180.0
    """Per-request timeout in seconds. Retries are handled by the agent's retry helper."""


class OpenAIModel:
    abort_exceptions: list[type[Exception]] = [
        AuthenticationError,
        NotFoundError,
        PermissionDeniedError,
        BadRequestError,
        KeyboardInterrupt,
    ]

    def __init__(self, *, config_class: Callable = OpenAIModelConfig, **kwargs):
        self.config = config_class(**kwargs)
        self.client = OpenAI(
            api_key=self.config.api_key or os.getenv("OPENAI_API_KEY") or "EMPTY",
            base_url=self.config.base_url or os.getenv("OPENAI_BASE_URL") or None,
            timeout=self.config.request_timeout,
            max_retries=0,
        )

    def _query(self, messages: list[dict], **kwargs):
        return self.client.chat.completions.create(
            model=self.config.model_name,
            messages=messages,
            tools=[BASH_TOOL],
            **(self.config.model_kwargs | kwargs),
        )

    def _prepare_messages_for_api(self, messages: list[dict]) -> list[dict]:
        return [{k: v for k, v in msg.items() if k != "extra"} for msg in messages]

    def query(self, messages: list[dict], **kwargs) -> dict:
        for attempt in retry(logger=logger, abort_exceptions=self.abort_exceptions):
            with attempt:
                response = self._query(self._prepare_messages_for_api(messages), **kwargs)
        cost_output = self._calculate_cost(response)
        GLOBAL_MODEL_STATS.add(cost_output["cost"])
        try:
            actions = self._parse_actions(response)
        except FormatError as e:
            # The call was billed even though parsing failed, so persist cost/response.
            e.messages[0]["extra"].update(cost_output)
            try:
                e.messages[0]["extra"]["response"] = response.model_dump(mode="json")
            except Exception:
                e.messages[0]["extra"]["response"] = repr(response)
            raise
        message = response.choices[0].message.model_dump()
        message["extra"] = {
            "actions": actions,
            "response": response.model_dump(mode="json"),
            **cost_output,
            "timestamp": time.time(),
        }
        return message

    def _calculate_cost(self, response) -> dict[str, float]:
        usage = getattr(response, "usage", None)
        prompt_tokens = getattr(usage, "prompt_tokens", 0) or 0
        completion_tokens = getattr(usage, "completion_tokens", 0) or 0
        cost = (
            prompt_tokens * self.config.price_input + completion_tokens * self.config.price_output
        ) / 1_000_000
        return {"cost": cost, "prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens}

    def _parse_actions(self, response) -> list[dict]:
        """Parse tool calls from the response. Raises FormatError if malformed."""
        tool_calls = response.choices[0].message.tool_calls or []
        return parse_toolcall_actions(
            tool_calls,
            format_error_template=self.config.format_error_template,
            template_kwargs={"finish_reason": response.choices[0].finish_reason},
        )

    def format_message(self, **kwargs) -> dict:
        return expand_multimodal_content(kwargs, pattern=self.config.multimodal_regex)

    def format_observation_messages(
        self, message: dict, outputs: list[dict], template_vars: dict | None = None
    ) -> list[dict]:
        """Format execution outputs into tool result messages."""
        actions = message.get("extra", {}).get("actions", [])
        return format_toolcall_observation_messages(
            actions=actions,
            outputs=outputs,
            observation_template=self.config.observation_template,
            template_vars=template_vars,
            multimodal_regex=self.config.multimodal_regex,
        )

    def get_template_vars(self, **kwargs) -> dict[str, Any]:
        return self.config.model_dump()

    def serialize(self) -> dict:
        return {
            "info": {
                "config": {
                    "model": self.config.model_dump(mode="json"),
                    "model_type": f"{self.__class__.__module__}.{self.__class__.__name__}",
                },
            }
        }
