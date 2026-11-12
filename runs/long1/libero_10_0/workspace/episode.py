from libero_env import LiberoEnv

env = LiberoEnv()
obs = env.reset()
objs = obs['objects']

def find(*terms):
    for n in objs:
        s = n.lower()
        if all(t in s for t in terms):
            return n
    return None

soup = find('alphabet', 'soup') or find('soup')
sauce = find('tomato', 'sauce') or find('sauce')
basket = find('basket')
if not (soup and sauce and basket):
    raise RuntimeError(f'Could not identify objects: {list(objs)}')

def move(p, grip, steps=25):
    global obs
    a = [float(p[0]), float(p[1]), float(p[2]), 0., 0., 0., float(grip)]
    for _ in range(steps):
        obs, _, done, _ = env.step(a)
        if done:
            return

def place(name):
    p = objs[name]['pos']
    b = objs[basket]['pos']
    move([p[0], p[1], p[2] + 0.10], -1, 25)
    move([p[0], p[1], p[2] - 0.01], -1, 25)
    move([p[0], p[1], p[2] - 0.01], 1, 45)
    move([p[0], p[1], p[2] + 0.20], 1, 25)
    move([b[0], b[1], b[2] + 0.20], 1, 30)
    move([b[0], b[1], b[2] + 0.06], 1, 25)
    move([b[0], b[1], b[2] + 0.06], -1, 30)
    move([b[0], b[1], b[2] + 0.20], -1, 20)

place(soup)
# refresh object references/poses after first placement
obs = env.get_obs()
objs = obs['objects']
place(sauce)
print({'success': env.check_success(), 'tries_left': env.tries_left, 'objects': objs})
