import logging
from dataclasses import dataclass, field
from typing import Any, Optional

import numpy as np

logger = logging.getLogger(__name__)

try:
    import gymnasium as gym
    from gymnasium import Env, spaces

    _GYM_AVAILABLE = True
    _GYM_API_VERSION = 1
except ImportError:
    try:
        import gym
        from gym import Env, spaces

        _GYM_AVAILABLE = True
        _GYM_API_VERSION = 0
    except ImportError:
        _GYM_AVAILABLE = False
        _GYM_API_VERSION = -1
        logger.warning("Neither gymnasium nor gym installed — RLTrading will raise on use")

try:
    from stable_baselines3 import PPO

    _SB3_AVAILABLE = True
except ImportError:
    _SB3_AVAILABLE = False
    logger.info("stable-baselines3 not installed — falling back to simple policy gradient")


@dataclass
class TradingStats:
    total_return: float = 0.0
    sharpe_ratio: float = 0.0
    max_drawdown: float = 0.0
    win_rate: float = 0.0
    n_trades: int = 0
    avg_trade_return: float = 0.0


if _GYM_AVAILABLE:

    class TradingEnvironment(Env):
        metadata = {"render.modes": ["human"]}

        def __init__(
            self,
            prices: np.ndarray,
            features: Optional[np.ndarray] = None,
            initial_balance: float = 1e6,
            commission: float = 0.001,
            lookback: int = 30,
            drawdown_penalty: float = 2.0,
        ) -> None:
            super().__init__()

            self._prices = prices.astype(float)
            self._features = features if features is not None else np.zeros((len(prices), 1))
            self._initial_balance = initial_balance
            self._commission = commission
            self._lookback = lookback
            self._drawdown_penalty = drawdown_penalty

            n_features = self._features.shape[1] if self._features.ndim > 1 else 1
            obs_dim = lookback + n_features * lookback + 3
            self.observation_space = spaces.Box(
                low=-np.inf, high=np.inf, shape=(obs_dim,), dtype=np.float32
            )
            self.action_space = spaces.Discrete(3)

            self._current_step = 0
            self._balance = initial_balance
            self._position = 0
            self._entry_price = 0.0
            self._peak_value = initial_balance
            self._total_value = initial_balance
            self._prev_total_value = initial_balance

        def reset(self, **kwargs: Any) -> Any:
            self._current_step = self._lookback
            self._balance = self._initial_balance
            self._position = 0
            self._entry_price = 0.0
            self._peak_value = self._initial_balance
            self._total_value = self._initial_balance
            self._prev_total_value = self._initial_balance
            obs = self._get_observation()
            if _GYM_API_VERSION >= 1:
                return obs, {}
            return obs

        def step(self, action: int) -> tuple:
            if self._current_step >= len(self._prices) - 1:
                obs = self._get_observation()
                if _GYM_API_VERSION >= 1:
                    return obs, 0.0, True, False, {}
                return obs, 0.0, True, {}

            current_price = self._prices[self._current_step]
            self._prev_total_value = self._total_value

            reward = 0.0
            if action == 1 and self._position <= 0:
                if self._position < 0:
                    self._balance -= abs(self._position) * current_price * (1 + self._commission)
                self._position = int(self._balance / (current_price * (1 + self._commission)))
                self._balance -= self._position * current_price * (1 + self._commission)
                self._entry_price = current_price

            elif action == 2 and self._position >= 0:
                if self._position > 0:
                    self._balance += self._position * current_price * (1 - self._commission)
                self._position = -int(self._balance / (current_price * (1 + self._commission)))
                self._balance += abs(self._position) * current_price * (1 - self._commission)
                self._entry_price = current_price

            self._current_step += 1
            next_price = self._prices[self._current_step]
            self._total_value = self._balance + self._position * next_price

            step_return = (self._total_value - self._prev_total_value) / (self._prev_total_value + 1e-10)
            self._peak_value = max(self._peak_value, self._total_value)
            drawdown = (self._peak_value - self._total_value) / (self._peak_value + 1e-10)

            reward = step_return - self._drawdown_penalty * max(drawdown - 0.05, 0.0)

            done = self._current_step >= len(self._prices) - 1
            info = {
                "total_value": self._total_value,
                "position": self._position,
                "drawdown": drawdown,
                "step_return": step_return,
            }

            obs = self._get_observation()
            if _GYM_API_VERSION >= 1:
                return obs, float(reward), done, False, info
            return obs, float(reward), done, info

        def _get_observation(self) -> np.ndarray:
            start = max(0, self._current_step - self._lookback)
            price_window = self._prices[start : self._current_step + 1]
            price_norm = price_window / (price_window[-1] + 1e-10) - 1.0

            feat_window = self._features[start : self._current_step + 1]
            if feat_window.ndim == 1:
                feat_window = feat_window.reshape(-1, 1)

            pad_len = self._lookback + 1 - len(price_norm)
            if pad_len > 0:
                price_norm = np.concatenate([np.zeros(pad_len), price_norm])
                feat_pad = np.zeros((pad_len, feat_window.shape[1]))
                feat_window = np.concatenate([feat_pad, feat_window], axis=0)

            feat_flat = feat_window.flatten()
            position_info = np.array([
                self._position / (abs(self._position) + 100),
                self._total_value / self._initial_balance - 1.0,
                (self._total_value - self._peak_value) / (self._peak_value + 1e-10),
            ], dtype=np.float32)

            obs = np.concatenate([price_norm, feat_flat, position_info]).astype(np.float32)
            expected_dim = self.observation_space.shape[0]
            if len(obs) < expected_dim:
                obs = np.concatenate([obs, np.zeros(expected_dim - len(obs), dtype=np.float32)])
            elif len(obs) > expected_dim:
                obs = obs[:expected_dim]

            return obs


