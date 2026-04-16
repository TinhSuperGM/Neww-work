import discord
import json
import os
import asyncio
import random
import copy
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, Tuple

from Data import data_user
from Data.level import sync_all

# ===== PATH =====
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
USER_FILE = os.path.join(BASE_DIR, "Data", "user.json")
INV_FILE = os.path.join(BASE_DIR, "Data", "inventory.json")
WAIFU_FILE = os.path.join(BASE_DIR, "Data", "waifu_data.json")
LEVEL_FILE = os.path.join(BASE_DIR, "Data", "level.json")

# ===== CONFIG =====
WORK_COOLDOWN = timedelta(hours=18)
WORK_DURATION = timedelta(hours=1)
CHECK_INTERVAL = 15

MIN_GOLD = 50
MAX_GOLD = 100_000

RANK_BASE = {
    "thuong": 1,
    "anh_hung": 2,
    "huyen_thoai": 4,
    "truyen_thuyet": 6,
    "toi_thuong": 8,
    "limited": 10,
}

WORK_AREAS = {
    "mine": {
        "label": "Khu mỏ",
        "emoji": "⛏️",
        "unlock": 1,
        "reward": 1.00,
        "bonus": 0.10,
        "bonus_multi": 1.10,
        "fail": 0.30,
    },
    "cave": {
        "label": "Hang động",
        "emoji": "🪨",
        "unlock": 10,
        "reward": 1.08,
        "bonus": 0.18,
        "bonus_multi": 1.18,
        "fail": 0.20,
    },
    "road": {
        "label": "Đường xá",
        "emoji": "🛣️",
        "unlock": 25,
        "reward": 1.16,
        "bonus": 0.28,
        "bonus_multi": 1.28,
        "fail": 0.12,
    },
    "company": {
        "label": "Công ty",
        "emoji": "🏢",
        "unlock": 50,
        "reward": 1.25,
        "bonus": 0.40,
        "bonus_multi": 1.40,
        "fail": 0.05,
    },
}

WORK_ORDER = ["mine", "cave", "road", "company"]

# ===== LOCKS =====
locks: Dict[str, asyncio.Lock] = {}

def get_lock(uid: str) -> asyncio.Lock:
    if uid not in locks:
        locks[uid] = asyncio.Lock()
    return locks[uid]

# ===== BOT / LOOP =====
BOT = None
WORK_TASK: Optional[asyncio.Task] = None

def init_work(bot):
    global BOT, WORK_TASK
    BOT = bot
    if WORK_TASK is None or WORK_TASK.done():
        WORK_TASK = bot.loop.create_task(work_loop())

# ===== JSON =====
def load_json(path, default):
    os.makedirs(os.path.dirname(path), exist_ok=True)

    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(default, f, ensure_ascii=False, indent=4)

    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, type(default)):
            return data
    except Exception:
        pass

    if isinstance(default, dict):
        return default.copy()
    if isinstance(default, list):
        return list(default)
    return default

def save_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)
    os.replace(tmp, path)

def _reload_cache():
    try:
        data_user.reload_cache()
    except Exception:
        pass

def _credit_gold(users: Dict[str, Any], uid: str, amount: int):
    user = _get_user(users, uid)
    user["gold"] = max(0, _safe_int(user.get("gold"), 0) + _safe_int(amount, 0))
    data_user.save_user(uid, user)

# ===== SAFE HELPERS =====
def _safe_int(value, default=1):
    try:
        return int(value)
    except Exception:
        return default

