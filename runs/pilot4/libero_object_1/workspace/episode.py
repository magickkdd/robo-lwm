from libero_env import LiberoEnv

env = LiberoEnv()
if env.tries_left <= 0:
    raise RuntimeError('no trials left')
obs = env.reset()
objs = obs['objects']
cheese = next((v for k,v in objs.items() if 'cream' in k.lower() or 'cheese' in k.lower()), None)
basket = next((v for k,v in objs.items() if 'basket' in k.lower()), None)
if cheese is None or basket is None:
    raise RuntimeError(f'could not identify objects: {list(objs)}')

def goto(p, g, n=25):
    last = None
    for _ in range(n):
        last = env.step([p[0], p[1], p[2], 0., 0., 0., g])[0]
        if env.check_success():
            break
    return last

cp = cheese['pos']; bp = basket['pos']
# Above the cheese, descend to fingertip-level grasp height.
goto([cp[0], cp[1], 0.12], -1., 25)
goto([cp[0], cp[1], 0.01], -1., 25)
goto([cp[0], cp[1], 0.01], 1., 35)
# Lift and transport while holding.
goto([cp[0], cp[1], 0.25], 1., 30)
goto([bp[0], bp[1], 0.25], 1., 30)
goto([bp[0], bp[1], 0.10], 1., 25)
goto([bp[0], bp[1], 0.10], -1., 35)
print({'success': env.check_success(), 'tries_left': env.tries_left, 'objects': obs['objects']})
