import json
import os
import random
import asyncio
import tempfile

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

from Commands.prayer import get_luck
from Data.level import sync_all

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INV_FILE = os.path.join(BASE_DIR, "Data", "inventory.json")

# ===== LOCKS =====
_user_locks = {}
_inventory_lock = asyncio.Lock()  # 🔥 GLOBAL LOCK


def get_lock(uid: str):
    if uid not in _user_locks:
        _user_locks[uid] = asyncio.Lock()
    return _user_locks[uid]


# ===== FILE =====
def ensure_file():
    os.makedirs(os.path.dirname(INV_FILE), exist_ok=True)
    if not os.path.exists(INV_FILE):
        with open(INV_FILE, "w", encoding="utf-8") as f:
            json.dump({}, f)


def _load():
    try:
        with open(INV_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except:
        return {}


def _save(inv):
    tmp_fd, tmp_path = tempfile.mkstemp(dir=os.path.dirname(INV_FILE))
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            json.dump(inv, f, indent=4, ensure_ascii=False)
        os.replace(tmp_path, INV_FILE)
    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except:
                pass


# ===== MAIN =====
async def use_logic(user, send, waifu_id=None, item_id=None, qty=1):
    ensure_file()
    uid = str(user.id)

    if qty <= 0:
        return await safe_send(user, content="❌ Số lượng phải lớn hơn 0.")

    async with get_lock(uid):           # lock user
        async with _inventory_lock:     # 🔥 lock toàn inventory

            inv = await asyncio.to_thread(_load)

            user_data = inv.setdefault(uid, {
                "waifus": {},
                "bag": {},
                "bag_item": {},
                "default_waifu": None
            })

            user_data.setdefault("waifus", {})
            user_data.setdefault("bag", {})
            user_data.setdefault("bag_item", {})

            # ===== USE WAIFU =====
            if waifu_id:
                if waifu_id not in user_data["bag"]:
                    return await safe_send(user, content=f"❌ Bạn không có waifu `{waifu_id}`.")

                if waifu_id in user_data["waifus"]:
                    return await safe_send(user, content=f"❌ Waifu `{waifu_id}` đã có.")

                user_data["waifus"][waifu_id] = 0
                user_data["bag"][waifu_id] -= 1

                if user_data["bag"][waifu_id] <= 0:
                    del user_data["bag"][waifu_id]

                if not user_data["default_waifu"]:
                    user_data["default_waifu"] = waifu_id

                await asyncio.to_thread(_save, inv)

                return await safe_send(user, content=f"✨ Đã mở khóa waifu **{waifu_id}**!")

            # ===== USE ITEM =====
            if item_id:
                item_id = item_id.lower()

                if item_id not in user_data["bag_item"]:
                    return await safe_send(user, content=f"❌ Bạn không có `{item_id}`.")

                if user_data["bag_item"][item_id] < qty:
                    return await safe_send(user, content=f"❌ Không đủ `{item_id}`.")

                default_w = user_data.get("default_waifu")

                if not default_w or default_w not in user_data["waifus"]:
                    return await safe_send(user, content="❌ Default waifu lỗi.")

                luck = get_luck(user.id)
                bonus = min(0.5, max(0, (luck - 1) / 100))

                total_point = 0

                if item_id == "soup":
                    total_point = 5 * qty

                elif item_id in ("pizza", "drug"):
                    base_min, base_max = (10, 30) if item_id == "pizza" else (30, 50)

                    for _ in range(qty):
                        r = random.random()
                        r = r + (1 - r) * bonus
                        total_point += int(base_min + (base_max - base_min) * r)

                else:
                    return await safe_send(user, content="❌ Item không hợp lệ.")

                # APPLY
                user_data["waifus"][default_w] += total_point
                user_data["bag_item"][item_id] -= qty

                if user_data["bag_item"][item_id] <= 0:
                    del user_data["bag_item"][item_id]

                # SAVE TRƯỚC
                await asyncio.to_thread(_save, inv)

                # SYNC SAU (không block transaction)
                try:
                    if asyncio.iscoroutinefunction(sync_one):
                        asyncio.create_task(sync_one(uid, default_w))
                    else:
                        sync_one(uid, default_w)
                except:
                    pass

                return await safe_send(user, content=f"✅ Dùng **{qty} {item_id}** → **{default_w}** +{total_point} ❤️")

            return await safe_send(user, content="❌ Bạn phải nhập waifu_id hoặc item_id.")
print("Loaded use has success")