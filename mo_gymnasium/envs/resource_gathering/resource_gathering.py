from pathlib import Path
from typing import List, Optional

import gymnasium as gym
import numpy as np
import pygame
from gymnasium.spaces import Box, Discrete
from gymnasium.utils import EzPickle


class ResourceGathering(gym.Env, EzPickle):
    """
    ## Description
    From "Barrett, Leon & Narayanan, Srini. (2008). Learning all optimal policies with multiple criteria.
    Proceedings of the 25th International Conference on Machine Learning. 41-47. 10.1145/1390156.1390162."

    ## Observation Space
    The observation is discrete and consists of 4 elements:
    - 0: The x coordinate of the agent
    - 1: The y coordinate of the agent
    - 2: Flag indicating if the agent collected the gold
    - 3: Flag indicating if the agent collected the diamond

    ## Action Space
    The action is discrete and consists of 4 elements:
    - 0: Move up
    - 1: Move down
    - 2: Move left
    - 3: Move right

    ## Reward Space
    The reward is 3-dimensional:
    - 0: +1 if returned home with gold, else 0
    - 1: +1 if returned home with diamond, else 0
    - 2: -1 if killed by an enemy, else 0

    ## Starting State
    The agent starts at the home position with no gold or diamond.

    ## Episode Termination
    The episode terminates when the agent returns home, or when the agent is killed by an enemy.
    """

    metadata = {"render_modes": ["human", "rgb_array"], "render_fps": 4}

    def __init__(self, render_mode: Optional[str] = None):
        EzPickle.__init__(self, render_mode)

        self.render_mode = render_mode
        self.size = 5
        self.window_size = 512
        self.window = None
        self.clock = None

        # The map of resource gathering env
        self.map = np.array(
            [
                [" ", " ", "R1", "E2", " "],
                [" ", " ", "E1", " ", "R2"],
                [" ", " ", " ", " ", " "],
                [" ", " ", " ", " ", " "],
                [" ", " ", "H", " ", " "],
            ]
        )
        self.initial_pos = np.array([4, 2], dtype=np.int32)

        self.dir = {
            0: np.array([-1, 0], dtype=np.int32),  # up
            1: np.array([1, 0], dtype=np.int32),  # down
            2: np.array([0, -1], dtype=np.int32),  # left
            3: np.array([0, 1], dtype=np.int32),  # right
        }

        self.observation_space = Box(low=0.0, high=5.0, shape=(4,), dtype=np.int32)

        # action space specification: 1 dimension, 0 up, 1 down, 2 left, 3 right
        self.action_space = Discrete(4)
        # reward space:
        self.reward_space = Box(low=-1, high=1, shape=(3,), dtype=np.float32)

    def pareto_front(self, gamma: float) -> List[np.ndarray]:
        """This function returns the pareto front of the resource gathering environment.

        Args:
            gamma (float): The discount factor.

        Returns:
            The pareto front of the resource gathering environment.
        """

        def get_non_dominated(candidates: List[np.ndarray]) -> List[np.ndarray]:
            """This function returns the non-dominated subset of elements.

            Source: https://stackoverflow.com/questions/32791911/fast-calculation-of-pareto-front-in-python
            The code provided in all the stackoverflow answers is wrong. Important changes have been made in this function.

            Args:
                candidates: The input set of candidate vectors.

            Returns:
                The non-dominated subset of this input set.
            """
            candidates = np.array(candidates)  # Turn the input set into a numpy array.
            candidates = candidates[candidates.sum(1).argsort()[::-1]]  # Sort candidates by decreasing sum of coordinates.
            for i in range(candidates.shape[0]):  # Process each point in turn.
                n = candidates.shape[0]  # Check current size of the candidates.
                if i >= n:  # If we've eliminated everything up until this size we stop.
                    break
                non_dominated = np.ones(candidates.shape[0], dtype=bool)  # Initialize a boolean mask for undominated points.
                # find all points not dominated by i
                # since points are sorted by coordinate sum
                # i cannot dominate any points in 1,...,i-1
                non_dominated[i + 1 :] = np.any(candidates[i + 1 :] > candidates[i], axis=1)
                candidates = candidates[non_dominated]  # Grab only the non-dominated vectors using the generated bitmask.

            non_dominated = set()
            for candidate in candidates:
                non_dominated.add(tuple(candidate))  # Add the non dominated vectors to a set again.

            return [np.array(point) for point in non_dominated]

        # Go directly to the diamond (R2) in 10 steps
        ret1 = np.array([0.0, 0.0, 1.0]) * gamma**10

        # Go to both resources, through both Es
        ret2 = 0.9 * 0.9 * np.array([0.0, 1.0, 1.0]) * gamma**12  # Didn't die
        ret2 += 0.1 * np.array([-1.0, 0.0, 0.0]) * gamma**7  # Died to E2
        ret2 += 0.9 * 0.1 * np.array([-1.0, 0.0, 0.0]) * gamma**9  # Died to E1

        # Go to gold (R1), through E1 both ways
        ret3 = 0.9 * 0.9 * np.array([0.0, 1.0, 0.0]) * gamma**8  # Didn't die
        ret3 += 0.1 * np.array([-1.0, 0.0, 0.0]) * gamma**3  # Died to E1
        ret3 += 0.9 * 0.1 * np.array([-1.0, 0.0, 0.0]) * gamma**5  # Died to E1 in the way back

        # Go to both resources, dodging E1 but through E2
        ret4 = 0.9 * np.array([0.0, 1.0, 1.0]) * gamma**14  # Didn't die
        ret4 += 0.1 * np.array([-1.0, 0.0, 0.0]) * gamma**7  # Died to E2

        # Go to gold (R1), doging all E's in 12 steps
        ret5 = np.array([0.0, 1.0, 0.0]) * gamma**12  # Didn't die

        # Go to gold (R1), going through E1 only once
        ret6 = 0.9 * np.array([0.0, 1.0, 0.0]) * gamma**10  # Didn't die
        ret6 += 0.1 * np.array([-1.0, 0.0, 0.0]) * gamma**7  # Died to E1

        return get_non_dominated([ret1, ret2, ret3, ret4, ret5, ret6])

    def get_map_value(self, pos):
        return self.map[pos[0]][pos[1]]

    def is_valid_state(self, state):
        return state[0] >= 0 and state[0] < self.size and state[1] >= 0 and state[1] < self.size

    def render(self):
        # The size of a single grid square in pixels
        pix_square_size = self.window_size / self.size
        if self.window is None:
            self.gold_img = pygame.image.load(str(Path(__file__).parent.absolute()) + "/assets/gold.png")
            self.gold_img = pygame.transform.scale(self.gold_img, (pix_square_size, pix_square_size))
            self.gem_img = pygame.image.load(str(Path(__file__).parent.absolute()) + "/assets/gem.png")
            self.gem_img = pygame.transform.scale(self.gem_img, (pix_square_size, pix_square_size))
            self.enemy_img = pygame.image.load(str(Path(__file__).parent.absolute()) + "/assets/sword.png")
            self.enemy_img = pygame.transform.scale(self.enemy_img, (pix_square_size, pix_square_size))
            self.home_img = pygame.image.load(str(Path(__file__).parent.absolute()) + "/assets/home.png")
            self.home_img = pygame.transform.scale(self.home_img, (pix_square_size, pix_square_size))
            self.agent_img = pygame.image.load(str(Path(__file__).parent.absolute()) + "/assets/stickerman.png")
            self.agent_img = pygame.transform.scale(self.agent_img, (pix_square_size, pix_square_size))

        if self.window is None and self.render_mode is not None:
            pygame.init()
            if self.render_mode == "human":
                pygame.display.init()
                self.window = pygame.display.set_mode((self.window_size, self.window_size))
        if self.clock is None and self.render_mode == "human":
            self.clock = pygame.time.Clock()

        canvas = pygame.Surface((self.window_size, self.window_size))
        canvas.fill((255, 255, 255))

        canvas.blit(self.home_img, self.initial_pos[::-1] * pix_square_size)
        for i in range(self.map.shape[0]):
            for j in range(self.map.shape[1]):
                if self.map[i, j] == "R1" and not self.has_gold:
                    canvas.blit(self.gold_img, np.array([j, i]) * pix_square_size)
                elif self.map[i, j] == "R2" and not self.has_gem:
                    canvas.blit(self.gem_img, np.array([j, i]) * pix_square_size)
                elif self.map[i, j] == "E1" or self.map[i, j] == "E2":
                    canvas.blit(self.enemy_img, np.array([j, i]) * pix_square_size)

        canvas.blit(self.agent_img, self.current_pos[::-1] * pix_square_size)

        for x in range(self.size + 1):
            pygame.draw.line(
                canvas,
                0,
                (0, pix_square_size * x),
                (self.window_size, pix_square_size * x),
                width=2,
            )
            pygame.draw.line(
                canvas,
                0,
                (pix_square_size * x, 0),
                (pix_square_size * x, self.window_size),
                width=2,
            )

        if self.render_mode == "human":
            # The following line copies our drawings from `canvas` to the visible window
            self.window.blit(canvas, canvas.get_rect())
            pygame.event.pump()
            pygame.display.update()

            # We need to ensure that human-rendering occurs at the predefined framerate.
            # The following line will automatically add a delay to keep the framerate stable.
            self.clock.tick(self.metadata["render_fps"])
        elif self.render_mode == "rgb_array":  # rgb_array
            return np.transpose(np.array(pygame.surfarray.pixels3d(canvas)), axes=(1, 0, 2))

    def get_state(self):
        pos = self.current_pos.copy()
        state = np.concatenate((pos, np.array([self.has_gold, self.has_gem], dtype=np.int32)))
        return state

    def reset(self, seed=None, **kwargs):
        super().reset(seed=seed)

        self.current_pos = self.initial_pos
        self.has_gem = 0
        self.has_gold = 0
        self.step_count = 0.0
        state = self.get_state()
        if self.render_mode == "human":
            self.render()
        return state, {}

    def step(self, action):
        next_pos = self.current_pos + self.dir[action]

        if self.is_valid_state(next_pos):
            self.current_pos = next_pos

        vec_reward = np.zeros(3, dtype=np.float32)
        done = False

        cell = self.get_map_value(self.current_pos)
        if cell == "R1":
            self.has_gold = 1
        elif cell == "R2":
            self.has_gem = 1
        elif cell == "E1" or cell == "E2":
            if self.np_random.random() < 0.1:
                vec_reward[0] = -1.0
                done = True
        elif cell == "H":
            done = True
            vec_reward[1] = self.has_gold
            vec_reward[2] = self.has_gem

        state = self.get_state()
        if self.render_mode == "human":
            self.render()
        return state, vec_reward, done, False, {}

    def close(self):
        if self.window is not None:
            pygame.display.quit()
            pygame.quit()


if __name__ == "__main__":

    env = ResourceGathering()
    terminated = False
    env.reset()
    while True:
        env.render()
        obs, r, terminated, truncated, info = env.step(env.action_space.sample())
        print(obs, r, terminated)
        if terminated:
            env.reset()
