import discord
from discord.ui import View, Button
from Data import data_user
import json
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WAIFU_FILE = os.path.join(BASE_DIR, "Data", "waifu_data.json")
INV_FILE = os.path.join(BASE_DIR, "Data", "inventory.json")

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


# ===== LOAD / SAVE INVENTORY =====
def load_inv():
    if not os.path.exists(INV_FILE):
        with open(INV_FILE, "w", encoding="utf-8") as f:
            json.dump({}, f, ensure_ascii=False, indent=4)
    with open(INV_FILE, encoding="utf-8") as f:
        return json.load(f)


def save_inv(data):
    tmp = INV_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)
    os.replace(tmp, INV_FILE)


# ===== RESPOND HELPERS =====
async def _defer_if_needed(interaction: discord.Interaction, *, ephemeral: bool = True):
    try:
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=ephemeral)
    except Exception:
        pass



# Đã thay thế _send bằng safe_send ở dưới


# ===== LOGIC =====
async def gift_logic(interaction, type: str, user: discord.User, amount: int = None, waifu_id: str = None):
    sender = interaction.user

    # Chỉ defer sớm cho flow dài; prompt confirm waifu vẫn dùng followup bình thường
    if type == "gold":
        await _defer_if_needed(interaction, ephemeral=True)

    # ===== LOAD DATA =====
    inv = load_inv()

    waifu_data = {}
    if os.path.exists(WAIFU_FILE):
        with open(WAIFU_FILE, encoding="utf-8") as f:
            waifu_data = json.load(f)

    # =========================================================
    # ===================== GIFT GOLD ==========================
    # =========================================================
    if type == "gold":
        if amount is None or amount <= 0:
            return await safe_send(interaction, content="❌ Số gold không hợp lệ!", ephemeral=True)

        if sender.id == user.id:
            return await safe_send(interaction, content="❌ Không thể tự chuyển gold!", ephemeral=True)

        fee = int(amount * 0.05)
        received = amount - fee

        # data_user.remove_gold / add_gold là coroutine -> phải await
        success = await data_user.remove_gold(sender.id, amount)
        if not success:
            return await safe_send(interaction, content="❌ Không đủ gold!", ephemeral=True)

        try:
            await data_user.add_gold(user.id, received)
        except Exception as e:
            # rollback an toàn nếu bước cộng gold thất bại
            print("[GIFT GOLD ERROR]", e)
            try:
                await data_user.add_gold(sender.id, amount)
            except Exception:
                pass
            return await safe_send(interaction, content="❌ Lỗi khi chuyển gold!", ephemeral=True)

        return await safe_send(
            interaction,
            content=f"💸 {sender.mention} chuyển {amount} <a:gold:1492792339436142703> cho {user.mention}\n"
                   f"📉 Phí: {fee} <a:gold:1492792339436142703> | Nhận: {received} <a:gold:1492792339436142703>",
            ephemeral=False
        )

    # =========================================================
    # ===================== GIFT WAIFU =========================
    # =========================================================
    elif type == "waifu":
        if waifu_id is None:
            return await safe_send(interaction, content="❌ Chưa chọn waifu!", ephemeral=True)

        uid = str(sender.id)
        recipient_id = str(user.id)

        sender_data = inv.setdefault(uid, {"waifus": {}, "bag": {}})
        sender_data.setdefault("waifus", {})
        sender_data.setdefault("bag", {})

        recipient_data = inv.setdefault(recipient_id, {"waifus": {}, "bag": {}})
        recipient_data.setdefault("waifus", {})
        recipient_data.setdefault("bag", {})

        bag = sender_data["bag"]
        owned = sender_data["waifus"]

        # ===== CHECK OWN =====
        if waifu_id in bag and bag[waifu_id] > 0:
            source = "bag"
        elif waifu_id in owned:
            source = "waifus"
        else:
            return await safe_send(
                interaction,
                content="❌ Bạn không có waifu này!",
                ephemeral=True
            )

        if uid == recipient_id:
            return await safe_send(interaction, content="❌ Không thể tự tặng!", ephemeral=True)

        rank = waifu_data.get(waifu_id, {}).get("rank", "thường")
        name = waifu_data.get(waifu_id, {}).get("name", waifu_id)

        # =====================================================
        # ================= CONFIRM FIX ========================
        # =====================================================
        if rank in ["truyen_thuyet", "toi_thuong", "limited"]:
            class ConfirmView(View):
                def __init__(self):
                    super().__init__(timeout=60)
                    self.result = None

                @discord.ui.button(label="Chắc chắn", style=discord.ButtonStyle.green)
                async def confirm(self, interaction2: discord.Interaction, button: Button):
                    await interaction2.response.defer()
                    self.result = True
                    self.stop()

                @discord.ui.button(label="Hủy", style=discord.ButtonStyle.red)
                async def cancel(self, interaction2: discord.Interaction, button: Button):
                    await interaction2.response.defer()
                    self.result = False
                    self.stop()

            view = ConfirmView()

            await safe_send(
                interaction,
                content=f"⚠️ Gửi **{name}** (rank {rank})?\nBạn chắc chưa?",
                view=view
            )

            await view.wait()

            if view.result is None:
                return await interaction.followup.send("⌛ Hết giờ, auto hủy!", ephemeral=True)

            if not view.result:
                return await interaction.followup.send("❌ Đã hủy!", ephemeral=True)

        # =====================================================
        # ================= TRANSACTION ========================
        # =====================================================
        try:
            # REMOVE
            if source == "bag":
                bag[waifu_id] -= 1
                if bag[waifu_id] <= 0:
                    del bag[waifu_id]
            else:
                owned.pop(waifu_id, None)

            # ADD
            recipient_data["bag"][waifu_id] = recipient_data["bag"].get(waifu_id, 0) + 1

            # SAVE (atomic)
            save_inv(inv)

        except Exception as e:
            print("[GIFT ERROR]", e)
            return await safe_send(interaction, content="❌ Lỗi khi chuyển waifu!", ephemeral=True)

        return await interaction.followup.send(
            f"✈️ {sender.mention} đã tặng **{name}** cho {user.mention} 🥰"
        )


# ===== SETUP =====
async def setup(bot):
    pass


print("Loaded gift has success")