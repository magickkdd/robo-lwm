# Robo-LWM 方法全解

> 本文档描述当前仓库的完整方法：从 `mini-swe-agent` 的最小 ReAct 内核，到 LIBERO 机器人仿真环境，再到任务编排、产物归档与一次真实成功运行的完整数据流。
>
> 成功案例：`runs/pilot4/libero_object_1`，任务 *"pick up the cream cheese and place it in the basket"*，1 次 try、157 个仿真步、4 次模型调用、119.4 秒，最终 `success=true / exit_status=Submitted`。

---

## 目录

1. 一句话概括
2. 设计原则
3. 仓库结构与模块职责
4. 分层与调用关系
5. 逐文件、逐方法详解
   - 5.1 `runner.py`
   - 5.2 `sim/libero_env.py`
   - 5.3 `src/minisweagent/environments/robot.py`
   - 5.4 `src/minisweagent/agents/default.py`
   - 5.5 `src/minisweagent/models/openai_model.py`
   - 5.6 `src/minisweagent/models/utils/actions_toolcall.py`
   - 5.7 `src/minisweagent/config/default.yaml`
   - 5.8 `template/` 任务契约
   - 5.9 支撑模块
   - 5.10 `pyproject.toml` 与 `.env`
6. 运行时目录与数据流
7. 一次成功任务的完整实录
8. 预算、安全与失败模式
9. 复现方式
10. 与 MCC-FAEA 的对应关系

---

## 1. 一句话概括

**一个极薄的 ReAct agent，包在一套厚的外部 harness 里。**

- Agent 内核只有 `DefaultAgent`（约 190 行）：调模型 → 拿一个 bash 命令 → 执行 → 看输出 → 继续。
- 外部 harness 负责一切“机器人特有的复杂度”：
  - `runner.py`：建任务目录、铺 workspace、起 agent、收产物、写 `run.json`。
  - `RobotEnvironment`：在 workspace 内执行命令，注入仿真环境变量，做路径守卫和提交哨兵识别。
  - `LiberoEnv`：唯一仿真入口，绝对位姿 → OSC delta 转换、try 计数、录像、特权观测、原生成功判定。
  - `template/`：给 agent 的任务契约、API 文档和骨架示例。
- 结果是：**agent 不需要任何机器人专用工具，仍然只有一个 `bash` 工具**；所有机器人语义都在 wrapper 里。

---

## 2. 设计原则

| 原则 | 落点 |
| :--- | :--- |
| 薄 agent、厚 harness | `DefaultAgent` 不改；新增代码全部在 `runner.py`、`RobotEnvironment`、`LiberoEnv` |
| 单一工具 | 模型只拿到 `bash(command)`，通过 shell 写/跑 `episode.py` |
| 绝对位姿 API | agent 只关心 `[x,y,z,ax,ay,az,gripper]`；wrapper 自动转成 LIBERO 的 delta 控制 |
| 唯一仿真入口 | agent 不能 import mujoco/robosuite；只能 `from libero_env import LiberoEnv` |
| 一次 episode = 一次 try | `env.reset()` 消耗一次预算；try 计数在 workspace 之外 |
| 任务级目录 | 每个任务一个文件夹，prompt、轨迹、workspace、视频、结果全部可追溯 |
| 事实与呈现分离 | wrapper 返回结构化 dict；模型只看到投影后的文本；`traj.json` 保留完整事实 |
| 不信任自报 | 最终 success 以 LIBERO 原生 `check_success()` 为准，agent 的 `meta.json` 不参与判定 |
| 预算分层 | 轮数（agent）、try（wrapper）、token/cost（model）、墙钟（agent） |
| 幂等 | `run.json` 已 `done` 的任务默认跳过，`--force` 才重跑 |

---

## 3. 仓库结构与模块职责

```text
RoboLWM/
├── .env                          # 模型配置（gitignore，不上传）
├── .venv/                        # agent 运行环境（Python 3.10）
├── pyproject.toml                # agent 依赖
├── runner.py                     # 任务编排入口
├── sim/
│   └── libero_env.py             # LIBERO wrapper（唯一仿真入口）
├── src/minisweagent/
│   ├── __init__.py               # .env 加载、runs_dir、三个 Protocol
│   ├── exceptions.py             # 流控异常
│   ├── agents/default.py         # ReAct 循环
│   ├── environments/
│   │   ├── local.py              # 原版本地 shell 环境（保留作参考）
│   │   └── robot.py              # 机器人任务环境
│   ├── models/
│   │   ├── __init__.py           # 全局模型统计
│   │   ├── openai_model.py       # OpenAI 兼容模型
│   │   └── utils/
│   │       ├── actions_toolcall.py    # bash 工具 schema、解析、观测格式化
│   │       ├── openai_multimodal.py   # 多模态内容展开（默认关闭）
│   │       └── retry.py               # tenacity 重试
│   ├── config/
│   │   ├── __init__.py           # 加载 default.yaml
│   │   └── default.yaml          # 提示词模板
│   └── utils/
│       ├── log.py                # 标准库日志
│       └── serialize.py          # 递归合并
├── template/
│   ├── README.md                 # 任务契约
│   ├── docs/api.md               # LiberoEnv API 文档
│   └── example_episode.py        # 骨架示例
└── runs/<stage>/<suite>_<task_id>/
    ├── run.json                  # 任务结果（runner 唯一真相）
    ├── prompt.txt                # 冻结的任务文本
    ├── traj.json                 # 完整会话轨迹
    ├── workspace/                # agent 可写沙箱
    └── artifacts/                # wrapper/runner 只写
```

---

## 4. 分层与调用关系

```text
runner.py
  │
  ├─ task_meta() ── subprocess(libero python) ── LIBERO benchmark
  │
  ├─ DefaultAgent ──────────────┐
  │    │                        │
  │    ├─ OpenAIModel ──────────┤  (HTTP /v1/chat/completions)
  │    │                        │
  │    └─ RobotEnvironment ─────┤  (subprocess, cwd=workspace)
  │                             │
  │                             └─ python episode.py
  │                                   │
  │                                   └─ LiberoEnv ── Robosuite/MuJoCo
  │
  └─ run.json / artifacts/
```

边界很清晰：

- `DefaultAgent` 只认识 `Model` / `Environment` 两个 Protocol。
- `OpenAIModel` 只负责“把 messages 变成一次 tool call 响应”。
- `RobotEnvironment` 只负责“在 workspace 里跑 bash 命令，并返回 stdout/returncode”。
- `LiberoEnv` 只负责“仿真、绝对位姿转换、try 预算、录像、成功判定”。

---

## 5. 逐文件、逐方法详解

### 5.1 `runner.py`

**职责**：一个任务一个目录；准备 workspace；构造 model/env/agent；调用 `agent.run()`；收集并判定产物；支持批量、幂等与强制重跑。

#### 完整代码

