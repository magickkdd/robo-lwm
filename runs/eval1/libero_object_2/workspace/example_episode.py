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
