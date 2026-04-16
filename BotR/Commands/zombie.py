import asyncio
import copy
import json
import os
import random
import time
from threading import Lock
from typing import Any, Dict, List, Optional, Set, Tuple

import discord
from discord.ui import Modal, Select, TextInput, View

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

INV_FILE = os.path.join(BASE_DIR, "Data", "inventory.json")
TEAM_FILE = os.path.join(BASE_DIR, "Data", "team.json")
WAIFU_FILE = os.path.join(BASE_DIR, "Data", "waifu_data.json")

INV_LOCK = asyncio.Lock()
SESSION_LOCK = asyncio.Lock()
FILE_LOCK = Lock()

ACTIVE_ZOMBIE_SESSIONS: Dict[str, "ZombieSession"] = {}

ITEM_META = {
    "soup": {
        "label": "Soup",
        "price": 100,
        "desc": "+5 love",
    },
    "pizza": {
        "label": "Pizza",
        "price": 200,
        "desc": "+10~30 love",
    },
    "drug": {
        "label": "Drug",
        "price": 300,
        "desc": "+30~50 love",
    },
    "health_potion": {
        "label": "Health Potion",
        "price": 500,
        "desc": "Heal 10~20% max HP",
    },
    "damage_potion": {
        "label": "Damage Potion",
        "price": 600,
        "desc": "+10~20% damage for 1 battle",
    },
}

ALLOWED_ZOMBIE_ITEMS = ["health_potion", "damage_potion"]
REWARD_ITEMS = ["soup", "pizza", "drug", "health_potion", "damage_potion"]

RANK_STATS = {
    "thuong": (110, 12, 6),
    "anh_hung": (145, 14, 7),
    "huyen_thoai": (180, 16, 8),
    "truyen_thuyet": (220, 18, 9),
    "toi_thuong": (260, 20, 10),
    "limited": (300, 22, 11),
}

RANK_ORDER = [
    "limited",
    "toi_thuong",
    "truyen_thuyet",
    "huyen_thoai",
    "anh_hung",
    "thuong",
]


# ========= JSON =========
def load_json(path):
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception as e:
        print(f"[zombie.py] load_json error: {path} -> {e}")
        return {}


def _atomic_write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def save_json(path, data):
    try:
        _atomic_write_json(path, data)
    except Exception as e:
        print(f"[zombie.py] save_json error: {path} -> {e}")


# ========= DISCORD HELPERS =========
def get_user_obj(ctx):
    return getattr(ctx, "user", None) or getattr(ctx, "author", None)


async def _defer_if_needed(ctx, ephemeral: bool = False):
    if isinstance(ctx, discord.Interaction) and not ctx.response.is_done():
        try:
            await ctx.response.defer(ephemeral=ephemeral)
        except Exception:
            pass


async def send_like(ctx, content=None, embed=None, view=None, ephemeral: bool = False):
    kwargs = {}
    if content is not None:
        kwargs["content"] = content
    if embed is not None:
        kwargs["embed"] = embed
    if view is not None:
        kwargs["view"] = view

    if isinstance(ctx, discord.Interaction):
        if not ctx.response.is_done():
            await ctx.response.send_message(**kwargs, ephemeral=ephemeral)
            try:
                return await ctx.original_response()
            except Exception:
                return None
        return await ctx.followup.send(**kwargs, ephemeral=ephemeral)

    if hasattr(ctx, "channel") and ctx.channel is not None:
        return await ctx.channel.send(**kwargs)

    return None


async def edit_like(msg, content=None, embed=None, view=None):
    try:
        kwargs = {}
        if content is not None:
            kwargs["content"] = content
        if embed is not None:
            kwargs["embed"] = embed
        if view is not None:
            kwargs["view"] = view
        return await msg.edit(**kwargs)
    except Exception as e:
        print(f"[zombie.py] edit_like error: {e}")
        return None


def make_embed(title: str, description: str, color: discord.Color):
    return discord.Embed(title=title, description=description, color=color)