```python
#!/usr/bin/env python3
"""Run the robot agent on LIBERO tasks and collect per-task artifacts.

Usage:
    python runner.py --suite libero_object --task-id 1
    python runner.py --suite libero_object --all --max-turns 40
"""

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from minisweagent.agents.default import DefaultAgent
from minisweagent.config import load_default_config
from minisweagent.environments.robot import RobotEnvironment
from minisweagent.models.openai_model import OpenAIModel

ROOT = Path(__file__).resolve().parent
RUNS = ROOT / "runs"
TEMPLATE = ROOT / "template"
SIM = ROOT / "sim"
LIBERO_PYTHON = "/home/czx/miniconda3/envs/libero/bin/python"
LIBERO_CONFIG_PATH = "/home/czx/.libero-roboclwm"


def task_meta(suite: str, task_id: int) -> dict:
    """Read task name/language through the LIBERO interpreter."""
    code = f"""
import json, os
os.environ.setdefault("MUJOCO_GL", "osmesa")
os.environ.setdefault("PYOPENGL_PLATFORM", "osmesa")
import robosuite
from libero.libero import benchmark
b = benchmark.get_benchmark({suite!r})()
t = b.get_task({task_id})
print("META:" + json.dumps({{"name": t.name, "language": t.language, "n_tasks": b.get_num_tasks()}}))
"""
    env = dict(os.environ)
    env["LIBERO_CONFIG_PATH"] = LIBERO_CONFIG_PATH
    env["MUJOCO_GL"] = "osmesa"
    env["PYOPENGL_PLATFORM"] = "osmesa"
    out = subprocess.check_output([LIBERO_PYTHON, "-c", code], env=env, text=True, stderr=subprocess.DEVNULL)
    for line in out.splitlines():
        if line.startswith("META:"):
            return json.loads(line[5:])
    raise RuntimeError(f"could not read task metadata from: {out[-500:]}")


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    os.replace(tmp, path)


def prepare_workspace(task_dir: Path, suite: str, task_id: int, language: str) -> Path:
    workspace = task_dir / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    for src in TEMPLATE.rglob("*"):
        if not src.is_file():
            continue
        rel = src.relative_to(TEMPLATE)
        dst = workspace / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        text = src.read_text(encoding="utf-8")
        text = text.replace("{{TASK}}", language).replace("{{SUITE}}", suite).replace("{{TASK_ID}}", str(task_id))
        dst.write_text(text, encoding="utf-8")
    return workspace


def all_try_results(artifacts: Path) -> list[dict]:
    results = []
    for path in sorted(artifacts.glob("tries/*/result.json")):
        try:
            results.append(json.loads(path.read_text()))
        except (OSError, json.JSONDecodeError):
            continue
    return results


def best_try_result(results: list[dict]) -> dict:
    for result in reversed(results):
        if result.get("success"):
            return result
    return results[-1] if results else {}


def run_task(args, suite: str, task_id: int, meta: dict) -> dict:
    task_dir = RUNS / args.stage / f"{suite}_{task_id}"
    run_path = task_dir / "run.json"
    if run_path.is_file() and not args.force:
        existing = json.loads(run_path.read_text())
        if existing.get("status") == "done":
            print(f"[skip] {suite}_{task_id} already done: success={existing.get('success')}")
            return existing

    workspace = prepare_workspace(task_dir, suite, task_id, meta["language"])
    artifacts = task_dir / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    prompt = meta["language"]
    (task_dir / "prompt.txt").write_text(prompt, encoding="utf-8")

    started = time.time()
    write_json(
        run_path,
        {
            "status": "running",
            "stage": args.stage,
            "suite": suite,
            "task_id": task_id,
            "task": meta["language"],
            "started": started,
        },
    )

    cfg = load_default_config()
    model_name = args.model or os.environ.get("MODEL_NAME")
    if not model_name:
        raise SystemExit("no model configured: set MODEL_NAME in .env or pass --model")

    model = OpenAIModel(
        model_name=model_name,
        model_kwargs={"reasoning_effort": args.reasoning_effort} if args.reasoning_effort != "default" else {},
        request_timeout=args.request_timeout,
    )
    env = RobotEnvironment(
        workspace=str(workspace),
        artifacts=str(artifacts),
        suite=suite,
        task_id=task_id,
        sim_path=str(SIM),
        python=LIBERO_PYTHON,
        libero_config_path=LIBERO_CONFIG_PATH,
        try_cap=args.try_cap,
        camera_size=args.camera,
        timeout=args.timeout,
    )
    agent = DefaultAgent(
        model,
        env,
        system_template=cfg["agent"]["system_template"],
        instance_template=cfg["agent"]["instance_template"],
        step_limit=args.max_turns,
        cost_limit=0.0,
        wall_time_limit_seconds=args.timeout,
        output_path=task_dir / "traj.json",
    )

    record = {
        "stage": args.stage,
        "suite": suite,
        "task_id": task_id,
        "task": meta["language"],
        "started": started,
    }
    try:
        result = agent.run(prompt)
        tries = all_try_results(artifacts)
        best = best_try_result(tries)
        success = any(t.get("success") for t in tries)
        record.update(
            {
                "status": "done",
                "success": success,
                "exit_status": result.get("exit_status"),
                "api_calls": agent.n_calls,
                "cost": round(agent.cost, 6),
                "tries": len(tries),
                "steps_last_try": best.get("steps"),
                "video": best.get("video") if success else None,
                "duration_s": round(time.time() - started, 1),
            }
        )
    except Exception as e:
        record.update(
            {
                "status": "error",
                "success": False,
                "error": f"{type(e).__name__}: {e}",
                "duration_s": round(time.time() - started, 1),
            }
        )
        print(f"[error] {suite}_{task_id}: {record['error']}")

    write_json(run_path, record)
    print(json.dumps(record))
    return record


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--stage", default="pilot")
    p.add_argument("--suite", default="libero_object")
    p.add_argument("--task-id", type=int, nargs="+", default=[1])
    p.add_argument("--all", action="store_true", help="run all 10 tasks of the suite")
    p.add_argument("--max-turns", type=int, default=40)
    p.add_argument("--try-cap", type=int, default=10)
    p.add_argument("--camera", type=int, default=256)
    p.add_argument("--timeout", type=int, default=1200)
    p.add_argument("--model", default=None)
    p.add_argument("--reasoning-effort", default=os.environ.get("REASONING_EFFORT", "none"))
    p.add_argument("--request-timeout", type=float, default=180.0)
    p.add_argument("--force", action="store_true")
    return p.parse_args()


def main():
    args = parse_args()
    if args.all:
        n_tasks = task_meta(args.suite, 0)["n_tasks"]
        args.task_id = list(range(n_tasks))
    records = []
    for task_id in args.task_id:
        meta = task_meta(args.suite, task_id)
        records.append(run_task(args, args.suite, task_id, meta))
    successes = sum(1 for r in records if r.get("success"))
    print(f"[summary] {successes}/{len(records)} success")
    return 0 if successes else 1


if __name__ == "__main__":
    sys.exit(main())
```

#### 方法说明

| 方法 | 作用 | 关键细节 |
| :--- | :--- | :--- |
| `task_meta(suite, task_id)` | 通过 LIBERO 解释器读取任务名/语言/任务总数 | 子进程里先 `import robosuite` 再 import LIBERO，避免 torch 先加载破坏 PyOpenGL；输出用 `META:` 前缀解析 |
| `write_json(path, data)` | 原子写 JSON | 先写 `.tmp`，再 `os.replace`，避免中途崩溃留下半截文件 |
| `prepare_workspace(...)` | 复制 `template/` 到 `workspace/` | 替换 `{{TASK}}`、`{{SUITE}}`、`{{TASK_ID}}`；agent 只在这个目录里工作 |
| `all_try_results(artifacts)` | 读取 `tries/*/result.json` | 排序后返回，坏文件跳过 |
| `best_try_result(results)` | 优先返回成功的那次 try | 没有成功则返回最后一次 |
| `run_task(...)` | 单任务完整流程 | 幂等检查 → 准备 workspace → 写初始 `run.json` → 构造 model/env/agent → `agent.run()` → 汇总 try → 写最终 `run.json` |
| `parse_args()` | CLI 参数 | `--task-id` 支持多个；`--all` 跑整个 suite；`--reasoning-effort` 默认 `none` |
| `main()` | 批量循环 | `--all` 时用 `task_meta(...)[n_tasks]` 决定任务数；最后打印 `[summary] x/y success` |

#### CLI 参数

| 参数 | 默认值 | 含义 |
| :--- | :--- | :--- |
| `--stage` | `pilot` | 产物一级目录 `runs/<stage>/` |
| `--suite` | `libero_object` | LIBERO suite |
| `--task-id` | `1` | 一个或多个任务 id |
| `--all` | false | 跑该 suite 全部任务 |
| `--max-turns` | 40 | agent 最大 LLM 轮数 |
| `--try-cap` | 10 | 每个任务最大仿真 try 数 |
| `--camera` | 256 | 录像分辨率 |
| `--timeout` | 1200 | 单命令超时 + agent 墙钟上限 |
| `--model` | `.env` 的 `MODEL_NAME` | 模型名 |
| `--reasoning-effort` | `none` | 透传给 Chat Completions；`default` 表示不传 |
| `--request-timeout` | 180 | 单次 LLM 请求超时 |
| `--force` | false | 已 `done` 也重跑 |

### 5.2 `sim/libero_env.py`

**职责**：agent 能接触到的唯一仿真接口。它把 LIBERO/robosuite/MuJoCo 完全包住，对外只暴露绝对末端位姿、特权观测、try 预算、录像和成功判定。

#### 完整代码

```python
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

    def __init__(self, suite=None, task_id=None, camera_size=None, fps=20, horizon=520):
        self.suite = suite or os.environ.get("ROBOLWM_SUITE", "libero_object")
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
        """Start a new trial. Consumes one try from the budget."""
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
            "tries_used": self.num_tries,
            "tries_left": self.remaining_tries,
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
```

#### 方法说明

| 方法/属性 | 作用 | 关键细节 |
| :--- | :--- | :--- |
| `__init__` | 读环境变量，加载 benchmark、任务、初始状态 | `suite/task_id/camera/try_cap` 全部可由 `ROBOLWM_*` 覆盖；`atexit.register(self.close)` 保证异常退出也落盘 |
| `_read_state` / `_write_state` | try 计数器读写 | 文件在 `artifacts/state.json`，位于 workspace 之外；写入用 tmp + `os.replace` |
| `num_tries` / `remaining_tries` / `tries_left` | 预算查询 | `tries_left` 是给 agent 的友好别名 |
| `_make_env` | 构造 LIBERO `OffScreenRenderEnv` | BDDL 路径来自 `get_libero_path("bddl_files")`；`env.seed(0)` |
| `reset` | 开始一次 try | 先检查并递增计数；`env.reset()` 后 `set_init_state(init_states[0])`，拿到固定初始状态 |
| `_controller_output_max` | 读取 OSC 控制器的每步最大增量 | 实测 `[0.05,0.05,0.05,0.5,0.5,0.5]` |
| `step` | 绝对位姿 → delta → 仿真步进 | 见下方控制数学；`check_success()` 为真时强制 `done=True` |
| `get_obs` | 返回最近一次观测 | 不步进 |
| `check_success` | 调 LIBERO 原生 `_check_success()` | 唯一可信的成功判定 |
| `describe` | 把原始 obs 投影成 agent 可见的 dict | 过滤 `robot*` 和 `*_to_robot0_eef`；保留物体 `pos/quat`、eef、夹爪、try 信息 |
| `_capture` | 收集视频帧 | `agentview_image` 上下翻转（MuJoCo 图像原点在左下） |
| `_try_dir` | `artifacts/tries/000` | 每次 try 独立目录 |
| `close` | 写视频、`result.json`、`actions.json`，成功时复制最终视频 | `atexit` 调用；打印一行 JSON 供 agent 观察 |

#### 控制数学：为什么 agent 写绝对位姿也能用

LIBERO 的 `OSC_POSE` 控制器默认是 **delta 控制**：动作是 `[-1,1]` 的归一化增量，乘以 `output_max` 才是真实位移。直接传绝对坐标会被当成“小增量”，机械臂几乎不动。

wrapper 在 `step()` 里做转换：

```text
pos_err  = target_xyz - current_eef_pos
pos_ctrl = clip(pos_err / output_max[:3], -1, 1)

rot_err  = (R_target * R_current^-1).as_rotvec()
rot_ctrl = clip(rot_err / output_max[3:], -1, 1)

env_action = [pos_ctrl, rot_ctrl, gripper]
```

约定：

- `action[3:6]` 全为 0 → 保持当前姿态（`rot_err = 0`）；
- 否则把 `action[3:6]` 当作绝对 axis-angle，先转旋转矩阵再求误差；
- `gripper = +1` 夹紧，`-1` 松开；
- 每步最多逼近 5cm / 0.5rad，所以要连续保持同一目标 20–30 步。

#### 观测投影

原始 obs 里有大量字段，包括每个物体的 `*_pos`、`*_quat`、`*_to_robot0_eef_*`。`describe()` 只保留：

```json
{
  "task": "pick up the cream cheese and place it in the basket",
  "suite": "libero_object",
  "task_id": 1,
  "try": 0,
  "tries_used": 1,
  "tries_left": 9,
  "eef_pos": [...],
  "eef_quat": [...],
  "gripper_qpos": [...],
  "objects": {
    "cream_cheese_1": {"pos": [...], "quat": [...]},
    "basket_1": {"pos": [...], "quat": [...]},
    "...": {}
  },
  "success": false
}
```

