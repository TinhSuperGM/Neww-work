import discord
from discord.ui import View, Button, Modal, TextInput
import json
import os

from Data import data_user  # 🔥 dùng chung hệ gold

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INV_FILE = os.path.join(BASE_DIR, "Data", "inventory.json")


# ===== LOAD / SAVE INVENTORY =====
def load_inv():
    if not os.path.exists(INV_FILE):
        with open(INV_FILE, "w", encoding="utf-8") as f:
            json.dump({}, f, indent=4)

    with open(INV_FILE, encoding="utf-8") as f:
        return json.load(f)


def save_inv(data):
    with open(INV_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)


# ===== MODAL =====
class QuantityModal(Modal):
    def __init__(self, item: str, price: int):
        super().__init__(title=f"Mua {item}")
        self.item = item
        self.price = price

        self.qty_input = TextInput(
            label="Nhập số lượng",
            placeholder="Số lượng...",
            required=True
        )
        self.add_item(self.qty_input)

    async def on_submit(self, interaction: discord.Interaction):
        # ===== PARSE SỐ =====
        try:
            qty = int(self.qty_input.value)
            if qty <= 0:
                return await interaction.response.send_message(
                    "❌ Số lượng phải > 0",
                    ephemeral=True
                )
        except:
            return await interaction.response.send_message(
                "❌ Số không hợp lệ",
                ephemeral=True
            )

        user_id = str(interaction.user.id)
        total = self.price * qty

        # ===== CHECK GOLD =====
        user = data_user.get_user(user_id)

        if not user or user.get("gold", 0) < total:
            return await interaction.response.send_message(
                f"❌ Không đủ {total} gold!",
                ephemeral=True
            )

        # ===== TRỪ GOLD (FIX CHÍNH) =====
        data_user.remove_gold(user_id, total)

        # ===== ADD ITEM =====
        inv_data = load_inv()

        if user_id not in inv_data:
            inv_data[user_id] = {
                "waifus": {},
                "bag": {},
                "bag_item": {}
            }

        inv_data[user_id].setdefault("bag_item", {})
        inv_data[user_id]["bag_item"][self.item] = (
            inv_data[user_id]["bag_item"].get(self.item, 0) + qty
        )

        save_inv(inv_data)

        # ===== RESPONSE =====
        await interaction.response.send_message(
            f"✅ Mua {qty} {self.item} (-{total} gold)",
            ephemeral=True
        )


# ===== VIEW =====
class ShopView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="🌹 Soup", style=discord.ButtonStyle.green, custom_id="shop_soup")
    async def soup(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_modal(
            QuantityModal("soup", 100)
        )

    @discord.ui.button(label="🍕 Pizza", style=discord.ButtonStyle.blurple, custom_id="shop_pizza")
    async def pizza(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_modal(
            QuantityModal("pizza", 2000)
        )

    @discord.ui.button(label="💊 Drug", style=discord.ButtonStyle.red, custom_id="shop_drug")
    async def drug(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_modal(
            QuantityModal("drug", 300)
        )


# ===== LOGIC =====
async def send_shop_embed_logic(interaction, channel_id: str):

    # ===== CHECK SERVER =====
    if not interaction.guild:
        return await interaction.response.send_message(
            "❌ Lệnh chỉ dùng trong server!",
            ephemeral=True
        )

    # ===== CHECK ADMIN =====
    if not interaction.user.guild_permissions.administrator:
        return await interaction.response.send_message(
            "❌ Cần quyền admin!",
            ephemeral=True
        )

    if not channel_id:
        return await interaction.response.send_message(
            "❌ Thiếu channel ID!",
            ephemeral=True
        )

    try:
        ch = interaction.guild.get_channel(int(channel_id))
        if not ch:
            return await interaction.response.send_message(
                "❌ Không tìm thấy channel!",
                ephemeral=True
            )
    except:
        return await interaction.response.send_message(
            "❌ ID không hợp lệ!",
            ephemeral=True
        )

    # ===== EMBED =====
    embed = discord.Embed(
        title="🛒 Shop waifu",
        description=(
            "> - Soup | 100 gold (+5 love)\n"
            "> - Pizza | 2000 gold (+10-30 love)\n"
            "> - Drug | 300 gold (+30-50 love)"
        ),
        color=discord.Color.purple()
    )

    embed.set_footer(text="Mua đi bro 😎")

    await ch.send(embed=embed, view=ShopView())

    await interaction.response.send_message(
        f"✅ Đã gửi shop vào {ch.mention}",
        ephemeral=True
    )


# ===== SETUP =====
async def setup(bot):
    async def add_views():
        await bot.wait_until_ready()
        bot.add_view(ShopView())  # giữ persistent button

    bot.loop.create_task(add_views())


print("Loaded shop has success and do no use")