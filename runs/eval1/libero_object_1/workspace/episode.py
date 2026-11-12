import json
from libero_env import LiberoEnv

env = LiberoEnv()
if env.tries_left <= 0:
    raise RuntimeError('no trials left')
obs = env.reset()
objects = obs['objects']

def find_obj(keys):
    for name, state in objects.items():
        low = name.lower()
        if any(k in low for k in keys):
            return state['pos']
    raise KeyError((keys, list(objects)))

cheese = find_obj(['cream_cheese', 'cream cheese', 'cheese'])
basket = find_obj(['basket'])

def goto(pos, grip, steps=25):
    global obs
    action = [float(pos[0]), float(pos[1]), float(pos[2]), 0.0, 0.0, 0.0, float(grip)]
    for _ in range(steps):
        obs, _, done, _ = env.step(action)
        if done:
            return

# Open, approach from above, then descend to fingertip-level grasp height.
goto([cheese[0], cheese[1], max(cheese[2] + 0.14, 0.16)], -1, 30)
goto([cheese[0], cheese[1], 0.012], -1, 30)
goto([cheese[0], cheese[1], 0.012], 1, 35)
# Lift and transport above the basket.
goto([cheese[0], cheese[1], 0.25], 1, 30)
goto([basket[0], basket[1], 0.25], 1, 35)
# Lower into the basket and release.
goto([basket[0], basket[1], max(basket[2] + 0.10, 0.12)], 1, 30)
goto([basket[0], basket[1], max(basket[2] + 0.10, 0.12)], -1, 35)
print(json.dumps({'success': bool(env.check_success()), 'tries_left': env.tries_left, 'obs': obs}, default=list))
