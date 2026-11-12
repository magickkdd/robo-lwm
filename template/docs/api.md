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

### Submission

`echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT` is accepted **only after at least
one trial has succeeded**. If no trial has succeeded, the submission is ignored
and the run keeps going. When the trial budget is exhausted without success,
the run ends as a failure.

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
