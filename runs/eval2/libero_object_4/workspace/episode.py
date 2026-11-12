from libero_env import LiberoEnv

env = LiberoEnv()
if env.tries_left <= 0:
    raise RuntimeError('No trials left')
obs = env.reset()
ketchup = obs['objects']['ketchup_1']['pos']
basket = obs['objects']['basket_1']['pos']
print('tries left:', env.tries_left, 'ketchup:', ketchup, 'basket:', basket)

def move(pos, grip, steps):
    global obs
    action = [float(pos[0]), float(pos[1]), float(pos[2]), 0., 0., 0., float(grip)]
    for _ in range(steps):
        obs, reward, done, info = env.step(action)
        if done:
            break

move([ketchup[0], ketchup[1], .20], -1, 40)
move([ketchup[0], ketchup[1], .01], -1, 35)
move([ketchup[0], ketchup[1], .01], 1, 35)
move([ketchup[0], ketchup[1], .26], 1, 40)
# Hold ample time for the full cross-table transit.
move([basket[0], basket[1], .26], 1, 90)
move([basket[0], basket[1], .12], 1, 35)
move([basket[0], basket[1], .12], -1, 35)
move([basket[0], basket[1], .26], -1, 25)
print('final objects:', {k: v['pos'] for k, v in obs['objects'].items()})
print('success:', env.check_success(), 'tries left:', env.tries_left)