这是“特权观测”：agent 直接拿到物体真实位姿，不需要从图像里估计。

---

### 5.3 `src/minisweagent/environments/robot.py`

**职责**：把 agent 的 bash 命令放到任务 workspace 里执行，注入仿真环境变量，做路径守卫、调用日志和提交哨兵识别。

#### 完整代码

```python
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
        env.update(
            {
                "PYTHONPATH": self.config.sim_path + os.pathsep + env.get("PYTHONPATH", ""),
                "PYTHONUNBUFFERED": "1",
                "LIBERO_CONFIG_PATH": self.config.libero_config_path,
                "MUJOCO_GL": "osmesa",
                "PYOPENGL_PLATFORM": "osmesa",
                "ROBOLWM_ARTIFACTS": str(self.artifacts),
                "ROBOLWM_STATE": str(self.artifacts / "state.json"),
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
```

#### 方法说明

| 方法 | 作用 | 关键细节 |
| :--- | :--- | :--- |
| `__init__` | 解析 workspace/artifacts，创建目录 | 两者都 `.resolve()`，后续路径判断稳定 |
| `_guard` | 阻止把 workspace 外的东西改掉 | 破坏性命令 + (`..` 或 artifacts 字样) → `PermissionError`；`>` 重定向到外部同理 |
| `_child_env` | 构造子进程环境 | 注入 `PYTHONPATH=sim/`、OSMesa 变量、`LIBERO_CONFIG_PATH`、`ROBOLWM_*`；把 libero python 目录放到 `PATH` 最前，保证 `python` 命令就是仿真解释器 |
| `execute` | 跑一条 shell 命令 | `shell=True`、`cwd=workspace`、stdout/stderr 合并、`start_new_session` + `killpg` 处理超时 |
| `_check_finished` | 外部提交门控 | 首行或末行是哨兵时：任一 try `success=true` → `Submitted`；否则若 try 用尽 → `TrialBudgetExhausted`；否则追加 `<submission_rejected>`，忽略提交、继续循环 |
| `_log_call` | 追加 `artifacts/calls.jsonl` | 每行一个 JSON：时间、命令、返回码、耗时、异常 |
| `get_template_vars` | 给 Jinja 模板提供变量 | `workspace` 会渲染进 user prompt |
| `serialize` | 写进 `traj.json` 的 info | 记录环境配置 |

#### 注入给子进程的环境变量

| 变量 | 值 | 用途 |
| :--- | :--- | :--- |
| `PYTHONPATH` | `<repo>/sim` + 原值 | `episode.py` 能 `from libero_env import LiberoEnv` |
| `PATH` | `<libero python dir>` + 原值 | `python` / `python3` 指向 LIBERO 解释器 |
| `LIBERO_CONFIG_PATH` | `~/.libero-roboclwm` | 隔离 LIBERO 配置，避免污染全局 |
| `MUJOCO_GL` / `PYOPENGL_PLATFORM` | `osmesa` | 无 GPU EGL 时的离屏渲染 |
| `ROBOLWM_ARTIFACTS` | `.../artifacts` | wrapper 写视频/结果 |
| `ROBOLWM_STATE` | `.../artifacts/state.json` | try 计数文件 |
| `ROBOLWM_SUITE` / `ROBOLWM_TASK_ID` | 当前任务 | wrapper 自动加载对应 benchmark |
| `ROBOLWM_TRY_CAP` | `--try-cap` | try 上限 |
| `ROBOLWM_CAMERA` | `--camera` | 录像分辨率 |

### 5.4 `src/minisweagent/agents/default.py`

**职责**：最小 ReAct 循环。它不知道“机器人”这件事，只负责：渲染 prompt → 调模型 → 执行动作 → 回填观测 → 检查预算/异常 → 保存轨迹。

#### 完整代码

```python
"""Basic agent class. See https://mini-swe-agent.com/latest/advanced/control_flow/ for visual explanation
or https://minimal-agent.com for a tutorial on the basic building principles.
"""

import json
import logging
import time
import traceback
from pathlib import Path

from jinja2 import StrictUndefined, Template
from pydantic import BaseModel

from minisweagent import Environment, Model, __version__
from minisweagent.exceptions import FormatError, InterruptAgentFlow, LimitsExceeded, TimeExceeded
from minisweagent.utils.serialize import recursive_merge


class AgentConfig(BaseModel):
    """Check the config files in minisweagent/config for example settings."""

    system_template: str
    """Template for the system message (the first message)."""
    instance_template: str
    """Template for the first user message specifying the task (the second message overall)."""
    step_limit: int = 0
    """Maximum number of steps the agent can take."""
    cost_limit: float = 3.0
    """Stop agent after exceeding (!) this cost."""
    wall_time_limit_seconds: int = 0
    """Stop agent after this many seconds of wall-clock time. 0 means no limit."""
    max_consecutive_format_errors: int = 3
    """Exit after this many format errors in a row (0 = no limit)."""
    output_path: Path | None = None
    """Save the trajectory to this path."""


class DefaultAgent:
    def __init__(self, model: Model, env: Environment, *, config_class: type = AgentConfig, **kwargs):
        """See the `AgentConfig` class for permitted keyword arguments."""
        self.config = config_class(**kwargs)
        self.messages: list[dict] = []
        self.model = model
        self.env = env
        self.extra_template_vars = {}
        self.logger = logging.getLogger("agent")
        self.cost = 0.0
        self.n_calls = 0
        self.n_consecutive_format_errors = 0
        self._start_time = time.time()

    def get_template_vars(self, **kwargs) -> dict:
        return recursive_merge(
            self.config.model_dump(),
            self.env.get_template_vars(),
            self.model.get_template_vars(),
            {
                "n_model_calls": self.n_calls,
                "model_cost": self.cost,
                "elapsed_seconds": int(time.time() - self._start_time),
            },
            self.extra_template_vars,
            kwargs,
        )

    def _render_template(self, template: str) -> str:
        return Template(template, undefined=StrictUndefined).render(**self.get_template_vars())

    def add_messages(self, *messages: dict) -> list[dict]:
        self.logger.debug(messages)  # set log level to debug to see
        self.messages.extend(messages)
        return list(messages)

    def handle_uncaught_exception(self, e: Exception) -> list[dict]:
        return self.add_messages(
            self.model.format_message(
                role="exit",
                content=str(e),
                extra={
                    "exit_status": type(e).__name__,
                    "submission": "",
                    "exception_str": str(e),
                    "traceback": traceback.format_exc(),
                },
            )
        )

    def run(self, task: str = "", **kwargs) -> dict:
        """Run step() until agent is finished. Returns dictionary with exit_status, submission keys."""
        self.extra_template_vars |= {"task": task, **kwargs}
        self.messages = []
        self.add_messages(
            self.model.format_message(role="system", content=self._render_template(self.config.system_template)),
            self.model.format_message(role="user", content=self._render_template(self.config.instance_template)),
        )
        while True:
            try:
                self.step()
                self.n_consecutive_format_errors = 0  # reset on any clean step
            except FormatError as e:
                # The call was billed before parsing failed, so query() never got to charge it.
                self.cost += e.messages[0].get("extra", {}).get("cost", 0.0)
                self.n_consecutive_format_errors += 1
                if 0 < self.config.max_consecutive_format_errors <= self.n_consecutive_format_errors:
                    self.add_messages(
                        *e.messages,
                        {
                            "role": "exit",
                            "content": "RepeatedFormatError",
                            "extra": {"exit_status": "RepeatedFormatError", "submission": ""},
                        },
                    )
                else:
                    self.add_messages(*e.messages)
            except InterruptAgentFlow as e:
                self.add_messages(*e.messages)
            except Exception as e:
                self.handle_uncaught_exception(e)
                raise
            finally:
                self.save(self.config.output_path)
            if self.messages[-1].get("role") == "exit":
                break
        return self.messages[-1].get("extra", {})

    def step(self) -> list[dict]:
        """Query the LM, execute actions."""
        return self.execute_actions(self.query())

    def query(self) -> dict:
        """Query the model and return model messages. Override to add hooks."""
        if 0 < self.config.step_limit <= self.n_calls or 0 < self.config.cost_limit <= self.cost:
            raise LimitsExceeded(
                {
                    "role": "exit",
                    "content": "LimitsExceeded",
                    "extra": {"exit_status": "LimitsExceeded", "submission": ""},
                }
            )
        if 0 < self.config.wall_time_limit_seconds <= int(time.time() - self._start_time):
            raise TimeExceeded(
                {
                    "role": "exit",
                    "content": "TimeExceeded",
                    "extra": {"exit_status": "TimeExceeded", "submission": ""},
                }
            )
        self.n_calls += 1
        message = self.model.query(self.messages)
        self.cost += message.get("extra", {}).get("cost", 0.0)
        self.add_messages(message)
        return message

    def execute_actions(self, message: dict) -> list[dict]:
        """Execute actions in message, add observation messages, return them."""
        outputs = [self.env.execute(action) for action in message.get("extra", {}).get("actions", [])]
        return self.add_messages(*self.model.format_observation_messages(message, outputs, self.get_template_vars()))

    def serialize(self, *extra_dicts) -> dict:
        """Serialize agent state to a json-compatible nested dictionary for saving."""
        last_message = self.messages[-1] if self.messages else {}
        last_extra = last_message.get("extra", {})
        agent_data = {
            "info": {
                "model_stats": {
                    "instance_cost": self.cost,
                    "api_calls": self.n_calls,
                },
                "config": {
                    "agent": self.config.model_dump(mode="json"),
                    "agent_type": f"{self.__class__.__module__}.{self.__class__.__name__}",
                },
                "mini_version": __version__,
                "exit_status": last_extra.get("exit_status", ""),
                "submission": last_extra.get("submission", ""),
            },
            "messages": self.messages,
            "trajectory_format": "mini-swe-agent-1.1",
        }
        return recursive_merge(agent_data, self.model.serialize(), self.env.serialize(), *extra_dicts)

    def save(self, path: Path | None, *extra_dicts) -> dict:
        """Save the trajectory of the agent to a file if path is given. Returns full serialized data.
        You can pass additional dictionaries with extra data to be (recursively) merged into the output data.
        """
        data = self.serialize(*extra_dicts)
        if path:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(data, indent=2))
        return data
```

