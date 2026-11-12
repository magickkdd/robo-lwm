import json
from libero_env import LiberoEnv

env = LiberoEnv()
if env.tries_left <= 0:
    raise RuntimeError('no trials left')
obs = env.reset()
objects = obs['objects']
def find(keys, avoid=()):
    for n in objects:
        low = n.lower()
        if any(k in low for k in keys) and not any(a in low for a in avoid):
            return n
    raise KeyError((keys, list(objects)))
milk_name = find(('milk',), ('basket',))
basket_name = find(('basket',))
milk = objects[milk_name]['pos']
basket = objects[basket_name]['pos']

def goto(p, g, steps=25):
    global obs
    for _ in range(steps):
        obs, _, done, _ = env.step([p[0], p[1], p[2], 0., 0., 0., g])
        if done:
            break

goto([milk[0], milk[1], max(milk[2] + .12, .18)], -1, 25)
goto([milk[0], milk[1], .01], -1, 30)
goto([milk[0], milk[1], .01], 1, 35)
goto([milk[0], milk[1], .25], 1, 30)
goto([basket[0], basket[1], .25], 1, 30)
goto([basket[0], basket[1], basket[2] + .10], 1, 25)
goto([basket[0], basket[1], basket[2] + .10], -1, 35)
print(json.dumps({'success': bool(env.check_success()), 'tries_left': env.tries_left, 'objects': obs.get('objects', {})}))
