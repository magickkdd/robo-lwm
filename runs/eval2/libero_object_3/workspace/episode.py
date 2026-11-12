from libero_env import LiberoEnv

env = LiberoEnv()
if env.tries_left <= 0:
    raise RuntimeError('No trials remaining')
obs = env.reset()
print('tries left:', env.tries_left)
for name, state in obs['objects'].items():
    print(name, state['pos'])

def goto(pos, grip, steps=25):
    global obs
    action = [float(pos[0]), float(pos[1]), float(pos[2]), 0.0, 0.0, 0.0, float(grip)]
    for _ in range(steps):
        obs, reward, done, info = env.step(action)
        if done:
            break

objects = obs['objects']
sauce_name = next((n for n in objects if 'bbq' in n.lower() or 'sauce' in n.lower()), None)
basket_name = next((n for n in objects if 'basket' in n.lower()), None)
if sauce_name is None or basket_name is None:
    raise RuntimeError(f'Could not identify targets: {list(objects)}')
sauce = objects[sauce_name]['pos']
basket = objects[basket_name]['pos']
# Approach, grasp at tabletop level, and lift.
goto([sauce[0], sauce[1], sauce[2] + 0.14], -1, 30)
goto([sauce[0], sauce[1], 0.01], -1, 30)
goto([sauce[0], sauce[1], 0.01], 1, 35)
goto([sauce[0], sauce[1], 0.25], 1, 30)
# Carry above the basket and release into it.
goto([basket[0], basket[1], 0.25], 1, 35)
goto([basket[0], basket[1], basket[2] + 0.10], 1, 25)
goto([basket[0], basket[1], basket[2] + 0.10], -1, 35)
for _ in range(5):
    obs, reward, done, info = env.step([basket[0], basket[1], basket[2] + 0.10, 0.0, 0.0, 0.0, -1.0])
print({'success': env.check_success(), 'tries_left': env.tries_left, 'objects': obs['objects']})
