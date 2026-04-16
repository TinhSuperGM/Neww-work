import asyncio
import json
import os
from typing import Optional

import discord

# Import lock chung từ fight để team/fight thật sự sync với nhau.
# Lưu ý: nếu project của bạn dùng path khác, đổi lại cho đúng structure.
from Commands.fight import INV_LOCK

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INV_FILE = os.path.join(BASE_DIR, "Data", "inventory.json")
TEAM_FILE = os.path.join(BASE_DIR, "Data", "team.json")
WAIFU_FILE = os.path.join(BASE_DIR, "Data", "waifu_data.json")

TEAM_LOCK = asyncio.Lock()
_LAST_SET = {}  # uid -> monotonic time


# ===== JSON SAFE =====
def load_json(path):
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception as e:
        print(f"[team.py] load_json error: {path} -> {e}")
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
        print(f"[team.py] save_json error: {path} -> {e}")

def resolve_waifu_id(input_id: str, waifu_data: dict, user_waifus: dict):
    input_id = str(input_id).lower()

    # 1. nếu user nhập đúng ID
    if input_id in user_waifus:
        return input_id

    # 2. match theo name
    for wid, meta in waifu_data.items():
        name = str(meta.get("name", "")).lower()
        display = str(meta.get("display_name", "")).lower()

        if input_id in (name, display):
            if wid in user_waifus:
                return wid

    return None
async def resolve_target_user(ctx, target):
    # 1. Ưu tiên param (slash command)
    if target:
        return target

    # 2. PREFIX: check reply
    if hasattr(ctx, "message") and ctx.message:
        ref = getattr(ctx.message, "reference", None)
        if ref and ref.resolved and getattr(ref.resolved, "author", None):
            return ref.resolved.author

        # 3. check mention trong message
        mentions = getattr(ctx.message, "mentions", [])
        if mentions:
            return mentions[0]

        # 4. check ID trong text
        content = ctx.message.content or ""
        import re
        match = re.search(r"\d{17,20}", content)
        if match:
            uid = int(match.group())
            guild = getattr(ctx, "guild", None)
            if guild:
                member = guild.get_member(uid)
                if member:
                    return member

    # 5. fallback chính mình
    return get_user_obj(ctx)
# ===== HELPER =====
def get_user_obj(ctx):
    return getattr(ctx, "user", None) or getattr(ctx, "author", None)


async def send_like(ctx, content=None, embed=None, view=None, ephemeral=False):
    kwargs = {}

    if content is not None:
        kwargs["content"] = content
    if embed is not None:
        kwargs["embed"] = embed
    if view is not None:  # 🔥 FIX: không truyền None
        kwargs["view"] = view

    # ===== SLASH COMMAND =====
    if hasattr(ctx, "response") and hasattr(ctx.response, "send_message"):
        is_done = False

        # 🔥 FIX: tránh crash PrefixResponse
        if hasattr(ctx.response, "is_done"):
            try:
                is_done = ctx.response.is_done()
            except Exception:
                is_done = False

        if not is_done:
            return await ctx.response.send_message(
                **kwargs,
                ephemeral=ephemeral
            )

        return await ctx.followup.send(
            **kwargs,
            ephemeral=ephemeral
        )

    # ===== PREFIX COMMAND =====
    if hasattr(ctx, "channel") and ctx.channel:
        return await ctx.channel.send(**kwargs)

    return None
# ===== TEAM CORE =====
def normalize_team_ids(inv, uid, team_data):
    uid = str(uid)

    user = inv.get(uid, {})
    waifus = user.get("waifus", {})

    if isinstance(waifus, list):
        waifus = {str(w): 0 for w in waifus}

    source = team_data.get(uid, {}).get("team", [])

    if not source:
        default_id = user.get("default_waifu")
        if default_id is not None:
            source = [str(default_id)]
        elif isinstance(waifus, dict):
            source = list(waifus.keys())

    out = []
    seen = set()

    for wid in source:
        wid = str(wid)

        if wid in seen:
            continue

        if isinstance(waifus, dict) and wid in waifus:
            out.append(wid)
            seen.add(wid)

        if len(out) >= 3:
            break

    return out


def _as_waifu_dict(inv: dict, uid: str) -> dict:
    uid = str(uid)
    user = inv.setdefault(uid, {})
    waifus = user.setdefault("waifus", {})

    if isinstance(waifus, list):
        waifus = {str(w): 0 for w in waifus}
        user["waifus"] = waifus

    if not isinstance(waifus, dict):
        waifus = {}
        user["waifus"] = waifus

    return waifus


def _waifu_name(waifu_data: dict, wid: str):
    meta = waifu_data.get(wid, {})
    return meta.get("name") or meta.get("display_name") or wid


# ===== ANTI-SPAM =====
def _can_set(uid):
    now = asyncio.get_event_loop().time()

    # cleanup nhẹ để tránh dict phình theo thời gian
    if len(_LAST_SET) > 5000:
        _LAST_SET.clear()

    last = _LAST_SET.get(uid, 0)
    if now - last < 2:
        return False

    _LAST_SET[uid] = now
    return True


# ===== LOGIC =====
async def show_team_logic(ctx, target: Optional[discord.Member] = None):
    inv = load_json(INV_FILE)
    team_data = load_json(TEAM_FILE)
    waifu_data = load_json(WAIFU_FILE)

    user = await resolve_target_user(ctx, target)

    if not user:
        return await send_like(ctx, content="❌ Không xác định user", ephemeral=True)

    uid = str(user.id)
    team = normalize_team_ids(inv, uid, team_data)

    if not team:
        return await send_like(ctx, content="Không có waifu.", ephemeral=True)

    lines = []
    for wid in team:
        meta = waifu_data.get(wid, {})
        rank = meta.get("rank", "unknown")
        lines.append(f"• **{_waifu_name(waifu_data, wid)}** (`{wid}`) | rank: `{rank}`")

    embed = discord.Embed(
        title=f"Team của {getattr(user, 'display_name', getattr(user, 'name', uid))}",
        description="\n".join(lines),
        color=discord.Color.blurple(),
    )

    return await send_like(ctx, embed=embed)

