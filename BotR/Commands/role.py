# BotR/Commands/role.py
from __future__ import annotations

from typing import Any, Optional

import discord

TEAM_VILLAGE = "village"
TEAM_WOLF = "wolf"
DEFAULT_ROLE_KEY = "civilian"

ROLE_DEFINITIONS: dict[str, dict[str, Any]] = {
    "civilian": {
        "name": "👤 Dân làng",
        "team": TEAM_VILLAGE,
        "description": "Ban ngày thảo luận và vote. Ban đêm không làm gì.",
        "skills": [],
    },
    "seer": {
        "name": "🔮 Tiên tri",
        "team": TEAM_VILLAGE,
        "description": "Ban đêm soi role của 1 người, mỗi đêm 1 lần.",
        "skills": [
            {
                "key": "inspect",
                "label": "Soi",
                "description": "Xem role của một người",
                "phase": "night",
                "kind": "inspect",
                "uses": 1,
                "reset": "night",
                "priority": 1,
            }
        ],
    },
    "guard": {
        "name": "🛡️ Người canh gác",
        "team": TEAM_VILLAGE,
        "description": "Ban ngày có thể dùng Bắn hoặc Soi, mỗi skill 1 lần/ván.",
        "skills": [
            {
                "key": "shoot",
                "label": "Bắn",
                "description": "Giết ngay mục tiêu, lộ role của bạn",
                "phase": "day",
                "kind": "shoot",
                "uses": 1,
                "reset": None,
                "priority": 5,
            },
            {
                "key": "inspect",
                "label": "Soi",
                "description": "Xem role mục tiêu; nếu là sói, sói biết bạn là ai",
                "phase": "day",
                "kind": "inspect_guard",
                "uses": 1,
                "reset": None,
                "priority": 1,
            },
        ],
    },
    "wolf": {
        "name": "🐺 Ma Sói",
        "team": TEAM_WOLF,
        "description": "Ban đêm ở cùng phe sói và chọn ra kẻ bị giết.",
        "skills": [],
    },
    "nightmare_wolf": {
        "name": "🌑 Sói ác mộng",
        "team": TEAM_WOLF,
        "description": "Trong lượt vote ban ngày, đặt token ác mộng lên 1 người. Có 2 lượt/ván.",
        "skills": [
            {
                "key": "nightmare",
                "label": "Ác mộng",
                "description": "Đặt token ác mộng lên 1 người; đổi mục tiêu thì token chuyển sang người mới",
                "phase": "day",
                "kind": "nightmare",
                "uses": 2,
                "reset": None,
                "priority": 2,
            }
        ],
    },
}


def _meta(role_key: str) -> dict[str, Any]:
    return ROLE_DEFINITIONS.get(role_key, ROLE_DEFINITIONS[DEFAULT_ROLE_KEY])


def _safe_name(player: discord.abc.User | None) -> str:
    if player is None:
        return "Unknown"
    return getattr(player, "display_name", None) or getattr(player, "name", "Unknown")


def _role_label(role_key: str) -> str:
    return _meta(role_key)["name"]


def _role_team(role_key: str) -> str:
    return _meta(role_key)["team"]


