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


def initial_obs(suite: str, task_id: int) -> dict:
    """Capture the initial observation without consuming a trial."""
    code = """
import json, os
os.environ.setdefault("MUJOCO_GL", "osmesa")
os.environ.setdefault("PYOPENGL_PLATFORM", "osmesa")
from libero_env import LiberoEnv
env = LiberoEnv(preview=True)
obs = env.reset()
print("OBS:" + json.dumps(obs))
env.close()
"""
    env = dict(os.environ)
    env["LIBERO_CONFIG_PATH"] = LIBERO_CONFIG_PATH
    env["MUJOCO_GL"] = "osmesa"
    env["PYOPENGL_PLATFORM"] = "osmesa"
    env["ROBOLWM_SUITE"] = suite
    env["ROBOLWM_TASK_ID"] = str(task_id)
    env["PYTHONPATH"] = os.pathsep.join(
        p for p in (str(SIM), env.get("PYTHONPATH", "")) if p
    )
    try:
        out = subprocess.check_output(
            [LIBERO_PYTHON, "-c", code],
            env=env,
            text=True,
            stderr=subprocess.DEVNULL,
            cwd=str(ROOT),
            timeout=180,
        )
    except (subprocess.SubprocessError, OSError) as e:
        print(f"[warn] could not capture initial observation: {e}")
        return {}
    for line in out.splitlines():
        if line.startswith("OBS:"):
            try:
                return json.loads(line[4:])
            except json.JSONDecodeError:
                break
    print("[warn] initial observation was not present in preview output")
    return {}


def count_lwm_reviews(artifacts: Path) -> int:
    path = artifacts / "lwm" / "reviews.jsonl"
    if not path.is_file():
        return 0
    return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())


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
    obs = initial_obs(suite, task_id)
    if obs:
        write_json(artifacts / "init_obs.json", obs)
        write_json(workspace / "obs.json", obs)
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
            "lwm": args.lwm,
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
        task_language=meta["language"],
        lwm_enabled=args.lwm,
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
                "lwm_reviews": count_lwm_reviews(artifacts),
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
    p.add_argument("--lwm", action="store_true", help="let the agent query the language world model")
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
