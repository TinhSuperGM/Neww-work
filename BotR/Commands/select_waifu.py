import discord
import json
import os
import tempfile
import asyncio
from typing import Any, Dict

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "Data")
INV_FILE = os.path.join(DATA_DIR, "inventory.json")

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

_inv_lock = asyncio.Lock()


def ensure_storage() -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    if not os.path.exists(INV_FILE):
        with open(INV_FILE, "w", encoding="utf-8") as f:
            json.dump({}, f, indent=4, ensure_ascii=False)


def _load_no_lock() -> Dict[str, Any]:
    try:
        with open(INV_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        return {}


def _save_no_lock(inv: Dict[str, Any]) -> None:
    tmp_fd, tmp_path = tempfile.mkstemp(
        prefix="inventory_",
        suffix=".json",
        dir=DATA_DIR
    )
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            json.dump(inv, f, indent=4, ensure_ascii=False)
        os.replace(tmp_path, INV_FILE)
    except Exception:
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            pass
        raise



# Đã thay thế _send_response bằng safe_send ở dưới


# ===== HELPER FIX DEFAULT =====
def _fix_default_waifu(user_data: Dict[str, Any]) -> None:
    """
    Nếu default_waifu không còn trong waifus hoặc count <= 0 → reset về None
    """
    default = user_data.get("default_waifu")
    waifus = user_data.get("waifus", {})

    if not default:
        return

    count = waifus.get(default, 0)

    try:
        count = int(count)
    except Exception:
        count = 0

    if count <= 0:
        user_data["default_waifu"] = None


# ===== LOGIC =====
async def select_waifu_logic(interaction, waifu_id: str):
    ensure_storage()

    if not interaction or not interaction.user:
        return

    uid = str(interaction.user.id)

    if not waifu_id or not isinstance(waifu_id, str):
        return await safe_send(
            interaction,
            content="❌ Bạn không sở hữu waifu ``!",
            ephemeral=True
        )

    waifu_id = waifu_id.lower().strip()

    error_msg = None

    async with _inv_lock:
        inv = await asyncio.to_thread(_load_no_lock)

        user_data = inv.get(uid)
        if not isinstance(user_data, dict):
            error_msg = f"❌ Bạn không sở hữu waifu `{waifu_id}`!"
        else:
            # đảm bảo structure
            if "waifus" not in user_data or not isinstance(user_data["waifus"], dict):
                user_data["waifus"] = {}

            if "default_waifu" not in user_data:
                user_data["default_waifu"] = None

            # 🔥 FIX: đảm bảo default không bị "treo"
            _fix_default_waifu(user_data)

            waifus = user_data["waifus"]

            if waifu_id not in waifus or int(waifus.get(waifu_id, 0)) <= 0:
                error_msg = f"❌ Bạn không sở hữu waifu `{waifu_id}`!"
            else:
                user_data["default_waifu"] = waifu_id
                inv[uid] = user_data

                try:
                    await asyncio.to_thread(_save_no_lock, inv)
                except Exception:
                    error_msg = "❌ Có lỗi khi lưu dữ liệu!"

    if error_msg:
        return await safe_send(interaction, content=error_msg, ephemeral=True)

    await safe_send(
        interaction,
        content=f"✅ Đã chọn **{waifu_id}** làm waifu mặc định!"
    )


# ===== OPTIONAL: AUTO CLEAN (GỌI Ở COMMAND KHÁC) =====
async def cleanup_default_waifu(uid: str):
    """
    Gọi hàm này sau khi SELL / REMOVE để auto clear default nếu cần
    """
    async with _inv_lock:
        inv = await asyncio.to_thread(_load_no_lock)

        user_data = inv.get(uid)
        if not isinstance(user_data, dict):
            return

        _fix_default_waifu(user_data)

        inv[uid] = user_data

        try:
            await asyncio.to_thread(_save_no_lock, inv)
        except Exception:
            pass


# ===== SETUP =====
async def setup(bot):
    pass


print("Loaded select waifu has success")