class Role:
    def __init__(self, player: discord.abc.User | None, role_key: str):
        self.player = player
        self.role_key = role_key

        data = _meta(role_key)
        self.name: str = data["name"]
        self.team: str = data["team"]
        self.description: str = data["description"]
        self.skills_meta: list[dict[str, Any]] = list(data.get("skills", []))

        self.selected_skill_key: Optional[str] = None
        self.target_id: Optional[int] = None
        self.uses_left: dict[str, int] = {}

        for skill in self.skills_meta:
            key = skill["key"]
            uses = skill.get("uses")
            if uses is not None:
                self.uses_left[key] = int(uses)

    async def send(self, message: str | None = None, embed: Optional[discord.Embed] = None):
        if self.player is None:
            return
        try:
            await self.player.send(content=message, embed=embed)
        except Exception:
            pass

    def card_embed(self) -> discord.Embed:
        color = discord.Color.dark_red() if self.team == TEAM_WOLF else discord.Color.blurple()
        embed = discord.Embed(title=self.name, description=self.description, color=color)
        embed.add_field(name="Phe", value="Ma Sói" if self.team == TEAM_WOLF else "Dân làng", inline=True)

        if self.skills_meta:
            lines = []
            for skill in self.skills_meta:
                left = self.uses_left.get(skill["key"], skill.get("uses"))
                left_text = "∞" if left is None else str(left)
                lines.append(f"• **{skill['label']}** — {skill['description']} (`{left_text}`)")
            embed.add_field(name="Kỹ năng", value="\n".join(lines), inline=False)
        else:
            embed.add_field(name="Kỹ năng", value="Không có", inline=False)

        return embed

    def set_skill(self, skill_key: str) -> bool:
        if skill_key not in {s["key"] for s in self.skills_meta}:
            return False
        self.selected_skill_key = skill_key
        self.target_id = None
        return True

    def set_target(self, target: object | None) -> None:
        try:
            self.target_id = int(target) if target is not None else None
        except Exception:
            self.target_id = None

    def clear_selection(self) -> None:
        self.selected_skill_key = None
        self.target_id = None

    def consume_use(self, skill_key: str) -> bool:
        if skill_key not in self.uses_left:
            return True
        if self.uses_left[skill_key] <= 0:
            return False
        self.uses_left[skill_key] -= 1
        return True

    def reset_night_use(self) -> None:
        for skill in self.skills_meta:
            if skill.get("reset") == "night":
                self.uses_left[skill["key"]] = int(skill.get("uses", 1))

    def can_use_skill(self, phase: str, skill_key: Optional[str] = None, game=None) -> bool:
        if game is not None and self._is_nightmare_locked(game):
            return False

        skill_key = skill_key or self.selected_skill_key
        if skill_key is None:
            return False

        skill = next((s for s in self.skills_meta if s["key"] == skill_key), None)
        if skill is None:
            return False
        if skill.get("phase") != phase:
            return False
        if self.uses_left.get(skill_key, 0) <= 0:
            return False

        if self.role_key == "seer":
            return phase == "night"
        if self.role_key == "guard":
            return phase == "day"
        if self.role_key == "nightmare_wolf":
            return phase == "day"
        return False

    def skill_options(self, phase: str, game=None) -> list[dict[str, Any]]:
        out = []
        for skill in self.skills_meta:
            key = skill["key"]
            if skill.get("phase") != phase:
                continue
            if self.uses_left.get(key, 0) <= 0:
                continue
            if not self.can_use_skill(phase, key, game=game):
                continue
            out.append(
                {
                    "key": key,
                    "label": skill["label"],
                    "description": skill["description"],
                    "kind": skill["kind"],
                }
            )
        return out

    def skill_targets(self, game, phase: str, skill_key: Optional[str] = None) -> list[str]:
        if game is None:
            return []

        skill_key = skill_key or self.selected_skill_key
        if skill_key is None:
            return []

        alive_ids = [uid for uid, pdata in game.players.items() if pdata.get("alive")]
        my_id = str(getattr(self.player, "id", ""))

        if self.role_key in {"seer", "guard", "nightmare_wolf"}:
            return [uid for uid in alive_ids if uid != my_id]

        return []

    def can_target(self, game, target_id: object, phase: str, skill_key: Optional[str] = None) -> bool:
        try:
            tid = str(int(target_id))
        except Exception:
            return False

        if game is None or tid not in game.players:
            return False
        if not game.players[tid].get("alive"):
            return False

        skill_key = skill_key or self.selected_skill_key
        if skill_key is None:
            return False

        my_id = str(getattr(self.player, "id", ""))
        if tid == my_id:
            return False

        if self.role_key == "seer" and skill_key == "inspect":
            return True
        if self.role_key == "guard" and skill_key in {"shoot", "inspect"}:
            return True
        if self.role_key == "nightmare_wolf" and skill_key == "nightmare":
            return True
        return False

    def use_skill(self, game, skill_key: str, target_id: object) -> Optional[dict[str, Any]]:
        if not self.can_use_skill(game.phase, skill_key, game=game):
            return None
        if not self.can_target(game, target_id, game.phase, skill_key=skill_key):
            return None

        try:
            tid = int(target_id)
        except Exception:
            return None

        self.set_skill(skill_key)
        self.set_target(tid)

        if not self.consume_use(skill_key):
            return None

        return self.build_action()

    def build_action(self) -> Optional[dict[str, Any]]:
        if self.selected_skill_key is None or self.target_id is None:
            return None

        skill = next((s for s in self.skills_meta if s["key"] == self.selected_skill_key), None)
        if skill is None:
            return None

        return {
            "type": skill["kind"],
            "skill_key": skill["key"],
            "role_key": self.role_key,
            "actor": self.player,
            "actor_id": getattr(self.player, "id", None),
            "target_id": self.target_id,
            "priority": int(skill.get("priority", 0)),
        }

    async def on_game_start(self, game):
        await self.send(embed=self.card_embed())

    async def on_night_start(self, game):
        self.clear_selection()
        if self.role_key == "seer":
            self.reset_night_use()
            await self.send("🌙 Đêm bắt đầu. Bấm **Skill** để soi 1 người.")
        elif self.role_key == "wolf":
            await self.send("🌙 Đêm bắt đầu. Phe sói sẽ chọn mục tiêu bằng vote.")
        elif self.role_key == "nightmare_wolf":
            await self.send("🌙 Đêm bắt đầu. Token ác mộng sẽ khóa kỹ năng của mục tiêu vào đêm tới.")

    async def on_day_start(self, game):
        self.clear_selection()
        await self._clear_nightmare_lock(game)
        if self.role_key == "guard":
            await self.send("☀️ Ban ngày bắt đầu. Bạn có thể dùng **Bắn** hoặc **Soi** trong lượt vote.")

    async def on_death(self, game):
        self.clear_selection()

    def _is_nightmare_locked(self, game) -> bool:
        my_id = str(getattr(self.player, "id", ""))
        pdata = game.players.get(my_id, {})
        return bool(pdata.get("nightmare_locked"))

    async def _apply_nightmare_lock(self, game):
        target_id = getattr(game, "nightmare_token_target_id", None)
        if target_id is None:
            return

        tid = str(target_id)
        pdata = game.players.get(tid)
        if not pdata or not pdata.get("alive"):
            return

        pdata["nightmare_locked"] = True
        try:
            member = game.guild.get_member(int(tid))
            if member is None:
                member = await game.guild.fetch_member(int(tid))
            if member:
                await member.send(
                    "🌑 Bạn đã chìm vào **cơn ác mộng**. Tối nay kỹ năng của bạn sẽ không dùng được cho đến sáng hôm sau."
                )
        except Exception:
            pass

    async def _clear_nightmare_lock(self, game):
        if game is None:
            return
        for pdata in game.players.values():
            if pdata.get("nightmare_locked"):
                pdata["nightmare_locked"] = False


