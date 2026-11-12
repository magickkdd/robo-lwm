from libero_env import LiberoEnv

env = LiberoEnv()
if env.tries_left <= 0:
    raise RuntimeError('no trials left')
obs = env.reset()
objects = obs['objects']

def find_obj(words):
    for n, s in objects.items():
        low = n.lower()
        if all(w in low for w in words):
            return s['pos']
    for n, s in objects.items():
        if any(w in n.lower() for w in words):
            return s['pos']
    raise KeyError((words, list(objects)))

pud = find_obj(['pudding'])
basket = find_obj(['basket'])

def move(pos, grip, steps=25):
    global obs
    a = [float(pos[0]), float(pos[1]), float(pos[2]), 0.0, 0.0, 0.0, float(grip)]
    for _ in range(steps):
        obs, _, done, _ = env.step(a)
        if done:
            break

# Open, approach above pudding, descend so pads straddle tabletop object.
move([pud[0], pud[1], 0.18], -1, 25)
move([pud[0], pud[1], 0.01], -1, 25)
move([pud[0], pud[1], 0.01], 1, 35)
# Lift, traverse above basket, lower into basket, release.
move([pud[0], pud[1], 0.25], 1, 30)
move([basket[0], basket[1], 0.25], 1, 30)
move([basket[0], basket[1], 0.12], 1, 25)
move([basket[0], basket[1], 0.12], -1, 35)
print({'success': env.check_success(), 'obs_success': obs.get('success'), 'tries_left': env.tries_left, 'objects': obs['objects']})
