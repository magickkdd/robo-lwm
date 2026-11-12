"""Environment that runs the agent's commands inside a per-task workspace."""

import json
import os
import re
import signal
import subprocess
import time
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from minisweagent.exceptions import LimitsExceeded, Submitted


class RobotEnvironmentConfig(BaseModel):
    workspace: str
    artifacts: str
    suite: str
    task_id: int
    sim_path: str
    task_language: str = ""
    lwm_enabled: bool = False
    python: str = "/home/czx/miniconda3/envs/libero/bin/python"
    libero_config_path: str = "/home/czx/.libero-roboclwm"
    try_cap: int = 10
    camera_size: int = 256
    timeout: int = 900


_DESTRUCTIVE = re.compile(r"\b(rm|rmdir|mv|cp|dd|truncate|chmod|chown|tee|ln)\b")


class RobotEnvironment:
    """Shell environment scoped to a workspace, with artifacts kept out of reach."""

    def __init__(self, *, config_class: type = RobotEnvironmentConfig, **kwargs):
        self.config = config_class(**kwargs)
        self.workspace = Path(self.config.workspace).resolve()
        self.artifacts = Path(self.config.artifacts).resolve()
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.artifacts.mkdir(parents=True, exist_ok=True)
        self.calls_path = self.artifacts / "calls.jsonl"

    def _guard(self, command: str) -> None:
        lowered = command.lower()
        touches_artifacts = "artifacts" in lowered or "state.json" in lowered or "roboblwm_state" in lowered
        if _DESTRUCTIVE.search(lowered) and (".." in command or touches_artifacts):
            raise PermissionError("refusing to modify paths outside the workspace")
        if ">" in command and ("../" in command or touches_artifacts):
            raise PermissionError("refusing to write outside the workspace")

    def _child_env(self) -> dict[str, str]:
        env = dict(os.environ)
        project_root = str(Path(self.config.sim_path).resolve().parent)
        python_path = os.pathsep.join(
            p for p in (self.config.sim_path, project_root, env.get("PYTHONPATH", "")) if p
        )
        env.update(
            {
                "PYTHONPATH": python_path,
                "PYTHONUNBUFFERED": "1",
                "LIBERO_CONFIG_PATH": self.config.libero_config_path,
                "MUJOCO_GL": "osmesa",
                "PYOPENGL_PLATFORM": "osmesa",
                "ROBOLWM_ARTIFACTS": str(self.artifacts),
                "ROBOLWM_STATE": str(self.artifacts / "state.json"),
                "ROBOLWM_INIT_OBS": str(self.artifacts / "init_obs.json"),
                "ROBOLWM_TASK": self.config.task_language,
                "ROBOLWM_LWM": "on" if self.config.lwm_enabled else "off",
                "ROBOLWM_SUITE": self.config.suite,
                "ROBOLWM_TASK_ID": str(self.config.task_id),
                "ROBOLWM_TRY_CAP": str(self.config.try_cap),
                "ROBOLWM_CAMERA": str(self.config.camera_size),
            }
        )
        python_dir = str(Path(self.config.python).parent)
        env["PATH"] = python_dir + os.pathsep + env.get("PATH", "")
        return env

    def execute(self, action: dict, cwd: str = "", *, timeout: int | None = None) -> dict[str, Any]:
        command = action.get("command", "")
        started = time.time()
        try:
            self._guard(command)
            proc = subprocess.Popen(
                command,
                shell=True,
                text=True,
                cwd=cwd or str(self.workspace),
                env=self._child_env(),
                encoding="utf-8",
                errors="replace",
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                start_new_session=os.name == "posix",
            )
            try:
                output, _ = proc.communicate(timeout=timeout or self.config.timeout)
            except subprocess.TimeoutExpired:
                if os.name == "posix":
                    os.killpg(proc.pid, signal.SIGKILL)
                else:
                    proc.kill()
                output, _ = proc.communicate()
                result = {
                    "output": output,
                    "returncode": -1,
                    "exception_info": f"command timed out after {timeout or self.config.timeout}s",
                }
            else:
                result = {"output": output, "returncode": proc.returncode, "exception_info": ""}
        except Exception as e:
            result = {"output": "", "returncode": -1, "exception_info": str(e)}
        self._log_call(command, result, time.time() - started)
        self._check_finished(result)
        return result

    def _try_results(self) -> list[dict]:
        results = []
        for path in sorted(self.artifacts.glob("tries/*/result.json")):
            try:
                results.append(json.loads(path.read_text()))
            except (OSError, json.JSONDecodeError):
                continue
        return results

    def _tries_used(self) -> int:
        state_path = self.artifacts / "state.json"
        if state_path.is_file():
            try:
                return int(json.loads(state_path.read_text()).get("tries", 0))
            except (OSError, ValueError, json.JSONDecodeError):
                pass
        return len(self._try_results())

    def _check_finished(self, result: dict) -> None:
        """Handle the completion sentinel under an external success gate.

        Submission is accepted only if at least one recorded trial succeeded.
        Otherwise it is rejected (and the agent keeps working) until the trial
        budget is exhausted, at which point the run ends as a failure.
        """
        lines = result.get("output", "").lstrip().splitlines(keepends=True)
        if not lines or result["returncode"] != 0:
            return
        sentinel = "COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT"
        first, last = lines[0].strip(), lines[-1].strip()
        if first != sentinel and last != sentinel:
            return

        results = self._try_results()
        if any(r.get("success") for r in results):
            submission = "" if last == sentinel else "".join(lines[1:])
            raise Submitted(
                {
                    "role": "exit",
                    "content": submission,
                    "extra": {"exit_status": "Submitted", "submission": submission},
                }
            )

        used = self._tries_used()
        if used >= self.config.try_cap:
            raise LimitsExceeded(
                {
                    "role": "exit",
                    "content": "TrialBudgetExhausted",
                    "extra": {
                        "exit_status": "TrialBudgetExhausted",
                        "submission": "",
                        "tries": used,
                    },
                }
            )

        result["output"] = result.get("output", "") + (
            "\n<submission_rejected>\n"
            f"No successful trial yet ({used}/{self.config.try_cap} tries used). "
            "Submission ignored. Fix episode.py and run it again.\n"
            "</submission_rejected>\n"
        )
        result.setdefault("extra", {})["submission_rejected"] = True

    def _log_call(self, command: str, result: dict, duration: float) -> None:
        entry = {
            "ts": time.time(),
            "command": command,
            "returncode": result["returncode"],
            "duration_s": round(duration, 3),
            "exception": result["exception_info"],
        }
        with self.calls_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")

    def get_template_vars(self, **kwargs) -> dict[str, Any]:
        return {
            "workspace": str(self.workspace),
            "artifacts": str(self.artifacts),
            "suite": self.config.suite,
            "task_id": self.config.task_id,
            "python": self.config.python,
            "lwm_enabled": self.config.lwm_enabled,
        }

    def serialize(self) -> dict:
        return {
            "info": {
                "config": {
                    "environment": self.config.model_dump(),
                    "environment_type": f"{self.__class__.__module__}.{self.__class__.__name__}",
                }
            }
        }
