import json
import os
import time
import asyncio
import datetime
from typing import Union

import discord
from discord.ext import commands

from Data import data_user

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "Data")

CODE_FILE = os.path.join(DATA_DIR, "code.json")
USED_FILE = os.path.join(DATA_DIR, "used_code.json")

_CODE_LOCK = asyncio.Lock()
_COOLDOWN = {}


# ===== SAFE JSON =====
def load_json(path):
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as f:
            json.dump({}, f, ensure_ascii=False, indent=4)

    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_json(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)
    os.replace(tmp, path)


# ===== UNIVERSAL SEND (FIX CHUẨN) =====
async def send(
    ctx: Union[commands.Context, discord.Interaction],
    msg: str
):
    try:
        if isinstance(ctx, discord.Interaction):
            try:
                if not ctx.response.is_done():
                    await ctx.response.send_message(msg)
                    return await ctx.original_response()
                else:
                    return await ctx.followup.send(msg)
            except discord.InteractionResponded:
                return await ctx.followup.send(msg)

        return await ctx.send(msg)

    except Exception as e:
        print("[SEND ERROR]", e)


# ===== FORMAT TIME =====
def format_time(ts):
    if ts is None:
        return "Không có"

    try:
        dt = datetime.datetime.fromtimestamp(float(ts))
    except Exception:
        return "Không có"

    now = datetime.datetime.now()
    diff = dt - now

    if diff.total_seconds() > 0:
        mins = int(diff.total_seconds() // 60)
        return dt.strftime("%d/%m %H:%M") + f" (còn {mins} phút)"
    return dt.strftime("%d/%m %H:%M") + " (đã hết hạn)"


# ===== MAIN LOGIC =====
async def code_logic(ctx, code: str):
    user = ctx.user if isinstance(ctx, discord.Interaction) else ctx.author
    user_id = str(user.id)

    if not code:
        return await send(ctx, "❌ Code không hợp lệ!")

    code_input = str(code).strip()
    code_lower = code_input.lower()

    # ===== COOLDOWN =====
    now = time.time()
    last = _COOLDOWN.get(user_id, 0)
    if now - last < 2:
        return await send(ctx, "⏳ Thg chóa, đừng spam nx!!!")

    _COOLDOWN[user_id] = now

    async with _CODE_LOCK:
        raw_codes = load_json(CODE_FILE)
        used = load_json(USED_FILE)

        code_map = {str(k).lower(): k for k in raw_codes.keys()}

        if code_lower not in code_map:
            return await send(ctx, "❌ Code không tồn tại hoặc đã hết hạn!")

        real_code = code_map[code_lower]
        code_data = raw_codes[real_code]

        # ===== MIGRATE JSON CŨ =====
        if isinstance(code_data, int):
            code_data = {
                "gold": code_data,
                "used": 0,
                "max_use": None,
                "expires": None
            }
            raw_codes[real_code] = code_data
            save_json(CODE_FILE, raw_codes)

        if not isinstance(code_data, dict):
            return await send(ctx, "❌ Code lỗi dữ liệu!")

        # ===== EXPIRE =====
        expires = code_data.get("expires")
        if expires is not None and time.time() > float(expires):
            return await send(ctx, "❌ Code đã hết hạn sử dụng!")

        # ===== MAX USE =====
        max_use = code_data.get("max_use")
        used_count = int(code_data.get("used", 0))

        if max_use is not None and used_count >= int(max_use):
            return await send(ctx, "❌ Code đã hết lượt sử dụng!")

        # ===== USER USED =====
        if user_id not in used or not isinstance(used.get(user_id), list):
            used[user_id] = []

        if real_code in used[user_id]:
            return await send(ctx, "❌ Bạn đã dùng code này rồi!")

        # ===== REWARD =====
        gold = int(code_data.get("gold", 0) or 0)

        if gold <= 0:
            return await send(ctx, "❌ Code này không hợp lệ!")

        # ===== GIVE GOLD =====
        await data_user.add_gold(user.id, gold)

        # ===== UPDATE =====
        used[user_id].append(real_code)
        code_data["used"] = used_count + 1
        raw_codes[real_code] = code_data

        save_json(USED_FILE, used)
        save_json(CODE_FILE, raw_codes)

    # ===== RESULT =====
    max_use_text = code_data.get("max_use") or "∞"
    expire_text = format_time(expires)

    return await send(
        ctx,
        f"🎉 Nhập code thành công!\n"
        f"🔑 Code đã dùng: `{real_code}`\n"
        f"💰 Đã cộng thêm {gold} <a:gold:1492792339436142703>\n"
        f"📊 Đã dùng: {code_data['used']}/{max_use_text}\n"
        f"⏰ Hết hạn: {expire_text}"
    )


print("Loaded code has success")