#### 方法说明

| 方法 | 作用 | 关键细节 |
| :--- | :--- | :--- |
| `AgentConfig` | 配置模型 | `system_template` / `instance_template` 必填；`step_limit`、`cost_limit`、`wall_time_limit_seconds`、`max_consecutive_format_errors`、`output_path` |
| `__init__` | 保存 model/env，初始化计数 | `messages=[]`、`cost=0`、`n_calls=0`、`_start_time` |
| `get_template_vars` | 汇总 Jinja 变量 | 顺序：agent config → env vars → model config → 运行统计 → `extra_template_vars` → kwargs；后者覆盖前者 |
| `_render_template` | Jinja 渲染 | `StrictUndefined`，模板里写错变量会立刻报错 |
| `add_messages` | 追加消息 | 同时作为轨迹记录 |
| `handle_uncaught_exception` | 未捕获异常 → exit 消息 | 记录 `exit_status`、`traceback` |
| `run` | 主循环 | 初始化 system/user → `step()` → 处理 `FormatError` / `InterruptAgentFlow` / 其他异常 → `finally: save()` → 遇到 `role=exit` 退出 |
| `step` | 一步 | `execute_actions(query())` |
| `query` | 预算检查 + 调模型 | 轮数/成本/墙钟超限分别抛 `LimitsExceeded` / `TimeExceeded`；成功后累加 cost、轮数 |
| `execute_actions` | 执行动作 + 回填观测 | 对每个 action 调 `env.execute()`；再让 model 格式化成 observation messages |
| `serialize` | 轨迹序列化 | `info` + `messages` + `trajectory_format`；合并 model/env 的 serialize 信息 |
| `save` | 写 `traj.json` | 每一步 `finally` 都写，崩溃可恢复；`path=None` 时只返回数据不落盘 |

#### 异常流

| 异常 | 触发点 | 结果 |
| :--- | :--- | :--- |
| `FormatError` | 模型没有 tool call / 参数不合法 | 把错误提示作为 user 消息追加；连续 3 次 → `RepeatedFormatError` 退出 |
| `Submitted` | `RobotEnvironment._check_finished` 看到哨兵 | 追加 `role=exit`，循环结束，`exit_status=Submitted` |
| `LimitsExceeded` | 轮数或成本超限 | `exit_status=LimitsExceeded` |
| `TimeExceeded` | 墙钟超限 | `exit_status=TimeExceeded` |
| 其他异常 | 代码 bug / 仿真崩溃 | 记录 traceback 为 exit 消息，然后重新抛出 |

---

### 5.5 `src/minisweagent/models/openai_model.py`

**职责**：把 messages 发给任何 OpenAI 兼容的 `/v1/chat/completions` 端点，拿回一个 `bash` tool call；负责重试、成本统计、错误格式化和观测消息构造。

#### 完整代码

```python
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
```

#### 方法说明

| 方法 | 作用 | 关键细节 |
| :--- | :--- | :--- |
| `OpenAIModelConfig` | 模型配置 | `model_name` 必填；`base_url/api_key` 可从参数或环境变量来；`model_kwargs` 透传（本项目用于 `reasoning_effort`）；`price_*` 用于成本；`request_timeout` 默认 180s |
| `__init__` | 构造 `OpenAI` client | `max_retries=0`（重试由 tenacity 统一控制）；无 key 时用 `"EMPTY"`，方便本地无鉴权端点 |
| `_query` | 发请求 | `tools=[BASH_TOOL]`；`model_kwargs` 与调用时 kwargs 合并 |
| `_prepare_messages_for_api` | 去掉内部字段 | 删除 `extra`（actions、原始 response、token 统计、时间戳），避免发给 API |
| `query` | 完整模型调用 | tenacity 重试 → 成本统计 → 解析 tool call → 组装 assistant message；`FormatError` 时也把成本和原始 response 挂在错误消息上 |
| `_calculate_cost` | 按 token 估算成本 | `(prompt*price_in + completion*price_out)/1e6`；本项目未配置单价，因此 `cost=0.0` |
| `_parse_actions` | 解析 tool calls | 交给 `parse_toolcall_actions`；把 `finish_reason` 传给错误模板，区分“格式错误”和“输出被截断” |
| `format_message` | 构造消息 | 默认不做多模态展开（`multimodal_regex=""`） |
| `format_observation_messages` | 执行结果 → tool 消息 | 用 `observation_template` 渲染 stdout/returncode/exception |
| `get_template_vars` | 模板变量 | 模型配置也可在 prompt 中使用 |
| `serialize` | 轨迹 info | 记录模型配置和类名 |

#### `reasoning_effort`

`runner.py` 默认传 `model_kwargs={"reasoning_effort": "none"}`。原因：当前账号的 `gpt-6-luna` 只支持 Chat Completions，带推理的 tool call 会返回 400：

```text
gpt-6-luna requires Responses for tool calls with reasoning; this account only supports Chat Completions.
Use reasoning_effort=none or a Responses-capable account
```

`--reasoning-effort default` 可以不传该参数。

---

### 5.6 `src/minisweagent/models/utils/actions_toolcall.py`

**职责**：定义唯一的 `bash` 工具 schema；把模型返回的 tool call 解析成动作；把执行输出格式化成 `role=tool` 的观测消息。

#### 完整代码

```python
"""Parse actions & format observations with toolcalls"""

import json
import time

from jinja2 import StrictUndefined, Template

from minisweagent.exceptions import FormatError
from minisweagent.models.utils.openai_multimodal import expand_multimodal_content

BASH_TOOL = {
    "type": "function",
    "function": {
        "name": "bash",
        "description": "Execute a bash command",
        "parameters": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The bash command to execute",
                }
            },
            "required": ["command"],
        },
    },
}


def parse_toolcall_actions(
    tool_calls: list, *, format_error_template: str, template_kwargs: dict | None = None
) -> list[dict]:
    """Parse tool calls from the response. Raises FormatError if unknown tool or invalid args.

    ``template_kwargs`` are extra variables exposed to ``format_error_template`` (e.g.
    ``{"finish_reason": ...}`` so a template can distinguish a real format mistake from a
    ``max_tokens`` truncation).
    """
    template_kwargs = template_kwargs or {}
    if not tool_calls:
        raise FormatError(
            {
                "role": "user",
                "content": Template(format_error_template, undefined=StrictUndefined).render(
                    error="No tool calls found in the response. Every response MUST include at least one tool call.",
                    actions=[],
                    has_tool_calls=False,
                    **template_kwargs,
                ),
                "extra": {"interrupt_type": "FormatError"},
            }
        )
    actions = []
    for tool_call in tool_calls:
        error_msg = ""
        args = {}
        try:
            args = json.loads(tool_call.function.arguments)
        except Exception as e:
            error_msg = f"Error parsing tool call arguments: {e}."
        if tool_call.function.name != "bash":
            error_msg += f"Unknown tool '{tool_call.function.name}'."
        if not isinstance(args, dict) or "command" not in args:
            error_msg += "Missing 'command' argument in bash tool call."
        if error_msg:
            raise FormatError(
                {
                    "role": "user",
                    "content": Template(format_error_template, undefined=StrictUndefined).render(
                        actions=[], error=error_msg.strip(), has_tool_calls=True, **template_kwargs
                    ),
                    "extra": {"interrupt_type": "FormatError"},
                }
            )
        actions.append({"command": args["command"], "tool_call_id": tool_call.id})
    return actions


def format_toolcall_observation_messages(
    *,
    actions: list[dict],
    outputs: list[dict],
    observation_template: str,
    template_vars: dict | None = None,
    multimodal_regex: str = "",
) -> list[dict]:
    """Format execution outputs into tool result messages."""
    not_executed = {"output": "", "returncode": -1, "exception_info": "action was not executed"}
    padded_outputs = outputs + [not_executed] * (len(actions) - len(outputs))
    results = []
    for action, output in zip(actions, padded_outputs):
        content = Template(observation_template, undefined=StrictUndefined).render(
            output=output, **(template_vars or {})
        )
        msg = {
            "content": content,
            "extra": {
                "raw_output": output.get("output", ""),
                "returncode": output.get("returncode"),
                "timestamp": time.time(),
                "exception_info": output.get("exception_info"),
                **output.get("extra", {}),
            },
        }
        if "tool_call_id" in action:
            msg["tool_call_id"] = action["tool_call_id"]
            msg["role"] = "tool"
        else:
            msg["role"] = "user"  # human issued commands
        if multimodal_regex:
            msg = expand_multimodal_content(msg, pattern=multimodal_regex)
        results.append(msg)
    return results
```

#### 关键点

- **只有一个工具**：`bash`，参数只有 `command`。机器人语义完全通过“写 `episode.py` 再执行”体现。
- **强制一次一个动作**：system prompt 要求“exactly ONE bash code block”；解析端支持多个 tool call，但正常路径是一个。
- **格式错误可恢复**：`FormatError` 会带一条 user 消息回去，提示模型“必须包含 tool call / 参数不合法”。
- **观测消息**：每个 action 对应一条 `role=tool` 消息，带 `tool_call_id`，这样 OpenAI 兼容端点能正确关联调用与结果。
- **截断策略**：在 `default.yaml` 的 `observation_template` 里做，>10000 字符时保留前 5000 + 后 5000。

### 5.7 `src/minisweagent/config/default.yaml`

**职责**：保存 agent 的 system/instance 提示词、观测渲染模板、格式错误模板。`load_default_config()` 在 runner 启动时读取，传给 `DefaultAgent` 和 `OpenAIModel`。

#### 完整内容

