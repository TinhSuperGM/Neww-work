import asyncio
import copy
import json
import os
import random
import re
import time
from threading import Lock
from typing import Dict, List, Optional, Set, Tuple

import discord
from Data import data_user
from Commands.lock import is_user_locked

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

INV_FILE = os.path.join(BASE_DIR, "Data", "inventory.json")
TEAM_FILE = os.path.join(BASE_DIR, "Data", "team.json")
WAIFU_FILE = os.path.join(BASE_DIR, "Data", "waifu_data.json")
COOLDOWN_FILE = os.path.join(BASE_DIR, "Data", "cooldown.json")

MAX_ROUNDS = 30
ACTION_DELAY = 2
MAX_LOG_LINES = 12
LOVE_DROP_RATE = 0.10
COOLDOWN_HOURS = 8

MAX_HP_CAP = 5000
MAX_DMG_CAP = 500
MAX_SPEED_CAP = 200

HEAL_ON_CRIT_CHANCE = 0.20
COMBO_CRIT_CHANCE = 0.25
CRIT_HEAL_MIN = 0.10
CRIT_HEAL_MAX = 0.14
CRIT_HEAL_COMBO_MIN = 0.14
CRIT_HEAL_COMBO_MAX = 0.20

INV_LOCK = asyncio.Lock()
GOLD_LOCK = asyncio.Lock()
BATTLE_STATE_LOCK = asyncio.Lock()
COOLDOWN_LOCK = Lock()

ACTIVE_BATTLE_USERS: Set[str] = set()
COOLDOWNS: Dict[str, float] = {}

RANK_ORDER = [
    "limited",
    "toi_thuong",
    "truyen_thuyet",
    "huyen_thoai",
    "anh_hung",
    "thuong",
]

RANK_STATS = {
    "thuong": (100, 10, 5),
    "anh_hung": (130, 12, 6),
    "huyen_thoai": (160, 14, 7),
    "truyen_thuyet": (190, 16, 8),
    "toi_thuong": (230, 18, 9),
    "limited": (270, 20, 10),
}

CRIT_BASE = {
    "thuong": 0.04,
    "anh_hung": 0.05,
    "huyen_thoai": 0.06,
    "truyen_thuyet": 0.07,
    "toi_thuong": 0.08,
    "limited": 0.10,
}

LIFESTEAL_BASE = {
    "thuong": 0.02,
    "anh_hung": 0.03,
    "huyen_thoai": 0.04,
    "truyen_thuyet": 0.05,
    "toi_thuong": 0.06,
    "limited": 0.08,
}


# ===== JSON =====
def load_json(path):
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception as e:
        print(f"[fight.py] load_json error: {path} -> {e}")
        return {}


def _atomic_write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp_path = f"{path}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp_path, path)


def save_json(path, data):
    try:
        _atomic_write_json(path, data)
    except Exception as e:
        print(f"[fight.py] save_json error: {path} -> {e}")


def load_cooldowns() -> Dict[str, float]:
    with COOLDOWN_LOCK:
        raw = load_json(COOLDOWN_FILE)
        out: Dict[str, float] = {}
        now = time.time()

        for key, value in raw.items():
            try:
                expiry = float(value)
            except Exception:
                continue

            if expiry > now:
                out[str(key)] = expiry

        return out


def save_cooldowns(data: Dict[str, float]):
    try:
        _atomic_write_json(COOLDOWN_FILE, data)
    except Exception as e:
        print(f"[fight.py] save_cooldowns error: {COOLDOWN_FILE} -> {e}")


COOLDOWNS = load_cooldowns()


# ===== DISCORD =====
def get_user_obj(ctx):
    return getattr(ctx, "user", None) or getattr(ctx, "author", None)


async def _defer_if_interaction(ctx, ephemeral: bool = False):
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
        print(f"[fight.py] edit_like error: {e}")
        return None


def make_embed(title: str, description: str = "", color: discord.Color = None) -> discord.Embed:
    return discord.Embed(
        title=title,
        description=description,
        color=color or discord.Color.blurple(),
    )


