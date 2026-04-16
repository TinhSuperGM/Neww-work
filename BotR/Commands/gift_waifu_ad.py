import discord
import json
import os
import asyncio
from Data.data_admin import ADMINS

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WAIFU_FILE = os.path.join(BASE_DIR, "Data", "waifu_data.json")
INV_FILE = os.path.join(BASE_DIR, "Data", "inventory.json")

FILE_LOCK = asyncio.Lock()


# ===== JSON SAFE =====
def load_json(path):
    if not os.path.exists(path):
        return {}

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception as e:
        print(f"[gift_waifu_ad] load error {path}: {e}")
        return {}


def save_json(path, data):
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
        os.replace(tmp, path)
    except Exception as e:
        print(f"[gift_waifu_ad] save error {path}: {e}")


# ===== INTERACTION SAFE =====
async def safe_send(interaction, content, ephemeral=False):
    try:
        if not interaction.response.is_done():
            await interaction.response.send_message(content, ephemeral=ephemeral)
        else:
            await interaction.followup.send(content, ephemeral=ephemeral)
    except Exception as e:
        print(f"[gift_waifu_ad] send error: {e}")


# ===== LOGIC =====
async def gift_waifu_ad_logic(interaction, waifu_id: str, user: discord.User = None):
    uid = str(interaction.user.id)

    # ===== ADMIN CHECK =====
    if uid not in list(map(str, ADMINS)):
        return await safe_send(
            interaction,
            "❌ Bạn không phải admin! Không được dùng lệnh này!",
            ephemeral=True
        )

    async with FILE_LOCK:
        waifu_data = load_json(WAIFU_FILE)
        inventory = load_json(INV_FILE)

        if waifu_id not in waifu_data:
            return await safe_send(interaction, "❌ Waifu không tồn tại!", True)

        target = user or interaction.user
        target_id = str(target.id)

        # ===== INIT USER =====
        target_data = inventory.setdefault(target_id, {})
        waifus = target_data.setdefault("waifus", {})
        target_data.setdefault("bag", {})

        waifu = waifu_data[waifu_id]

        quantity = waifu.get("quantity", -1)
        claimed = int(waifu.get("claimed", 0))

        # ===== LIMITED CHECK =====
        if quantity != -1 and claimed >= quantity:
            return await safe_send(
                interaction,
                "❌ Waifu này thuộc rank **Limited**, đã đạt giới hạn!",
                True
            )

        # ===== DUPLICATE CHECK =====
        if waifu_id in waifus:
            return await safe_send(
                interaction,
                "❌ Người nhận đã sở hữu waifu này rồi!",
                True
            )

        # ===== ADD WAIFU =====
        waifus[waifu_id] = 1

        if quantity != -1:
            waifu["claimed"] = claimed + 1

        # ===== SAVE =====
        save_json(INV_FILE, inventory)
        save_json(WAIFU_FILE, waifu_data)

    # ===== RESPONSE =====
    await safe_send(
        interaction,
        f"🎁 **{waifu_id}** đã được gửi cho {target.mention}. || ADMIN ||"
    )


# ===== SETUP =====
async def setup(bot):
    pass


print("Loaded gift waifu admin has success")