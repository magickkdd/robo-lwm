from libero_env import LiberoEnv


def main():
    env = LiberoEnv()
    if env.tries_left <= 0:
        raise RuntimeError('no trials left')
    obs = env.reset()
    print('objects:', obs['objects'])

    names = list(obs['objects'])
    sauce_name = next((n for n in names if 'tomato' in n.lower() or 'sauce' in n.lower()), None)
    basket_name = next((n for n in names if 'basket' in n.lower()), None)
    if sauce_name is None or basket_name is None:
        raise RuntimeError(f'could not identify objects: {names}')
    sauce = obs['objects'][sauce_name]['pos']
    basket = obs['objects'][basket_name]['pos']
    print('sauce:', sauce_name, sauce, 'basket:', basket_name, basket)

    def goto(pos, grip, steps):
        nonlocal obs
        action = [float(pos[0]), float(pos[1]), float(pos[2]), 0.0, 0.0, 0.0, float(grip)]
        for _ in range(steps):
            obs, reward, done, info = env.step(action)
            if done:
                break

    # Move above the sauce, descend to fingertip grasp height, close, and lift.
    goto([sauce[0], sauce[1], 0.22], -1, 30)
    goto([sauce[0], sauce[1], 0.012], -1, 30)
    goto([sauce[0], sauce[1], 0.012], 1, 35)
    goto([sauce[0], sauce[1], 0.25], 1, 30)
    # Move above the basket, lower into its interior, and release.
    goto([basket[0], basket[1], 0.25], 1, 30)
    goto([basket[0], basket[1], basket[2] + 0.10], 1, 30)
    goto([basket[0], basket[1], basket[2] + 0.10], -1, 35)
    print('final_obs:', env.get_obs())
    print('success:', env.check_success(), 'tries left:', env.tries_left)


if __name__ == '__main__':
    main()
