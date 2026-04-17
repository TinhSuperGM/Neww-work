from __future__ import annotations
from typing import Any, Optional
import discord

# ===== TEAM =====
TEAM_VILLAGE = "village"
TEAM_WOLF = "wolf"

# ⚠️ Không tạo class dân làng (theo yêu cầu)
DEFAULT_ROLE = "civilian"


# ===== ROLE DEFINITIONS =====
ROLE_DEFINITIONS = {
    "seer": {
        "name": "🔮 Tiên tri",
        "team": TEAM_VILLAGE,
        "action": "inspect",
        "priority": 1
    },
    "guard": {
        "name": "🛡️ Người canh gác",
        "team": TEAM_VILLAGE,
        "action": "protect",
        "priority": 0
    },
    "wolf": {
        "name": "🐺 Ma Sói",
        "team": TEAM_WOLF,
        "action": "kill",
        "priority": 3
    },
    "wolf_witch": {
        "name": "🧪 Sói phù thủy",
        "team": TEAM_WOLF,
        "action": "curse",
        "priority": 4
    },
    "wolf_seer": {
        "name": "👁️ Sói tiên tri",
        "team": TEAM_WOLF,
        "action": "inspect",
        "priority": 1
    }
}


# ===== BASE ROLE =====
class Role:
    def __init__(self, player: discord.abc.User, role_key: str):
        self.player = player
        self.role_key = role_key

        data = ROLE_DEFINITIONS.get(role_key, {})
        self.name = data.get("name", "Unknown")
        self.team = data.get("team")
        self.action_type = data.get("action")
        self.priority = data.get("priority", 0)

        self.target_id: Optional[int] = None

    async def send(self, msg: str):
        try:
            await self.player.send(msg)
        except:
            pass

    def set_target(self, target):
        try:
            self.target_id = int(target.id if hasattr(target, "id") else target)
        except:
            self.target_id = None

    def build_action(self):
        if not self.target_id or not self.action_type:
            return None

        return {
            "type": self.action_type,
            "actor": self.player,
            "target_id": self.target_id,
            "priority": self.priority,
            "role": self.role_key
        }


# ===== FACTORY =====
def create_role(role_key: str, player):
    return Role(player, role_key)


# ===== ROLE ASSIGN =====
def build_role_assignments(player_ids, players):
    """
    Phân role kiểu Wolvesville cơ bản
    """
    n = len(player_ids)
    ids = list(player_ids)

    result = {}

    # Role đặc biệt
    special_roles = ["seer", "guard", "wolf_seer", "wolf_witch"]

    for i, role in enumerate(special_roles):
        if i < n:
            result[ids[i]] = role

    # Sói thường
    remaining = ids[len(special_roles):]
    wolf_count = max(1, n // 4)

    for uid in remaining[:wolf_count]:
        result[uid] = "wolf"

    # Còn lại = dân thường (không class riêng)
    for uid in remaining[wolf_count:]:
        result[uid] = DEFAULT_ROLE

    return result


# ===== BUILD ACTION =====
def build_night_actions(game):
    actions = []

    for p in game.players.values():
        role_obj = p.get("role_obj")
        if not role_obj:
            continue

        action = role_obj.build_action()
        if action:
            actions.append(action)

    return actions