def format_duration(seconds: int) -> str:
    seconds = max(0, int(seconds))
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    parts = []
    if h > 0:
        parts.append(f"{h}h")
    if m > 0:
        parts.append(f"{m}m")
    if s > 0 or not parts:
        parts.append(f"{s}s")
    return " ".join(parts)


# ===== TEAM SAFE =====
def normalize_team(team):
    if isinstance(team, list):
        return [str(x) for x in team if isinstance(x, (str, int))]
    if isinstance(team, dict):
        return [str(v) for v in team.values() if isinstance(v, (str, int))]
    return []


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


def get_eligible_team_opponents(inv, team_data, exclude_uid, challenger_uid):
    candidates = []

    for raw_uid in team_data.keys():
        uid = str(raw_uid)
        if uid == str(exclude_uid):
            continue
        if uid not in inv:
            continue
        if not normalize_team_ids(inv, uid, team_data):
            continue

        on_cd, _ = is_on_cooldown(challenger_uid, uid)
        if on_cd:
            continue

        candidates.append(uid)

    return candidates


def _pick_random_team_opponent(inv, team_data, exclude_uid, challenger_uid):
    candidates = get_eligible_team_opponents(inv, team_data, exclude_uid, challenger_uid)
    if not candidates:
        return None
    return random.choice(candidates)


# ===== LOVE =====
def _ensure_waifus_dict(user_record: dict) -> dict:
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
    waifus = _ensure_waifus_dict(user)

    current = waifus.get(wid)
    new_val = max(0, int(val))

    if isinstance(current, dict):
        current["love"] = new_val
        if "amount" in current:
            current["amount"] = new_val
    else:
        waifus[wid] = new_val


def drop_love(inv, uid, wid):
    old = get_love(inv, uid, wid)
    new = max(0, int(old * (1 - LOVE_DROP_RATE)))
    set_love(inv, uid, wid, new)
    return new


# ===== STATS HELPERS =====
def fmt_pct(value: float) -> str:
    try:
        return f"{max(0.0, float(value)) * 100:.0f}%"
    except Exception:
        return "0%"


def hp_bar(current, max_hp, length=10):
    max_hp = max(1, int(max_hp))
    current = max(0, min(int(current), max_hp))
    ratio = current / max_hp
    filled = int(ratio * length)
    return "█" * filled + "░" * (length - filled)


def team_text(team: List[dict]) -> str:
    if not team:
        return "Không có waifu."

    out = []
    for c in team:
        hp = max(0, int(c.get("hp", 0)))
        max_hp = max(1, int(c.get("max_hp", 1)))
        out.append(
            f"**{c.get('name', '???')}** | HP: `{hp}/{max_hp}` `{hp_bar(hp, max_hp)}`"
        )
    return "\n".join(out)


# ===== COOLDOWN =====
def _battle_key(uid1: str, uid2: str) -> str:
    return "|".join(sorted((str(uid1), str(uid2))))


def cleanup_cooldowns():
    with COOLDOWN_LOCK:
        now = time.time()
        expired = [k for k, expiry in COOLDOWNS.items() if expiry <= now]
        for k in expired:
            COOLDOWNS.pop(k, None)


def is_on_cooldown(uid1: str, uid2: str) -> Tuple[bool, int]:
    with COOLDOWN_LOCK:
        now = time.time()
        key = _battle_key(uid1, uid2)
        expiry = COOLDOWNS.get(key)
        if not expiry:
            return False, 0

        remain = int(expiry - now)
        if remain <= 0:
            COOLDOWNS.pop(key, None)
            return False, 0

        return True, remain


def set_cooldown(uid1: str, uid2: str, hours: int = COOLDOWN_HOURS):
    with COOLDOWN_LOCK:
        now = time.time()

        expired = [k for k, expiry in COOLDOWNS.items() if expiry <= now]
        for k in expired:
            COOLDOWNS.pop(k, None)

        if len(COOLDOWNS) > 2000:
            COOLDOWNS.clear()

        key = _battle_key(uid1, uid2)
        COOLDOWNS[key] = now + hours * 3600
        snapshot = dict(COOLDOWNS)

    save_cooldowns(snapshot)


