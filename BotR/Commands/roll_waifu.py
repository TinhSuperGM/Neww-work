import discord
import json
import os
import random
import time

from Data import data_user
from Commands.prayer import get_luck

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

WAIFU_FILE = os.path.join(BASE_DIR, "Data", "waifu_data.json")
INV_FILE = os.path.join(BASE_DIR, "Data", "inventory.json")


def load_data():
    for path in [WAIFU_FILE, INV_FILE]:
        if not os.path.exists(path):
            with open(path, "w", encoding="utf-8") as f:
                json.dump({}, f, indent=4, ensure_ascii=False)

    try:
        with open(WAIFU_FILE, encoding="utf-8") as f:
            waifu_data = json.load(f)
    except:
        waifu_data = {}

    try:
        with open(INV_FILE, encoding="utf-8") as f:
            inventory = json.load(f)
    except:
        inventory = {}

    return waifu_data, inventory


def save_data(waifu_data, inventory):
    with open(WAIFU_FILE, "w", encoding="utf-8") as f:
        json.dump(waifu_data, f, indent=4, ensure_ascii=False)
    with open(INV_FILE, "w", encoding="utf-8") as f:
        json.dump(inventory, f, indent=4, ensure_ascii=False)


def roll_rank(level, luck=0):
    """
    luck: %
    10 = đẩy 10% mỗi rank lên trên
    """

    shift_percent = luck / 100  # 10 = 0.1

    # ===== BASE RATE =====
    if level in ["free", "200"]:
        ranks = [None, "thuong", "anh_hung", "huyen_thoai", "truyen_thuyet"]

        rates = [0.40, 0.30, 0.20, 0.08, 0.02]

    elif level == "500":
        ranks = [None, "thuong", "anh_hung", "huyen_thoai", "truyen_thuyet"]

        rates = [0.30, 0.20, 0.25, 0.20, 0.05]

    elif level == "1000":
        ranks = [None, "thuong", "anh_hung", "huyen_thoai", "truyen_thuyet", "toi_thuong"]

        rates = [0.15, 0.15, 0.20, 0.30, 0.18, 0.02]

    elif level == "2000":
        ranks = ["thuong", "anh_hung", "huyen_thoai", "truyen_thuyet", "toi_thuong"]

        rates = [0.10, 0.15, 0.40, 0.30, 0.05]

    # ===== SHIFT LOGIC =====
    for i in range(len(rates) - 1):
        shift = rates[i] * shift_percent
        rates[i] -= shift
        rates[i + 1] += shift

    # ===== ROLL =====
    r = random.random()
    current = 0

    for rank, rate in zip(ranks, rates):
        current += rate
        if r <= current:
            return rank
def get_random_waifu(waifu_data, rank):
    pool = []
    for wid, data in waifu_data.items():
        if data.get("rank") == rank:
            if data.get("quantity", -1) == -1 or data.get("claimed", 0) < data.get("quantity", -1):
                pool.append(wid)

    if not pool:
        return None

    return random.choice(pool)


# ===== LOGIC =====
async def roll_waifu_logic(ctx, mode: str):
    waifu_data, inventory = load_data()

    user_obj = ctx.user if hasattr(ctx, "user") else ctx.author
    user_id = str(user_obj.id)

    # ===== INIT USER =====
    if user_id not in inventory:
        inventory[user_id] = {
            "waifus": {},
            "bag": {},
            "bag_item": {},
            "default_waifu": None
        }

    inventory[user_id].setdefault("bag", {})
    inventory[user_id].setdefault("waifus", {})
    inventory[user_id].setdefault("bag_item", {})
    inventory[user_id].setdefault("default_waifu", None)

    cost_map = {
        "free": 0,
        "200": 200,
        "500": 500,
        "1000": 1000,
        "2000": 2000
    }

    cost = cost_map.get(mode)

    if cost is None:
        if hasattr(ctx, "response"):
            return await ctx.response.send_message("❌ Mode không hợp lệ!", ephemeral=True)
        return await ctx.send("❌ Mode không hợp lệ!")

    user_data = data_user.get_user(user_id)
    luck = get_luck(user_obj.id)

    # ===== FREE ROLL =====
    if mode == "free":
        now = time.time()
        last_free = user_data.get("last_free", 0)

        if now - last_free < 64800:
            msg = "⏱ Bạn đã roll free hôm nay rồi, chờ thêm nhé!"
            if hasattr(ctx, "response"):
                return await ctx.response.send_message(msg, ephemeral=True)
            return await ctx.send(msg)

        user_data["last_free"] = now
        data_user.save_user(user_id, user_data)

    else:
        if not data_user.remove_gold(user_id, cost):
            msg = "❌ Không đủ gold!"
            if hasattr(ctx, "response"):
                return await ctx.response.send_message(msg, ephemeral=True)
            return await ctx.send(msg)

    # ===== ROLL =====
    rank = roll_rank(mode, luck)

    if rank is None:
        save_data(waifu_data, inventory)
        msg = "💀 Xịt rồi... thử lại lần sau nhé!"
        if hasattr(ctx, "response"):
            return await ctx.response.send_message(msg)
        return await ctx.send(msg)

    waifu_id = get_random_waifu(waifu_data, rank)

    if not waifu_id:
        msg = "❌ Không có waifu phù hợp!"
        if hasattr(ctx, "response"):
            return await ctx.response.send_message(msg, ephemeral=True)
        return await ctx.send(msg)

    waifu = waifu_data[waifu_id]

    # ===== ADD WAIFU =====
    if waifu_id in inventory[user_id]["waifus"]:
        inventory[user_id]["bag"][waifu_id] = inventory[user_id]["bag"].get(waifu_id, 0) + 1
        count = inventory[user_id]["bag"][waifu_id]
        result_text = f"🎒 Roll ra **{waifu_id}** ({rank}) → đã có nên vào kho (x{count})"
    else:
        inventory[user_id]["waifus"][waifu_id] = 0
        result_text = f"🎉 Roll ra **{waifu_id}** ({rank})"

    # ===== UPDATE CLAIMED =====
    if waifu.get("quantity", -1) != -1:
        waifu["claimed"] = waifu.get("claimed", 0) + 1

    save_data(waifu_data, inventory)

    if hasattr(ctx, "response"):
        return await ctx.response.send_message(result_text)
    return await ctx.send(result_text)


# ===== SETUP =====
async def setup(bot):
    pass


print("Loaded roll waifu has success and Do not use")