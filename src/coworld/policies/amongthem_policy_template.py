"""Editable scripted policy template for BitWorld Among Them Coworld players.

Generate a copy with:
    coworld make-policy among_them -o amongthem_policy.py

Then edit AmongThemPolicy._choose_actions(). This file is a policy starting point;
public Among Them submissions still need a Docker player wrapper that follows the
Coworld flow in https://softmax.com/play_amongthem.md.
"""

from __future__ import annotations

import numpy as np

from mettagrid.bitworld import (
    BITWORLD_ACTION_NAMES,
    bitworld_action_index,
    bitworld_action_name,
    encode_buttons,
)
from mettagrid.policy.policy import AgentPolicy, MultiAgentPolicy
from mettagrid.policy.policy_env_interface import PolicyEnvInterface
from mettagrid.simulator import Action, AgentObservation

BUTTON_CYCLE: tuple[tuple[str, ...], ...] = (
    (),
    ("right",),
    ("right", "a"),
    ("down",),
    ("down", "a"),
    ("left",),
    ("left", "b"),
    ("up",),
    ("up", "a"),
)

ACTION_CYCLE = np.asarray(
    [bitworld_action_index(encode_buttons(buttons)) for buttons in BUTTON_CYCLE],
    dtype=np.int32,
)


class AmongThemAgentPolicy(AgentPolicy):
    def __init__(self, policy_env_info: PolicyEnvInterface, parent: "AmongThemPolicy", agent_id: int):
        super().__init__(policy_env_info)
        self._parent = parent
        self._agent_id = agent_id

    def step(self, obs: AgentObservation) -> Action:
        del obs
        return Action(name=bitworld_action_name(self._parent.next_action(self._agent_id)))


class AmongThemPolicy(MultiAgentPolicy):
    """Small starting point for an Among Them scripted policy.

    The BitWorld runner passes raw pixel or sprite_player observations to step_batch().
    Replace _choose_actions() with your game logic; keep returning integer
    indices in the BitWorld trainable action set.
    """

    def __init__(self, policy_env_info: PolicyEnvInterface, device: str = "cpu", *, hold_ticks: str | int = 4):
        super().__init__(policy_env_info, device=device)
        if tuple(policy_env_info.action_names) != BITWORLD_ACTION_NAMES:
            raise ValueError("AmongThemPolicy requires the BitWorld Among Them action space")
        self._hold_ticks = int(hold_ticks)
        if self._hold_ticks < 1:
            raise ValueError("hold_ticks must be at least 1")
        self._tick = 0
        self._agent_steps_this_tick = 0

    def agent_policy(self, agent_id: int) -> AgentPolicy:
        return AmongThemAgentPolicy(self._policy_env_info, self, agent_id)

    def next_action(self, agent_id: int) -> int:
        cycle_index = ((self._tick // self._hold_ticks) + agent_id) % len(ACTION_CYCLE)
        self._agent_steps_this_tick += 1
        if self._agent_steps_this_tick == self._policy_env_info.num_agents:
            self._agent_steps_this_tick = 0
            self._tick += 1
        return int(ACTION_CYCLE[cycle_index])

    def step_batch(self, raw_observations: np.ndarray, raw_actions: np.ndarray) -> None:
        raw_actions[...] = self._choose_actions(raw_observations)
        self._tick += 1
        self._agent_steps_this_tick = 0

    def _choose_actions(self, raw_observations: np.ndarray) -> np.ndarray:
        batch_size = raw_observations.shape[0]
        flat_observations = raw_observations.reshape(batch_size, -1)

        # This deliberately reads a tiny observation signal so the template works
        # for both pixel and sprite_player-observation leagues. Replace it with
        # real Among Them sprite_player extraction or pixel logic.
        observation_signal = flat_observations[:, 0].astype(np.int64)
        agent_offsets = np.arange(batch_size, dtype=np.int64)
        cycle_indices = ((self._tick // self._hold_ticks) + agent_offsets + observation_signal) % len(ACTION_CYCLE)
        return ACTION_CYCLE[cycle_indices]