# ===== GOLD =====
def get_gold_rate_by_turn(t):
    t = max(1, int(t))

    if t == 1:
        return random.uniform(0.50, 0.60)
    if t <= 4:
        return random.uniform(0.30, 0.40)
    if t <= 7:
        return random.uniform(0.20, 0.30)
    if t <= 10:
        return random.uniform(0.10, 0.20)
    if t >= MAX_ROUNDS:
        return random.uniform(0.01, 0.03)
    return random.uniform(0.01, 0.05)


async def transfer_gold_safely(winner_uid: str, loser_uid: str, bonus: int) -> int:
    bonus = max(0, int(bonus))
    if bonus <= 0:
        return 0

    async with GOLD_LOCK:
        try:
            loser_gold = int((data_user.get_user(loser_uid) or {}).get("gold", 0))
        except Exception as e:
            print(f"[fight.py] get_user gold error: {e}")
            loser_gold = 0

        amount = min(loser_gold, bonus)
        if amount <= 0:
            return 0

        try:
            removed = await data_user.remove_gold(loser_uid, amount)
            if not removed:
                return 0
        except Exception as e:
            print(f"[fight.py] remove_gold error: {e}")
            return 0

        try:
            await data_user.add_gold(winner_uid, amount)
            return amount
        except Exception as e:
            print(f"[fight.py] add_gold error: {e}")
            try:
                await data_user.add_gold(loser_uid, amount)
            except Exception as restore_error:
                print(f"[fight.py] rollback gold error: {restore_error}")
            return 0


# ===== BATTLE HELPERS =====
def get_battle_crit_chance(rank: str, love: int, level: int) -> float:
    base = CRIT_BASE.get(rank, 0.04)
    bonus_level = max(0, int(level) - 1) * 0.01
    bonus_love = min(0.05, max(0, int(love)) / 2000.0)
    return min(0.30, base + bonus_level + bonus_love)


def get_lifesteal(rank: str, level: int) -> float:
    base = LIFESTEAL_BASE.get(rank, 0.02)
    bonus = min(0.10, max(0, int(level) - 1) * 0.005)
    return min(0.20, base + bonus)


def get_dodge_chance(attacker_speed: int, defender_speed: int) -> float:
    attacker_speed = max(1, int(attacker_speed))
    defender_speed = max(1, int(defender_speed))
    base = 0.05
    bonus = min(0.20, defender_speed / max(1, attacker_speed * 12))
    return min(0.25, base + bonus)


def get_crit_damage(base_damage: int, is_combo: bool = False) -> int:
    base_damage = max(1, int(base_damage))
    if is_combo:
        return max(1, int(base_damage * random.uniform(1.40, 1.50)))
    return max(1, int(base_damage * random.uniform(1.30, 1.35)))


def get_crit_heal_amount(max_hp: int, is_combo: bool = False) -> int:
    max_hp = max(1, int(max_hp))
    if is_combo:
        return max(1, int(max_hp * random.uniform(CRIT_HEAL_COMBO_MIN, CRIT_HEAL_COMBO_MAX)))
    return max(1, int(max_hp * random.uniform(CRIT_HEAL_MIN, CRIT_HEAL_MAX)))


