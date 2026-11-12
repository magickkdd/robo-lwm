"""Command-line interface for the language world model.

Usage (inside a task workspace):
    python -m lwm.cli --episode episode.py
"""

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path

from lwm.agent import LWMAgent


def _format(review: dict) -> str:
    if not review.get("available"):
        error = review.get("error") or "unavailable"
        return f'<lwm_review available="false">{error}</lwm_review>'
    return (
        f'<lwm_review available="true" outcome="{review["outcome"]}" '
        f'confidence="{review["confidence"]:.2f}">\n'
        f"failure_step: {review['failure_step']}\n"
        f"reason: {review['reason']}\n"
        f"suggestion: {review['suggestion']}\n"
        f"</lwm_review>"
    )


def _log(review: dict, *, task: str, episode_py: str) -> None:
    root = os.environ.get("ROBOLWM_ARTIFACTS")
    if not root:
        return
    path = Path(root) / "lwm" / "reviews.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "ts": time.time(),
        "task": task,
        "episode_sha256": hashlib.sha256(episode_py.encode("utf-8")).hexdigest(),
        **review,
    }
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--episode", default="episode.py")
    parser.add_argument("--obs", default=None, help="defaults to ROBOLWM_INIT_OBS or obs.json")
    parser.add_argument("--task", default=None)
    args = parser.parse_args(argv)

    if os.environ.get("ROBOLWM_LWM", "off").lower() not in {"on", "1", "true", "yes"}:
        print('<lwm_review available="false">world model disabled for this run</lwm_review>')
        return 0

    episode_path = Path(args.episode)
    if not episode_path.is_file():
        print(f'<lwm_review available="false">episode file not found: {args.episode}</lwm_review>')
        return 0
    try:
        episode_py = episode_path.read_text(encoding="utf-8")
    except OSError as e:
        print(f'<lwm_review available="false">could not read episode: {e}</lwm_review>')
        return 0

    candidates = [args.obs, os.environ.get("ROBOLWM_INIT_OBS"), "obs.json"]
    obs_path = next((Path(p) for p in candidates if p and Path(p).is_file()), None)
    obs = {}
    if obs_path is not None:
        try:
            obs = json.loads(obs_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            print(f'<lwm_review available="false">could not read observation: {e}</lwm_review>')
            return 0

    task = args.task or obs.get("task") or os.environ.get("ROBOLWM_TASK", "")
    review = LWMAgent().review(task=task, obs=obs, episode_py=episode_py)
    print(_format(review), flush=True)
    try:
        _log(review, task=task, episode_py=episode_py)
    except OSError:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