class _SimplePolicyGradient:
    def __init__(
        self,
        obs_dim: int,
        n_actions: int = 3,
        lr: float = 1e-3,
        gamma: float = 0.99,
    ) -> None:
        try:
            import torch
            import torch.nn as nn
        except ImportError:
            raise RuntimeError("PyTorch required for simple policy gradient fallback") from None

        self._gamma = gamma
        self._device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

        self._policy = nn.Sequential(
            nn.Linear(obs_dim, 128),
            nn.ReLU(),
            nn.Linear(128, 64),
            nn.ReLU(),
            nn.Linear(64, n_actions),
            nn.Softmax(dim=-1),
        ).to(self._device)

        self._optimizer = torch.optim.Adam(self._policy.parameters(), lr=lr)
        self._log_probs: list[torch.Tensor] = []
        self._rewards: list[float] = []

    def select_action(self, obs: np.ndarray) -> int:
        import torch

        with torch.no_grad():
            state = torch.from_numpy(obs).float().unsqueeze(0).to(self._device)
            probs = self._policy(state)
            dist = torch.distributions.Categorical(probs)
            action = dist.sample()
            self._log_probs.append(dist.log_prob(action))
            return int(action.item())

    def store_reward(self, reward: float) -> None:
        self._rewards.append(reward)

    def update(self) -> float:
        import torch

        if not self._rewards:
            return 0.0

        returns = []
        g = 0.0
        for r in reversed(self._rewards):
            g = r + self._gamma * g
            returns.insert(0, g)

        returns_tensor = torch.tensor(returns, dtype=torch.float32).to(self._device)
        if len(returns_tensor) > 1:
            returns_tensor = (returns_tensor - returns_tensor.mean()) / (returns_tensor.std() + 1e-10)

        loss = torch.stack([
            -log_prob * g for log_prob, g in zip(self._log_probs, returns_tensor, strict=False)
        ]).sum()

        self._optimizer.zero_grad()
        loss.backward()
        torch.nn.utils.clip_grad_norm_(self._policy.parameters(), max_norm=0.5)
        self._optimizer.step()

        self._log_probs.clear()
        self._rewards.clear()

        return float(loss.item())


