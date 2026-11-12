from libero_env import LiberoEnv


env = LiberoEnv()
if env.tries_left <= 0:
    raise RuntimeError('no trials left')
obs = env.reset()
objs = obs['objects']
print('objects:', objs)

def find(*terms):
    for n in objs:
        s = n.lower().replace('_', ' ')
        if all(t in s for t in terms):
            return n
    raise KeyError((terms, list(objs)))

basket_name = find('basket')
soup_name = find('soup')
try:
    cheese_name = find('cream', 'cheese')
except KeyError:
    cheese_name = find('cheese')

basket = objs[basket_name]['pos']
# Place over the basket center, with a modest clearance above its rim.
place_xy = [basket[0], basket[1]]

def goto(pos, grip, steps=25):
    last = None
    for _ in range(steps):
        last = env.step([float(pos[0]), float(pos[1]), float(pos[2]), 0.0, 0.0, 0.0, float(grip)])
        if last[2]:
            break
    return last

def move_object(name):
    p = objs[name]['pos']
    # Approach, descend to fingertip grasp height, close and allow clamp time.
    goto([p[0], p[1], p[2] + 0.18], -1.0, 25)
    goto([p[0], p[1], p[2]], -1.0, 25)
    goto([p[0], p[1], p[2]], 1.0, 32)
    # Lift while closed, translate, then lower into basket and release.
    goto([p[0], p[1], p[2] + 0.18], 1.0, 30)
    goto([place_xy[0], place_xy[1], 0.65], 1.0, 30)
    goto([place_xy[0], place_xy[1], 0.50], 1.0, 25)
    goto([place_xy[0], place_xy[1], 0.50], -1.0, 32)
    goto([place_xy[0], place_xy[1], 0.65], -1.0, 25)

move_object(soup_name)
# Refresh positions after the first placement, retaining the fixed basket target.
obs = env.get_obs()
objs = obs['objects']
move_object(cheese_name)
print({'success': env.check_success(), 'tries_left': env.tries_left, 'objects': env.get_obs()['objects']})