````yaml
agent:
  system_template: |
    You are a robot manipulation agent controlling a simulated Franka Panda arm
    in LIBERO through a Python wrapper called `LiberoEnv`.

    Your response must contain exactly ONE bash code block with ONE command
    (or commands connected with && or ||).
    Include a THOUGHT section before your command where you explain your reasoning.

    <format_example>
    Your reasoning and analysis here.

    ```mswea_bash_command
    your_command_here
    ```
    </format_example>

    Failure to follow these rules will cause your response to be rejected.

  instance_template: |
    Task: {{task}}

    You are working inside the workspace `{{workspace}}` (this is your current
    directory). The simulator Python is already on `PATH`, so run scripts with
    `python episode.py`.

    ## Read first

    1. `README.md` — task assignment and required outputs.
    2. `docs/api.md` — the complete `LiberoEnv` contract: action format,
       observation schema, trial budget.
    3. `example_episode.py` — a skeleton you can adapt.

    ## Workflow

    1. Inspect the scene: object names and positions are in `obs["objects"]`.
    2. Write `episode.py`: reset, read object poses, move the end effector
       through a pick-and-place sequence, check success.
    3. Run `python episode.py` and read the printed JSON summary.
    4. If it fails, inspect the error or the poses, fix `episode.py`, and run
       again. Each run consumes one trial from a limited budget.
    5. When the task succeeds, submit with:

       `echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT`

    ## Rules

    - Use only `LiberoEnv`; never import mujoco/robosuite directly.
    - Never modify trial counters, success checks, or paths outside this
      workspace.
    - The action is `[x, y, z, ax, ay, az, gripper]`, an absolute end-effector
      pose. `+1` closes the gripper, `-1` opens it; all-zero orientation keeps
      the current orientation. Hold each action for 20–30 steps to reach the
      target; the gripper needs about 30 steps to clamp.
    - To grasp, descend until the fingertips straddle the object. Fingertip pads
      are about 1 cm below the `eef_pos` frame, so for table-top objects (≈2 cm
      tall) target z ≈ 0.01; z ≈ 0.03 is too high.
    - Check `env.tries_left` before spending a trial.

  step_limit: 40
  cost_limit: 0.
environment:
  env:
    PAGER: cat
    MANPAGER: cat
    LESS: -R
model:
  observation_template: |
    {% if output.exception_info -%}
    <exception>{{output.exception_info}}</exception>
    {% endif -%}
    <returncode>{{output.returncode}}</returncode>
    {% if output.output | length < 10000 -%}
    <output>
    {{ output.output -}}
    </output>
    {%- else -%}
    <warning>
    The output of your last command was too long.
    Please try a different command that produces less output.
    </warning>
    <output_head>
    {{ output.output[:5000] }}
    </output_head>
    <elided_chars>
    {{ output.output | length - 10000 }} characters elided
    </elided_chars>
    <output_tail>
    {{ output.output[-5000:] }}
    </output_tail>
    {%- endif -%}
  format_error_template: |
    {% if finish_reason is defined and finish_reason in ["length", "tool_calls"] -%}
    Your previous response reached the output token limit (finish_reason={{ finish_reason }}) before you produced a complete action, so it was cut off. Respond more concisely and provide exactly one action in the required format.
    {%- else -%}
    Format error:

    <error>
    {{error}}
    </error>

    Please always provide EXACTLY ONE action in triple backticks, found {{actions|length}} actions.
    If you want to end the task, issue: `echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT`
    {%- endif %}
````

#### 渲染变量

| 变量 | 来源 | 用途 |
| :--- | :--- | :--- |
| `{{task}}` | `agent.run(task=...)` 的 `task` | 任务语言 |
| `{{workspace}}` | `RobotEnvironment.get_template_vars()` | 告诉 agent 当前目录 |
| `{{python}}` | `RobotEnvironment.get_template_vars()` | 解释器路径（模板里未直接用） |
| `{{suite}}` / `{{task_id}}` | `RobotEnvironment.get_template_vars()` | 可选 |
| `{{n_model_calls}}` / `{{model_cost}}` / `{{elapsed_seconds}}` | `DefaultAgent` 运行统计 | 可选 |
| `{{..., ...}}` 模型配置 | `OpenAIModel.get_template_vars()` | 可选 |

#### pilot4 实际渲染出的 system prompt

````text
You are a robot manipulation agent controlling a simulated Franka Panda arm
in LIBERO through a Python wrapper called `LiberoEnv`.

Your response must contain exactly ONE bash code block with ONE command
(or commands connected with && or ||).
Include a THOUGHT section before your command where you explain your reasoning.

<format_example>
Your reasoning and analysis here.

```mswea_bash_command
your_command_here
```
</format_example>

Failure to follow these rules will cause your response to be rejected.
````

#### pilot4 实际渲染出的 user prompt

```text
Task: pick up the cream cheese and place it in the basket

You are working inside the workspace `/home/czx/RoboLWM/runs/pilot4/libero_object_1/workspace` (this is your current
directory). The simulator Python is already on `PATH`, so run scripts with
`python episode.py`.

## Read first

1. `README.md` — task assignment and required outputs.
2. `docs/api.md` — the complete `LiberoEnv` contract: action format,
   observation schema, trial budget.
3. `example_episode.py` — a skeleton you can adapt.

## Workflow

1. Inspect the scene: object names and positions are in `obs["objects"]`.
2. Write `episode.py`: reset, read object poses, move the end effector
   through a pick-and-place sequence, check success.
3. Run `python episode.py` and read the printed JSON summary.
4. If it fails, inspect the error or the poses, fix `episode.py`, and run
   again. Each run consumes one trial from a limited budget.
5. When the task succeeds, submit with:

   `echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT`

## Rules

- Use only `LiberoEnv`; never import mujoco/robosuite directly.
- Never modify trial counters, success checks, or paths outside this
  workspace.
- The action is `[x, y, z, ax, ay, az, gripper]`, an absolute end-effector
  pose. `+1` closes the gripper, `-1` opens it; all-zero orientation keeps
  the current orientation. Hold each action for 20–30 steps to reach the
  target; the gripper needs about 30 steps to clamp.
- To grasp, descend until the fingertips straddle the object. Fingertip pads
  are about 1 cm below the `eef_pos` frame, so for table-top objects (≈2 cm
  tall) target z ≈ 0.01; z ≈ 0.03 is too high.
- Check `env.tries_left` before spending a trial.
```

---

### 5.8 `template/` 任务契约

runner 会把这三个文件复制到每个任务的 `workspace/`，并替换 `{{TASK}}`、`{{SUITE}}`、`{{TASK_ID}}`。

#### `template/README.md`

````markdown
# Task workspace

**Task:** {{TASK}}

- suite: `{{SUITE}}`
- task id: `{{TASK_ID}}`

You are inside a writable workspace. Your job is to write `episode.py`, a Python
script that completes the task above by driving the simulated Franka Panda arm
through the `LiberoEnv` wrapper described in `docs/api.md`.

## Required output

- `episode.py` — must run to completion with `python episode.py`

## Rules

- Only interact with the simulator through `LiberoEnv`. Never import mujoco or
  robosuite directly, and never read raw simulator internals.
- Do not modify trial counters, success checks, or anything outside this
  workspace.
- Every `env.reset()` consumes one trial. The trial budget is limited; check
  `env.tries_left` before spending one.
- Start from `example_episode.py`, but do not assume it solves your task.
- When you are done, submit with exactly:

  ```bash
  echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT
  ```
````

#### `template/docs/api.md`

````markdown
# `LiberoEnv` API

`LiberoEnv` is the only supported way to interact with the simulator.

```python
from libero_env import LiberoEnv
```

## Construction

```python
env = LiberoEnv()   # suite/task are fixed by the runner
```

## Methods

### `obs = env.reset()`

Starts a new trial and returns the initial observation.

- **Consumes one trial** from the budget.
- Raises `TrialCapExceeded` when the budget is exhausted.
- The scene is reset to the task's fixed initial state.

### `obs, reward, done, info = env.step(action)`

Applies one control step.

`action` is a list of **7 floats**:

```
[x, y, z, ax, ay, az, gripper]
```

| Field | Meaning |
| :--- | :--- |
| `x, y, z` | Absolute end-effector target position in the world frame (meters) |
| `ax, ay, az` | Absolute axis-angle orientation (radians). **All zeros means "keep the current orientation"** |
| `gripper` | `+1` close, `-1` open |

- The wrapper converts the absolute target into the controller's delta command
  for you (`output_max` is 5 cm / 0.5 rad per step).
- Hold the same action for **20–30 steps** to actually reach a target. The
  gripper needs about **30 steps** to fully clamp before you lift.
- To grasp an object, descend until the fingertips straddle it. The fingertip
  pads sit about **1 cm below** the `eef_pos` frame, so for table-top objects
  (≈2 cm tall) a grasp target of **z ≈ 0.01** usually works; `z ≈ 0.03` is too
  high and the fingers will close in the air.
- To place into a container, lift clear of the table (z ≈ 0.25), move above the
  container, lower to about `container_z + 0.10`, then open the gripper.

### `obs = env.get_obs()`

Returns the latest observation without stepping.

### `success = env.check_success()`

Returns the task's native success predicate.

### `env.tries_left` / `env.num_tries`

Remaining and consumed trial budget.

## Observation schema

`obs` is a dictionary:

```python
{
  "task": "pick up the cream cheese and place it in the basket",
  "suite": "libero_object",
  "task_id": 1,
  "try": 0,
  "tries_used": 1,
  "tries_left": 9,
  "eef_pos": [x, y, z],
  "eef_quat": [x, y, z, w],
  "gripper_qpos": [left, right],
  "objects": {
      "cream_cheese_1": {"pos": [x, y, z], "quat": [x, y, z, w]},
      "basket_1":       {"pos": [x, y, z], "quat": [x, y, z, w]},
      ...
  },
  "success": False,
}
```

Object names are the bodies present in the scene. The task language tells you
which object to pick and where to place it; inspect `objects` to find the
matching names.

## Minimal example

```python
from libero_env import LiberoEnv

env = LiberoEnv()
obs = env.reset()
print(obs["objects"])

# Move 5 cm above the current end-effector position, gripper open.
target = [obs["eef_pos"][0], obs["eef_pos"][1], obs["eef_pos"][2] + 0.05]
for _ in range(10):
    obs, reward, done, info = env.step(target + [0.0, 0.0, 0.0, -1.0])
    if done:
        break

print("success:", env.check_success(), "tries left:", env.tries_left)
```
````

#### `template/example_episode.py`

