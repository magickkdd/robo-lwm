"""LIBERO wrapper: the only simulation entry point for the agent.

The agent never imports mujoco/robosuite directly. It gets privileged state
through this class, and every `reset()` consumes one trial from a budget that
lives outside the agent-writable workspace.
"""

import atexit
import json
import os
import time
from pathlib import Path

os.environ.setdefault("MUJOCO_GL", "osmesa")
os.environ.setdefault("PYOPENGL_PLATFORM", "osmesa")
os.environ.setdefault("LIBERO_CONFIG_PATH", os.path.expanduser("~/.libero-roboclwm"))

import imageio
import numpy as np
import robosuite  # noqa: F401  # must be imported before libero's torch import
from libero.libero import benchmark, get_libero_path
from libero.libero.envs import OffScreenRenderEnv
from scipy.spatial.transform import Rotation


class TrialCapExceeded(RuntimeError):
    """Raised when the agent tries to run more episodes than allowed."""


class LiberoEnv:
    """One task, one trial budget, one video per trial."""

    def __init__(self, suite=None, task_id=None, camera_size=None, fps=20, horizon=520, preview=False):
        self.suite = suite or os.environ.get("ROBOLWM_SUITE", "libero_object")
        self.preview = preview
        self.task_id = int(task_id if task_id is not None else os.environ.get("ROBOLWM_TASK_ID", "0"))
        self.camera_size = int(camera_size or os.environ.get("ROBOLWM_CAMERA", "256"))
        self.fps = fps
        self.horizon = horizon
        self.try_cap = int(os.environ.get("ROBOLWM_TRY_CAP", "10"))
        self.artifacts_dir = Path(os.environ.get("ROBOLWM_ARTIFACTS", "./artifacts"))
        self.state_path = Path(os.environ.get("ROBOLWM_STATE", str(self.artifacts_dir / "state.json")))

        self._bench = benchmark.get_benchmark(self.suite)()
        self.task = self._bench.get_task(self.task_id)
        self._init_states = self._bench.get_task_init_states(self.task_id)
        self._env = None
        self._frames = []
        self._actions = []
        self._try_index = None
        self._success = False
        self._last_obs = None
        self._output_max = None
        self._closed = False
        atexit.register(self.close)

    # ---------- budget ----------

    def _read_state(self):
        if self.state_path.is_file():
            return json.loads(self.state_path.read_text())
        return {"tries": 0}

    def _write_state(self, state):
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(state))
        os.replace(tmp, self.state_path)

    @property
    def num_tries(self):
        return self._read_state()["tries"]

    @property
    def remaining_tries(self):
        return max(0, self.try_cap - self.num_tries)

    @property
    def tries_left(self):
        return self.remaining_tries

    # ---------- lifecycle ----------

    def _make_env(self):
        bddl = os.path.join(get_libero_path("bddl_files"), self.task.problem_folder, self.task.bddl_file)
        env = OffScreenRenderEnv(
            bddl_file_name=bddl,
            camera_heights=self.camera_size,
            camera_widths=self.camera_size,
            horizon=self.horizon,
        )
        env.seed(0)
        return env

    def reset(self):
        """Start a new trial. Consumes one try from the budget.

        In preview mode this only captures the initial observation: no trial is
        consumed, no artifacts are written, and ``step`` is disabled.
        """
        if self.preview:
            if self._env is None:
                self._env = self._make_env()
            self._env.reset()
            obs = self._env.set_init_state(self._init_states[0])
            self._last_obs = obs
            return self.describe()

        state = self._read_state()
        if state["tries"] >= self.try_cap:
            raise TrialCapExceeded(f"trial cap reached: {state['tries']}/{self.try_cap}")
        self._try_index = state["tries"]
        state["tries"] += 1
        self._write_state(state)

        self._frames = []
        self._actions = []
        self._success = False
        if self._env is None:
            self._env = self._make_env()
        self._env.reset()
        obs = self._env.set_init_state(self._init_states[0])
        self._last_obs = obs
        self._capture(obs)
        return self.describe()

    def _controller_output_max(self):
        if self._output_max is None:
            ctrl = self._env.env.robots[0].controller
            self._output_max = np.asarray(ctrl.output_max, dtype=np.float64)
        return self._output_max

    def step(self, action):
        """Apply one absolute 7-D end-effector pose; the wrapper converts to OSC deltas."""
        if self.preview:
            raise RuntimeError("preview mode is read-only; call reset() without preview to execute")
        if self._env is None:
            raise RuntimeError("call reset() before step()")
        arr = np.asarray(action, dtype=np.float64).reshape(-1)
        if arr.size != 7:
            raise ValueError(f"action must have 7 values, got {arr.size}")

        cur_pos = np.asarray(self._last_obs["robot0_eef_pos"], dtype=np.float64)
        cur_rot = Rotation.from_quat(np.asarray(self._last_obs["robot0_eef_quat"], dtype=np.float64))
        if np.allclose(arr[3:6], 0.0):
            rot_err = np.zeros(3)
        else:
            rot_err = (Rotation.from_rotvec(arr[3:6]) * cur_rot.inv()).as_rotvec()

        output_max = self._controller_output_max()
        delta = np.concatenate([(arr[:3] - cur_pos) / output_max[:3], rot_err / output_max[3:]])
        ctrl = np.clip(delta, -1.0, 1.0)
        obs, reward, done, info = self._env.step(np.concatenate([ctrl, [arr[6]]]))
        self._actions.append(arr.tolist())
        self._last_obs = obs
        self._capture(obs)
        if self.check_success():
            self._success = True
            done = True
        return self.describe(), reward, done, info

    def get_obs(self):
        if self._last_obs is None:
            raise RuntimeError("call reset() before get_obs()")
        return self.describe()

    def check_success(self):
        if self._env is None:
            return False
        return bool(self._env.check_success())

    def describe(self):
        """Compact privileged observation for the agent (no images)."""
        obs = self._last_obs or {}
        objects = {}
        for key, value in obs.items():
            if key.startswith("robot") or "_to_robot0_eef" in key:
                continue
            if key.endswith("_pos"):
                objects.setdefault(key[:-4], {})["pos"] = np.asarray(value).round(4).tolist()
            elif key.endswith("_quat"):
                objects.setdefault(key[:-5], {})["quat"] = np.asarray(value).round(4).tolist()
        return {
            "task": self.task.language,
            "suite": self.suite,
            "task_id": self.task_id,
            "try": self._try_index,
            "tries_used": 0 if self.preview else self.num_tries,
            "tries_left": self.try_cap if self.preview else self.remaining_tries,
            "eef_pos": np.asarray(obs.get("robot0_eef_pos", [])).round(4).tolist(),
            "eef_quat": np.asarray(obs.get("robot0_eef_quat", [])).round(4).tolist(),
            "gripper_qpos": np.asarray(obs.get("robot0_gripper_qpos", [])).round(4).tolist(),
            "objects": objects,
            "success": self.check_success(),
        }

    # ---------- artifacts ----------

    def _capture(self, obs):
        frame = obs.get("agentview_image")
        if frame is not None:
            self._frames.append(np.asarray(frame)[::-1].copy())

    def _try_dir(self):
        return self.artifacts_dir / "tries" / f"{self._try_index:03d}"

    def close(self):
        if self._closed:
            return
        self._closed = True
        if self.preview:
            if self._env is not None:
                try:
                    self._env.close()
                except Exception:
                    pass
            return
        if self._try_index is None:
            return

        try_dir = self._try_dir()
        try_dir.mkdir(parents=True, exist_ok=True)
        video_path = try_dir / "video.mp4"
        if self._frames:
            imageio.mimsave(video_path, self._frames, fps=self.fps, macro_block_size=None)

        success = self.check_success()
        result = {
            "success": success,
            "try": self._try_index,
            "steps": len(self._actions),
            "task": self.task.language,
            "suite": self.suite,
            "task_id": self.task_id,
            "video": str(video_path),
        }
        (try_dir / "result.json").write_text(json.dumps(result, indent=2))
        (try_dir / "actions.json").write_text(json.dumps(self._actions))

        if success:
            final = self.artifacts_dir / "video.mp4"
            final.parent.mkdir(parents=True, exist_ok=True)
            final.write_bytes(video_path.read_bytes())

        print(json.dumps(result), flush=True)
        if self._env is not None:
            try:
                self._env.close()
            except Exception:
                pass
