# Task workspace

**Task:** put both the cream cheese box and the butter in the basket

- suite: `libero_10`
- task id: `1`

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
- Submission is accepted only after a successful trial. If no trial has
  succeeded yet, the submission is ignored and you must keep iterating; when
  the trial budget is exhausted, the run ends as a failure.
- Start from `example_episode.py`, but do not assume it solves your task.
- When you are done, submit with exactly:

  ```bash
  echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT
  ```
