from libero_env import LiberoEnv

env = LiberoEnv()
if env.tries_left <= 0:
    raise RuntimeError('No trials remain')
obs = env.reset()

# Absolute-position motions; give the controller time to settle each target.
def goto(x, y, z, grip, steps):
    global obs
    action = [float(x), float(y), float(z), 0.0, 0.0, 0.0, float(grip)]
    for _ in range(steps):
        obs, reward, done, info = env.step(action)
        if done:
            break
    return obs

objects = obs['objects']
dressing = objects['salad_dressing_1']['pos']
basket = objects['basket_1']['pos']
# Stage above the target, then descend to straddle the tabletop bottle.
goto(dressing[0], dressing[1], 0.20, -1, 25)
goto(dressing[0], dressing[1], 0.01, -1, 25)
goto(dressing[0], dressing[1], 0.01, 1, 32)
# Lift before traversing to the basket.
goto(dressing[0], dressing[1], 0.25, 1, 25)
goto(basket[0], basket[1], 0.32, 1, 30)
# Descend into the basket footprint without striking its near wall.
goto(basket[0], basket[1], 0.085, 1, 30)
goto(basket[0], basket[1], 0.085, -1, 32)
goto(basket[0], basket[1], 0.25, -1, 20)
print({'success': env.check_success(), 'tries_left': env.tries_left, 'eef_pos': obs['eef_pos'], 'objects': obs['objects']})