def clamp(n, low, high):
    return max(low, min(high, n))


def hp_bar(current, max_hp, length=10):
    max_hp = max(1, int(max_hp))
    current = clamp(int(current), 0, max_hp)
    filled = int((current / max_hp) * length)
    return "█" * filled + "░" * (length - filled)


def fmt_hp(hp: int, max_hp: int) -> str:
    return f"`{max(0, int(hp)):,}/{max(1, int(max_hp)):,}`"


def display_name_from_ctx(ctx, uid: str, fallback: str = None) -> str:
    uid = str(uid)
    guild = getattr(ctx, "guild", None)
    if guild and uid.isdigit():
        member = guild.get_member(int(uid))
        if member:
            return member.display_name

    bot = getattr(ctx, "bot", None)
    if bot and uid.isdigit():
        try:
            user = bot.get_user(int(uid))
            if user:
                return getattr(user, "global_name", None) or user.name
        except Exception:
            pass

    return fallback or f"<@{uid}>"


# ========= INVENTORY =========
def ensure_user_schema(inv: Dict[str, Any], uid: str) -> Dict[str, Any]:
    uid = str(uid)
    user = inv.get(uid)
    if not isinstance(user, dict):
        user = {}
        inv[uid] = user

    if not isinstance(user.get("waifus"), dict):
        user["waifus"] = {}
    if not isinstance(user.get("bag"), dict):
        user["bag"] = {}
    if not isinstance(user.get("bag_item"), dict):
        user["bag_item"] = {}
    if "default_waifu" not in user:
        user["default_waifu"] = None
    if not isinstance(user.get("gold"), int):
        try:
            user["gold"] = int(user.get("gold", 0))
        except Exception:
            user["gold"] = 0
    return user


def get_item_count(inv: Dict[str, Any], uid: str, item_key: str) -> int:
    user = inv.get(str(uid), {})
    bag_item = user.get("bag_item", {})
    try:
        return max(0, int(bag_item.get(item_key, 0)))
    except Exception:
        return 0


def add_item(inv: Dict[str, Any], uid: str, item_key: str, qty: int):
    uid = str(uid)
    qty = max(0, int(qty))
    if qty <= 0:
        return
    user = ensure_user_schema(inv, uid)
    bag_item = user["bag_item"]
    bag_item[item_key] = max(0, int(bag_item.get(item_key, 0))) + qty


def remove_item(inv: Dict[str, Any], uid: str, item_key: str, qty: int) -> bool:
    uid = str(uid)
    qty = max(0, int(qty))
    if qty <= 0:
        return False
    user = ensure_user_schema(inv, uid)
    bag_item = user["bag_item"]
    current = max(0, int(bag_item.get(item_key, 0)))
    if current < qty:
        return False
    bag_item[item_key] = current - qty
    return True


def get_team_source(team_data, uid):
    user_data = team_data.get(str(uid), team_data.get(uid, {}))

    if isinstance(user_data, list):
        return list(user_data)

    if not isinstance(user_data, dict):
        return []

    for key in ("team", "waifus", "members", "list"):
        value = user_data.get(key)
        if isinstance(value, list):
            return list(value)

    return []


def normalize_team_ids(inv, uid, team_data=None):
    team_data = team_data or {}
    source = get_team_source(team_data, uid)

    user = inv.get(str(uid), {})
    waifus = user.get("waifus", {})

    if isinstance(waifus, list):
        waifus = {str(w): 0 for w in waifus}

    if not source:
        default_id = user.get("default_waifu")
        if isinstance(default_id, (str, int)):
            source = [default_id]
        elif isinstance(waifus, dict):
            source = list(waifus.keys())

    out = []
    seen = set()

    for wid in source:
        if not isinstance(wid, (str, int)):
            continue
        wid = str(wid)

        if wid in seen:
            continue

        if isinstance(waifus, dict) and wid in waifus:
            out.append(wid)
            seen.add(wid)

        if len(out) >= 3:
            break

    return out