async def set_team_logic(ctx, waifu_ids: str):
    user = get_user_obj(ctx)
    if not user:
        return await send_like(ctx, content="❌ Không xác định user", ephemeral=True)

    uid = str(user.id)

    if not _can_set(uid):
        return await send_like(ctx, content="⏳ Thao tác quá nhanh", ephemeral=True)

    async with INV_LOCK:
        async with TEAM_LOCK:
            inv = load_json(INV_FILE)
            team_data = load_json(TEAM_FILE)
            waifu_data = load_json(WAIFU_FILE)

            waifus = _as_waifu_dict(inv, uid)

            raw_ids = [
                str(x.strip())
                for x in waifu_ids.replace(",", " ").replace("\n", " ").split()
                if x.strip()
            ]

            if not raw_ids:
                return await send_like(ctx, content="❌ Chưa nhập waifu", ephemeral=True)

            chosen = []
            seen = set()
            invalid = []

            for raw in raw_ids:
                wid = resolve_waifu_id(raw, waifu_data, waifus)

                if not wid:
                    invalid.append(raw)
                    continue

                if wid in seen:
                    continue

                chosen.append(wid)
                seen.add(wid)

                if len(chosen) >= 3:
                    break

            if not chosen:
                return await send_like(ctx, content="❌ Không có waifu hợp lệ", ephemeral=True)

            team_data[uid] = {"team": chosen}
            save_json(TEAM_FILE, team_data)

    msg = f"✅ Team: {', '.join(chosen)}"

    if invalid:
        msg += f"\n⚠️ Không hợp lệ: {', '.join(invalid[:10])}"

    return await send_like(ctx, content=msg, ephemeral=True)
async def add_team_logic(ctx, waifu_id: str):
    user = get_user_obj(ctx)
    if not user:
        return await send_like(ctx, content="❌ Không xác định user", ephemeral=True)

    uid = str(user.id)

    if not _can_set(uid):
        return await send_like(ctx, content="⏳ Thao tác quá nhanh", ephemeral=True)

    async with INV_LOCK:
        async with TEAM_LOCK:
            inv = load_json(INV_FILE)
            team_data = load_json(TEAM_FILE)

            waifus = _as_waifu_dict(inv, uid)

            wid = str(waifu_id).strip()

            if wid not in waifus:
                return await send_like(ctx, content="❌ Bạn không sở hữu waifu này", ephemeral=True)

            current = team_data.get(uid, {}).get("team", [])

            if wid in current:
                return await send_like(ctx, content="⚠️ Waifu đã có trong team", ephemeral=True)

            if len(current) >= 3:
                return await send_like(ctx, content="❌ Team đã đủ 3 waifu", ephemeral=True)

            current.append(wid)
            team_data[uid] = {"team": current}

            save_json(TEAM_FILE, team_data)

    return await send_like(ctx, content=f"✅ Đã thêm {wid} vào team", ephemeral=True)
async def remove_team_logic(ctx, waifu_id: str):
    user = get_user_obj(ctx)
    if not user:
        return await send_like(ctx, content="❌ Không xác định user", ephemeral=True)

    uid = str(user.id)

    async with INV_LOCK:
        async with TEAM_LOCK:
            team_data = load_json(TEAM_FILE)

            current = team_data.get(uid, {}).get("team", [])

            wid = str(waifu_id).strip()

            if wid not in current:
                return await send_like(ctx, content="❌ Waifu không có trong team", ephemeral=True)

            current.remove(wid)

            if current:
                team_data[uid] = {"team": current}
            else:
                team_data.pop(uid, None)

            save_json(TEAM_FILE, team_data)

    return await send_like(ctx, content=f"✅ Đã xoá {wid} khỏi team", ephemeral=True)
async def clear_team_logic(ctx):
    user = get_user_obj(ctx)
    if not user:
        return await send_like(ctx, content="❌ Không xác định user", ephemeral=True)

    uid = str(user.id)

    # QUY TẮC CHUNG TOÀN PROJECT:
    # INV_LOCK -> TEAM_LOCK
    async with INV_LOCK:
        async with TEAM_LOCK:
            team_data = load_json(TEAM_FILE)
            team_data.pop(uid, None)
            save_json(TEAM_FILE, team_data)

    return await send_like(ctx, content="✅ Đã xoá team", ephemeral=True)


async def team_logic(ctx, action: str = None, args: str = None, target: Optional[discord.Member] = None):
    if not action or action == "show":
        return await show_team_logic(ctx, target)

    if action == "set":
        return await set_team_logic(ctx, args or "")

    if action == "add":
        if not args:
            return await send_like(ctx, content="❌ Cú pháp: team add <waifu_id>", ephemeral=True)
        return await add_team_logic(ctx, args)

    if action in ("remove", "rm", "del"):
        if not args:
            return await send_like(ctx, content="❌ Cú pháp: team remove <waifu_id>", ephemeral=True)
        return await remove_team_logic(ctx, args)

    if action == "clear":
        return await clear_team_logic(ctx)

    return await send_like(ctx, content="❌ Lệnh không hợp lệ")
async def setup(bot):
    return None


print("Loaded team has success")