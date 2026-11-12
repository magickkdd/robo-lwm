from libero_env import LiberoEnv

env = LiberoEnv()
if env.tries_left <= 0:
    raise RuntimeError('no trials left')
obs = env.reset()

def goto(pos, grip, steps=25):
    global obs
    action = [float(pos[0]), float(pos[1]), float(pos[2]), 0.0, 0.0, 0.0, float(grip)]
    for _ in range(steps):
        obs, reward, done, info = env.step(action)
        if done:
            return

cream = obs['objects']['cream_cheese_1']['pos']
basket = obs['objects']['basket_1']['pos']
# Open and approach above the object, then descend to fingertip grasp height.
goto([cream[0], cream[1], 0.12], -1, 25)
goto([cream[0], cream[1], 0.01], -1, 25)
# Clamp fully while maintaining the grasp pose.
goto([cream[0], cream[1], 0.01], 1, 35)
# Lift and carry above the basket.
goto([cream[0], cream[1], 0.25], 1, 30)
goto([basket[0], basket[1], 0.25], 1, 30)
# Lower into the basket and release.
goto([basket[0], basket[1], 0.13], 1, 25)
goto([basket[0], basket[1], 0.13], -1, 35)
print({'success': bool(env.check_success()), 'tries_left': env.tries_left, 'obs_success': obs.get('success', False)})