```python
"""Skeleton episode. Adapt it to the task; it is not the solution."""

from libero_env import LiberoEnv

env = LiberoEnv()
obs = env.reset()

print("tries left:", env.tries_left)
print("objects:")
for name, state in obs["objects"].items():
    print(f"  {name}: pos={state['pos']} quat={state['quat']}")

# Example motion helper: hold an absolute end-effector target for N steps.
def goto(pos, gripper=-1.0, steps=10):
    action = [pos[0], pos[1], pos[2], 0.0, 0.0, 0.0, gripper]
    for _ in range(steps):
        obs, reward, done, info = env.step(action)
        if done:
            break
    return obs

# Safe probe: lift the end effector 5 cm above its current position (gripper open).
start = obs["eef_pos"]
goto([start[0], start[1], start[2] + 0.05], gripper=-1.0, steps=10)

print("success:", env.check_success(), "tries left:", env.tries_left)
```

---

### 5.9 支撑模块

#### `src/minisweagent/__init__.py`

职责：

- 加载项目根目录的 `.env`（`find_dotenv(usecwd=True)`，从当前目录向上找）。
- 暴露 `runs_dir = Path.cwd() / "runs"`。
- 定义 `Model` / `Environment` / `Agent` 三个 Protocol。

关键代码：

```python
_env_path = find_dotenv(usecwd=True)
env_file = Path(_env_path) if _env_path else Path.cwd() / ".env"
dotenv.load_dotenv(dotenv_path=env_file, override=False)
runs_dir = Path.cwd() / "runs"


class Model(Protocol):
    config: Any
    def query(self, messages: list[dict[str, str]], **kwargs) -> dict: ...
    def format_message(self, **kwargs) -> dict: ...
    def format_observation_messages(self, message: dict, outputs: list[dict], template_vars: dict | None = None) -> list[dict]: ...
    def get_template_vars(self, **kwargs) -> dict[str, Any]: ...
    def serialize(self) -> dict: ...


class Environment(Protocol):
    config: Any
    def execute(self, action: dict, cwd: str = "") -> dict[str, Any]: ...
    def get_template_vars(self, **kwargs) -> dict[str, Any]: ...
    def serialize(self) -> dict: ...


class Agent(Protocol):
    config: Any
    def run(self, task: str, **kwargs) -> dict: ...
    def save(self, path: Path | None, *extra_dicts) -> dict: ...
```

#### `src/minisweagent/exceptions.py`

```python
class InterruptAgentFlow(Exception):
    def __init__(self, *messages: dict):
        self.messages = messages
        super().__init__()


class Submitted(InterruptAgentFlow):
    """agent 主动提交"""


class LimitsExceeded(InterruptAgentFlow):
    """轮数/成本超限"""


class TimeExceeded(LimitsExceeded):
    """墙钟超限"""


class FormatError(InterruptAgentFlow):
    """模型输出格式错误"""
```

#### `src/minisweagent/models/__init__.py`

进程级模型统计与可选全局限额：

```python
"""Global model statistics and limits."""

import os
import threading


class GlobalModelStats:
    """Global model statistics tracker with optional limits."""

    def __init__(self):
        self._cost = 0.0
        self._n_calls = 0
        self._lock = threading.Lock()
        self.cost_limit = float(os.getenv("MSWEA_GLOBAL_COST_LIMIT", "0"))
        self.call_limit = int(os.getenv("MSWEA_GLOBAL_CALL_LIMIT", "0"))

    def add(self, cost: float) -> None:
        """Add a model call with its cost, checking limits."""
        with self._lock:
            self._cost += cost
            self._n_calls += 1
        if 0 < self.cost_limit < self._cost or 0 < self.call_limit < self._n_calls + 1:
            raise RuntimeError(f"Global cost/call limit exceeded: ${self._cost:.4f} / {self._n_calls}")

    @property
    def cost(self) -> float:
        return self._cost

    @property
    def n_calls(self) -> int:
        return self._n_calls


GLOBAL_MODEL_STATS = GlobalModelStats()
```

#### `src/minisweagent/models/utils/retry.py`

```python
def retry(*, logger: logging.Logger, abort_exceptions: list[type[Exception]]) -> Retrying:
    return Retrying(
        reraise=True,
        stop=stop_after_attempt(int(os.getenv("MSWEA_MODEL_RETRY_STOP_AFTER_ATTEMPT", "3"))),
        wait=wait_exponential(multiplier=1, min=4, max=60),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        retry=retry_if_not_exception_type(tuple(abort_exceptions)),
    )
```

- 默认最多 3 次；指数退避 4s → 60s。
- 认证/权限/400/404/KeyboardInterrupt 不重试。
- OpenAI SDK 自身 `max_retries=0`，避免双层重试叠加。

#### `src/minisweagent/models/utils/openai_multimodal.py`

默认关闭（`multimodal_regex=""`）。开启时，把字符串里的特殊标签递归展开成 OpenAI 的 `text` / `image_url` 内容块。当前机器人任务只传文本，因此不触发。

```python
"""Utilities for handling multimodal content in OpenAI-style messages."""

import copy
import re
from typing import Any


def _expand_content_string(*, content: str, pattern: str) -> list[dict]:
    """Expand a content string, replacing multimodal tags with structured content."""
    matches = list(re.finditer(pattern, content))
    if not matches:
        return [{"type": "text", "text": content}]
    result = []
    last_end = 0
    for match in matches:
        text_before = content[last_end : match.start()]
        if text_before:
            result.append({"type": "text", "text": text_before})
        content_type = match.group(1).strip()
        extracted = match.group(2).strip()
        if content_type == "image_url":
            result.append({"type": "image_url", "image_url": {"url": extracted}})
        last_end = match.end()
    text_after = content[last_end:]
    if text_after:
        result.append({"type": "text", "text": text_after})
    return result


def expand_multimodal_content(content: Any, *, pattern: str) -> Any:
    """Recursively expand multimodal content in messages.

    Note: Returns a copy of content, original content is not modified.
    """
    if not pattern:
        return content
    content = copy.deepcopy(content)
    if isinstance(content, str):
        return _expand_content_string(content=content, pattern=pattern)
    if isinstance(content, list):
        return [expand_multimodal_content(item, pattern=pattern) for item in content]
    if isinstance(content, dict):
        if "content" not in content:
            return content
        content["content"] = expand_multimodal_content(content["content"], pattern=pattern)
        return content
    return str(content)
```

#### `src/minisweagent/utils/serialize.py`

```python
from typing import Any

UNSET = object()


def recursive_merge(*dictionaries: dict | None) -> dict:
    """Merge multiple dictionaries recursively.

    Later dictionaries take precedence over earlier ones.
    Nested dictionaries are merged recursively.
    UNSET values are skipped.
    """
    if not dictionaries:
        return {}
    result: dict[str, Any] = {}
    for d in dictionaries:
        if d is None:
            continue
        for key, value in d.items():
            if value is UNSET:
                continue
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = recursive_merge(result[key], value)
            elif isinstance(value, dict):
                result[key] = recursive_merge(value)
            else:
                result[key] = value
    return result
```

#### `src/minisweagent/utils/log.py`

```python
import logging


def _setup_root_logger() -> None:
    logger = logging.getLogger("minisweagent")
    logger.setLevel(logging.DEBUG)
    _handler = logging.StreamHandler()
    _formatter = logging.Formatter("%(name)s: %(levelname)s: %(message)s")
    _handler.setFormatter(_formatter)
    logger.addHandler(_handler)


_setup_root_logger()
logger = logging.getLogger("minisweagent")


__all__ = ["logger"]
```

#### `agents/__init__.py` 与 `environments/__init__.py`

两者都只剩一行 docstring（`"""Agent implementations."""` / `"""Environment implementations."""`），不导出任何工厂函数；调用方直接 import 具体类。

#### `src/minisweagent/py.typed`

空文件，标记包支持类型检查。

#### `src/minisweagent/config/__init__.py`

```python
builtin_config_dir = Path(__file__).parent


def load_default_config() -> dict:
    return yaml.safe_load((builtin_config_dir / "default.yaml").read_text(encoding="utf-8"))
```

---

### 5.10 `pyproject.toml` 与 `.env`

#### `pyproject.toml`

```toml
[build-system]
requires = ["setuptools"]
build-backend = "setuptools.build_meta"

[project]
name = "mini-swe-agent"
dynamic = ["version"]
description = "Minimal LLM agent harness for driving a robot environment"
requires-python = ">=3.10"
license = {file = "LICENSE.md"}

dependencies = [
    "pyyaml",
    "jinja2",
    "pydantic >= 2.0",
    "tenacity",
    "python-dotenv",
    "openai != 1.100.0,!=1.100.1",
]

[tool.setuptools]
include-package-data = true

[tool.setuptools.dynamic]
version = {attr = "minisweagent.__version__"}

[tool.setuptools.packages.find]
where = ["src"]
include = ["minisweagent*"]

[tool.setuptools.package-data]
minisweagent = ["config/**/*"]
```

#### `.env`

位于项目根目录，已被 `.gitignore` 忽略：

```bash
OPENAI_API_KEY=sk-...
OPENAI_BASE_URL=https://your-endpoint/v1
MODEL_NAME=gpt-6-luna
```

加载时机：`import minisweagent` 时，`find_dotenv(usecwd=True)` 从当前目录向上找到 `.env`，`dotenv.load_dotenv(..., override=False)` 写入 `os.environ`。shell 中已存在的变量优先。

## 6. 运行时目录与数据流

### 6.1 目录结构

```text
runs/<stage>/<suite>_<task_id>/
├── run.json                    # 任务级结果（runner 唯一真相）
├── prompt.txt                  # 冻结的任务语言
├── traj.json                   # 完整会话轨迹（每步覆盖写）
├── workspace/                  # agent 可写沙箱
│   ├── README.md               # 任务契约（模板替换后）
│   ├── docs/api.md             # LiberoEnv API
│   ├── example_episode.py      # 骨架示例
│   ├── episode.py              # agent 最终产物
│   └── ...                     # agent 自己的调试脚本
└── artifacts/                  # wrapper/runner 只写
    ├── state.json              # {"tries": N}
    ├── calls.jsonl             # 每条 shell 命令的审计日志
    ├── tries/
    │   └── 000/
    │       ├── video.mp4       # 本次 try 的录像
    │       ├── result.json     # success / steps / task / video
    │       └── actions.json    # 157 × 7 的动作序列
    └── video.mp4               # 成功那次的副本
```

