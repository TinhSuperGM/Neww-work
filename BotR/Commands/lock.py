import asyncio
import json
import os
from typing import Optional, Union

import discord

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOCK_FILE = os.path.join(BASE_DIR, "Data", "lock.json")
LOCK_LOCK = asyncio.Lock()


def load_json(path):
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception as e:
        print(f"[lock.py] load_json error: {path} -> {e}")
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
        print(f"[lock.py] save_json error: {path} -> {e}")


def get_user_obj(ctx):
    if hasattr(ctx, "author") and ctx.author:
        return ctx.author
    if hasattr(ctx, "user") and ctx.user:
        return ctx.user
    return None


async def _send_like(ctx, content=None, embed=None, ephemeral=False):
    if isinstance(ctx, discord.Interaction):
        if ctx.response.is_done():
            return await ctx.followup.send(content=content, embed=embed, ephemeral=ephemeral)
        return await ctx.response.send_message(content=content, embed=embed, ephemeral=ephemeral)
    return await ctx.send(content=content, embed=embed)


async def _defer_if_needed(ctx):
    if isinstance(ctx, discord.Interaction) and not ctx.response.is_done():
        try:
            await ctx.response.defer(ephemeral=True, thinking=False)
        except Exception:
            pass


def _normalize_state(state):
    if state is None:
        return None
    if isinstance(state, bool):
        return state
    s = str(state).strip().lower()
    if s in ("on", "true", "1", "lock", "enable", "enabled", "yes"):
        return True
    if s in ("off", "false", "0", "unlock", "disable", "disabled", "no"):
        return False
    if s in ("toggle", "switch"):
        return None
    return None


async def is_user_locked(uid) -> bool:
    async with LOCK_LOCK:
        data = load_json(LOCK_FILE)
    entry = data.get(str(uid), False)

    if isinstance(entry, bool):
        return entry
    if isinstance(entry, dict):
        return bool(entry.get("locked", entry.get("lock", False)))
    return False


async def set_user_locked(uid, locked: bool):
    async with LOCK_LOCK:
        data = load_json(LOCK_FILE)
        data[str(uid)] = {"locked": bool(locked)}
        save_json(LOCK_FILE, data)
    return bool(locked)


async def lock_logic(ctx, state: Optional[Union[str, bool]] = None):
    user = get_user_obj(ctx)
    if not user:
        return await _send_like(ctx, content="❌ Không xác định user", ephemeral=True)

    await _defer_if_needed(ctx)

    current = await is_user_locked(user.id)
    desired = _normalize_state(state)

    if desired is None:
        new_state = not current
    else:
        new_state = desired

    await set_user_locked(user.id, new_state)

    if new_state:
        return await _send_like(ctx, content="🔒 Đã bật lock.", ephemeral=True)
    return await _send_like(ctx, content="🔓 Đã tắt lock.", ephemeral=True)


async def setup(bot):
    return None