# ===== COMBATANT =====
def build_char(uid, wid, inv, waifu):
    if not isinstance(wid, (str, int)):
        return None

    uid = str(uid)
    wid = str(wid)

    meta = waifu.get(wid, {}) if isinstance(waifu, dict) else {}
    rank = str(meta.get("rank", "thuong")).lower()
    if rank not in RANK_ORDER:
        rank = "thuong"

    love = get_love(inv, uid, wid)
    level = max(1, love // 100 + 1)

    base_hp, base_dmg, base_spd = RANK_STATS.get(rank, RANK_STATS["thuong"])

    max_hp = base_hp + level * 20 + love // 10
    damage = base_dmg + level * 5 + love // 25
    speed = base_spd + level * 2 + love // 20

    max_hp = min(MAX_HP_CAP, max(1, max_hp))
    damage = min(MAX_DMG_CAP, max(1, damage))
    speed = min(MAX_SPEED_CAP, max(1, speed))

    crit_chance = get_battle_crit_chance(rank, love, level)
    lifesteal = get_lifesteal(rank, level)

    name = meta.get("name") or meta.get("display_name") or wid

    return {
        "uid": uid,
        "wid": wid,
        "name": name,
        "rank": rank,
        "love": love,
        "level": level,
        "hp": max_hp,
        "max_hp": max_hp,
        "damage": damage,
        "speed": speed,
        "crit_chance": crit_chance,
        "lifesteal": lifesteal,
        "alive": True,
    }


# ===== UI =====
class SpeedView(discord.ui.View):
    def __init__(self, session, timeout: Optional[float] = None):
        super().__init__(timeout=timeout)
        self.session = session
        self.message = None
        self.last_click_by_user: Dict[str, float] = {}

        self.btn_x1 = discord.ui.Button(label="x1", style=discord.ButtonStyle.gray)
        self.btn_x2 = discord.ui.Button(label="x2", style=discord.ButtonStyle.gray)

        self.btn_x1.callback = self.set_x1
        self.btn_x2.callback = self.set_x2

        self.add_item(self.btn_x1)
        self.add_item(self.btn_x2)
        self.refresh_buttons()

    def refresh_buttons(self):
        if self.session.delay <= 1:
            self.btn_x2.disabled = True
            self.btn_x2.style = discord.ButtonStyle.green
            self.btn_x1.disabled = False
            self.btn_x1.style = discord.ButtonStyle.gray
        else:
            self.btn_x1.disabled = True
            self.btn_x1.style = discord.ButtonStyle.green
            self.btn_x2.disabled = False
            self.btn_x2.style = discord.ButtonStyle.gray

    def disable_all(self):
        for item in self.children:
            item.disabled = True

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if getattr(self.session, "finished", False):
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message(
                        "❌ Trận đã kết thúc.",
                        ephemeral=True,
                    )
            except Exception:
                pass
            return False

        uid = str(getattr(interaction.user, "id", ""))
        if uid not in {self.session.uid1, self.session.uid2}:
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message(
                        "❌ Chỉ 2 người đang đấu mới bấm được nút này.",
                        ephemeral=True,
                    )
            except Exception:
                pass
            return False

        now = time.time()
        last = self.last_click_by_user.get(uid, 0.0)
        if now - last < 0.5:
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message(
                        "⏳ Bấm chậm lại một chút.",
                        ephemeral=True,
                    )
            except Exception:
                pass
            return False

        self.last_click_by_user[uid] = now
        return True

    async def set_x1(self, interaction: discord.Interaction):
        self.session.delay = 2
        self.refresh_buttons()
        try:
            await interaction.response.edit_message(embed=self.session.render(), view=self)
        except Exception as e:
            print(f"[fight.py] set_x1 error: {e}")

    async def set_x2(self, interaction: discord.Interaction):
        self.session.delay = 1
        self.refresh_buttons()
        try:
            await interaction.response.edit_message(embed=self.session.render(), view=self)
        except Exception as e:
            print(f"[fight.py] set_x2 error: {e}")

    async def on_timeout(self):
        self.disable_all()
        if self.message is not None:
            try:
                await self.message.edit(view=self)
            except Exception as e:
                print(f"[fight.py] view timeout edit error: {e}")


# ===== SESSION =====
class FightSession:
    def __init__(self, ctx, uid1, uid2, ta, tb, inv, waifu, na, nb):
        self.ctx = ctx
        self.uid1 = str(uid1)
        self.uid2 = str(uid2)
        self.na = na
        self.nb = nb

        self.inv = inv
        self.waifu = waifu

        self.ta = [c for c in (build_char(self.uid1, w, inv, waifu) for w in ta) if isinstance(c, dict)]
        self.tb = [c for c in (build_char(self.uid2, w, inv, waifu) for w in tb) if isinstance(c, dict)]

        self.turn = 1
        self.logs: List[str] = []
        self.delay = ACTION_DELAY
        self.finished = False
        self.sudden_death_applied = False
        self.winner_uid = None
        self.love_drop_targets: Set[Tuple[str, str]] = set()

    def alive(self, team):
        return [c for c in team if c["alive"] and c["hp"] > 0]

    def log(self, txt):
        self.logs.append(txt)
        if len(self.logs) > MAX_LOG_LINES:
            self.logs = self.logs[-MAX_LOG_LINES:]

    def mark_love_drop(self, uid: str, wid: str):
        self.love_drop_targets.add((str(uid), str(wid)))

    def render(self):
        mode = "x2" if self.delay <= 1 else "x1"

        a_alive = len(self.alive(self.ta))
        b_alive = len(self.alive(self.tb))
        a_total = len(self.ta)
        b_total = len(self.tb)

        e = discord.Embed(
            title=f"⚔️ Trận đấu: {self.na} vs {self.nb}",
            description="Trận chiến đang diễn ra.",
            color=discord.Color.red(),
        )

        e.add_field(
            name=f"🔴 {self.na}",
            value=(
                f"**Sống:** `{a_alive}/{a_total}`\n"
                f"{team_text(self.ta)[:900] or 'Không có waifu.'}"
            ),
            inline=True,
        )
        e.add_field(
            name=f"🔵 {self.nb}",
            value=(
                f"**Sống:** `{b_alive}/{b_total}`\n"
                f"{team_text(self.tb)[:900] or 'Không có waifu.'}"
            ),
            inline=True,
        )
        e.add_field(
            name="📜 Diễn biến",
            value="\n".join(self.logs)[:1000] or "Chưa có diễn biến.",
            inline=False,
        )
        e.set_footer(text=f"Turn {min(self.turn, MAX_ROUNDS)}/{MAX_ROUNDS} • Mode {mode}")
        return e

    def render_result(self):
        winner_name = self.na if self.winner_uid == self.uid1 else self.nb if self.winner_uid == self.uid2 else "Hòa"
        loser_name = self.nb if self.winner_uid == self.uid1 else self.na if self.winner_uid == self.uid2 else "Hòa"

        embed = discord.Embed(
            title="🏆 Kết quả trận đấu",
            color=discord.Color.gold()
        )

        if self.winner_uid:
            embed.description = f"🎉 **{winner_name} chiến thắng!**"
            embed.add_field(name="👑 Winner", value=winner_name, inline=True)
            embed.add_field(name="💀 Loser", value=loser_name, inline=True)

            # hiển thị log cuối (có gold)
            if self.logs:
                embed.add_field(
                    name="📜 Diễn biến cuối",
                    value="\n".join(self.logs[-5:])[:1000],
                    inline=False
                )    
        else:
            embed.description = "🤝 Trận đấu kết thúc với kết quả hòa."

        return embed

    def choose_attacker(self, side: str) -> Optional[dict]:
        team = self.ta if side == "a" else self.tb
        alive = self.alive(team)
        if not alive:
            return None
        if len(alive) == 1:
            return alive[0]
        weights = [max(1, c["speed"]) for c in alive]
        return random.choices(alive, weights=weights, k=1)[0]

    def choose_defender(self, side: str) -> Optional[dict]:
        enemy = self.tb if side == "a" else self.ta
        alive = self.alive(enemy)
        if not alive:
            return None
        return random.choice(alive)

    def get_side_name(self, side: str) -> str:
        return self.na if side == "a" else self.nb

    def get_side_id(self, side: str) -> str:
        return self.uid1 if side == "a" else self.uid2

    def is_over(self):
        return not (self.alive(self.ta) and self.alive(self.tb))

    def winner(self):
        a = self.alive(self.ta)
        b = self.alive(self.tb)
        if a and not b:
            return "a"
        if b and not a:
            return "b"
        return None

    def apply_sudden_death(self):
        if self.sudden_death_applied:
            return
        self.sudden_death_applied = True

        for team in (self.ta, self.tb):
            for c in self.alive(team):
                loss = max(1, int(c["max_hp"] * 0.20))
                c["hp"] = max(0, c["hp"] - loss)
                self.log(f"☠️ SUDDEN DEATH: {c['name']} mất {loss} HP!")

                if c["hp"] <= 0 and c["alive"]:
                    c["alive"] = False
                    old_love = get_love(self.inv, c["uid"], c["wid"])
                    new_love = drop_love(self.inv, c["uid"], c["wid"])
                    self.mark_love_drop(c["uid"], c["wid"])
                    self.log(f"💔 {c['name']} bị hạ bởi sudden death. Love giảm từ {old_love} còn {new_love}.")

    async def attack(self, msg, attacker: dict, defender: dict, view: SpeedView):
        if not attacker or not defender:
            return
        if attacker["hp"] <= 0 or defender["hp"] <= 0:
            return

        dodge_chance = get_dodge_chance(attacker["speed"], defender["speed"])
        if random.random() < dodge_chance:
            self.log(f"💨 {defender['name']} né đòn của {attacker['name']}!")
            await edit_like(msg, embed=self.render(), view=view)
            await asyncio.sleep(self.delay)
            return

        base_damage = int(attacker["damage"] * random.uniform(0.90, 1.10))
        base_damage = max(1, base_damage)

        is_crit = random.random() < attacker["crit_chance"]
        is_combo = is_crit and random.random() < COMBO_CRIT_CHANCE

        if is_crit and random.random() < HEAL_ON_CRIT_CHANCE:
            heal = get_crit_heal_amount(attacker["max_hp"], is_combo)
            start_hp = attacker["hp"]
            attacker["hp"] = min(attacker["max_hp"], attacker["hp"] + heal)
            actual = attacker["hp"] - start_hp

            if actual > 0:
                if is_combo:
                    self.log(f"✨🔥 {attacker['name']} COMBO HEAL hồi {actual} HP!")
                else:
                    self.log(f"✨ {attacker['name']} hồi {actual} HP nhờ chí mạng!")
            else:
                self.log(f"✨ {attacker['name']} kích hoạt hồi máu nhưng HP đã đầy.")

            await edit_like(msg, embed=self.render(), view=view)
            await asyncio.sleep(self.delay)
            return

        damage = get_crit_damage(base_damage, is_combo) if is_crit else base_damage
        damage = max(1, damage)

        defender["hp"] = max(0, defender["hp"] - damage)

        if is_crit and is_combo:
            self.log(f"🔥 {attacker['name']} COMBO CRIT {defender['name']} gây {damage} dame!")
        elif is_crit:
            self.log(f"💥 {attacker['name']} CRIT {defender['name']} gây {damage} dame!")
        else:
            self.log(f"⚔️ {attacker['name']} đánh {defender['name']} gây {damage} dame!")

        if defender["hp"] <= 0 and defender["alive"]:
            defender["alive"] = False
            old_love = get_love(self.inv, defender["uid"], defender["wid"])
            new_love = drop_love(self.inv, defender["uid"], defender["wid"])
            self.mark_love_drop(defender["uid"], defender["wid"])
            self.log(f"☠️ {defender['name']} đã bị hạ gục. Love giảm từ {old_love} còn {new_love}.")

        heal = min(
            int(attacker["max_hp"] * 0.25),
            int(damage * attacker.get("lifesteal", 0)),
        )

        if heal > 0 and attacker["hp"] > 0 and attacker["hp"] < attacker["max_hp"]:
            start_hp = attacker["hp"]
            attacker["hp"] = min(attacker["max_hp"], attacker["hp"] + heal)
            actual = attacker["hp"] - start_hp
            if actual > 0:
                self.log(f"🩸 {attacker['name']} hút {actual} HP.")

        await edit_like(msg, embed=self.render(), view=view)
        await asyncio.sleep(self.delay)

    async def play_round(self, msg, view: SpeedView):
        if self.is_over():
            return

        if self.turn == MAX_ROUNDS and not self.sudden_death_applied:
            self.apply_sudden_death()
            if self.is_over():
                return

        speed_a = sum(c["speed"] for c in self.alive(self.ta))
        speed_b = sum(c["speed"] for c in self.alive(self.tb))
        roll_a = speed_a + random.randint(0, max(1, speed_a // 5 + 1))
        roll_b = speed_b + random.randint(0, max(1, speed_b // 5 + 1))

        order = ("a", "b") if roll_a >= roll_b else ("b", "a")

        for side in order:
            if self.is_over():
                break

            attacker = self.choose_attacker(side)
            defender = self.choose_defender(side)

            if not attacker or not defender:
                continue

            await self.attack(msg, attacker, defender, view)

    async def play(self, msg):
        view = SpeedView(self, timeout=max(300, MAX_ROUNDS * (ACTION_DELAY + 5)))
        view.message = msg

        await edit_like(msg, embed=self.render(), view=view)

        while not self.is_over() and self.turn <= MAX_ROUNDS:
            await self.play_round(msg, view)
            self.turn += 1

        self.finished = True
        view.disable_all()

        winner_side = self.winner()
        if winner_side == "a":
            self.winner_uid = self.uid1
        elif winner_side == "b":
            self.winner_uid = self.uid2
        else:
            self.winner_uid = None

        await edit_like(msg, embed=self.render(), view=view)
        return view

    async def commit(self):
        if not self.love_drop_targets:
            return

        async with INV_LOCK:
            latest = load_json(INV_FILE)

            for uid, wid in self.love_drop_targets:
                uid = str(uid)
                wid = str(wid)

                user = latest.setdefault(uid, {})
                waifus = _ensure_waifus_dict(user)

                current = waifus.get(wid, 0)
                if isinstance(current, dict):
                    current_love = current.get("love", current.get("amount", 0))
                else:
                    current_love = current

                try:
                    current_love = max(0, int(current_love))
                except Exception:
                    current_love = 0

                new_love = max(0, int(current_love * (1 - LOVE_DROP_RATE)))
                set_love(latest, uid, wid, new_love)

            save_json(INV_FILE, latest)
            self.inv = latest


# ===== MAIN =====
def _resolve_opponent(opponent):
    if opponent is None:
        return None, None

    if hasattr(opponent, "id"):
        uid = str(opponent.id)
        name = getattr(opponent, "display_name", getattr(opponent, "name", f"<@{uid}>"))
        return uid, name

    if isinstance(opponent, (str, int)):
        raw = str(opponent).strip()
        digits = re.sub(r"\D", "", raw)
        uid = digits if digits else raw
        name = f"<@{uid}>" if digits else raw
        return uid, name

    return None, None


async def resolve_user_name(ctx, uid: str, fallback: str = None):
    uid = str(uid)

    # Ưu tiên lấy trong server
    guild = getattr(ctx, "guild", None)
    if guild and uid.isdigit():
        member = guild.get_member(int(uid))
        if member:
            return member.display_name

    # Nếu không có trong server → fetch global
    try:
        user = await ctx.bot.fetch_user(int(uid))
        return user.global_name or user.name
    except Exception:
        return fallback or f"<@{uid}>"


async def fight_logic(ctx, opponent=None):
    await _defer_if_interaction(ctx)

    user = get_user_obj(ctx)
    if not user:
        return await send_like(
            ctx,
            embed=make_embed("❌ Lỗi", "Không xác định được người dùng.", discord.Color.red()),
        )

    uid1 = str(user.id)
    user_name = getattr(user, "display_name", getattr(user, "name", f"<@{uid1}>"))

    explicit_target = opponent is not None
    uid2 = None
    opponent_name = None

    try:
        async with INV_LOCK:
            inv = load_json(INV_FILE)
            waifu = load_json(WAIFU_FILE)
            team = load_json(TEAM_FILE)

        if uid1 not in inv:
            return await send_like(
                ctx,
                embed=make_embed("❌ Không thể đấu", "Bạn chưa có inventory.", discord.Color.red()),
            )

        if explicit_target:
            uid2, _ = _resolve_opponent(opponent)
            if not uid2:
                return await send_like(
                    ctx,
                    embed=make_embed("❌ Không thể đấu", "Chọn đối thủ hợp lệ.", discord.Color.red()),
                )

            opponent_name = await resolve_user_name(ctx, uid2, fallback=str(opponent))

            if uid1 == uid2:
                return await send_like(
                    ctx,
                    embed=make_embed("❌ Không thể đấu", "Bạn không thể tự đánh chính mình.", discord.Color.red()),
                )

            if await is_user_locked(uid2):
                return await send_like(
                    ctx,
                    embed=make_embed(
                        "🔒 Đối thủ đang lock",
                        f"**{opponent_name}** đang bật lock, không thể thách đấu bằng mention.",
                        discord.Color.orange(),
                    ),
                )

            on_cd, remain = is_on_cooldown(uid1, uid2)
            if on_cd:
                return await send_like(
                    ctx,
                    embed=make_embed(
                        "⏳ Đang hồi chiêu",
                        f"Bạn đã fight với **{opponent_name}** rồi. Cần chờ **{format_duration(remain)}** nữa.",
                        discord.Color.orange(),
                    ),
                )

        async with BATTLE_STATE_LOCK:
            if uid1 in ACTIVE_BATTLE_USERS or (uid2 and uid2 in ACTIVE_BATTLE_USERS):
                return await send_like(
                    ctx,
                    embed=make_embed("⏳ Đang bận", "Đang có trận khác diễn ra.", discord.Color.orange()),
                )

            ACTIVE_BATTLE_USERS.add(uid1)
            if uid2:
                ACTIVE_BATTLE_USERS.add(uid2)

            try:
                if not explicit_target:
                    uid2 = _pick_random_team_opponent(inv, team, uid1, uid1)
                    if not uid2:
                        return await send_like(
                            ctx,
                            embed=make_embed(
                                "⚠️ Hôm nay đã đấu quá nhiều",
                                "Hôm nay bạn đã đấu quá nhiều rồi, nghĩ ngơi đi",
                                discord.Color.orange(),
                            ),
                        )
                    opponent_name = await resolve_user_name(ctx, uid2, fallback=uid2)

                if uid2 not in inv:
                    return await send_like(
                        ctx,
                        embed=make_embed("❌ Không thể đấu", "Đối thủ chưa có inventory.", discord.Color.red()),
                    )

                ta = normalize_team_ids(inv, uid1, team)
                tb = normalize_team_ids(inv, uid2, team)

                if not ta:
                    return await send_like(
                        ctx,
                        embed=make_embed("❌ Không thể đấu", "Bạn không có team.", discord.Color.red()),
                    )

                if not tb:
                    return await send_like(
                        ctx,
                        embed=make_embed("❌ Không thể đấu", "Đối thủ không có team.", discord.Color.red()),
                    )

                session = FightSession(
                    ctx=ctx,
                    uid1=uid1,
                    uid2=uid2,
                    ta=ta,
                    tb=tb,
                    inv=copy.deepcopy(inv),
                    waifu=waifu,
                    na=user_name,
                    nb=opponent_name or resolve_user_name(ctx, uid2, fallback=uid2),
                )

                start_embed = make_embed(
                    "⚔️ Trận đấu bắt đầu",
                    f"**{session.na}** vs **{session.nb}**\n"
                    f"Chọn tốc độ bằng nút bên dưới.",
                    discord.Color.blurple(),
                )

                msg = await send_like(ctx, embed=start_embed)
                if msg is None:
                    return

                await session.play(msg)
                await session.commit()
                # ===== GOLD REWARD =====
                if session.winner_uid:
                    loser_uid = session.uid1 if session.winner_uid == session.uid2 else session.uid2

                    # thưởng dựa theo turn (càng nhanh càng nhiều)
                    gold_rate = get_gold_rate_by_turn(session.turn)
                    base_gold = random.randint(100, 300)
                    bonus = int(base_gold * gold_rate)

                    gained = await transfer_gold_safely(session.winner_uid, loser_uid, bonus)

                    if gained > 0:
                        winner_name = await resolve_user_name(ctx, session.winner_uid, "Winner")
                        session.logs.append(f"💰 {winner_name} nhận {gained} gold từ đối thủ!")
                set_cooldown(uid1, uid2, hours=COOLDOWN_HOURS)

                result_embed = session.render_result()
                await edit_like(msg, content=None, embed=result_embed, view=None)
                return

            finally:
                ACTIVE_BATTLE_USERS.discard(uid1)
                if uid2:
                    ACTIVE_BATTLE_USERS.discard(uid2)

    except Exception as e:
        print(f"[fight.py] fight_logic error: {e}")
        return await send_like(
            ctx,
            embed=make_embed("❌ Lỗi", "Đã xảy ra lỗi trong trận đấu.", discord.Color.red()),
        )


print("Loaded fight has success")