def ensure_waifus_dict(user_record: dict) -> dict:
    waifus = user_record.get("waifus", {})
    if isinstance(waifus, list):
        waifus = {str(w): 0 for w in waifus}
        user_record["waifus"] = waifus
    elif not isinstance(waifus, dict):
        waifus = {}
        user_record["waifus"] = waifus
    return waifus


def get_love(inv, uid, wid):
    uid = str(uid)
    wid = str(wid)

    user = inv.get(uid, {})
    waifus = user.get("waifus", {})

    if isinstance(waifus, list):
        waifus = {str(w): 0 for w in waifus}

    val = waifus.get(wid, 0)
    if isinstance(val, dict):
        val = val.get("love", val.get("amount", 0))

    try:
        return max(0, int(val))
    except Exception:
        return 0


def set_love(inv, uid, wid, val):
    uid = str(uid)
    wid = str(wid)
    user = inv.setdefault(uid, {})
    waifus = ensure_waifus_dict(user)

    current = waifus.get(wid)
    new_val = max(0, int(val))

    if isinstance(current, dict):
        current["love"] = new_val
        if "amount" in current:
            current["amount"] = new_val
    else:
        waifus[wid] = new_val


def get_waifu_meta(waifu_data: Dict[str, Any], wid: str) -> Dict[str, Any]:
    meta = waifu_data.get(str(wid), {})
    return meta if isinstance(meta, dict) else {}


