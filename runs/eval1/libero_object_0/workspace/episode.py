from libero_env import LiberoEnv

env = LiberoEnv()
if env.tries_left <= 0:
    raise RuntimeError('no trials left')
obs = env.reset()
objs = obs['objects']
print('objects:', objs)

def find(keys):
    for n in objs:
        s = n.lower()
        if all(k in s for k in keys):
            return n
    return None
soup_name = find(['soup']) or find(['alphabet'])
basket_name = find(['basket'])
if soup_name is None or basket_name is None:
    raise RuntimeError(f'could not identify soup/basket: {list(objs)}')
soup = objs[soup_name]['pos']
basket = objs[basket_name]['pos']

def goto(p, grip, steps=30):
    global obs
    a = [float(p[0]), float(p[1]), float(p[2]), 0.0, 0.0, 0.0, float(grip)]
    for _ in range(steps):
        obs, _, done, _ = env.step(a)
        if done:
            break

# Approach above the soup, descend to fingertip grasp height, clamp, and lift.
goto([soup[0], soup[1], 0.18], -1, 30)
goto([soup[0], soup[1], 0.01], -1, 30)
goto([soup[0], soup[1], 0.01], 1, 35)
goto([soup[0], soup[1], 0.25], 1, 30)
# Move over basket, lower into it, then release.
goto([basket[0], basket[1], 0.25], 1, 35)
goto([basket[0], basket[1], basket[2] + 0.10], 1, 30)
goto([basket[0], basket[1], basket[2] + 0.10], -1, 35)
goto([basket[0], basket[1], 0.25], -1, 20)
print({'success': env.check_success(), 'tries_left': env.tries_left, 'eef_pos': obs.get('eef_pos'), 'objects': obs.get('objects')})
