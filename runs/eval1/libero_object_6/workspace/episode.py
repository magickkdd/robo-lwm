import json
from libero_env import LiberoEnv

env = LiberoEnv()
if env.tries_left <= 0:
    raise RuntimeError('no trials left')
obs = env.reset()

objects = obs['objects']
def find_object(words):
    for name in objects:
        low = name.lower()
        if all(w in low for w in words):
            return name
    for name in objects:
        if any(w in name.lower() for w in words):
            return name
    raise KeyError((words, list(objects)))

butter_name = find_object(['butter'])
basket_name = find_object(['basket'])
butter = objects[butter_name]['pos']
basket = objects[basket_name]['pos']

def goto(pos, grip, steps=30):
    global obs
    action = [float(pos[0]), float(pos[1]), float(pos[2]), 0.0, 0.0, 0.0, float(grip)]
    for _ in range(steps):
        obs, reward, done, info = env.step(action)
        if done:
            break
    return obs

# Approach above the butter, then descend to fingertip-level grasp height.
goto([butter[0], butter[1], 0.14], -1, 30)
goto([butter[0], butter[1], 0.012], -1, 30)
# Close and hold long enough for the fingers to clamp.
goto([butter[0], butter[1], 0.012], 1, 35)
# Lift clear of the table and carry over the basket.
goto([butter[0], butter[1], 0.25], 1, 30)
goto([basket[0], basket[1], 0.25], 1, 30)
# Lower into the basket and release.
goto([basket[0], basket[1], 0.12], 1, 30)
goto([basket[0], basket[1], 0.12], -1, 35)
# Allow settling while open.
goto([basket[0], basket[1], 0.18], -1, 20)

result = {
    'success': bool(env.check_success()),
    'tries_left': env.tries_left,
    'butter_name': butter_name,
    'basket_name': basket_name,
    'objects': obs['objects'],
}
print(json.dumps(result, default=lambda x: x.tolist() if hasattr(x, 'tolist') else x))