### 6.2 每个文件的生产者与消费者

| 文件 | 生产者 | 消费者 | 说明 |
| :--- | :--- | :--- | :--- |
| `run.json` | `runner.py` | 人 / 批量脚本 | 状态、success、api_calls、tries、video、duration |
| `prompt.txt` | `runner.py` | 人 | 冻结任务语言，保证可复现 |
| `traj.json` | `DefaultAgent.save()` | 人 / 调试 | 每步 `finally` 覆盖写；包含 system/user/所有消息/token |
| `workspace/README.md` | `runner.prepare_workspace` | agent | 任务契约 |
| `workspace/docs/api.md` | `runner.prepare_workspace` | agent | API 文档 |
| `workspace/example_episode.py` | `runner.prepare_workspace` | agent | 骨架 |
| `workspace/episode.py` | agent | `LiberoEnv` | 最终策略脚本 |
| `artifacts/state.json` | `LiberoEnv._write_state` | `LiberoEnv` | try 计数；workspace 之外 |
| `artifacts/calls.jsonl` | `RobotEnvironment._log_call` | 人 / 审计 | append-only |
| `artifacts/tries/NNN/video.mp4` | `LiberoEnv.close` | 人 | 每次 try 自动录像 |
| `artifacts/tries/NNN/result.json` | `LiberoEnv.close` | `runner.all_try_results` | 原生 success |
| `artifacts/tries/NNN/actions.json` | `LiberoEnv.close` | 人 / 分析 | 实际下发的绝对位姿动作 |
| `artifacts/video.mp4` | `LiberoEnv.close` | 人 | 成功 try 的副本 |

### 6.3 一次任务的完整数据流

```text
1. 用户执行 runner.py --suite ... --task-id ...
        │
2. main() → task_meta() 子进程读取任务名/语言/任务数
        │
3. run_task() → 检查 run.json（幂等）
        │
4. prepare_workspace() 复制 template/ → workspace/
        │
5. 写初始 run.json（status=running）
        │
6. 构造 OpenAIModel / RobotEnvironment / DefaultAgent
        │
7. agent.run(task)
        │
8. 渲染 system_template / instance_template（Jinja）
        │
9. 循环：
        │   OpenAIModel.query()
        │      → /v1/chat/completions（tools=[bash]）
        │      → 解析 tool_calls → actions
        │   RobotEnvironment.execute(action)
        │      → subprocess(shell=True, cwd=workspace)
        │      → python episode.py
        │          → LiberoEnv.reset()  （try+1）
        │          → env.step() × N     （绝对位姿→delta→仿真）
        │          → check_success()    （原生判定）
        │          → close(): 写视频/result/actions
        │      → stdout/returncode → role=tool 观测
        │   DefaultAgent.save(traj.json)
        │
10. 模型看到 success 后执行提交哨兵
        │
11. RobotEnvironment._check_finished → Submitted
        │
12. agent.run 返回 exit_status=Submitted
        │
13. runner 汇总所有 tries → 写最终 run.json
```

---

## 7. 一次成功任务的完整实录

### 7.1 启动命令

```bash
cd /home/czx/RoboLWM
.venv/bin/python runner.py --stage pilot4 --suite libero_object --task-id 1 \
    --max-turns 40 --try-cap 10 --camera 256 --timeout 1200
```

### 7.2 任务元数据

`task_meta("libero_object", 1)` 通过 LIBERO 解释器返回：

```json
{
  "name": "pick_up_the_cream_cheese_and_place_it_in_the_basket",
  "language": "pick up the cream cheese and place it in the basket",
  "n_tasks": 10
}
```

写入 `prompt.txt`：

```text
pick up the cream cheese and place it in the basket
```

### 7.3 workspace 准备

复制并替换模板后，agent 看到：

```text
workspace/
├── README.md
├── docs/api.md
└── example_episode.py
```

### 7.4 初始 `run.json`

```json
{
  "status": "running",
  "stage": "pilot4",
  "suite": "libero_object",
  "task_id": 1,
  "task": "pick up the cream cheese and place it in the basket",
  "started": 1794456445.3908262
}
```

### 7.5 前两次模型调用

| 调用 | prompt tokens | completion tokens | 模型行为 | 执行结果 |
| :--- | ---: | ---: | :--- | :--- |
| 1 | 601 | 88 | `cat README.md && cat docs/api.md && cat example_episode.py` | returncode 0，agent 读到契约 |
| 2 | 2081 | 519 | 写 `episode.py` 并执行 `python episode.py` | 22.989s，仿真成功，stdout 打印 `{'success': True, ...}` |

第 2 次调用的完整命令（来自 `calls.jsonl`）：

```bash
cat > episode.py <<'PY'
from libero_env import LiberoEnv

env = LiberoEnv()
if env.tries_left <= 0:
    raise RuntimeError('no trials left')
obs = env.reset()
objs = obs['objects']
cheese = next((v for k,v in objs.items() if 'cream' in k.lower() or 'cheese' in k.lower()), None)
basket = next((v for k,v in objs.items() if 'basket' in k.lower()), None)
if cheese is None or basket is None:
    raise RuntimeError(f'could not identify objects: {list(objs)}')

def goto(p, g, n=25):
    last = None
    for _ in range(n):
        last = env.step([p[0], p[1], p[2], 0., 0., 0., g])[0]
        if env.check_success():
            break
    return last

cp = cheese['pos']; bp = basket['pos']
# Above the cheese, descend to fingertip-level grasp height.
goto([cp[0], cp[1], 0.12], -1., 25)
goto([cp[0], cp[1], 0.01], -1., 25)
goto([cp[0], cp[1], 0.01], 1., 35)
# Lift and transport while holding.
goto([cp[0], cp[1], 0.25], 1., 30)
goto([bp[0], bp[1], 0.25], 1., 30)
goto([bp[0], bp[1], 0.10], 1., 25)
goto([bp[0], bp[1], 0.10], -1., 35)
print({'success': env.check_success(), 'tries_left': env.tries_left, 'objects': obs['objects']})
PY
python episode.py
```

### 7.6 仿真内部发生了什么

`episode.py` 执行时：

1. `LiberoEnv()`：
   - 从 `ROBOLWM_SUITE=libero_object`、`ROBOLWM_TASK_ID=1` 读取任务；
   - 读取 `artifacts/state.json`（初始 `{"tries": 0}`）；
   - 注册 `atexit close`。
2. `env.reset()`：
   - 检查 try 预算（0 < 10）；
   - `state["tries"] = 1`，原子写回；
   - 创建 `OffScreenRenderEnv`，`env.reset()`；
   - `set_init_state(init_states[0])`，拿到固定初始场景；
   - `describe()` 返回物体位姿；
   - 捕获第一帧。
3. `goto` 阶段（每个动作保持若干步）：

| 阶段 | 目标 | 夹爪 | 步数上限 |
| :--- | :--- | :--- | ---: |
| 悬停 | `[cheese_x, cheese_y, 0.12]` | `-1` 打开 | 25 |
| 下降 | `[cheese_x, cheese_y, 0.01]` | `-1` 打开 | 25 |
| 夹紧 | 同上 | `+1` 夹紧 | 35 |
| 抬升 | `[cheese_x, cheese_y, 0.25]` | `+1` | 30 |
| 搬运 | `[basket_x, basket_y, 0.25]` | `+1` | 30 |
| 下降 | `[basket_x, basket_y, 0.10]` | `+1` | 25 |
| 松开 | 同上 | `-1` | 35 |

4. 每一步 `env.step(action)`：
   - 读当前 eef 位姿；
   - 位置误差 / `output_max[:3]`、旋转误差 / `output_max[3:]`；
   - clip 到 `[-1,1]`，拼接夹爪，调用底层 `env.step`；
   - 记录动作，捕获帧；
   - 调 `check_success()`；成功则 `done=True`，`goto` 提前 break。
5. 成功在“下降/松开”阶段触发，最终 **157 步**。
6. 脚本退出 → `atexit close()`：
   - `imageio.mimsave` 写 `tries/000/video.mp4`；
   - 写 `result.json`、`actions.json`；
   - 成功时复制到 `artifacts/video.mp4`；
   - 打印一行 JSON。

agent 看到的 tool 输出尾部：

```text
[Warning]: datasets path /home/czx/LWM/LIBERO/datasets does not exist!
{'success': True, 'tries_left': 9, 'objects': {'cream_cheese_1': {'pos': [0.0461, -0.1026, 0.0], 'quat': [0.0, 0.0, 1.0, 0.0]}, 'basket_1': {'pos': [-0.0088, 0.2673, 0.035], 'quat': [0.0, 0.0, 0.7071, 0.7071]}, 'alphabet_soup_1': {'pos': [-0.12, -0.24, 0.015], 'quat': [0.0, 0.7071, 0.7071, 0.0]}, 'milk_1': {'pos': [-0.148, 0.0646, 0.035], 'quat': [0.5, 0.5, 0.5, 0.5]}, 'tomato_sauce_1': {'pos': [0.1, -0.2, 0.035], 'quat': [0.0, 0.7071, 0.7071, 0.0]}, 'butter_1': {'pos': [0.1525, 0.0276, -0.005], 'quat': [0.0, 0.0, 1.0, 0.0]}, 'orange_juice_1': {'pos': [-0.2, -0.08, 0.035], 'quat': [0.5, 0.5, 0.5, 0.5]}}}
{"success": true, "try": 0, "steps": 157, "task": "pick up the cream cheese and place it in the basket", "suite": "libero_object", "task_id": 1, "video": "/home/czx/RoboLWM/runs/pilot4/libero_object_1/artifacts/tries/000/video.mp4"}
```

### 7.7 FormatError 插曲

第 3 次模型调用（3516 prompt / 43 completion）没有返回 tool call，只返回了文本。`parse_toolcall_actions` 抛 `FormatError`，agent 注入一条 user 消息：

```text
No tool calls found in the response. Every response MUST include at least one tool call.
```