class Civilian(Role):
    def __init__(self, player):
        super().__init__(player, DEFAULT_ROLE_KEY)


class Seer(Role):
    def __init__(self, player):
        super().__init__(player, "seer")


class Guard(Role):
    def __init__(self, player):
        super().__init__(player, "guard")


class Wolf(Role):
    def __init__(self, player):
        super().__init__(player, "wolf")


class NightmareWolf(Role):
    def __init__(self, player):
        super().__init__(player, "nightmare_wolf")
        self.nightmare_token_target_id: Optional[int] = None

    def set_target(self, target: object | None) -> None:
        super().set_target(target)
        if self.selected_skill_key == "nightmare" and self.target_id is not None:
            self.nightmare_token_target_id = self.target_id

    def use_skill(self, game, skill_key: str, target_id: object) -> Optional[dict[str, Any]]:
        if skill_key != "nightmare":
            return None
        if not self.can_use_skill(game.phase, skill_key, game=game):
            return None
        if not self.can_target(game, target_id, game.phase, skill_key=skill_key):
            return None

        try:
            tid = int(target_id)
        except Exception:
            return None

        if self.nightmare_token_target_id == tid:
            return None

        self.nightmare_token_target_id = tid
        self.set_skill(skill_key)
        self.set_target(tid)
        if not self.consume_use(skill_key):
            return None
        return self.build_action()

    async def on_night_start(self, game):
        await super().on_night_start(game)
        await self._apply_nightmare_lock(game)

    async def on_day_start(self, game):
        await super().on_day_start(game)
        await self._clear_nightmare_lock(game)


ROLE_MAP = {
    "civilian": Civilian,
    "seer": Seer,
    "guard": Guard,
    "wolf": Wolf,
    "nightmare_wolf": NightmareWolf,
}

