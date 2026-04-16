import asyncio
import json
import os
import time
from typing import Any, Dict, Optional, Union

import discord
from discord.ext import commands

# FIX: Helper gửi message an toàn với None và interaction
async def safe_send(ctx, *, content=None, embed=None, view=None, ephemeral=False):
    kwargs = {}
    if content is not None:
        kwargs["content"] = content
    if embed is not None:
        kwargs["embed"] = embed
    if view is not None:
        kwargs["view"] = view

    if hasattr(ctx, "response"):
        if not ctx.response.is_done():
            return await ctx.response.send_message(**kwargs, ephemeral=ephemeral)
        return await ctx.followup.send(**kwargs)

    return await ctx.send(**kwargs)

# FIX: Helper edit message an toàn với None
async def safe_edit(msg, *, content=None, embed=None, view=None):
    kwargs = {}
    if content is not None:
        kwargs["content"] = content
    if embed is not None:
        kwargs["embed"] = embed
    if view is not None:
        kwargs["view"] = view
    return await msg.edit(**kwargs)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "Data")
INV_FILE = os.path.join(DATA_DIR, "inventory.json")
WAIFU_FILE = os.path.join(DATA_DIR, "waifu_data.json")

_INV_CACHE: Dict[str, Any] = {}
_WAIFU_CACHE: Dict[str, Any] = {}
_INV_TS = 0.0
_WAIFU_TS = 0.0
_INV_TTL = 10.0
_WAIFU_TTL = 30.0

_LOCKS: Dict[str, asyncio.Lock] = {}


def get_lock(path: str) -> asyncio.Lock:
    if path not in _LOCKS:
        _LOCKS[path] = asyncio.Lock()
    return _LOCKS[path]


def safe_int(value: Any) -> int:
    try:
        return int(value)
    except Exception:
        return 0


def safe_load_json(path: str) -> Dict[str, Any]:
    if not os.path.exists(path):
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump({}, f, ensure_ascii=False, indent=4)
        except Exception:
            pass
        return {}

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def load_inventory(force: bool = False) -> Dict[str, Any]:
    global _INV_CACHE, _INV_TS
    now = time.time()
    if force or not _INV_CACHE or (now - _INV_TS) > _INV_TTL:
        _INV_CACHE = safe_load_json(INV_FILE)
        _INV_TS = now
    return _INV_CACHE


def load_waifu_data(force: bool = False) -> Dict[str, Any]:
    global _WAIFU_CACHE, _WAIFU_TS
    now = time.time()
    if force or not _WAIFU_CACHE or (now - _WAIFU_TS) > _WAIFU_TTL:
        _WAIFU_CACHE = safe_load_json(WAIFU_FILE)
        _WAIFU_TS = now
    return _WAIFU_CACHE


async def save_inventory(data: Dict[str, Any]) -> None:
    global _INV_CACHE, _INV_TS
    lock = get_lock(INV_FILE)

    async with lock:
        tmp = INV_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
        os.replace(tmp, INV_FILE)

        # sync cache ngay sau khi save
        _INV_CACHE = data
        _INV_TS = time.time()


def get_waifu_name(waifu_id: str, waifu_data: Dict[str, Any]) -> str:
    meta = waifu_data.get(waifu_id, {})
    if isinstance(meta, dict):
        for key in ("name", "display_name", "title", "char_name"):
            if meta.get(key):
                return str(meta[key])
    return str(waifu_id)


def build_entries(user_data: Dict[str, Any], waifu_data: Dict[str, Any]):
    entries = []

    bag = user_data.get("bag", {})
    if isinstance(bag, dict):
        for wid, count in bag.items():
            count = safe_int(count)
            if count > 0:
                entries.append(("waifu", str(wid), count, get_waifu_name(str(wid), waifu_data)))

    bag_item = user_data.get("bag_item", {})
    if isinstance(bag_item, dict):
        for item_name, count in bag_item.items():
            count = safe_int(count)
            if count > 0:
                entries.append(("item", str(item_name), count, str(item_name)))

    entries.sort(key=lambda x: (0 if x[0] == "waifu" else 1, x[3].lower()))
    return entries


def build_embed(
    target_user: Union[discord.User, discord.Member],
    requester: Union[discord.User, discord.Member],
    entries,
) -> discord.Embed:
    waifu_lines = []
    item_lines = []

    for t, raw_id, count, display_name in entries:
        if t == "waifu":
            waifu_lines.append(f"• `{display_name}` x{count}")
        else:
            item_lines.append(f"• `{display_name}` x{count}")

    waifu_text = "\n".join(waifu_lines) if waifu_lines else "Trống"
    item_text = "\n".join(item_lines) if item_lines else "Trống"

    embed = discord.Embed(
        title=f"🎒 Túi đồ của {target_user.display_name}",
        color=0x1E1F22,
    )
    embed.set_thumbnail(url=target_user.display_avatar.url)
    embed.add_field(name="💖 Waifus", value=waifu_text, inline=False)
    embed.add_field(name="📦 Vật phẩm", value=item_text, inline=False)
    embed.set_footer(
        text=f"Yêu cầu bởi: {requester.display_name} • Waifu: {len(waifu_lines)} • Item: {len(item_lines)}"
    )
    return embed


# ===== CTX HELPERS =====

def get_user(ctx):
    return ctx.user if isinstance(ctx, discord.Interaction) else ctx.author


async def resolve_target_user(
    ctx: Union[commands.Context, discord.Interaction],
    target_user: Optional[Union[discord.User, discord.Member]] = None,
):
    if target_user is not None:
        return target_user

    if isinstance(ctx, commands.Context):
        if ctx.message and ctx.message.reference and ctx.message.reference.resolved:
            ref = ctx.message.reference.resolved
            if isinstance(ref, discord.Message) and ref.author:
                return ref.author
        return ctx.author

    if isinstance(ctx, discord.Interaction):
        return ctx.user

    return None



# Đã thay thế send_message bằng safe_send ở dưới


# ===== MAIN =====

async def bag_logic(
    ctx: Union[commands.Context, discord.Interaction],
    target_user: Optional[Union[discord.User, discord.Member]] = None,
):
    requester = get_user(ctx)
    target_user = await resolve_target_user(ctx, target_user)

    # 🔥 FIX QUAN TRỌNG: luôn load mới để tránh stale data
    inv = load_inventory(force=True)
    waifu_data = load_waifu_data(force=True)

    user_data = inv.get(str(target_user.id), {})
    if not isinstance(user_data, dict):
        user_data = {}

    entries = build_entries(user_data, waifu_data)
    embed = build_embed(target_user, requester, entries)

    content = None
    if target_user.id != requester.id:
        content = target_user.mention

    await safe_send(ctx, content=content, embed=embed)


print("Loaded bag has successs")