from libero_env import LiberoEnv

env = LiberoEnv()
if env.tries_left <= 0:
    raise RuntimeError('no trials left')
obs = env.reset()

def goto(x, y, z, grip, steps):
    global obs
    action = [x, y, z, 0.0, 0.0, 0.0, grip]
    for _ in range(steps):
        obs, reward, done, info = env.step(action)
        if done:
            break
    return obs

cream = obs['objects']['cream_cheese_1']['pos']
basket = obs['objects']['basket_1']['pos']
# Open and approach above the object.
goto(cream[0], cream[1], 0.12, -1.0, 25)
# Descend to fingertip/object contact height and close fully.
goto(cream[0], cream[1], 0.02, -1.0, 25)
goto(cream[0], cream[1], 0.02, 1.0, 35)
# Lift, carry above the basket, and lower into its interior.
goto(cream[0], cream[1], 0.25, 1.0, 30)
goto(basket[0], basket[1], 0.25, 1.0, 30)
goto(basket[0], basket[1], 0.135, 1.0, 25)
# Release in the basket.
goto(basket[0], basket[1], 0.135, -1.0, 35)
print({'success': env.check_success(), 'tries_left': env.tries_left, 'obs_success': obs.get('success')})