ROLE_ALIASES = {
    "villager": "civilian",
    "dân_làng": "civilian",
    "sói_ác_mộng": "nightmare_wolf",
    "nightmare-wolf": "nightmare_wolf",
    "nightmarewolf": "nightmare_wolf",
}


def normalize_role_key(role_key: str) -> str:
    key = role_key.strip().lower().replace(" ", "_").replace("-", "_")
    return ROLE_ALIASES.get(key, key)


def create_role(role_key: str, player):
    key = normalize_role_key(role_key)
    role_cls = ROLE_MAP.get(key, Civilian)
    return role_cls(player)


def build_role_assignments(player_ids: list[str], players: dict[str, dict]) -> dict[str, str]:
    ids = list(player_ids)
    n = len(ids)
    result: dict[str, str] = {}

    if n == 0:
        return result

    specials = ["seer", "guard", "nightmare_wolf"]
    special_count = min(len(specials), max(0, n - 1))
    for i in range(special_count):
        result[ids[i]] = specials[i]

    remaining = ids[special_count:]
    if not remaining:
        return result

    wolf_count = max(1, n // 4)
    wolf_count = min(wolf_count, len(remaining))
    for uid in remaining[:wolf_count]:
        result[uid] = "wolf"

    for uid in remaining[wolf_count:]:
        result[uid] = "civilian"

    return result


def build_night_actions(game) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    for pdata in game.players.values():
        role_obj = pdata.get("role_obj")
        if role_obj is None:
            continue
        try:
            action = role_obj.build_action()
            if action:
                actions.append(action)
        except Exception:
            pass
    return actions


def resolve_actions(game, actions: list[dict[str, Any]]) -> dict[str, Any]:
    actions = sorted(actions, key=lambda a: a.get("priority", 0))

    plan: dict[str, Any] = {
        "killed": [],
        "public_messages": [],
        "private_dms": [],
        "nightmare_token_target_id": None,
    }

    for action in actions:
        a_type = action.get("type")
        actor = action.get("actor")
        actor_id = action.get("actor_id")
        target_id = action.get("target_id")

        if target_id is None:
            continue

        target_id = str(target_id)
        target_pdata = game.players.get(target_id)
        if not target_pdata or not target_pdata.get("alive"):
            continue

        actor_name = _safe_name(actor)
        target_name = target_pdata.get("name", "Unknown")
        target_role_key = target_pdata.get("role", DEFAULT_ROLE_KEY)
        target_role_label = _role_label(target_role_key)

        if a_type in ("inspect", "inspect_guard"):
            plan["private_dms"].append((str(actor_id), f"🔎 {target_name} là **{target_role_label}**."))
            if a_type == "inspect_guard" and _role_team(target_role_key) == TEAM_WOLF:
                plan["private_dms"].append((target_id, f"🕵️ Bạn đã bị **Người canh gác {actor_name}** soi."))
            continue

        if a_type == "shoot":
            if target_id not in plan["killed"]:
                plan["killed"].append(target_id)
            plan["public_messages"].append(
                f"🔫 **{actor_name}** đã nổ súng và lộ vai trò của mình: **{_role_label(action.get('role_key', 'guard'))}**."
            )
            continue

        if a_type == "kill":
            if target_id not in plan["killed"]:
                plan["killed"].append(target_id)
            continue

        if a_type == "nightmare":
            plan["nightmare_token_target_id"] = int(target_id)
            continue

    return plan


async def apply_action_plan(game, plan: dict[str, Any]) -> None:
    if plan.get("nightmare_token_target_id") is not None:
        setattr(game, "nightmare_token_target_id", plan["nightmare_token_target_id"])

    for uid, msg in plan.get("private_dms", []):
        try:
            member = game.guild.get_member(int(uid))
            if member is None:
                member = await game.guild.fetch_member(int(uid))
            if member:
                await member.send(msg)
        except Exception:
            pass

    for msg in plan.get("public_messages", []):
        try:
            await game.channel.send(msg)
        except Exception:
            pass

    for uid in plan.get("killed", []):
        try:
            await game.kill_player(str(uid), "bị loại trong đêm.")
        except Exception:
            pass


def build_day_actions(game) -> list[dict[str, Any]]:
    return build_night_actions(game)
