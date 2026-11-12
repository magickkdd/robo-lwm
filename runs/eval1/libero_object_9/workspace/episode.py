from libero_env import LiberoEnv

env = LiberoEnv()
if env.tries_left <= 0:
    raise RuntimeError('no trials left')
obs = env.reset()
juice = obs['objects']['orange_juice_1']['pos']
basket = obs['objects']['basket_1']['pos']

def goto(x, y, z, grip, n):
    global obs
    for _ in range(n):
        obs, _, done, _ = env.step([x, y, z, 0.0, 0.0, 0.0, grip])
        if done:
            break

# Approach with the gripper open, then descend to straddle the juice.
goto(juice[0], juice[1], 0.16, -1.0, 30)
goto(juice[0], juice[1], 0.01, -1.0, 30)
# Clamp fully before lifting.
goto(juice[0], juice[1], 0.01, 1.0, 35)
goto(juice[0], juice[1], 0.25, 1.0, 35)
# Move over the basket while keeping the object high and closed.
goto(basket[0], basket[1], 0.25, 1.0, 35)
goto(basket[0], basket[1], 0.13, 1.0, 30)
# Release into the basket.
goto(basket[0], basket[1], 0.13, -1.0, 35)
print({'success': env.check_success(), 'tries_left': env.tries_left, 'obs_success': obs.get('success')})
