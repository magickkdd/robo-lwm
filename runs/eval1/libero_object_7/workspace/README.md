# Task workspace

**Task:** pick up the milk and place it in the basket

- suite: `libero_object`
- task id: `7`

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