class RLTrainer:

    def __init__(self, seed: int = 42) -> None:
        self._seed = seed
        np.random.seed(seed)

    def train(
        self,
        env: "TradingEnvironment",
        total_timesteps: int = 100000,
        algorithm: str = "ppo",
        learning_rate: float = 3e-4,
        verbose: int = 0,
    ) -> dict:
        if not _GYM_AVAILABLE:
            raise RuntimeError("gym/gymnasium required for RLTrainer")

        if algorithm == "ppo" and _SB3_AVAILABLE:
            return self._train_sb3(env, total_timesteps, learning_rate, verbose)
        elif algorithm == "ppo" and not _SB3_AVAILABLE:
            logger.info("stable-baselines3 unavailable — using simple policy gradient")
            return self._train_policy_gradient(env, total_timesteps, learning_rate)
        else:
            return self._train_policy_gradient(env, total_timesteps, learning_rate)

    def _train_sb3(
        self,
        env: "TradingEnvironment",
        total_timesteps: int,
        lr: float,
        verbose: int,
    ) -> dict:
        model = PPO(
            "MlpPolicy",
            env,
            learning_rate=lr,
            n_steps=2048,
            batch_size=64,
            n_epochs=10,
            verbose=verbose,
            seed=self._seed,
        )
        model.learn(total_timesteps=total_timesteps)
        logger.info("PPO training completed: %d timesteps", total_timesteps)
        return {"algorithm": "ppo", "total_timesteps": total_timesteps, "model": model}

    def _train_policy_gradient(
        self,
        env: "TradingEnvironment",
        total_timesteps: int,
        lr: float,
    ) -> dict:
        reset_result = env.reset()
        obs = reset_result[0] if isinstance(reset_result, tuple) else reset_result
        obs_dim = env.observation_space.shape[0]
        agent = _SimplePolicyGradient(obs_dim=obs_dim, lr=lr)

        episode_rewards: list[float] = []
        episode = 0
        steps = 0
        ep_reward = 0.0

        while steps < total_timesteps:
            action = agent.select_action(obs)
            step_result = env.step(action)
            if _GYM_API_VERSION >= 1:
                obs, reward, done, truncated, info = step_result
            else:
                obs, reward, done, info = step_result
                truncated = False
            agent.store_reward(reward)
            ep_reward += reward
            steps += 1

            if done or truncated:
                loss = agent.update()
                episode_rewards.append(ep_reward)
                episode += 1
                ep_reward = 0.0
                reset_result = env.reset()
                obs = reset_result[0] if isinstance(reset_result, tuple) else reset_result

                if episode % 50 == 0:
                    avg = np.mean(episode_rewards[-50:])
                    logger.info(
                        "Episode %d  avg_reward(50)=%.4f  steps=%d/%d  loss=%.4f",
                        episode, avg, steps, total_timesteps, loss,
                    )

        logger.info("Policy gradient training completed: %d episodes, %d steps", episode, steps)
        return {
            "algorithm": "policy_gradient",
            "total_timesteps": steps,
            "episodes": episode,
            "avg_reward_last_50": float(np.mean(episode_rewards[-50:])) if episode_rewards else 0.0,
            "agent": agent,
        }

    def evaluate(self, env: "TradingEnvironment", n_episodes: int = 10) -> dict:
        if not _GYM_AVAILABLE:
            raise RuntimeError("gym/gymnasium required for evaluation")

        all_sharpes: list[float] = []
        all_returns: list[float] = []
        all_drawdowns: list[float] = []
        all_win_rates: list[float] = []
        all_trades: list[int] = []

        for _ep in range(n_episodes):
            reset_result = env.reset()
            obs = reset_result[0] if isinstance(reset_result, tuple) else reset_result
            done = False
            values: list[float] = []
            n_trades = 0
            prev_position = 0

            while not done:
                action = env.action_space.sample()
                step_result = env.step(action)
                if _GYM_API_VERSION >= 1:
                    obs, reward, done, truncated, info = step_result
                else:
                    obs, reward, done, info = step_result
                    truncated = False
                values.append(info.get("total_value", 0))
                if info.get("position", 0) != prev_position:
                    n_trades += 1
                prev_position = info.get("position", 0)
                if truncated:
                    break

            if len(values) < 2:
                continue

            total_return = (values[-1] - values[0]) / (values[0] + 1e-10)
            peak = np.maximum.accumulate(values)
            dd = (peak - values) / (peak + 1e-10)
            max_dd = float(np.max(dd)) if len(dd) > 0 else 0.0

            step_returns = np.diff(values) / (np.array(values[:-1]) + 1e-10)
            sharpe = float(np.mean(step_returns) / (np.std(step_returns) + 1e-10) * np.sqrt(252))
            win_rate = float(np.mean(step_returns > 0))

            all_returns.append(total_return)
            all_sharpes.append(sharpe)
            all_drawdowns.append(max_dd)
            all_win_rates.append(win_rate)
            all_trades.append(n_trades)

        result = {
            "avg_return": float(np.mean(all_returns)) if all_returns else 0.0,
            "sharpe": float(np.mean(all_sharpes)) if all_sharpes else 0.0,
            "max_drawdown": float(np.max(all_drawdowns)) if all_drawdowns else 0.0,
            "avg_win_rate": float(np.mean(all_win_rates)) if all_win_rates else 0.0,
            "avg_trades": float(np.mean(all_trades)) if all_trades else 0.0,
            "n_episodes": n_episodes,
        }
        logger.info("Evaluation result: %s", result)
        return result
