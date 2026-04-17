from __future__ import annotations

from typing import Any, Optional

import discord

TEAM_VILLAGE = "village"
TEAM_WOLF = "wolf"
TEAM_SOLO = "solo"
DEFAULT_ROLE_KEY = "civilian"

ROLE_DEFINITIONS: dict[str, dict[str, Any]] = {
    "civilian": {
        "name": "👤 Dân làng",
        "team": TEAM_VILLAGE,
        "description": "Ban ngày thảo luận và vote. Ban đêm không có kỹ năng chủ động.",
        "skills": [],
    },
    "seer": {
        "name": "🔮 Tiên tri",
        "team": TEAM_VILLAGE,
        "description": "Ban đêm soi role thật của 1 người.",
        "skills": [
            {
                "key": "inspect",
                "label": "Soi",
                "description": "Xem role thật của một người",
                "phase": "night",
                "kind": "inspect",
                "uses": None,
                "reset": None,
                "priority": 1,
                "target_state": "alive",
                "allow_self": False,
            }
        ],
    },
    "guard": {
        "name": "🛡️ Người gác",
        "team": TEAM_VILLAGE,
        "description": "Ban ngày có thể dùng Bắn hoặc Soi, mỗi kỹ năng 1 lần/ván.",
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
                "target_state": "alive",
                "allow_self": False,
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
                "target_state": "alive",
                "allow_self": False,
            },
        ],
    },
    "protector": {
        "name": "🛡️ Bảo vệ",
        "team": TEAM_VILLAGE,
        "description": "Mỗi đêm chọn 1 người để bảo vệ. Lần đầu bị tấn công sẽ sống, lần sau nếu cùng mục tiêu bị tấn công thì Bảo vệ chết thay.",
        "skills": [
            {
                "key": "protect",
                "label": "Bảo vệ",
                "description": "Bảo vệ 1 người trong đêm",
                "phase": "night",
                "kind": "protect",
                "uses": 1,
                "reset": "night",
                "priority": 0,
                "target_state": "alive",
                "allow_self": True,
            }
        ],
    },
    "wolf": {
        "name": "🐺 Ma Sói",
        "team": TEAM_WOLF,
        "description": "Ban đêm vote trong hang sói để chọn nạn nhân.",
        "skills": [],
    },
    "wolf_seer": {
        "name": "🌘 Sói tiên tri",
        "team": TEAM_WOLF,
        "description": "Giống tiên tri nhưng thuộc phe sói.",
        "skills": [
            {
                "key": "inspect",
                "label": "Soi",
                "description": "Xem role thật của một người",
                "phase": "night",
                "kind": "wolf_inspect",
                "uses": 1,
                "reset": "night",
                "priority": 1,
                "target_state": "alive",
                "allow_self": False,
            }
        ],
    },
    "wolf_shaman": {
        "name": "🧙 Sói pháp sư",
        "team": TEAM_WOLF,
        "description": "Ban ngày chọn 1 người để tối đó tiên tri soi nhầm thành Sói pháp sư.",
        "skills": [
            {
                "key": "bless",
                "label": "Làm mờ",
                "description": "Che mắt tiên tri lên 1 mục tiêu",
                "phase": "day",
                "kind": "mark_blind",
                "uses": 1,
                "reset": "day",
                "priority": 2,
                "target_state": "alive",
                "allow_self": False,
            }
        ],
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
                "target_state": "alive",
                "allow_self": False,
            }
        ],
    },
    "medium": {
        "name": "🕯️ Thầy đồng",
        "team": TEAM_VILLAGE,
        "description": "Đêm đầu không làm gì. Từ đêm sau có thể nói chuyện với người chết và hồi sinh 1 dân làng duy nhất.",
        "skills": [
            {
                "key": "revive",
                "label": "Hồi sinh",
                "description": "Hồi sinh 1 người thuộc phe dân làng",
                "phase": "night",
                "kind": "revive",
                "uses": 1,
                "reset": None,
                "priority": 3,
                "target_state": "dead",
                "allow_self": False,
            }
        ],
    },
    "jailer": {
        "name": "🔒 Quản ngục",
        "team": TEAM_VILLAGE,
        "description": "Ban ngày chọn 1 người để đêm đó bị giam cùng bạn trong phòng riêng. Có 1 viên đạn duy nhất để bắn tù nhân.",
        "skills": [
            {
                "key": "jail",
                "label": "Giam",
                "description": "Chọn 1 người để đưa vào phòng giam ban đêm",
                "phase": "day",
                "kind": "jail",
                "uses": 1,
                "reset": "day",
                "priority": 2,
                "target_state": "alive",
                "allow_self": False,
            }
        ],
    },
    "jester": {
        "name": "🎭 Thằng ngố",
        "team": TEAM_SOLO,
        "description": "Mục tiêu là bị dân làng treo cổ. Nếu bị treo cổ, bạn thắng ngay. Bị sói cắn thì vẫn chết bình thường.",
        "skills": [],
    },
    "serial_killer": {
        "name": "🔪 Kẻ giết người hàng loạt",
        "team": TEAM_SOLO,
        "description": "Mỗi đêm có thể giết 1 người. Sói không thể giết bạn bằng cắn. Mục tiêu là sống tới cuối cùng.",
        "skills": [
            {
                "key": "kill",
                "label": "Giết",
                "description": "Giết 1 người vào ban đêm",
                "phase": "night",
                "kind": "kill",
                "uses": None,
                "reset": None,
                "priority": 4,
                "target_state": "alive",
                "allow_self": False,
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
        color = discord.Color.dark_red() if self.team == TEAM_WOLF else discord.Color.purple() if self.team == TEAM_SOLO else discord.Color.blurple()
        embed = discord.Embed(title=self.name, description=self.description, color=color)
        team_label = "Ma Sói" if self.team == TEAM_WOLF else "Solo" if self.team == TEAM_SOLO else "Dân làng"
        embed.add_field(name="Phe", value=team_label, inline=True)

        if self.skills_meta:
            lines = []
            for skill in self.skills_meta:
                left = self.uses_left.get(skill["key"])
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

    def reset_uses_for_phase(self, phase: str) -> None:
        for skill in self.skills_meta:
            if skill.get("reset") == phase and skill.get("uses") is not None:
                self.uses_left[skill["key"]] = int(skill.get("uses", 1))

    def can_use_skill(self, phase: str, skill_key: Optional[str] = None, game=None) -> bool:
        if game is not None and self._is_nightmare_locked(game):
            return False

        if game is not None and game.is_jailed(getattr(self.player, "id", None)):
            return False

        skill_key = skill_key or self.selected_skill_key
        if skill_key is None:
            return False

        skill = next((s for s in self.skills_meta if s["key"] == skill_key), None)
        if skill is None or skill.get("phase") != phase:
            return False

        if self.role_key == "medium" and phase == "night" and game is not None and getattr(game, "round_no", 1) < 2:
            return False

        uses = self.uses_left.get(skill_key)
        if uses is not None and uses <= 0:
            return False

        if self.role_key == "seer":
            return phase == "night"
        if self.role_key == "wolf_seer":
            return phase == "night"
        if self.role_key == "protector":
            return phase == "night"
        if self.role_key == "wolf_shaman":
            return phase == "day"
        if self.role_key == "medium":
            return phase == "night"
        if self.role_key == "jailer":
            return phase == "day"
        if self.role_key == "serial_killer":
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

        my_id = str(getattr(self.player, "id", ""))

        if self.role_key in {"seer", "wolf_seer", "wolf_shaman", "nightmare_wolf"}:
            return [uid for uid, pdata in game.players.items() if pdata.get("alive") and uid != my_id]
        if self.role_key == "protector":
            return [uid for uid, pdata in game.players.items() if pdata.get("alive")]
        if self.role_key in {"guard", "jailer", "serial_killer"}:
            return [uid for uid, pdata in game.players.items() if pdata.get("alive") and uid != my_id]
        if self.role_key == "medium" and skill_key == "revive":
            return [
                uid
                for uid, pdata in game.players.items()
                if not pdata.get("alive") and game.role_team(pdata.get("role", DEFAULT_ROLE_KEY)) == TEAM_VILLAGE
            ]
        return []

    def can_target(self, game, target_id: object, phase: str, skill_key: Optional[str] = None) -> bool:
        try:
            tid = str(int(target_id))
        except Exception:
            return False

        if game is None or tid not in game.players:
            return False

        skill_key = skill_key or self.selected_skill_key
        if skill_key is None:
            return False

        skill = next((s for s in self.skills_meta if s["key"] == skill_key), None)
        if skill is None:
            return False

        target_state = skill.get("target_state", "alive")
        allow_self = bool(skill.get("allow_self", False))
        my_id = str(getattr(self.player, "id", ""))

        if tid == my_id and not allow_self:
            return False

        pdata = game.players.get(tid)
        if target_state == "alive" and not pdata.get("alive"):
            return False
        if target_state == "dead" and pdata.get("alive"):
            return False

        if self.role_key == "seer" and skill_key == "inspect":
            return pdata.get("alive")
        if self.role_key == "wolf_seer" and skill_key == "inspect":
            return pdata.get("alive")
        if self.role_key == "protector" and skill_key == "protect":
            return pdata.get("alive") or tid == my_id
        if self.role_key == "wolf_shaman" and skill_key == "bless":
            return pdata.get("alive")
        if self.role_key == "medium" and skill_key == "revive":
            return not pdata.get("alive") and game.role_team(pdata.get("role", DEFAULT_ROLE_KEY)) == TEAM_VILLAGE
        if self.role_key == "jailer" and skill_key == "jail":
            return pdata.get("alive")
        if self.role_key == "serial_killer" and skill_key == "kill":
            return pdata.get("alive") and tid != my_id
        if self.role_key == "guard" and skill_key in {"shoot", "inspect"}:
            return pdata.get("alive") and tid != my_id
        if self.role_key == "nightmare_wolf" and skill_key == "nightmare":
            return pdata.get("alive") and tid != my_id
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
        self.reset_uses_for_phase("night")
        if self.role_key == "seer":
            await self.send("🌙 Đêm bắt đầu. Bấm **Skill** để soi 1 người.")
        elif self.role_key == "wolf_seer":
            await self.send("🌙 Đêm bắt đầu. Bạn có thể soi 1 người.")
        elif self.role_key == "protector":
            await self.send("🌙 Đêm bắt đầu. Bạn có thể bảo vệ 1 người.")
        elif self.role_key == "medium":
            if getattr(game, "round_no", 1) >= 2:
                await self.send("🌙 Bạn có thể nhìn và chat với kênh người chết, đồng thời hồi sinh 1 dân làng.")
        elif self.role_key == "serial_killer":
            await self.send("🌙 Đêm bắt đầu. Bạn có thể chọn 1 người để giết.")
        elif self.role_key == "wolf":
            await self.send("🌙 Đêm bắt đầu. Phe sói sẽ chọn mục tiêu bằng vote.")
        elif self.role_key == "nightmare_wolf":
            await self.send("🌙 Đêm bắt đầu. Token ác mộng sẽ khóa kỹ năng của mục tiêu vào đêm tới.")

    async def on_day_start(self, game):
        self.clear_selection()
        self.reset_uses_for_phase("day")
        await self._clear_nightmare_lock(game)
        if self.role_key == "guard":
            await self.send("☀️ Ban ngày bắt đầu. Bạn có thể dùng **Bắn** hoặc **Soi** trong lượt vote.")
        elif self.role_key == "wolf_shaman":
            await self.send("☀️ Ban ngày. Chọn 1 người để tiên tri soi nhầm trong đêm nay.")
        elif self.role_key == "jailer":
            await self.send("☀️ Ban ngày. Chọn 1 người để giam vào đêm nay.")

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


class Protector(Role):
    def __init__(self, player):
        super().__init__(player, "protector")


class Wolf(Role):
    def __init__(self, player):
        super().__init__(player, "wolf")


class WolfSeer(Role):
    def __init__(self, player):
        super().__init__(player, "wolf_seer")


class WolfShaman(Role):
    def __init__(self, player):
        super().__init__(player, "wolf_shaman")


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


class Medium(Role):
    def __init__(self, player):
        super().__init__(player, "medium")


class Jailer(Role):
    def __init__(self, player):
        super().__init__(player, "jailer")


class Jester(Role):
    def __init__(self, player):
        super().__init__(player, "jester")


class SerialKiller(Role):
    def __init__(self, player):
        super().__init__(player, "serial_killer")


ROLE_MAP = {
    "civilian": Civilian,
    "seer": Seer,
    "guard": Guard,
    "protector": Protector,
    "wolf": Wolf,
    "wolf_seer": WolfSeer,
    "wolf_shaman": WolfShaman,
    "nightmare_wolf": NightmareWolf,
    "medium": Medium,
    "jailer": Jailer,
    "jester": Jester,
    "serial_killer": SerialKiller,
}

ROLE_ALIASES = {
    "villager": "civilian",
    "dân_làng": "civilian",
    "guard": "guard",
    "người_gác": "guard",
    "bảo_vệ": "protector",
    "bao_ve": "protector",
    "protect": "protector",
    "seer": "seer",
    "tiên_tri": "seer",
    "wolf": "wolf",
    "ma_sói": "wolf",
    "wolfseer": "wolf_seer",
    "wolf-seer": "wolf_seer",
    "sói_tiên_tri": "wolf_seer",
    "wolfshaman": "wolf_shaman",
    "wolf-shaman": "wolf_shaman",
    "sói_pháp_sư": "wolf_shaman",
    "nightmare_wolf": "nightmare_wolf",
    "nightmare-wolf": "nightmare_wolf",
    "medium": "medium",
    "thầy_đồng": "medium",
    "jailer": "jailer",
    "quản_ngục": "jailer",
    "jester": "jester",
    "thằng_ngố": "jester",
    "serial_killer": "serial_killer",
    "kẻ_giết_người_hàng_loạt": "serial_killer",
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
    random = __import__("random")
    random.shuffle(ids)
    n = len(ids)
    result: dict[str, str] = {}

    if n == 0:
        return result

    specials: list[str] = []
    if n >= 5:
        specials.append("seer")
    if n >= 6:
        specials.append("protector")
    if n >= 7:
        specials.append(random.choice(["wolf_seer", "wolf_shaman"]))
    if n >= 8:
        specials.append(random.choice(["jester", "serial_killer", "medium", "jailer"]))
    if n >= 9:
        specials.append("nightmare_wolf")

    for uid, role_key in zip(ids, specials):
        result[uid] = role_key

    remaining = ids[len(specials):]
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
        "kills": [],
        "private_dms": [],
        "public_messages": [],
        "inspect_results": [],
        "protects": [],
        "revives": [],
        "jail_target_id": None,
        "wolf_shaman_cover_target_id": None,
        "nightmare_token_target_id": None,
    }

    for action in actions:
        a_type = action.get("type")
        actor = action.get("actor")
        actor_id = action.get("actor_id")
        target_id = action.get("target_id")
        target_id_str = None

        if target_id is not None:
            try:
                target_id_str = str(int(target_id))
            except Exception:
                target_id_str = None

        if a_type in {"inspect", "wolf_inspect", "inspect_guard"}:
            if target_id_str is None or target_id_str not in game.players:
                continue
            target = game.players[target_id_str]
            target_name = target.get("name", "Unknown")
            target_role_key = target.get("role", DEFAULT_ROLE_KEY)
            target_role_label = _role_label(target_role_key)

            cover_target = getattr(game, "wolf_shaman_cover_target_id", None)
            cover_round = getattr(game, "wolf_shaman_cover_round", None)
            fake_label = _role_label("wolf_shaman")
            if (
                cover_target is not None
                and str(cover_target) == target_id_str
                and cover_round == getattr(game, "round_no", None)
                and a_type in {"inspect", "wolf_inspect"}
            ):
                target_role_label = fake_label

            plan["inspect_results"].append(
                {
                    "actor_id": str(actor_id) if actor_id is not None else None,
                    "target_id": target_id_str,
                    "target_name": target_name,
                    "role_label": target_role_label,
                    "role_key": target_role_key,
                }
            )
            plan["private_dms"].append((str(actor_id), f"🔎 {target_name} là **{target_role_label}**."))
            if a_type == "inspect_guard" and game.role_team(target_role_key) == TEAM_WOLF:
                plan["private_dms"].append((target_id_str, f"🕵️ Bạn đã bị **{_safe_name(actor)}** soi."))
            continue

        if a_type == "protect":
            if target_id_str is not None:
                plan["protects"].append(
                    {
                        "protector_id": str(actor_id) if actor_id is not None else None,
                        "target_id": target_id_str,
                    }
                )
            continue

        if a_type == "mark_blind":
            if target_id_str is not None:
                plan["wolf_shaman_cover_target_id"] = int(target_id_str)
            continue

        if a_type == "jail":
            if target_id_str is not None:
                plan["jail_target_id"] = int(target_id_str)
            continue

        if a_type == "revive":
            if target_id_str is not None:
                plan["revives"].append(
                    {
                        "actor_id": str(actor_id) if actor_id is not None else None,
                        "target_id": target_id_str,
                    }
                )
            continue

        if a_type == "nightmare":
            if target_id_str is not None:
                plan["nightmare_token_target_id"] = int(target_id_str)
            continue

        if a_type in {"kill", "shoot"}:
            if target_id_str is not None:
                plan["kills"].append(
                    {
                        "actor_id": str(actor_id) if actor_id is not None else None,
                        "target_id": target_id_str,
                        "source_role_key": action.get("role_key"),
                        "source_type": a_type,
                    }
                )
            if a_type == "shoot" and target_id_str is not None and target_id_str in game.players:
                target = game.players[target_id_str]
                plan["public_messages"].append(
                    f"🔫 **{_safe_name(actor)}** đã nổ súng vào **{target.get('name', 'Unknown')}** và lộ vai trò của mình: **{_role_label(action.get('role_key', 'guard'))}**."
                )
            continue

    return plan


async def apply_action_plan(game, plan: dict[str, Any]) -> None:
    if plan.get("wolf_shaman_cover_target_id") is not None:
        game.wolf_shaman_cover_target_id = plan["wolf_shaman_cover_target_id"]
        game.wolf_shaman_cover_round = getattr(game, "round_no", 1)

    if plan.get("jail_target_id") is not None:
        game.jailer_target_id = plan["jail_target_id"]

    if plan.get("nightmare_token_target_id") is not None:
        game.nightmare_token_target_id = plan["nightmare_token_target_id"]

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

    for revive in plan.get("revives", []):
        try:
            await game.revive_player(revive["target_id"], source_role_key="medium")
        except Exception:
            pass

    if plan.get("protects"):
        if not hasattr(game, "active_protections"):
            game.active_protections = {}
        for item in plan["protects"]:
            protector_id = item.get("protector_id")
            target_id = item.get("target_id")
            if protector_id and target_id:
                game.active_protections[str(target_id)] = str(protector_id)

    for kill in plan.get("kills", []):
        try:
            await game.resolve_kill_event(kill["target_id"], kill.get("source_role_key"), kill.get("actor_id"))
        except Exception:
            pass

    if plan.get("jail_target_id") is not None:
        try:
            await game.open_jail_room()
        except Exception:
            pass


def build_day_actions(game) -> list[dict[str, Any]]:
    return build_night_actions(game)
