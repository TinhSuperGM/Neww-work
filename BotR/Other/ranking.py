import discord
import asyncio
import json
import os
import copy
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Tuple, Optional

from Data import data_user

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODULE_DIR = os.path.dirname(os.path.abspath(__file__))

TOP_FILE = os.path.join(MODULE_DIR, "top.json")
STATE_FILE = os.path.join(MODULE_DIR, "top_state.json")
REWARD_FILE = os.path.join(MODULE_DIR, "reward_state.json")
SEASON_FILE = os.path.join(MODULE_DIR, "seasonal_history.json")
CHEAT_FILE = os.path.join(MODULE_DIR, "anti_cheat.json")

INV_FILE = os.path.join(BASE_DIR, "Data", "inventory.json")
CHANNEL_FILE = os.path.join(BASE_DIR, "Data", "auction_channels.json")
COUPLE_FILE = os.path.join(BASE_DIR, "Data", "couple.json")
WAIFU_FILE = os.path.join(BASE_DIR, "Data", "waifu_data.json")

VN_TZ = timezone(timedelta(hours=7))
file_lock = asyncio.Lock()

TOP_N = 10
PAGE_SIZE = 10

GOLD_REWARD = [10000, 7000, 5000]
WAIFU_REWARD = [8000, 5000, 3000]
COUPLE_REWARD = [10000, 7000, 5000]
LOVE_REWARD = [10000, 7000, 5000]

MAX_GOLD_DIFF_PER_CYCLE = 50000000
MAX_WAIFU_DIFF_PER_CYCLE = 1000000
MAX_LOVE_DIFF_PER_CYCLE = 50000000
MAX_COUPLE_DIFF_PER_CYCLE = 15000000

_MESSAGE_SIGNATURE_CACHE: Dict[str, str] = {}


# =========================
# SAFE JSON
# =========================
def load_json(path: str) -> Dict[str, Any]:
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception as e:
        print(f"[JSON LOAD ERROR] {path}: {e}")
        return {}


async def save_json(path: str, data: Dict[str, Any]) -> None:
    async with file_lock:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
        except Exception as e:
            print(f"[JSON SAVE ERROR] {path}: {e}")


