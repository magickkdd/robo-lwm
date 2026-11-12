"""Minimal language world model.

The model receives exactly what the robot agent sees: the task language, the
initial observation, and the episode script the agent wrote. It predicts what
will happen if the script is executed. It never talks to the simulator.

Only the public ``review`` method is part of the contract. Everything else
(transport, parsing, normalization) is an implementation detail.
"""

import json
import os
import re
import time
import urllib.error
import urllib.request

SYSTEM_PROMPT = """You are a language world model for a Franka Panda arm in the LIBERO simulator.

You receive:
- the task instruction,
- the initial observation as JSON,
- a Python plan (episode.py) written by another agent.

Predict what will happen if the plan is executed. You cannot run the simulator
and you must use only the information provided.

Observation fields:
- eef_pos: current end-effector position.
- eef_quat: current orientation (x, y, z, w).
- gripper_qpos: finger joint positions; larger values mean a wider opening.
- objects: object name -> {pos, quat}.
- success: native success flag at the initial state (usually false).

Plan conventions:
- Each action is [x, y, z, ax, ay, az, gripper]: an absolute end-effector pose.
- gripper = +1 closes, -1 opens. All-zero orientation keeps the current orientation.
- The controller moves at most 5 cm and 0.5 rad per simulation step.
- Repeating the same action for many steps approaches the target.
- The fingertip pads are about 1 cm below the eef_pos frame.
- A grasp usually works when the fingers straddle the object at mid-height.

Rules:
- Do not rewrite the plan. Only predict and diagnose.
- If the plan is ambiguous or you are unsure, use outcome "uncertain" and a low confidence.
- Return exactly one JSON object, with no markdown:
{"outcome": "success" | "failure" | "uncertain",
 "failure_step": <int or null>,
 "reason": "<why>",
 "suggestion": "<smallest fix, or empty if success>",
 "confidence": <0.0 to 1.0>}
"""


class LWMAgent:
    """Predicts the outcome of a robot plan from the same information the agent has."""

    def __init__(self, model=None, base_url=None, api_key=None, timeout=None):
        self.model = model or os.environ.get("LWM_MODEL") or os.environ.get("MODEL_NAME") or ""
        self.base_url = (
            base_url
            or os.environ.get("LWM_BASE_URL")
            or os.environ.get("OPENAI_BASE_URL")
            or ""
        ).rstrip("/")
        self.api_key = (
            api_key
            or os.environ.get("LWM_API_KEY")
            or os.environ.get("OPENAI_API_KEY")
            or "EMPTY"
        )
        self.timeout = float(timeout or os.environ.get("LWM_TIMEOUT", "60"))
        self.reasoning_effort = os.environ.get("LWM_REASONING_EFFORT", "none")

    def review(self, *, task: str, obs: dict, episode_py: str) -> dict:
        """Predict the outcome of ``episode_py``. Always returns a dict, never raises."""
        started = time.time()
        if not self.model or not self.base_url:
            return self._unavailable(
                "LWM model or base URL is not configured "
                "(set LWM_MODEL/OPENAI_BASE_URL or MODEL_NAME/OPENAI_BASE_URL)",
                started,
            )

        user = (
            f"TASK:\n{task}\n\n"
            f"INITIAL OBSERVATION:\n{json.dumps(obs, indent=2)}\n\n"
            f"EPISODE.PY:\n{episode_py}"
        )
        try:
            raw = self._chat(user)
            review = _normalize(_extract_json(raw))
            review.update(
                {
                    "available": True,
                    "model": self.model,
                    "duration_s": round(time.time() - started, 2),
                    "error": None,
                    "raw": raw,
                }
            )
            return review
        except Exception as e:  # fail-open: the agent must keep working
            return self._unavailable(f"{type(e).__name__}: {e}", started)

    def _chat(self, user: str) -> str:
        url = self.base_url
        if not url.endswith("/chat/completions"):
            url += "/chat/completions"
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user},
            ],
        }
        if self.reasoning_effort:
            payload["reasoning_effort"] = self.reasoning_effort
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
                # the endpoint rejects the default urllib user agent
                "User-Agent": "OpenAI/Python 1.0",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")[:500]
            raise RuntimeError(f"HTTP {e.code}: {body}") from e

        choices = data.get("choices") or []
        if not choices:
            raise RuntimeError(f"no choices in response: {str(data)[:300]}")
        message = choices[0].get("message") or {}
        content = message.get("content")
        if isinstance(content, list):
            content = "".join(
                part.get("text", "") for part in content if isinstance(part, dict)
            )
        if not isinstance(content, str) or not content.strip():
            reason = choices[0].get("finish_reason")
            raise RuntimeError(f"empty model output (finish_reason={reason})")
        return content

    def _unavailable(self, error: str, started: float) -> dict:
        return {
            "available": False,
            "outcome": "uncertain",
            "failure_step": None,
            "reason": "",
            "suggestion": "",
            "confidence": 0.0,
            "model": self.model,
            "duration_s": round(time.time() - started, 2),
            "error": error,
            "raw": "",
        }


def _extract_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            raise
        data = json.loads(text[start : end + 1])
    if not isinstance(data, dict):
        raise ValueError(f"expected a JSON object, got {type(data).__name__}")
    return data


def _normalize(data: dict) -> dict:
    outcome = str(data.get("outcome", "uncertain")).strip().lower()
    if outcome not in {"success", "failure", "uncertain"}:
        outcome = "uncertain"

    step = data.get("failure_step")
    if isinstance(step, bool):
        step = None
    elif isinstance(step, float):
        step = int(step) if step.is_integer() else None
    elif isinstance(step, str):
        step = int(step) if step.strip().lstrip("-").isdigit() else None
    elif not isinstance(step, int):
        step = None
    if outcome != "failure":
        step = None

    try:
        confidence = float(data.get("confidence", 0.0))
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))

    return {
        "outcome": outcome,
        "failure_step": step,
        "reason": str(data.get("reason") or ""),
        "suggestion": str(data.get("suggestion") or ""),
        "confidence": round(confidence, 3),
    }