def _parse_dt(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except Exception as e:
        print(f"[work._reply] {e}")
        return None

def _format_remaining(delta: timedelta) -> str:
    total = max(0, int(delta.total_seconds()))
    h = total // 3600
    m = (total % 3600) // 60
    return f"{h} giờ {m} phút"

def _ts(dt: Optional[datetime]) -> int:
    return int(dt.timestamp()) if dt else int(datetime.now().timestamp())

def _get_user(users: Dict[str, Any], uid: str) -> Dict[str, Any]:
    user = users.setdefault(uid, {})
    if not isinstance(user, dict):
        users[uid] = {}
        user = users[uid]
    return user

def _get_love_store(user_data: Dict[str, Any]) -> Dict[str, Any]:
    store = user_data.get("waifu_loves")
    if not isinstance(store, dict):
        store = {}
        user_data["waifu_loves"] = store
    return store

def _waifu_exists(waifus, default_id: str) -> bool:
    if isinstance(waifus, dict):
        return default_id in waifus
    if isinstance(waifus, list):
        for item in waifus:
            if isinstance(item, dict):
                if str(item.get("id") or item.get("waifu_id") or item.get("wid")) == default_id:
                    return True
            elif str(item) == default_id:
                return True
    return False

def _get_rank(default_id: str, waifu_data: Dict[str, Any]) -> Optional[str]:
    info = waifu_data.get(default_id)
    if not isinstance(info, dict):
        return None
    rank = str(info.get("rank", "")).strip().lower()
    return rank or None

def _get_level(levels: Dict[str, Any], uid: str, default_id: str) -> int:
    return max(1, _safe_int(levels.get(uid, {}).get(default_id, 1), 1))

def _get_love(users: Dict[str, Any], inv: Dict[str, Any], uid: str, default_id: str) -> int:
    inv_store = inv.get(uid, {}).get("waifus")
    if isinstance(inv_store, dict) and default_id in inv_store:
        return max(1, _safe_int(inv_store.get(default_id, 1), 1))

    user_data = _get_user(users, uid)
    user_store = _get_love_store(user_data)
    if default_id in user_store:
        return max(1, _safe_int(user_store.get(default_id, 1), 1))

    return 100

def _set_love(users: Dict[str, Any], inv: Dict[str, Any], uid: str, default_id: str, new_love: int):
    love_val = max(1, _safe_int(new_love, 1))

    if uid not in inv or not isinstance(inv.get(uid), dict):
        inv[uid] = {}
    if "waifus" not in inv[uid] or not isinstance(inv[uid]["waifus"], dict):
        inv[uid]["waifus"] = {}
    inv[uid]["waifus"][default_id] = love_val

    user_data = _get_user(users, uid)
    user_store = _get_love_store(user_data)
    user_store[default_id] = love_val

def _get_rank_base(rank_str: str) -> int:
    return RANK_BASE.get(rank_str, 1)

def _work_base_gold(rank_base: int, love_point: int, level: int) -> int:
    return max(1, (rank_base * love_point // max(level, 1)) + 1 + (level // 10))

def _clamp_gold(value: int) -> int:
    return max(MIN_GOLD, min(int(value), MAX_GOLD))

def _cooldown_end(user_data: Dict[str, Any]) -> Optional[datetime]:
    return _parse_dt(user_data.get("last_work"))

def _is_job_active(job: Dict[str, Any]) -> bool:
    return isinstance(job, dict) and bool(job.get("active")) and bool(job.get("area"))

def _job_ready(job: Dict[str, Any]) -> bool:
    claim_at = _parse_dt(job.get("claim_at"))
    return claim_at is not None and datetime.now() >= claim_at

def _remaining_to_claim(job: Dict[str, Any]) -> Optional[timedelta]:
    claim_at = _parse_dt(job.get("claim_at"))
    if not claim_at:
        return None
    return max(timedelta(0), claim_at - datetime.now())

# ===== EMBEDS =====
def build_area_select_embed(display_name: str, mention: str, default_id: str, rank_str: str, level: int, love_point: int):
    embed = discord.Embed(
        title="💼 Chọn khu vực đi làm",
        description=(
            f"👤 **{mention}**\n"
            f"🩷 Waifu mặc định: **{default_id}**\n"
            f"🎖️ Rank: **{rank_str}**\n"
            f"📊 Level: **{level}**\n"
            f"💖 Love: **{love_point}**\n\n"
            f"Chọn một khu vực. Khu vực càng cao thì thưởng càng tốt, nhưng rủi ro cũng khác nhau."
        ),
        color=0xF1C40F,
    )

    for key in WORK_ORDER:
        cfg = WORK_AREAS[key]
        state = "🔓 Mở khóa" if level >= cfg["unlock"] else f"🔒 Cần level {cfg['unlock']}"
        embed.add_field(
            name=f"{cfg['emoji']} {cfg['label']}",
            value=(
                f"{state}\n"
                f"Reward: x{cfg['reward']}\n"
                f"Bonus: {int(cfg['bonus'] * 100)}% / x{cfg['bonus_multi']}\n"
                f"Fail: {int(cfg['fail'] * 100)}%"
            ),
            inline=False,
        )
    return embed

def build_working_embed(display_name: str, mention: str, job: Dict[str, Any], remaining: Optional[timedelta]):
    area_cfg = WORK_AREAS.get(job.get("area"), WORK_AREAS["mine"])
    claim_at = _parse_dt(job.get("claim_at"))
    remaining_text = "Đã sẵn sàng nhận" if (remaining is not None and remaining.total_seconds() <= 0) else _format_remaining(remaining or timedelta(0))

    embed = discord.Embed(
        title="💼 Waifu đang đi làm",
        description=(
            f"👤 **{mention}**\n"
            f"🩷 Waifu: **{job.get('default_id', 'unknown')}**\n"
            f"📍 Khu vực: {area_cfg['emoji']} **{area_cfg['label']}**\n"
            f"🎖️ Rank: **{job.get('rank', 'thuong')}**\n"
            f"📊 Level: **{job.get('level', 1)}**\n"
            f"⏳ Còn lại: **{remaining_text}**"
        ),
        color=0x3498DB if (remaining is None or remaining.total_seconds() > 0) else 0x2ECC71,
    )

    embed.add_field(
        name="Khu vực",
        value=f"{area_cfg['emoji']} {area_cfg['label']}",
        inline=True,
    )
    embed.add_field(
        name="Tỉ lệ",
        value=(
            f"Bonus: **{int(area_cfg['bonus'] * 100)}%**\n"
            f"Fail: **{int(area_cfg['fail'] * 100)}%**"
        ),
        inline=True,
    )
    embed.add_field(
        name="Mốc nhận",
        value=(
            f"<t:{_ts(claim_at)}:R>\n"
            f"<t:{_ts(claim_at)}:F>"
        ),
        inline=True,
    )
    return embed

def build_result_embed(user_id: str, pending: Dict[str, Any]):
    area_cfg = WORK_AREAS.get(pending.get("area"), WORK_AREAS["mine"])
    failed = bool(pending.get("failed"))
    gold = _safe_int(pending.get("gold"), 0)
    base_gold = _safe_int(pending.get("base_gold"), 0)
    love_before = _safe_int(pending.get("love_before"), 1)
    love_after = _safe_int(pending.get("love_after"), 1)
    love_loss = _safe_int(pending.get("love_loss"), 0)
    bonus_hit = bool(pending.get("bonus_hit"))
    rank_str = str(pending.get("rank", "thuong"))
    level = _safe_int(pending.get("level"), 1)
    default_id = str(pending.get("default_id", "unknown"))
    completed_at = _parse_dt(pending.get("completed_at")) or datetime.now()

    if failed:
        title = "💼 Làm việc thất bại"
        color = 0xE74C3C
        lines = [
            f"💼 <@{user_id}> đã đưa **{default_id}** đi làm tại **{area_cfg['label']}**",
            f"🎖️ Rank: **{rank_str}** | 📊 Level: **{level}**",
            f"💥 Kết quả: **Thất bại**",
            f"💵 Nhận: **0 🪙**",
            f"🕒 Hoàn thành lúc: <t:{_ts(completed_at)}:F>",
        ]
    else:
        title = "💼 Làm việc thành công"
        color = 0x2ECC71
        bonus_text = "Có bonus" if bonus_hit else "Không có bonus"
        lines = [
            f"💼 <@{user_id}> đã đưa **{default_id}** đi làm tại **{area_cfg['label']}**",
            f"🎖️ Rank: **{rank_str}** | 📊 Level: **{level}**",
            f"🏷️ Base: **{base_gold} 🪙** | {bonus_text}",
            f"💰 Nhận: **{gold} 🪙**",
            f"💖 Love: **{love_before} → {love_after}** (-{love_loss})",
            f"🕒 Hoàn thành lúc: <t:{_ts(completed_at)}:F>",
        ]

    embed = discord.Embed(
        title=title,
        description="\n".join(lines),
        color=color,
    )
    embed.add_field(name="Khu vực", value=f"{area_cfg['emoji']} {area_cfg['label']}", inline=True)
    embed.add_field(
        name="Tỉ lệ",
        value=(
            f"Bonus: **{int(area_cfg['bonus'] * 100)}%**\n"
            f"Fail: **{int(area_cfg['fail'] * 100)}%**"
        ),
        inline=True,
    )
    embed.add_field(
        name="Hệ số",
        value=(
            f"Reward: **x{area_cfg['reward']}**\n"
            f"Bonus: **x{area_cfg['bonus_multi']}**"
        ),
        inline=True,
    )
    return embed

def _make_payload(uid: str, pending: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "channel_id": pending.get("channel_id"),
        "content": f"<@{uid}>",
        "embed": build_result_embed(uid, pending),
    }

# ===== SEND HELPERS =====
async def _send_payload(bot, payload: Dict[str, Any], target=None) -> bool:
    try:
        if target is not None:
            if hasattr(target, "response"):  # interaction
                if not target.response.is_done():
                    await target.response.send_message(
                        content=payload.get("content"),
                        embed=payload.get("embed"),
                    )
                else:
                    await target.followup.send(
                        content=payload.get("content"),
                        embed=payload.get("embed"),
                    )
                return True

            await target.send(
                content=payload.get("content"),
                embed=payload.get("embed"),
            )
            return True

        channel_id = _safe_int(payload.get("channel_id"), 0)
        if not channel_id or bot is None:
            return False

        channel = bot.get_channel(channel_id)
        if channel is None:
            channel = await bot.fetch_channel(channel_id)

        if channel is None:
            return False

        await channel.send(
            content=payload.get("content"),
            embed=payload.get("embed"),
        )
        return True
    except Exception as e:
        print(f"[work._send_payload] {e}")
        return False

async def _reply(target, content=None, embed=None, view=None, ephemeral=False):
    try:
        if hasattr(target, "response"):
            if not target.response.is_done():
                return await target.response.send_message(
                    content=content,
                    embed=embed,
                    view=view,
                    ephemeral=ephemeral,
                )
            return await target.followup.send(
                content=content,
                embed=embed,
                view=view,
                ephemeral=ephemeral,
            )
        return await target.send(content=content, embed=embed, view=view)
    except Exception:
        return None

# ===== PENDING REWARD =====
async def _flush_pending_reward_locked(bot, users: Dict[str, Any], uid: str, target=None) -> Optional[Dict[str, Any]]:
    user = users.get(uid)
    if not isinstance(user, dict):
        return None

    pending = user.get("work_reward_pending")
    if not isinstance(pending, dict):
        return None

    # Credit gold once
    if not pending.get("credited", False):
        if not pending.get("failed", False):
            gold = _safe_int(pending.get("gold"), 0)
            if gold > 0:
                _credit_gold(users, uid, gold)
            pending["credited"] = True
            try:
                save_json(USER_FILE, users)
                _reload_cache()
            except Exception:
                return None
        else:
            pending["credited"] = True
            try:
                save_json(USER_FILE, users)
                _reload_cache()
            except Exception:
                return None

    payload = _make_payload(uid, pending)

    # Send notification once
    if not pending.get("sent", False):
        ok = await _send_payload(bot, payload, target=target)
        if not ok:
            return None
        pending["sent"] = True
        user.pop("work_reward_pending", None)
        try:
            save_json(USER_FILE, users)
            _reload_cache()
        except Exception:
            return None
        return payload

    # Already sent, just clear leftover pending
    user.pop("work_reward_pending", None)
    try:
        save_json(USER_FILE, users)
        _reload_cache()
    except Exception:
        pass
    return payload

# ===== SETTLE =====
async def _settle_job_locked(bot, users: Dict[str, Any], inv: Dict[str, Any], waifu_data: Dict[str, Any], uid: str, target=None) -> Optional[Dict[str, Any]]:
    user = users.get(uid)
    if not isinstance(user, dict):
        return None

    job = user.get("work_job")
    if not _is_job_active(job):
        return None

    if not _job_ready(job):
        return None

    area_key = str(job.get("area"))
    area_cfg = WORK_AREAS.get(area_key)
    if not area_cfg:
        user.pop("work_job", None)
        try:
            save_json(USER_FILE, users)
        except Exception:
            pass
        return None

    default_id = str(job.get("default_id", "unknown"))
    rank_str = str(job.get("rank", "thuong")).strip().lower() or "thuong"
    level = max(1, _safe_int(job.get("level", 1), 1))
    love_before = max(1, _safe_int(job.get("love_before", 1), 1))
    rank_base = _get_rank_base(rank_str)
    base_gold = _work_base_gold(rank_base, love_before, level)

    failed = random.random() < area_cfg["fail"]
    bonus_hit = False
    gold = 0
    love_loss = 0
    love_after = love_before

    if not failed:
        gold = int(base_gold * area_cfg["reward"])
        if random.random() < area_cfg["bonus"]:
            bonus_hit = True
            gold = int(gold * area_cfg["bonus_multi"])
        gold = _clamp_gold(gold)
        love_loss = max(1, gold // 50)
        love_after = max(1, love_before - love_loss)
        _set_love(users, inv, uid, default_id, love_after)

    user.pop("work_job", None)
    user["last_work"] = job.get("started_at", datetime.now().isoformat())
    user["work_reward_pending"] = {
        "area": area_key,
        "rank": rank_str,
        "level": level,
        "default_id": default_id,
        "love_before": love_before,
        "love_after": love_after,
        "love_loss": love_loss,
        "base_gold": base_gold,
        "gold": gold,
        "bonus_hit": bonus_hit,
        "failed": failed,
        "channel_id": job.get("channel_id"),
        "user_name": job.get("user_name"),
        "completed_at": datetime.now().isoformat(),
        "credited": False if not failed else True,
        "sent": False,
    }

    try:
        save_json(USER_FILE, users)
        save_json(INV_FILE, inv)
        _reload_cache()
    except Exception:
        return None

    return await _flush_pending_reward_locked(bot, users, uid, target=target)

# ===== START JOB =====
async def _start_job_locked(target, users: Dict[str, Any], inv: Dict[str, Any], levels: Dict[str, Any], waifu_data: Dict[str, Any], uid: str, area_key: str):
    user = _get_user(users, uid)

    if isinstance(user.get("work_reward_pending"), dict):
        return False, "⏳ Phần thưởng trước đó هنوز đang được xử lý, hãy thử lại sau vài giây."

    active_job = user.get("work_job")
    if _is_job_active(active_job):
        claim_at = _parse_dt(active_job.get("claim_at"))
        if claim_at and datetime.now() < claim_at:
            remain = claim_at - datetime.now()
            embed = build_working_embed(
                target.user.display_name if hasattr(target, "user") else uid,
                f"<@{uid}>",
                active_job,
                remain,
            )
            return False, embed

        # If job is ready, try to flush immediately
        return True, await _settle_job_locked(BOT, users, inv, waifu_data, uid, target=target)

    default_id = inv.get(uid, {}).get("default_waifu")
    if not default_id:
        return False, "❌ Bạn chưa có waifu để đi làm."

    waifus = inv.get(uid, {}).get("waifus")
    if not _waifu_exists(waifus, default_id):
        return False, "❌ Waifu mặc định không hợp lệ."

    rank_str = _get_rank(default_id, waifu_data)
    if not rank_str:
        return False, "❌ Waifu này chưa có dữ liệu trong waifu_data.json."

    try:
        await sync_all()
    except Exception as e:
        print(f"[work.sync_all] {e}")

    level = _get_level(levels, uid, default_id)
    area_cfg = WORK_AREAS.get(area_key)
    if not area_cfg:
        return False, "❌ Khu vực không hợp lệ."

    if level < area_cfg["unlock"]:
        return False, f"🔒 Khu vực **{area_cfg['label']}** cần level **{area_cfg['unlock']}**."

    now = datetime.now()
    last_work = _cooldown_end(user)
    if last_work and now < last_work + WORK_COOLDOWN:
        remain = (last_work + WORK_COOLDOWN) - now
        return False, f"⏳ Hãy chờ **{_format_remaining(remain)}** nữa!"

    love_point = _get_love(users, inv, uid, default_id)
    love_point = max(1, min(love_point, 1_000_000))

    job = {
        "active": True,
        "area": area_key,
        "default_id": default_id,
        "rank": rank_str,
        "level": level,
        "love_before": love_point,
        "started_at": now.isoformat(),
        "claim_at": (now + WORK_DURATION).isoformat(),
        "channel_id": str(getattr(target, "channel_id", None)) if getattr(target, "channel_id", None) else None,
        "user_name": getattr(getattr(target, "user", None), "display_name", None) if hasattr(target, "user") else getattr(target, "display_name", uid),
    }

    user["work_job"] = job
    user["last_work"] = now.isoformat()

    try:
        save_json(USER_FILE, users)
        _reload_cache()
    except Exception:
        return False, "❌ Có lỗi khi lưu dữ liệu, vui lòng thử lại."

    pending_embed = build_working_embed(
        job["user_name"] or uid,
        f"<@{uid}>",
        job,
        WORK_DURATION,
    )
    return True, pending_embed

# ===== UI =====
class WorkButton(discord.ui.Button):
    def __init__(self, view_ref, area_key: str, disabled: bool = False):
        cfg = WORK_AREAS[area_key]
        super().__init__(
            label=cfg["label"],
            emoji=cfg["emoji"],
            style=discord.ButtonStyle.primary,
            disabled=disabled,
        )
        self.view_ref = view_ref
        self.area_key = area_key

    async def callback(self, interaction: discord.Interaction):
        await self.view_ref.handle_area(interaction, self.area_key)

class WorkView(discord.ui.View):
    def __init__(self, owner_id: str, level: int):
        super().__init__(timeout=60)
        self.owner_id = str(owner_id)
        self.level = max(1, _safe_int(level, 1))
        self.message: Optional[discord.Message] = None

        for area_key in WORK_ORDER:
            cfg = WORK_AREAS[area_key]
            self.add_item(WorkButton(self, area_key, disabled=self.level < cfg["unlock"]))

    async def interaction_check(self, interaction: discord.Interaction):
        if str(interaction.user.id) != self.owner_id:
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message("❌ Bạn không phải người mở bảng này.", ephemeral=True)
                else:
                    await interaction.followup.send("❌ Bạn không phải người mở bảng này.", ephemeral=True)
            except Exception:
                pass
            return False
        return True

    async def handle_area(self, interaction: discord.Interaction, area_key: str):
        lock = get_lock(self.owner_id)
        async with lock:
            users = load_json(USER_FILE, {})
            inv = load_json(INV_FILE, {})
            levels = load_json(LEVEL_FILE, {})
            waifu_data = load_json(WAIFU_FILE, {})

            if not isinstance(users, dict):
                users = {}
            if not isinstance(inv, dict):
                inv = {}
            if not isinstance(levels, dict):
                levels = {}
            if not isinstance(waifu_data, dict):
                waifu_data = {}

            ok, result = await _start_job_locked(interaction, users, inv, levels, waifu_data, self.owner_id, area_key)

            if not ok:
                if isinstance(result, discord.Embed):
                    try:
                        await interaction.response.edit_message(embed=result, view=None)
                    except Exception:
                        try:
                            await interaction.followup.send(embed=result, ephemeral=True)
                        except Exception:
                            pass
                else:
                    await _reply(interaction, content=str(result), ephemeral=True)
                return

            # Job started or settled result
            if isinstance(result, discord.Embed):
                try:
                    await interaction.response.edit_message(embed=result, view=None)
                except Exception:
                    try:
                        await interaction.followup.send(embed=result, ephemeral=False)
                    except Exception:
                        pass
                return

            if isinstance(result, dict):
                # settle result payload was produced
                try:
                    await interaction.response.edit_message(content="💼 Công việc đã hoàn tất.", view=None)
                except Exception:
                    try:
                        await interaction.followup.send(content="💼 Công việc đã hoàn tất.", ephemeral=False)
                    except Exception:
                        pass
                return

            await _reply(interaction, content="💼 Đã bắt đầu làm việc!", ephemeral=False)

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        try:
            if self.message:
                await self.message.edit(view=self)
        except Exception:
            pass

# ===== LOOP =====
async def work_loop():
    await BOT.wait_until_ready()

    while not BOT.is_closed():
        try:
            users = load_json(USER_FILE, {})
            if isinstance(users, dict):
                for uid in list(users.keys()):
                    lock = get_lock(str(uid))
                    if lock.locked():
                        continue

                    async with lock:
                        fresh_users = load_json(USER_FILE, {})
                        fresh_inv = load_json(INV_FILE, {})
                        fresh_waifu = load_json(WAIFU_FILE, {})
                        fresh_levels = load_json(LEVEL_FILE, {})

                        if not all(isinstance(x, dict) for x in [fresh_users, fresh_inv, fresh_waifu, fresh_levels]):
                            continue

                        user = fresh_users.get(str(uid))
                        if not isinstance(user, dict):
                            continue

                        # First, try to finish pending reward if any
                        if isinstance(user.get("work_reward_pending"), dict):
                            await _flush_pending_reward_locked(BOT, fresh_users, str(uid))
                            continue

                        job = user.get("work_job")
                        if _is_job_active(job) and _job_ready(job):
                            await _settle_job_locked(BOT, fresh_users, fresh_inv, fresh_waifu, str(uid))
        except Exception:
            pass

        await asyncio.sleep(CHECK_INTERVAL)

# ===== COMMAND =====
async def work(ctx_or_interaction):
    if hasattr(ctx_or_interaction, "response") and not ctx_or_interaction.response.is_done():
        try:
            await ctx_or_interaction.response.defer(thinking=True)
        except Exception as e:
            print(f"[work] defer error: {e}")

    user_obj = ctx_or_interaction.user if hasattr(ctx_or_interaction, "user") else ctx_or_interaction.author
    uid = str(user_obj.id)
    display_name = getattr(user_obj, "display_name", getattr(user_obj, "name", uid))
    mention = getattr(user_obj, "mention", f"<@{uid}>")

    lock = get_lock(uid)
    async with lock:
        users = load_json(USER_FILE, {})
        inv = load_json(INV_FILE, {})
        levels = load_json(LEVEL_FILE, {})
        waifu_data = load_json(WAIFU_FILE, {})

        if not all(isinstance(x, dict) for x in [users, inv, levels, waifu_data]):
            return await _reply(ctx_or_interaction, content="❌ Lỗi dữ liệu, vui lòng thử lại.", ephemeral=True)

        user = _get_user(users, uid)

        # pending reward has priority
        if isinstance(user.get("work_reward_pending"), dict):
            payload = await _flush_pending_reward_locked(BOT, users, uid, target=ctx_or_interaction)
            if payload:
                return None
            return await _reply(ctx_or_interaction, content="⏳ Đang xử lý phần thưởng cũ, thử lại sau vài giây.", ephemeral=True)

        active_job = user.get("work_job")
        if _is_job_active(active_job):
            if _job_ready(active_job):
                payload = await _settle_job_locked(BOT, users, inv, waifu_data, uid, target=ctx_or_interaction)
                if payload:
                    return None
                return await _reply(ctx_or_interaction, content="❌ Có lỗi khi nhận thưởng, hãy thử lại.", ephemeral=True)

            remain = _remaining_to_claim(active_job) or timedelta(0)
            embed = build_working_embed(display_name, mention, active_job, remain)
            return await _reply(ctx_or_interaction, embed=embed, ephemeral=False)

        # cooldown
        last_work = _cooldown_end(user)
        if last_work and datetime.now() < last_work + WORK_COOLDOWN:
            remain = (last_work + WORK_COOLDOWN) - datetime.now()
            return await _reply(ctx_or_interaction, content=f"⏳ Hãy chờ **{_format_remaining(remain)}** nữa!", ephemeral=True)

        # prerequisites
        default_id = inv.get(uid, {}).get("default_waifu")
        if not default_id:
            return await _reply(ctx_or_interaction, content="❌ Bạn chưa có waifu nào để đi làm!", ephemeral=True)

        waifus = inv.get(uid, {}).get("waifus")
        if not _waifu_exists(waifus, default_id):
            return await _reply(ctx_or_interaction, content="❌ Waifu mặc định không hợp lệ!", ephemeral=True)

        rank_str = _get_rank(default_id, waifu_data)
        if not rank_str:
            return await _reply(ctx_or_interaction, content="❌ Waifu này chưa có dữ liệu trong waifu_data.json.", ephemeral=True)

        try:
            await sync_all()
        except Exception as e:
            print(f"[work.sync_all] {e}")

        level = _get_level(levels, uid, default_id)
        love_point = _get_love(users, inv, uid, default_id)

        view = WorkView(uid, level)
        embed = build_area_select_embed(display_name, mention, default_id, rank_str, level, love_point)

        if hasattr(ctx_or_interaction, "response"):
            try:
                if ctx_or_interaction.response.is_done():
                    msg = await ctx_or_interaction.followup.send(embed=embed, view=view, wait=True)
                    view.message = msg
                else:
                    await ctx_or_interaction.response.send_message(embed=embed, view=view)
                    try:
                        view.message = await ctx_or_interaction.original_response()
                    except Exception:
                        view.message = None
            except Exception:
                pass
        else:
            try:
                view.message = await ctx_or_interaction.send(embed=embed, view=view)
            except Exception:
                pass

print("Loaded work has success")