def merge_defaults(data: Any, default: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(data, dict):
        return copy.deepcopy(default)

    merged = copy.deepcopy(data)
    for key, value in default.items():
        if key not in merged:
            merged[key] = copy.deepcopy(value)
        elif isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = merge_defaults(merged[key], value)
    return merged


def ensure_file(path: str, default: Dict[str, Any]) -> Dict[str, Any]:
    data = load_json(path)

    if not data:
        return copy.deepcopy(default)

    return merge_defaults(data, default)


# =========================
# LOADERS
# =========================
def load_top() -> Dict[str, Dict[str, int]]:
    return ensure_file(TOP_FILE, {"gold": {}, "waifu": {}, "couple": {}, "love": {}})


def load_state() -> Dict[str, Dict[str, int]]:
    return ensure_file(STATE_FILE, {"gold": {}, "waifu": {}, "couple": {}, "love": {}})


def load_reward() -> Dict[str, Any]:
    return ensure_file(REWARD_FILE, {"last_week": None})


def load_season() -> Dict[str, Any]:
    return ensure_file(
        SEASON_FILE,
        {"weeks": {}, "hall_of_fame": {"gold": {}, "waifu": {}, "couple": {}, "love": {}}}
    )


def load_cheat() -> Dict[str, Any]:
    return ensure_file(CHEAT_FILE, {"gold_alerts": {}, "command_usage": {}, "logs": []})


# =========================
# HELPERS
# =========================
def safe_int(x: Any) -> int:
    try:
        return int(x)
    except Exception:
        return 0


def safe_uid(uid: Any) -> str:
    return str(uid)


def get_default_love(inv: Dict[str, Any], uid: str) -> Tuple[Optional[str], int]:
    user = inv.get(uid, {})
    if not isinstance(user, dict):
        return None, 0

    default_id = user.get("default_waifu")
    if not default_id:
        return None, 0

    waifus = user.get("waifus", {})
    love = 0

    if isinstance(waifus, dict):
        love = waifus.get(default_id, 0)
    elif isinstance(waifus, list):
        for item in waifus:
            if isinstance(item, dict) and item.get("waifu_id") == default_id:
                love = item.get("love", 0)
                break

    if isinstance(love, dict):
        love = love.get("amount", 0)

    return str(default_id), safe_int(love)


def get_couple_key(uid1: Any, uid2: Any) -> str:
    a = safe_uid(uid1)
    b = safe_uid(uid2)
    return ":".join(sorted([a, b]))


def split_couple_key(key: str) -> Tuple[str, str]:
    parts = key.split(":", 1)
    if len(parts) != 2:
        return key, ""
    return parts[0], parts[1]


def seconds_until_next_half_hour() -> int:
    now = datetime.now(VN_TZ)
    if now.minute < 30:
        target = now.replace(minute=30, second=0, microsecond=0)
    else:
        target = (now + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
    return max(10, int((target - now).total_seconds()))


def is_weekly_reward_time() -> bool:
    now = datetime.now(VN_TZ)
    return now.weekday() == 5 and now.hour == 0 and now.minute < 30


def get_week_id() -> str:
    now = datetime.now(VN_TZ)
    return now.strftime("%G-W%V")


def get_page_slice(items: List[Any], page: int, per_page: int = PAGE_SIZE) -> Tuple[List[Any], int]:
    total = len(items)
    total_pages = max(1, (total + per_page - 1) // per_page)
    page = page % total_pages
    start = page * per_page
    end = start + per_page
    return items[start:end], total_pages


def clamp_page(page: int, total_pages: int) -> int:
    if total_pages <= 0:
        return 0
    return page % total_pages


def _embed_signature(embed: discord.Embed) -> str:
    try:
        payload = embed.to_dict()
    except Exception:
        payload = {
            "title": getattr(embed, "title", None),
            "description": getattr(embed, "description", None),
        }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


# =========================
# ANTI-CHEAT
# =========================
async def flag_suspicious(uid: str, reason: str, detail: Optional[Dict[str, Any]] = None) -> None:
    cheat = load_cheat()
    logs = cheat.setdefault("logs", [])
    alerts = cheat.setdefault("gold_alerts", {})

    entry = {
        "uid": safe_uid(uid),
        "reason": reason,
        "detail": detail or {},
        "time": datetime.now(VN_TZ).isoformat()
    }

    logs.append(entry)
    if len(logs) > 500:
        del logs[:-500]

    uid_key = safe_uid(uid)
    alerts[uid_key] = alerts.get(uid_key, 0) + 1

    await save_json(CHEAT_FILE, cheat)
    print(f"[ANTI-CHEAT] {uid_key} | {reason} | {detail or {}}")


def command_spam_key(uid: str, command_name: str) -> str:
    return f"{safe_uid(uid)}:{command_name}"


async def record_command_usage(uid: str, command_name: str, window_seconds: int = 10, limit: int = 8) -> bool:
    """
    Dùng ở file command khác.
    Trả về False nếu user spam quá nhanh.
    """
    cheat = load_cheat()
    usage = cheat.setdefault("command_usage", {})
    key = command_spam_key(uid, command_name)
    now_ts = int(datetime.now(VN_TZ).timestamp())

    bucket = usage.get(key, [])
    if not isinstance(bucket, list):
        bucket = []

    bucket = [ts for ts in bucket if now_ts - safe_int(ts) <= window_seconds]
    bucket.append(now_ts)
    usage[key] = bucket

    await save_json(CHEAT_FILE, cheat)
    return len(bucket) <= limit


# =========================
# TOP CALC
# =========================
def get_top_gold() -> List[Tuple[str, int]]:
    top = load_top().get("gold", {})
    ranked = sorted(
        ((safe_uid(uid), safe_int(value)) for uid, value in top.items()),
        key=lambda x: x[1],
        reverse=True
    )
    return ranked[:TOP_N]


def get_top_waifus() -> List[Tuple[str, int]]:
    top = load_top().get("waifu", {})
    ranked = sorted(
        ((safe_uid(uid), safe_int(value)) for uid, value in top.items()),
        key=lambda x: x[1],
        reverse=True
    )
    return ranked[:TOP_N]


def get_top_love() -> List[Tuple[str, int]]:
    top = load_top().get("love", {})
    ranked = sorted(
        ((safe_uid(uid), safe_int(value)) for uid, value in top.items()),
        key=lambda x: x[1],
        reverse=True
    )
    return ranked[:TOP_N]


def get_top_couples() -> List[Tuple[str, str, int]]:
    top = load_top().get("couple", {})
    ranked = sorted(
        ((str(key), safe_int(value)) for key, value in top.items()),
        key=lambda x: x[1],
        reverse=True
    )[:TOP_N]

    result: List[Tuple[str, str, int]] = []
    for key, value in ranked:
        u1, u2 = split_couple_key(key)
        result.append((u1, u2, value))
    return result


# =========================
# EMBEDS
# =========================
def build_embed_base(title: str, color: discord.Color, page: int, total_pages: int) -> discord.Embed:
    now = datetime.now(VN_TZ)
    embed = discord.Embed(title=title, color=color)
    embed.set_footer(text=f"Trang {page + 1}/{total_pages} • {now.day}/{now.month}/{now.year}")
    return embed


def build_gold_embed(entries: List[Tuple[str, int]], page: int = 0) -> discord.Embed:
    page_items, total_pages = get_page_slice(entries, page, PAGE_SIZE)
    embed = build_embed_base("💰 Top Gold tuần", discord.Color.gold(), page, total_pages)

    if not page_items:
        embed.description = "Không có dữ liệu"
        return embed

    medals = ["🥇", "🥈", "🥉"]
    lines = []
    for idx, (uid, value) in enumerate(page_items):
        rank = page * PAGE_SIZE + idx + 1
        prefix = medals[idx] if idx < 3 and page == 0 else f"**#{rank}**"
        lines.append(f"{prefix} <@{uid}> | +{value} 🪙")
    embed.description = "\n".join(lines)
    return embed


def build_waifu_embed(entries: List[Tuple[str, int]], page: int = 0) -> discord.Embed:
    page_items, total_pages = get_page_slice(entries, page, PAGE_SIZE)
    embed = build_embed_base("🌸 Top Waifu tuần", discord.Color.from_rgb(255, 182, 193), page, total_pages)

    if not page_items:
        embed.description = "Không có dữ liệu"
        return embed

    medals = ["🥇", "🥈", "🥉"]
    lines = []
    for idx, (uid, value) in enumerate(page_items):
        rank = page * PAGE_SIZE + idx + 1
        prefix = medals[idx] if idx < 3 and page == 0 else f"**#{rank}**"
        lines.append(f"{prefix} <@{uid}> | +{value} waifu")
    embed.description = "\n".join(lines)
    return embed


def build_love_embed(entries: List[Tuple[str, int]], inv: Dict[str, Any], waifu_data: Dict[str, Any], page: int = 0) -> discord.Embed:
    page_items, total_pages = get_page_slice(entries, page, PAGE_SIZE)
    embed = build_embed_base("💖 Top Love tuần", discord.Color.dark_magenta(), page, total_pages)

    if not page_items:
        embed.description = "Không có dữ liệu"
        return embed

    medals = ["🥇", "🥈", "🥉"]
    lines = []
    for idx, (uid, value) in enumerate(page_items):
        rank = page * PAGE_SIZE + idx + 1
        default_id, _ = get_default_love(inv, uid)
        waifu_name = waifu_data.get(default_id, {}).get("name", default_id or "Unknown")
        prefix = medals[idx] if idx < 3 and page == 0 else f"**#{rank}**"
        lines.append(f"{prefix} <@{uid}> | {waifu_name}: +{value} 💕")
    embed.description = "\n".join(lines)
    return embed


def build_couple_embed(entries: List[Tuple[str, str, int]], page: int = 0) -> discord.Embed:
    page_items, total_pages = get_page_slice(entries, page, PAGE_SIZE)
    embed = build_embed_base("❤️ Top Couple tuần", discord.Color.from_rgb(255, 105, 180), page, total_pages)

    if not page_items:
        embed.description = "Không có dữ liệu"
        return embed

    medals = ["🥇", "🥈", "🥉"]
    lines = []
    for idx, (u1, u2, value) in enumerate(page_items):
        rank = page * PAGE_SIZE + idx + 1
        prefix = medals[idx] if idx < 3 and page == 0 else f"**#{rank}**"
        lines.append(f"{prefix} <@{u1}> × <@{u2}> | +{value} ⭐")
    embed.description = "\n".join(lines)
    return embed


def build_embed_for_kind(
    kind: str,
    entries: List[Any],
    page: int,
    inv: Optional[Dict[str, Any]] = None,
    waifu_data: Optional[Dict[str, Any]] = None
) -> discord.Embed:
    if kind == "gold":
        return build_gold_embed(entries, page)
    if kind == "waifu":
        return build_waifu_embed(entries, page)
    if kind == "couple":
        return build_couple_embed(entries, page)
    if kind == "love":
        return build_love_embed(entries, inv or {}, waifu_data or {}, page)
    return discord.Embed(title="Leaderboard", description="Không có dữ liệu")


# =========================
# PAGINATION VIEW
# =========================
class LeaderboardView(discord.ui.View):
    def __init__(self, kind: str, entries: List[Any], page: int = 0, timeout: float = 180.0):
        super().__init__(timeout=timeout)
        self.kind = kind
        self.entries = entries
        self.page = page

    def _total_pages(self) -> int:
        total = len(self.entries)
        return max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)

    def _embed(self) -> discord.Embed:
        total_pages = self._total_pages()
        self.page = clamp_page(self.page, total_pages)
        inv = load_json(INV_FILE) if self.kind == "love" else None
        waifu_data = load_json(WAIFU_FILE) if self.kind == "love" else None
        return build_embed_for_kind(self.kind, self.entries, self.page, inv, waifu_data)

    async def _persist_page(self, interaction: discord.Interaction) -> None:
        channels = load_json(CHANNEL_FILE)
        target_key = None

        for gid, data in channels.items():
            if not isinstance(data, dict):
                continue
            if str(data.get("leaderboard_channel_id")) == str(interaction.channel_id):
                target_key = gid
                break

        if target_key is None:
            return

        data = channels[target_key]
        data[f"leaderboard_page_{self.kind}"] = self.page
        channels[target_key] = data
        await save_json(CHANNEL_FILE, channels)

    @discord.ui.button(label="◀", style=discord.ButtonStyle.secondary, custom_id="leaderboard_prev")
    async def prev_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page -= 1
        embed = self._embed()
        await self._persist_page(interaction)
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="▶", style=discord.ButtonStyle.secondary, custom_id="leaderboard_next")
    async def next_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page += 1
        embed = self._embed()
        await self._persist_page(interaction)
        await interaction.response.edit_message(embed=embed, view=self)


# =========================
# REWARD
# =========================
def reward_gold(top: List[Tuple[str, int]], rewards: List[int]) -> None:
    for i, (uid, _) in enumerate(top):
        if i < len(rewards):
            data_user.add_gold(uid, rewards[i])


def reward_waifu(top: List[Tuple[str, int]], rewards: List[int]) -> None:
    for i, (uid, _) in enumerate(top):
        if i < len(rewards):
            data_user.add_gold(uid, rewards[i])


def reward_love(top: List[Tuple[str, int]], rewards: List[int]) -> None:
    for i, (uid, _) in enumerate(top):
        if i < len(rewards):
            data_user.add_gold(uid, rewards[i])


def reward_couple(top: List[Tuple[str, str, int]], rewards: List[int]) -> None:
    for i, (u1, u2, _) in enumerate(top):
        if i < len(rewards):
            total = rewards[i]
            half = total // 2
            data_user.add_gold(u1, half)
            data_user.add_gold(u2, total - half)


# =========================
# SEASONAL HISTORY
# =========================
async def record_seasonal_history(
    week_id: str,
    top_gold: List[Tuple[str, int]],
    top_waifu: List[Tuple[str, int]],
    top_couple: List[Tuple[str, str, int]],
    top_love: List[Tuple[str, int]],
) -> None:
    season = load_season()
    weeks = season.setdefault("weeks", {})
    hof = season.setdefault("hall_of_fame", {"gold": {}, "waifu": {}, "couple": {}, "love": {}})

    weeks[week_id] = {
        "time": datetime.now(VN_TZ).isoformat(),
        "gold": [{"uid": uid, "value": value} for uid, value in top_gold],
        "waifu": [{"uid": uid, "value": value} for uid, value in top_waifu],
        "couple": [{"u1": u1, "u2": u2, "value": value} for u1, u2, value in top_couple],
        "love": [{"uid": uid, "value": value} for uid, value in top_love],
    }

    def bump(category: str, uid: str, amount: int = 1):
        cat = hof.setdefault(category, {})
        uid = safe_uid(uid)
        cat[uid] = safe_int(cat.get(uid, 0)) + amount

    if top_gold:
        bump("gold", top_gold[0][0], 1)
    if top_waifu:
        bump("waifu", top_waifu[0][0], 1)
    if top_love:
        bump("love", top_love[0][0], 1)
    if top_couple:
        bump("couple", top_couple[0][0], 1)
        bump("couple", top_couple[0][1], 1)

    await save_json(SEASON_FILE, season)


# =========================
# RESET WEEKLY STORAGE
# =========================
async def reset_weekly_storage() -> None:
    empty_top = {"gold": {}, "waifu": {}, "couple": {}, "love": {}}
    empty_state = {"gold": {}, "waifu": {}, "couple": {}, "love": {}}
    await save_json(TOP_FILE, empty_top)
    await save_json(STATE_FILE, empty_state)


# =========================
# TOP UPDATE
# =========================
async def update_top() -> None:
    try:
        top = load_top()
        state = load_state()

        users = data_user.load_data()
        inv = load_json(INV_FILE)
        couples = load_json(COUPLE_FILE)

        # GOLD
        for uid, data in users.items():
            uid = safe_uid(uid)
            current = safe_int(data.get("gold", 0)) if isinstance(data, dict) else 0
            prev = safe_int(state["gold"].get(uid, current))
            diff = current - prev

            if diff > 0:
                if diff > MAX_GOLD_DIFF_PER_CYCLE:
                    await flag_suspicious(uid, "gold_spike", {"diff": diff, "prev": prev, "current": current})
                    diff = MAX_GOLD_DIFF_PER_CYCLE
                top["gold"][uid] = safe_int(top["gold"].get(uid, 0)) + diff

            state["gold"][uid] = current

        # WAIFU
        for uid, data in inv.items():
            uid = safe_uid(uid)
            waifus = data.get("waifus", {}) if isinstance(data, dict) else {}
            current = 0

            if isinstance(waifus, list):
                current = len(waifus)
            elif isinstance(waifus, dict):
                for w in waifus.values():
                    if isinstance(w, dict):
                        current += safe_int(w.get("amount", 1))
                    elif isinstance(w, int):
                        current += w
                    else:
                        current += 1

            prev = safe_int(state["waifu"].get(uid, current))
            diff = current - prev

            if diff > 0:
                if diff > MAX_WAIFU_DIFF_PER_CYCLE:
                    await flag_suspicious(uid, "waifu_spike", {"diff": diff, "prev": prev, "current": current})
                    diff = MAX_WAIFU_DIFF_PER_CYCLE
                top["waifu"][uid] = safe_int(top["waifu"].get(uid, 0)) + diff

            state["waifu"][uid] = current

        # LOVE
        for uid in inv.keys():
            uid = safe_uid(uid)
            _, current = get_default_love(inv, uid)
            prev = safe_int(state["love"].get(uid, current))
            diff = current - prev

            if diff > 0:
                if diff > MAX_LOVE_DIFF_PER_CYCLE:
                    await flag_suspicious(uid, "love_spike", {"diff": diff, "prev": prev, "current": current})
                    diff = MAX_LOVE_DIFF_PER_CYCLE
                top["love"][uid] = safe_int(top["love"].get(uid, 0)) + diff

            state["love"][uid] = current

        # COUPLE: xử lý theo cặp, không double count
        visited = set()
        for uid, info in couples.items():
            uid = safe_uid(uid)
            if not isinstance(info, dict):
                continue

            partner = info.get("partner")
            if not partner:
                continue

            partner = safe_uid(partner)
            key = get_couple_key(uid, partner)
            if key in visited:
                continue
            visited.add(key)

            current = safe_int(info.get("points", 0))
            prev = safe_int(state["couple"].get(key, current))
            diff = current - prev

            if diff > 0:
                if diff > MAX_COUPLE_DIFF_PER_CYCLE:
                    await flag_suspicious(key, "couple_spike", {"diff": diff, "prev": prev, "current": current})
                    diff = MAX_COUPLE_DIFF_PER_CYCLE
                top["couple"][key] = safe_int(top["couple"].get(key, 0)) + diff

            state["couple"][key] = current

        await save_json(TOP_FILE, top)
        await save_json(STATE_FILE, state)

    except Exception as e:
        print(f"[UPDATE ERROR] {e}")


# =========================
# CHANNEL / MESSAGE HELPERS
# =========================
async def resolve_channel(bot: discord.Client, channel_id: int):
    ch = bot.get_channel(channel_id)
    if ch:
        return ch
    try:
        return await bot.fetch_channel(channel_id)
    except Exception:
        return None


async def upsert_leaderboard_message(
    channel: discord.TextChannel,
    msg_id: Optional[int],
    embed: discord.Embed,
    view: discord.ui.View,
    cache_key: Optional[str] = None
) -> Tuple[int, bool]:
    signature = _embed_signature(embed)

    if cache_key and msg_id and _MESSAGE_SIGNATURE_CACHE.get(cache_key) == signature:
        return int(msg_id), False

    if msg_id:
        try:
            msg = await channel.fetch_message(int(msg_id))
            if msg.embeds:
                current_signature = _embed_signature(msg.embeds[0])
                if current_signature == signature:
                    if cache_key:
                        _MESSAGE_SIGNATURE_CACHE[cache_key] = signature
                    return msg.id, False

            await msg.edit(embed=embed, view=view)
            if cache_key:
                _MESSAGE_SIGNATURE_CACHE[cache_key] = signature
            return msg.id, True

        except Exception:
            pass

    msg = await channel.send(embed=embed, view=view)
    if cache_key:
        _MESSAGE_SIGNATURE_CACHE[cache_key] = signature
    return msg.id, True


# =========================
# LOOP
# =========================
async def ranking_loop(bot):
    await bot.wait_until_ready()

    while True:
        try:
            reward_state = load_reward()

            await update_top()

            top_gold = get_top_gold()
            top_waifu = get_top_waifus()
            top_couple = get_top_couples()
            top_love = get_top_love()

            inv = load_json(INV_FILE)
            waifu_data = load_json(WAIFU_FILE)

            channels = load_json(CHANNEL_FILE)

            for gid, data in channels.items():
                if not isinstance(data, dict):
                    continue

                ch_id = data.get("leaderboard_channel_id")
                if not ch_id:
                    continue

                channel = await resolve_channel(bot, int(ch_id))
                if not channel:
                    continue

                gold_page = safe_int(data.get("leaderboard_page_gold", 0))
                waifu_page = safe_int(data.get("leaderboard_page_waifu", 0))
                couple_page = safe_int(data.get("leaderboard_page_couple", 0))
                love_page = safe_int(data.get("leaderboard_page_love", 0))

                guild_updated = False

                # GOLD
                gold_view = LeaderboardView("gold", top_gold, gold_page)
                gold_embed = build_gold_embed(top_gold, gold_page)
                new_msg_id, changed = await upsert_leaderboard_message(
                    channel,
                    data.get("leaderboard_message_gold"),
                    gold_embed,
                    gold_view,
                    cache_key=f"{gid}:gold"
                )
                data["leaderboard_message_gold"] = new_msg_id
                guild_updated |= changed
                if changed:
                    await asyncio.sleep(0.35)

                # WAIFU
                waifu_view = LeaderboardView("waifu", top_waifu, waifu_page)
                waifu_embed = build_waifu_embed(top_waifu, waifu_page)
                new_msg_id, changed = await upsert_leaderboard_message(
                    channel,
                    data.get("leaderboard_message_waifu"),
                    waifu_embed,
                    waifu_view,
                    cache_key=f"{gid}:waifu"
                )
                data["leaderboard_message_waifu"] = new_msg_id
                guild_updated |= changed
                if changed:
                    await asyncio.sleep(0.35)

                # COUPLE
                couple_view = LeaderboardView("couple", top_couple, couple_page)
                couple_embed = build_couple_embed(top_couple, couple_page)
                new_msg_id, changed = await upsert_leaderboard_message(
                    channel,
                    data.get("leaderboard_message_couple"),
                    couple_embed,
                    couple_view,
                    cache_key=f"{gid}:couple"
                )
                data["leaderboard_message_couple"] = new_msg_id
                guild_updated |= changed
                if changed:
                    await asyncio.sleep(0.35)

                # LOVE
                love_view = LeaderboardView("love", top_love, love_page)
                love_embed = build_love_embed(top_love, inv, waifu_data, love_page)
                new_msg_id, changed = await upsert_leaderboard_message(
                    channel,
                    data.get("leaderboard_message_love"),
                    love_embed,
                    love_view,
                    cache_key=f"{gid}:love"
                )
                data["leaderboard_message_love"] = new_msg_id
                guild_updated |= changed
                if changed:
                    await asyncio.sleep(0.35)

                if guild_updated:
                    await asyncio.sleep(0.5)

            await save_json(CHANNEL_FILE, channels)

            # ===== WEEKLY REWARD =====
            week_id = get_week_id()

            if is_weekly_reward_time() and reward_state.get("last_week") != week_id:
                await record_seasonal_history(week_id, top_gold, top_waifu, top_couple, top_love)

                reward_gold(top_gold, GOLD_REWARD)
                reward_waifu(top_waifu, WAIFU_REWARD)
                reward_love(top_love, LOVE_REWARD)
                reward_couple(top_couple, COUPLE_REWARD)

                await reset_weekly_storage()

                reward_state["last_week"] = week_id
                await save_json(REWARD_FILE, reward_state)

                print(f"[RANKING] Reward distributed & reset for week {week_id}!")

        except Exception as e:
            print(f"[RANKING ERROR] {e}")

        await asyncio.sleep(seconds_until_next_half_hour())


# =========================
# SETUP
# =========================
async def setup(bot):
    asyncio.create_task(ranking_loop(bot))


print("Loaded Ranking has success")