def build_party_member(uid: str, wid: str, inv: Dict[str, Any], waifu_data: Dict[str, Any]) -> Dict[str, Any]:
    uid = str(uid)
    wid = str(wid)

    love = get_love(inv, uid, wid)
    meta = get_waifu_meta(waifu_data, wid)
    rank = str(meta.get("rank", "thuong")).lower()
    if rank not in RANK_ORDER:
        rank = "thuong"

    base_hp, base_dmg, base_spd = RANK_STATS.get(rank, RANK_STATS["thuong"])

    max_hp = base_hp + (love // 10) + 120
    damage = base_dmg + (love // 30) + 12
    speed = base_spd + (love // 25) + 5

    max_hp = max(1, int(max_hp))
    damage = max(1, int(damage))
    speed = max(1, int(speed))

    name = meta.get("name") or meta.get("display_name") or wid

    return {
        "uid": uid,
        "wid": wid,
        "name": name,
        "rank": rank,
        "love": love,
        "max_hp": max_hp,
        "hp": max_hp,
        "damage": damage,
        "speed": speed,
        "alive": True,
        "temp_dmg_pct": 0.0,
    }


def get_team_members(inv, uid, team_data, waifu_data):
    team_ids = normalize_team_ids(inv, uid, team_data)
    out = []
    for wid in team_ids:
        out.append(build_party_member(uid, wid, inv, waifu_data))
    return out


# ========= ZOMBIE ENEMY =========
def build_zombie(level: int) -> Dict[str, Any]:
    level = max(1, int(level))
    if level % 10 == 0:
        kind = "boss"
        name = f"Boss Zombie Lv.{level}"
        hp = 1400 + level * 260
        dmg = 80 + level * 18
        spd = 30 + level * 3
        color = discord.Color.dark_red()
    elif level >= 10 and random.random() < 0.35:
        kind = "miniboss"
        name = f"Mini Boss Zombie Lv.{level}"
        hp = 900 + level * 180
        dmg = 55 + level * 14
        spd = 24 + level * 2
        color = discord.Color.orange()
    else:
        kind = "normal"
        name = f"Zombie Lv.{level}"
        hp = 350 + level * 110
        dmg = 28 + level * 10
        spd = 16 + level * 2
        color = discord.Color.green()

    return {
        "kind": kind,
        "name": name,
        "hp": int(hp),
        "max_hp": int(hp),
        "damage": int(dmg),
        "speed": int(spd),
        "color": color,
    }


# ========= REWARD =========
def random_reward(level: int) -> Tuple[str, int]:
    level = max(1, int(level))
    if random.random() < 0.55:
        gold = random.randint(60, 140) * level
        return "gold", gold
    item = random.choice(REWARD_ITEMS)
    qty = 1 if random.random() < 0.80 else 2
    return item, qty


# ========= SESSION =========
class ZombieSession:
    def __init__(self, ctx):
        self.ctx = ctx
        self.user = get_user_obj(ctx)
        self.uid = str(self.user.id)

        self.inv = {}
        self.waifu_data = {}
        self.team_data = {}

        self.party: List[Dict[str, Any]] = []
        self.level = 1
        self.in_battle = False
        self.ended = False
        self.logs: List[str] = []
        self.message = None

        self.load_state()
        self.rebuild_party()

    def load_state(self):
        self.inv = load_json(INV_FILE)
        self.waifu_data = load_json(WAIFU_FILE)
        self.team_data = load_json(TEAM_FILE)
        ensure_user_schema(self.inv, self.uid)

    def save_state(self):
        save_json(INV_FILE, self.inv)

    def finish(self):
        self.ended = True
        ACTIVE_ZOMBIE_SESSIONS.pop(self.uid, None)

    def rebuild_party(self, preserve_hp: bool = True):
        old_state = {}
        if preserve_hp:
            for c in self.party:
                old_state[c["wid"]] = {
                    "hp": c.get("hp", c.get("max_hp", 1)),
                    "buff": float(c.get("temp_dmg_pct", 0.0)),
                    "alive": bool(c.get("alive", True)),
                }

        self.party = get_team_members(self.inv, self.uid, self.team_data, self.waifu_data)

        for c in self.party:
            state = old_state.get(c["wid"])
            if state:
                c["hp"] = clamp(int(state["hp"]), 0, c["max_hp"])
                c["temp_dmg_pct"] = float(state["buff"])
                c["alive"] = bool(state["alive"]) and c["hp"] > 0

    def alive_party(self) -> List[Dict[str, Any]]:
        return [c for c in self.party if c["alive"] and c["hp"] > 0]

    def party_dead(self) -> bool:
        return len(self.alive_party()) == 0

    def log(self, text: str):
        self.logs.append(text)
        if len(self.logs) > 10:
            self.logs = self.logs[-10:]

    def clear_temp_buffs(self):
        for c in self.party:
            c["temp_dmg_pct"] = 0.0

    def member_by_wid(self, wid: str) -> Optional[Dict[str, Any]]:
        wid = str(wid)
        for c in self.party:
            if c["wid"] == wid:
                return c
        return None

    def use_potion(self, wid: str, item_key: str, qty: int) -> Tuple[bool, str]:
        wid = str(wid)
        qty = max(1, int(qty))
        member = self.member_by_wid(wid)
        if not member:
            return False, "Không tìm thấy waifu."

        if item_key not in ALLOWED_ZOMBIE_ITEMS:
            return False, "Item này không được dùng trong zombie."

        if not remove_item(self.inv, self.uid, item_key, qty):
            return False, "Bạn không đủ item."

        if item_key == "health_potion":
            heal_total = 0
            for _ in range(qty):
                pct = random.uniform(0.10, 0.20)
                heal_total += max(1, int(member["max_hp"] * pct))

            old_hp = member["hp"]
            member["hp"] = clamp(member["hp"] + heal_total, 0, member["max_hp"])
            if member["hp"] > 0:
                member["alive"] = True

            gained = member["hp"] - old_hp
            self.save_state()
            self.log(f"🧪 {member['name']} hồi {gained} HP bằng Health Potion.")
            return True, f"Đã dùng {qty} Health Potion lên {member['name']}."

        if item_key == "damage_potion":
            if member["hp"] <= 0:
                return False, "Waifu này đã gục, không thể buff damage."
            boost_total = 0.0
            for _ in range(qty):
                boost_total += random.uniform(0.10, 0.20)
            member["temp_dmg_pct"] = float(member.get("temp_dmg_pct", 0.0)) + boost_total
            self.save_state()
            self.log(f"⚔️ {member['name']} nhận +{boost_total * 100:.0f}% damage trong 1 trận.")
            return True, f"Đã dùng {qty} Damage Potion lên {member['name']}."

        return False, "Item không hợp lệ."

    def render_menu(self) -> discord.Embed:
        embed = discord.Embed(
            title=f"🧟 Zombie Hunt — {display_name_from_ctx(self.ctx, self.uid)}",
            description=(
                f"**Level hiện tại:** `{self.level}`\n"
                f"Boss xuất hiện mỗi 10 level. Mini boss có thể xuất hiện sau level 10.\n"
                f"Không có hồi máu tự động giữa các level."
            ),
            color=discord.Color.dark_green(),
        )

        if not self.party:
            embed.add_field(name="Team", value="Không tìm thấy team hợp lệ.", inline=False)
        else:
            lines = []
            for idx, c in enumerate(self.party[:3], start=1):
                status = "☠️" if c["hp"] <= 0 else "❤️"
                lines.append(
                    f"{idx}. {status} **{c['name']}** | HP {fmt_hp(c['hp'], c['max_hp'])} `{hp_bar(c['hp'], c['max_hp'])}` | "
                    f"DMG `{c['damage']}` | SPD `{c['speed']}`"
                )
            embed.add_field(name="Team", value="\n".join(lines)[:1024], inline=False)

        embed.add_field(
            name="Hướng dẫn",
            value="`Chiến trận tiếp theo` để đánh level mới. `Sử dụng item` để chọn waifu và dùng potion trước trận.",
            inline=False,
        )

        if self.logs:
            embed.add_field(name="Log gần nhất", value="\n".join(self.logs[-5:])[:1024], inline=False)

        embed.set_footer(text="Chỉ health potion và damage potion được dùng trong zombie.")
        return embed

    def render_battle(self, zombie: Dict[str, Any]) -> discord.Embed:
        embed = discord.Embed(
            title=f"⚔️ {display_name_from_ctx(self.ctx, self.uid)} vs {zombie['name']}",
            description=f"Level `{self.level}` • `{zombie['kind']}`",
            color=zombie["color"],
        )
        if self.party:
            party_lines = []
            for c in self.party:
                status = "☠️" if c["hp"] <= 0 else "❤️"
                buff = f" (+{int(c['temp_dmg_pct'] * 100)}% DMG)" if c.get("temp_dmg_pct", 0) else ""
                party_lines.append(
                    f"{status} **{c['name']}** | HP {fmt_hp(c['hp'], c['max_hp'])} `{hp_bar(c['hp'], c['max_hp'])}` | "
                    f"DMG `{c['damage']}`{buff}"
                )
            embed.add_field(name="Party", value="\n".join(party_lines)[:1024], inline=False)
        else:
            embed.add_field(name="Party", value="Không còn waifu nào.", inline=False)

        embed.add_field(
            name=zombie["name"],
            value=(
                f"HP {fmt_hp(zombie['hp'], zombie['max_hp'])} `{hp_bar(zombie['hp'], zombie['max_hp'])}`\n"
                f"DMG `{zombie['damage']}` | SPD `{zombie['speed']}`"
            ),
            inline=False,
        )
        if self.logs:
            embed.add_field(name="Diễn biến", value="\n".join(self.logs[-6:])[:1024], inline=False)
        return embed

    def render_reward(self, title: str, desc: str) -> discord.Embed:
        embed = discord.Embed(title=title, description=desc, color=discord.Color.gold())
        embed.add_field(name="Level", value=str(self.level), inline=True)
        embed.add_field(name="Party còn sống", value=str(len(self.alive_party())), inline=True)
        if self.logs:
            embed.add_field(name="Log", value="\n".join(self.logs[-5:])[:1024], inline=False)
        return embed

    def render_end(self) -> discord.Embed:
        return make_embed(
            "⚠️ Hôm nay bạn đã đấu quá nhiều rồi, nghĩ ngơi đi",
            "Không còn waifu đủ sức để tiếp tục săn zombie.",
            discord.Color.orange(),
        )

    def render_win(self) -> discord.Embed:
        return make_embed(
            "🎉 Vượt qua một level!",
            f"Bạn đã vượt qua level `{self.level}`.",
            discord.Color.green(),
        )

    def attack_roll(self, attacker, defender, is_zombie=False) -> int:
        if is_zombie:
            base = int(attacker["damage"] * random.uniform(0.90, 1.10))
            return max(1, base)

        boost_pct = float(attacker.get("temp_dmg_pct", 0.0))
        base_damage = int(attacker["damage"] * random.uniform(0.90, 1.10) * (1 + boost_pct))
        crit = random.random() < min(0.35, 0.04 + attacker["love"] / 2000.0)
        if crit:
            base_damage = int(base_damage * random.uniform(1.25, 1.50))
            self.log(f"💥 {attacker['name']} chí mạng!")
        return max(1, base_damage)

    async def battle_round(self, zombie: Dict[str, Any], msg, view):
        alive = self.alive_party()
        if not alive:
            return

        party_total_spd = sum(c["speed"] for c in alive)
        zombie_roll = zombie["speed"] + random.randint(0, max(1, zombie["speed"] // 4 + 1))
        party_roll = party_total_spd + random.randint(0, max(1, party_total_spd // 4 + 1))
        party_first = party_roll >= zombie_roll

        if party_first:
            attacker = random.choices(alive, weights=[max(1, c["speed"]) for c in alive], k=1)[0]
            dmg = self.attack_roll(attacker, zombie, is_zombie=False)
            zombie["hp"] = max(0, zombie["hp"] - dmg)
            self.log(f"⚔️ {attacker['name']} gây {dmg} damage lên zombie.")
            await edit_like(msg, embed=self.render_battle(zombie), view=view)
            await asyncio.sleep(1.1)

            if zombie["hp"] <= 0:
                return

            target = random.choice(self.alive_party())
            z_dmg = self.attack_roll(zombie, target, is_zombie=True)
            target["hp"] = max(0, target["hp"] - z_dmg)
            self.log(f"☠️ {zombie['name']} phản công {target['name']} gây {z_dmg}.")
            if target["hp"] <= 0:
                target["alive"] = False
                self.log(f"💀 {target['name']} đã gục.")
        else:
            target = random.choice(self.alive_party())
            z_dmg = self.attack_roll(zombie, target, is_zombie=True)
            target["hp"] = max(0, target["hp"] - z_dmg)
            self.log(f"☠️ {zombie['name']} đánh trước {target['name']} gây {z_dmg}.")
            if target["hp"] <= 0:
                target["alive"] = False
                self.log(f"💀 {target['name']} đã gục.")

            await edit_like(msg, embed=self.render_battle(zombie), view=view)
            await asyncio.sleep(1.1)

            if not self.alive_party():
                return

            attacker = random.choices(
                self.alive_party(),
                weights=[max(1, c["speed"]) for c in self.alive_party()],
                k=1,
            )[0]
            dmg = self.attack_roll(attacker, zombie, is_zombie=False)
            zombie["hp"] = max(0, zombie["hp"] - dmg)
            self.log(f"⚔️ {attacker['name']} gây {dmg} damage lên zombie.")

        await edit_like(msg, embed=self.render_battle(zombie), view=view)
        await asyncio.sleep(1.1)

    async def run_level(self, msg, view) -> bool:
        self.in_battle = True
        self.logs = []

        zombie = build_zombie(self.level)
        await edit_like(msg, embed=self.render_battle(zombie), view=view)

        turn_limit = 16 if zombie["kind"] == "boss" else 12 if zombie["kind"] == "miniboss" else 10

        for _ in range(turn_limit):
            if zombie["hp"] <= 0:
                break
            if self.party_dead():
                self.in_battle = False
                return False
            await self.battle_round(zombie, msg, view)

        self.in_battle = False
        return zombie["hp"] <= 0

    def reward_level(self):
        kind, value = random_reward(self.level)
        if kind == "gold":
            user = ensure_user_schema(self.inv, self.uid)
            user["gold"] = int(user.get("gold", 0)) + int(value)
            self.save_state()
            return f"💰 Nhận **{value:,} gold**."
        add_item(self.inv, self.uid, kind, value)
        self.save_state()
        return f"🎁 Nhận **{value} {ITEM_META[kind]['label']}**."

    async def play_next_level(self, msg, view):
        if self.ended:
            return

        self.load_state()
        self.rebuild_party(preserve_hp=True)

        if self.party_dead():
            self.ended = True
            self.finish()
            await edit_like(msg, embed=self.render_end(), view=view)
            return

        battle_ok = await self.run_level(msg, view)
        if not battle_ok:
            self.ended = True
            self.finish()
            await edit_like(msg, embed=self.render_end(), view=view)
            return

        reward_text = self.reward_level()
        self.logs.append(reward_text)
        self.level += 1
        self.clear_temp_buffs()
        self.save_state()

        self.rebuild_party(preserve_hp=True)
        if self.party_dead():
            self.ended = True
            self.finish()
            await edit_like(msg, embed=self.render_end(), view=view)
            return

        reward_embed = self.render_reward("✅ Vượt qua zombie", reward_text)
        await edit_like(msg, embed=reward_embed, view=view)
        self.in_battle = False


# ========= ITEM FLOW =========
class ZombieQuantityModal(Modal):
    def __init__(self, session: ZombieSession, target_wid: str, item_key: str):
        super().__init__(title=f"Dùng {ITEM_META[item_key]['label']}")
        self.session = session
        self.target_wid = target_wid
        self.item_key = item_key

        self.qty_input = TextInput(
            label="Số lượng",
            placeholder="Nhập số lượng item cần dùng",
            required=True,
        )
        self.add_item(self.qty_input)

    async def on_submit(self, interaction: discord.Interaction):
        await _defer_if_needed(interaction, ephemeral=True)

        if self.session.in_battle:
            return await interaction.followup.send("❌ Đang đánh zombie nên không thể dùng item.", ephemeral=True)

        try:
            qty = int(self.qty_input.value)
        except Exception:
            return await interaction.followup.send("❌ Số lượng không hợp lệ.", ephemeral=True)

        if qty <= 0:
            return await interaction.followup.send("❌ Số lượng phải > 0.", ephemeral=True)

        ok, msg = self.session.use_potion(self.target_wid, self.item_key, qty)
        if not ok:
            return await interaction.followup.send(f"❌ {msg}", ephemeral=True)

        await interaction.followup.send(f"✅ {msg}", ephemeral=True)


class ZombiePotionSelect(Select):
    def __init__(self, session: ZombieSession, target_wid: str):
        self.session = session
        self.target_wid = target_wid

        options = []
        for key in ALLOWED_ZOMBIE_ITEMS:
            meta = ITEM_META[key]
            count = get_item_count(self.session.inv, self.session.uid, key)
            options.append(
                discord.SelectOption(
                    label=f"{meta['label']} ({count})"[:100],
                    value=key,
                    description=meta["desc"][:100],
                )
            )

        super().__init__(
            placeholder="Chọn potion",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction):
        if self.session.in_battle:
            return await interaction.response.send_message(
                "❌ Đang đánh zombie nên không thể dùng item.",
                ephemeral=True,
            )

        item_key = self.values[0]
        if get_item_count(self.session.inv, self.session.uid, item_key) <= 0:
            return await interaction.response.send_message("❌ Bạn không còn item này.", ephemeral=True)

        await interaction.response.send_modal(ZombieQuantityModal(self.session, self.target_wid, item_key))


class ZombiePotionView(View):
    def __init__(self, session: ZombieSession, target_wid: str):
        super().__init__(timeout=120)
        self.add_item(ZombiePotionSelect(session, target_wid))


class ZombieTargetSelect(Select):
    def __init__(self, session: ZombieSession):
        self.session = session
        options = []

        for idx, c in enumerate(self.session.party[:3], start=1):
            options.append(
                discord.SelectOption(
                    label=f"{idx}. {c['name']}"[:100],
                    value=c["wid"],
                    description=f"HP {c['hp']}/{c['max_hp']}"[:100],
                )
            )

        if not options:
            options = [discord.SelectOption(label="Không có waifu", value="none")]

        super().__init__(
            placeholder="Chọn waifu để dùng potion",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction):
        wid = self.values[0]
        if wid == "none":
            return await interaction.response.send_message("❌ Không có waifu phù hợp.", ephemeral=True)

        if self.session.in_battle:
            return await interaction.response.send_message(
                "❌ Đang đánh zombie nên không thể dùng item.",
                ephemeral=True,
            )

        view = ZombiePotionView(self.session, wid)
        embed = make_embed(
            "🧪 Chọn potion",
            f"Chọn item để dùng cho **{display_name_from_ctx(self.session.ctx, self.session.uid)}**",
            discord.Color.blurple(),
        )
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


class ZombieTargetView(View):
    def __init__(self, session: ZombieSession):
        super().__init__(timeout=120)
        self.add_item(ZombieTargetSelect(session))


# ========= MAIN VIEW =========
class ZombieMenuView(View):
    def __init__(self, session: ZombieSession):
        super().__init__(timeout=None)
        self.session = session

    def disable_all(self):
        for item in self.children:
            item.disabled = True

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        uid = str(interaction.user.id)
        if uid != self.session.uid:
            await interaction.response.send_message("❌ Chỉ chủ lệnh mới dùng được.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Chiến trận tiếp theo", style=discord.ButtonStyle.red)
    async def next_battle(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.session.ended:
            return await interaction.response.send_message("❌ Phiên săn zombie đã kết thúc.", ephemeral=True)

        if self.session.in_battle:
            return await interaction.response.send_message("❌ Đang đánh zombie, chờ xong đã.", ephemeral=True)

        await interaction.response.defer()
        await self.session.play_next_level(self.session.message, self)

    @discord.ui.button(label="Sử dụng item", style=discord.ButtonStyle.green)
    async def use_item(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.session.ended:
            return await interaction.response.send_message("❌ Phiên săn zombie đã kết thúc.", ephemeral=True)

        if self.session.in_battle:
            return await interaction.response.send_message(
                "❌ Đang đánh zombie nên không thể dùng item.",
                ephemeral=True,
            )

        embed = make_embed(
            "🧪 Chọn waifu",
            "Chọn 1 trong 3 waifu đầu team để dùng potion trước khi vào trận.",
            discord.Color.green(),
        )
        await interaction.response.send_message(embed=embed, view=ZombieTargetView(self.session), ephemeral=True)


# ========= LOGIC =========
async def zombie_logic(ctx):
    await _defer_if_needed(ctx)

    user = get_user_obj(ctx)
    if not user:
        return await send_like(
            ctx,
            embed=make_embed("❌ Lỗi", "Không xác định được người dùng.", discord.Color.red()),
        )

    uid = str(user.id)

    async with SESSION_LOCK:
        old_session = ACTIVE_ZOMBIE_SESSIONS.get(uid)
        if old_session and not old_session.ended:
            return await send_like(
                ctx,
                embed=make_embed(
                    "⚠️ Đang có phiên zombie",
                    "Bạn đang có một phiên săn zombie đang chạy rồi.",
                    discord.Color.orange(),
                ),
            )

        session = ZombieSession(ctx)
        ACTIVE_ZOMBIE_SESSIONS[uid] = session

    if not session.party:
        session.finish()
        return await send_like(
            ctx,
            embed=make_embed(
                "⚠️ Không có team",
                "Bạn chưa có team hợp lệ để đi săn zombie.",
                discord.Color.orange(),
            ),
        )

    start_embed = session.render_menu()
    view = ZombieMenuView(session)

    msg = await send_like(ctx, embed=start_embed, view=view)
    if msg is None:
        session.finish()
        return

    session.message = msg
    return


print("Loaded zombie has success")