第 4 次调用（3538 prompt / 53 completion）模型理解后执行：

```bash
echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT
```

`RobotEnvironment._check_finished` 检测到末行哨兵，抛 `Submitted`，agent 追加 `role=exit` 并退出。

### 7.8 最终 `run.json`

```json
{
  "stage": "pilot4",
  "suite": "libero_object",
  "task_id": 1,
  "task": "pick up the cream cheese and place it in the basket",
  "started": 1794456445.3908262,
  "status": "done",
  "success": true,
  "exit_status": "Submitted",
  "api_calls": 4,
  "cost": 0.0,
  "tries": 1,
  "steps_last_try": 157,
  "video": "/home/czx/RoboLWM/runs/pilot4/libero_object_1/artifacts/tries/000/video.mp4",
  "duration_s": 119.4
}
```

### 7.9 产物清单

| 文件 | 大小（约） | 内容 |
| :--- | ---: | :--- |
| `run.json` | 420B | 最终结果 |
| `prompt.txt` | 51B | 任务语言 |
| `traj.json` | 36KB | 9 条消息、4 次调用、token 统计 |
| `workspace/episode.py` | 1.1KB | agent 写的策略 |
| `artifacts/state.json` | 12B | `{"tries": 1}` |
| `artifacts/calls.jsonl` | 1.6KB | 3 条命令审计 |
| `artifacts/tries/000/result.json` | 248B | 原生 success |
| `artifacts/tries/000/actions.json` | 7.1KB | 157 × 7 动作 |
| `artifacts/tries/000/video.mp4` | 82KB | 本次 try 录像 |
| `artifacts/video.mp4` | 82KB | 成功副本 |

### 7.10 时序图

```text
用户            runner          DefaultAgent      OpenAIModel      RobotEnvironment     LiberoEnv
 │                │                  │                │                  │                  │
 │─ runner.py ───▶│                  │                │                  │                  │
 │                │─ task_meta ─────────────────────────────────────────────────────────────▶│
 │                │◀─ language ──────────────────────────────────────────────────────────────│
 │                │─ prepare workspace ──┐                                             │
 │                │◀─────────────────────┘                                             │
 │                │─ 写 run.json(running) │                                             │
 │                │─ 构造 ──────────▶│                │                  │                  │
 │                │                  │─ query ───────▶│                  │                  │
 │                │                  │                │─ HTTP tool call ▶│                  │
 │                │                  │◀─ action ──────│                  │                  │
 │                │                  │─ execute ────────────────────────▶│                  │
 │                │                  │                │                  │─ python episode ▶│
 │                │                  │                │                  │                  │─ reset(try+1)
 │                │                  │                │                  │                  │─ step ×157
 │                │                  │                │                  │                  │─ success
 │                │                  │                │                  │◀─ stdout ────────│
 │                │                  │◀─ observation ────────────────────│                  │
 │                │                  │─ save traj.json                   │                  │
 │                │                  │─ query（提交）──▶│                  │                  │
 │                │                  │◀─ submit action │                  │                  │
 │                │                  │─ execute(echo sentinel) ─────────▶│                  │
 │                │                  │◀─ Submitted ──────────────────────│                  │
 │                │◀─ exit_status ───│                  │                  │                  │
 │                │─ 写 run.json(done) │                  │                  │                  │
 │◀─ summary ────│                  │                │                  │                  │
```

---

## 8. 预算、安全与失败模式

### 8.1 四类预算

| 预算 | 参数 | 执行位置 | 超限结果 |
| :--- | :--- | :--- | :--- |
| LLM 轮数 | `--max-turns` | `DefaultAgent.query` | `LimitsExceeded` |
| 墙钟 | `--timeout` | `DefaultAgent.query` | `TimeExceeded` |
| 单命令 | `--timeout` | `RobotEnvironment.execute` | kill 进程组，`returncode=-1` |
| 仿真 try | `--try-cap` | `LiberoEnv.reset` | `TrialCapExceeded` |
| 成本 | `price_input/price_output` | `OpenAIModel._calculate_cost` | 本项目为 0，不触发 |

### 8.2 安全边界

- **路径守卫**：破坏性命令 + `..` / `artifacts` / `state.json` → `PermissionError`。
- **计数器外置**：`state.json` 在 `artifacts/`，不在 `workspace/`；agent 的 `rm` 被守卫拦截。
- **唯一仿真入口**：只允许 `from libero_env import LiberoEnv`；直接 import mujoco/robosuite 被 prompt 禁止。
- **成功判定**：只看 `env.check_success()`（LIBERO 原生谓词）；agent 自报不参与。
- **提交哨兵 + 外部成功门控**：首行或末行匹配才视为提交；但只有至少一次 try `success=true` 才真正接受。否则追加 `<submission_rejected>` 并继续；try 用尽仍未成功 → `TrialBudgetExhausted`。`cat README.md` 不会误触发。

### 8.3 失败状态

| `exit_status` | 含义 |
| :--- | :--- |
| `Submitted` | 正常提交（成功或 agent 认为完成） |
| `LimitsExceeded` | 轮数/成本超限 |
| `TimeExceeded` | 墙钟超限 |
| `RepeatedFormatError` | 连续 3 次格式错误 |
| `TrialBudgetExhausted` | try 预算耗尽且没有任何一次成功，提交被外部门控拒绝后终止 |
| 其他异常类名 | 未捕获异常，`traj.json` 里有 traceback |

### 8.4 已知限制（当前版本的刻意取舍）

- 没有 clean-room replay 验证；成功只信原生 reward（对应 3A 决策）。
- 没有 reward-hacking 扫描（R1–R5）。
- 没有上下文压缩 / stall detector / todo 工具；长任务可能触顶或走偏。
- 固定使用 `init_states[0]`，不采样多个初始状态。
- try 计数是单进程文件计数，不支持多进程并发抢同一个任务。
- `.env` 不参与版本控制；换机器需要重新配置。

---

## 9. 复现方式

### 9.1 环境

```bash
cd /home/czx/RoboLWM
uv venv --python 3.10 .venv
uv pip install --python .venv/bin/python -e .
```

仿真侧（已存在）：

```text
/home/czx/miniconda3/envs/libero/bin/python
```

并把 `sim/` 注册进 LIBERO 环境：

```bash
SITE=$(/home/czx/miniconda3/envs/libero/bin/python -c "import site; print(site.getsitepackages()[0])")
echo "/home/czx/RoboLWM/sim" > "$SITE/roboclwm.pth"
```

### 9.2 配置

项目根目录 `.env`：

```bash
OPENAI_API_KEY=sk-...
OPENAI_BASE_URL=https://your-endpoint/v1
MODEL_NAME=gpt-6-luna
```

### 9.3 运行

```bash
cd /home/czx/RoboLWM

# 单任务
.venv/bin/python runner.py --suite libero_object --task-id 1

# 批量（整个 suite）
.venv/bin/python runner.py --suite libero_object --all

# 幂等：已完成会跳过
.venv/bin/python runner.py --stage pilot4 --suite libero_object --task-id 1

# 强制重跑
.venv/bin/python runner.py --stage pilot4 --suite libero_object --task-id 1 --force
```

### 9.4 期望结果

成功时：

```text
{"stage": "...", "suite": "libero_object", "task_id": 1, ..., "status": "done", "success": true,
 "exit_status": "Submitted", "api_calls": 4, "tries": 1, "steps_last_try": 157, ...}
[summary] 1/1 success
```

产物在 `runs/<stage>/libero_object_1/`。

---

## 10. 与 MCC-FAEA 的对应关系

| MCC-FAEA 设计 | 本项目落点 |
| :--- | :--- |
| `runner.py` 任务编排 | `runner.py`：stage/task 目录、幂等、批量 |
| `results/<stage>/<task_id>/` | `runs/<stage>/<suite>_<task_id>/` |
| `workspace/` 契约（README/docs/example） | `template/` → `workspace/` |
| `sim/libero_env.py` 唯一仿真入口 | `sim/libero_env.py` |
| 绝对 EE 控制 | wrapper 内部转 OSC delta |
| trial counter 在沙箱外 | `artifacts/state.json` + `_guard` |
| 每次 try 录像 | `LiberoEnv._capture` + `close` |
| `meta.json` 自报 | 未采用；只看原生 `check_success()` |
| clean-room replay | 暂不做（3A） |
| 作弊扫描 R1–R5 | 暂不做 |
| `trace.jsonl` | `calls.jsonl` + `traj.json` |
| 上下文压缩 / stall detector | 暂不做，保持 agent 最简 |

---

## 附录 A：成功运行的关键数字

| 指标 | 值 |
| :--- | :--- |
| 任务 | `libero_object` task 1 |
| 语言 | pick up the cream cheese and place it in the basket |
| try | 0（第 1 次） |
| 仿真步数 | 157 |
| 模型调用 | 4 |
| prompt / completion tokens | 601/88、2081/519、3516/43、3538/53 |
| 总耗时 | 119.4s |
| 单次仿真执行耗时 | 22.989s |
| 最终结果 | success=true，exit_status=Submitted |
| 视频 | `artifacts/tries/000/video.mp4`（82KB） |

## 附录 B：成功轨迹的消息序列

| # | role | 内容/动作 | tokens |
| ---: | :--- | :--- | :--- |
| 0 | system | 机器人 system prompt | — |
| 1 | user | 渲染后的任务 prompt | — |
| 2 | assistant | `cat README.md && cat docs/api.md && cat example_episode.py` | 601/88 |
| 3 | tool | returncode 0，契约内容 | — |
| 4 | assistant | 写并运行 `episode.py` | 2081/519 |
| 5 | tool | returncode 0，`success=True` | — |
| 6 | user | `No tool calls found...`（FormatError） | 3516/43 |
| 7 | assistant | `echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT` | 3538/53 |
| 8 | exit | submission 为空，`exit_status=Submitted` | — |

## 附录 C：基线成绩

- LIBERO-Object：8 / 10 = 80.0%
- LIBERO-Long（`libero_10`）：3 / 10 = 30.0%
- 合计：11 / 20 = 55.0%

完整明细、评测口径与改进判定见 [baseline.md](baseline.md)。

---

*文档生成时间：2026-11-12。对应提交：`df51018`。*




