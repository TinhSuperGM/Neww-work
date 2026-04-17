from __future__ import annotations
from typing import Any, Optional
import discord

TEAM_VILLAGE = "village"
TEAM_WOLF = "wolf"
DEFAULT_ROLE = "civilian"

ROLE_DEFINITIONS = {
    "seer": {"name": "🔮 Tiên tri", "team": TEAM_VILLAGE, "action": "inspect", "priority": 1},
    "guard": {"name": "🛡️ Người canh gác", "team": TEAM_VILLAGE, "action": "protect", "priority": 0},
    "wolf": {"name": "🐺 Ma Sói", "team": TEAM_WOLF, "action": "kill", "priority": 3},
    "wolf_witch": {"name": "🧪 Sói phù thủy", "team": TEAM_WOLF, "action": "curse", "priority": 4},
    "wolf_seer": {"name": "👁️ Sói tiên tri", "team": TEAM_WOLF, "action": "inspect", "priority": 1},
}


class Role:
    def __init__(self, player, role_key):
        self.player = player
        self.role_key = role_key

        data = ROLE_DEFINITIONS.get(role_key, {})
        self.name = data.get("name", "Dân thường")
        self.team = data.get("team", TEAM_VILLAGE)
        self.action = data.get("action")
        self.priority = data.get("priority", 0)

        self.target_id = None

    def set_target(self, target):
        try:
            self.target_id = int(target)
        except:
            self.target_id = None

    def build_action(self):
        if not self.action or not self.target_id:
            return None

        return {
            "type": self.action,
            "actor": self.player,
            "target": self.target_id,
            "priority": self.priority,
        }


def create_role(role_key, player):
    return Role(player, role_key)


def build_role_assignments(ids, players):
    n = len(ids)
    result = {}

    special = ["seer", "guard", "wolf_seer", "wolf_witch"]

    for i, role in enumerate(special):
        if i < n:
            result[ids[i]] = role

    remaining = ids[len(special):]

    wolf_count = max(1, n // 4)

    for uid in remaining[:wolf_count]:
        result[uid] = "wolf"

    for uid in remaining[wolf_count:]:
        result[uid] = DEFAULT_ROLE

    return result


def build_night_actions(game):
    actions = []
    for p in game.players.values():
        role = p.get("role_obj")
        if role:
            a = role.build_action()
            if a:
                actions.append(a)
    return actions
