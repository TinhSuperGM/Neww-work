import asyncio
import copy
import json
import os
import random
import time
from threading import Lock
from typing import Any, Dict, Optional

import discord
from discord.ui import Button, Modal, TextInput, View, Select

from Commands.prayer import get_luck
from Data import data_user
from Data.level import sync_all

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

CHANNEL_FILE = os.path.join(BASE_DIR, "Data", "auction_channels.json")
AUCTION_FILE = os.path.join(BASE_DIR, "Data", "auction.json")
WAIFU_FILE = os.path.join(BASE_DIR, "Data", "waifu_data.json")
INV_FILE = os.path.join(BASE_DIR, "Data", "inventory.json")

_FILE_LOCK = Lock()


# =========================
# SAFE JSON
# =========================
def _ensure_json(path: str, default):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(default, f, indent=4, ensure_ascii=False)


def _safe_load(path: str, default):
    _ensure_json(path, default)
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else default
    except Exception:
        return default


def _safe_save(path: str, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.tmp"
    with _FILE_LOCK:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
        os.replace(tmp, path)


def load_channels():
    return _safe_load(CHANNEL_FILE, {})


def save_channels(data):
    _safe_save(CHANNEL_FILE, data)


def load_auctions():
    return _safe_load(AUCTION_FILE, {})


def save_auctions(data):
    _safe_save(AUCTION_FILE, data)


def load_inventory():
    return _safe_load(INV_FILE, {})


def save_inventory(data):
    _safe_save(INV_FILE, data)


def load_waifu_data():
    return _safe_load(WAIFU_FILE, {})


def save_waifu_data(data):
    _safe_save(WAIFU_FILE, data)


# =========================
# RESPOND HELPERS
# =========================
async def _defer_if_needed(interaction: discord.Interaction, *, ephemeral: bool = True):
    try:
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=ephemeral)
    except Exception:
        pass


async def _respond(interaction: discord.Interaction, content=None, **kwargs):
    try:
        if interaction.response.is_done():
            return await interaction.followup.send(content, **kwargs)
        return await interaction.response.send_message(content, **kwargs)
    except discord.InteractionResponded:
        return await interaction.followup.send(content, **kwargs)


def _ensure_inventory_schema(inventory: Dict[str, Any], user_id: str) -> Dict[str, Any]:
    user_inv = inventory.get(user_id)
    if not isinstance(user_inv, dict):
        user_inv = {}
        inventory[user_id] = user_inv

    if not isinstance(user_inv.get("waifus"), dict):
        user_inv["waifus"] = {}
    if not isinstance(user_inv.get("bag"), dict):
        user_inv["bag"] = {}
    if not isinstance(user_inv.get("bag_item"), dict):
        user_inv["bag_item"] = {}
    if "default_waifu" not in user_inv:
        user_inv["default_waifu"] = None

    return user_inv


# =========================
# AUCTION / RANK / SHOP / ROLL CHANNEL SETUP
# =========================
async def setup_channel_logic(interaction, type: str, channel_id: str):
    await _defer_if_needed(interaction, ephemeral=True)

    guild = interaction.guild

    if not guild:
        return await _respond(interaction, "❌ Chỉ dùng trong server!", ephemeral=True)

    if not interaction.user.guild_permissions.administrator:
        return await _respond(interaction, "❌ Cần quyền admin!", ephemeral=True)

    if not type:
        return await _respond(interaction, "❌ Thiếu type!", ephemeral=True)

    if not channel_id:
        return await _respond(interaction, "❌ Thiếu channel ID!", ephemeral=True)

    try:
        ch_id = int(channel_id)
    except Exception:
        return await _respond(interaction, "❌ ID không hợp lệ!", ephemeral=True)

    channel = guild.get_channel(ch_id)
    if not channel:
        try:
            channel = await guild.fetch_channel(ch_id)
        except Exception:
            return await _respond(interaction, "❌ Không tìm thấy channel!", ephemeral=True)

    type = str(type).strip().lower()
    type_alias = {
        "rank": "ranking",
        "leaderboard": "ranking",
        "rollwaifu": "roll",
        "roll_waifu": "roll",
        "roll-waifu": "roll",
    }
    type = type_alias.get(type, type)

    channels = load_channels()
    guild_key = str(guild.id)

    if guild_key not in channels or not isinstance(channels.get(guild_key), dict):
        channels[guild_key] = {}

    if type == "auction":
        old_channel_id = channels[guild_key].get("auction_channel_id")
        auctions = load_auctions()

        if old_channel_id and int(old_channel_id) != ch_id:
            try:
                old_channel = guild.get_channel(int(old_channel_id))
                if not old_channel:
                    old_channel = await guild.fetch_channel(int(old_channel_id))
            except Exception:
                old_channel = None

            if old_channel:
                for auction_id, auction in list(auctions.items()):
                    if not isinstance(auction, dict):
                        continue

                    msg_key = f"message_id_{guild_key}"
                    msg_id = auction.get(msg_key)

                    if msg_id:
                        try:
                            msg = await old_channel.fetch_message(int(msg_id))
                            await msg.delete()
                        except Exception:
                            pass

                        auction.pop(msg_key, None)

                save_auctions(auctions)

        channels[guild_key]["auction_channel_id"] = ch_id
        save_channels(channels)
        return await _respond(
            interaction,
            f"✅ Set kênh đấu giá: {channel.mention}",
            ephemeral=True,
        )

    if type == "ranking":
        channels[guild_key]["leaderboard_channel_id"] = ch_id
        save_channels(channels)
        return await _respond(
            interaction,
            f"✅ Set kênh BXH: {channel.mention}",
            ephemeral=True,
        )

    if type == "shop":
        channels[guild_key]["shop_channel_id"] = ch_id
        save_channels(channels)
        return await _respond(
            interaction,
            f"✅ Set kênh shop: {channel.mention}",
            ephemeral=True,
        )

    if type in ("roll", "roll_waifu"):
        channels[guild_key]["roll_waifu_channel_id"] = ch_id
        save_channels(channels)
        return await _respond(
            interaction,
            f"✅ Set kênh roll waifu: {channel.mention}",
            ephemeral=True,
        )

    return await _respond(interaction, "❌ Type không hợp lệ!", ephemeral=True)


# =========================
# ROLL LOGIC
# =========================
def roll_rank(level, luck=0):
    shift_percent = luck / 100

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
        rates = [0.15, 0.30, 0.40, 0.10, 0.05]
    else:
        return None

    for i in range(len(rates) - 1):
        shift = rates[i] * shift_percent
        rates[i] -= shift
        rates[i + 1] += shift

    r = random.random()
    current = 0
    for rank, rate in zip(ranks, rates):
        current += rate
        if r <= current:
            return rank

    return ranks[-1] if ranks else None


def get_random_waifu(waifu_data, rank):
    pool = []
    for wid, data in waifu_data.items():
        if not isinstance(data, dict):
            continue
        if data.get("rank") == rank and (
            data.get("quantity", -1) == -1 or data.get("claimed", 0) < data.get("quantity", -1)
        ):
            pool.append(wid)

    if not pool:
        return None
    return random.choice(pool)


def build_roll_embed():
    embed = discord.Embed(
        title="🌀 Cổng Triệu Hồi Waifu 🌀",
        description=(
            "**Mỗi ngày, cổng triệu hồi sẽ ban tặng bạn một lượt roll miễn phí. "
            "Ngoài ra, bạn còn có thể dùng Gold để thực hiện nghi thức triệu hồi. "
            "Hãy chọn nghi thức bên dưới!**\n\n"
            "**Thẻ Đồng**\n"
            "> - 2% - Truyền Thuyết\n"
            "> - 8% - Huyền Thoại\n"
            "> - 20% - Anh Hùng\n"
            "> - 30% - Thường\n"
            "> - 40% - Hụt\n\n"
            "**Hãy chọn mức Free / 200 để quay Thẻ Đồng**\n\n"
            "**Thẻ Bạc**\n"
            "> - 5% - Truyền Thuyết\n"
            "> - 20% - Huyền Thoại\n"
            "> - 25% - Anh Hùng\n"
            "> - 20% - Thường\n"
            "> - 30% - Hụt\n\n"
            "**Hãy chọn mức 500 để quay Thẻ Bạc**\n\n"
            "**Thẻ Vàng**\n"
            "> - 2% - Tối Thượng\n"
            "> - 18% - Truyền Thuyết\n"
            "> - 30% - Huyền Thoại\n"
            "> - 20% - Anh Hùng\n"
            "> - 15% - Thường\n"
            "> - 15% - Hụt\n\n"
            "**Hãy chọn mức 1000 để quay Thẻ Vàng**\n\n"
            "**Thẻ Kim Cương**\n"
            "> - 5% - Tối Thượng\n"
            "> - 10% - Truyền Thuyết\n"
            "> - 40% - Huyền Thoại\n"
            "> - 30% - Anh Hùng\n"
            "> - 15% - Thường\n"
            "**Hãy chọn mức 2000 để quay Thẻ Kim Cương**"
        ),
        color=discord.Color.purple(),
    )
    embed.set_image(
        url="https://cdn.discordapp.com/attachments/1387434589756199046/1490938876150153246/roll-banner.gif?ex=69d7dac8&is=69d68948&hm=64f21018e71cce80d54e3c0e324d710bc162e7aca06edba0dd1dd3ecfab3ac2f"
    )
    embed.set_footer(
        text="Giờ thì... hãy bước vào thế giới waifu huyền ảo, nơi trái tim bạn sẽ tìm thấy ánh sáng dẫn đường!"
    )
    return embed


async def _rollback_user_snapshot(user_id: str, snapshot: Dict[str, Any]):
    try:
        data_user.save_user(user_id, snapshot)
    except Exception:
        pass
    try:
        data_user.save_data()
    except Exception:
        pass


async def roll_waifu_logic(ctx, mode: str):
    if hasattr(ctx, "response"):
        await _defer_if_needed(ctx, ephemeral=True)

    user_obj = getattr(ctx, "user", getattr(ctx, "author", None))
    user_id = str(user_obj.id)

    lock = data_user.get_lock(user_id)
    async with lock:
        waifu_data = load_waifu_data()
        inventory = load_inventory()

        user_inv = _ensure_inventory_schema(inventory, user_id)

        cost_map = {"free": 0, "200": 200, "500": 500, "1000": 1000, "2000": 2000}
        if mode not in cost_map:
            return await _respond(ctx, "❌ Mode không hợp lệ!", ephemeral=True)

        user_before = copy.deepcopy(data_user.get_user(user_id))
        luck = get_luck(user_obj.id) if callable(get_luck) else 0

        spent = 0
        free_consumed = False

        if mode == "free":
            now = time.time()
            last_free = int(user_before.get("last_free", 0) or 0)

            if now - last_free < 64800:
                return await _respond(ctx, "⏱ Bạn đã roll free hôm nay rồi!", ephemeral=True)

            free_consumed = True
        else:
            cost = cost_map[mode]
            current_gold = int(user_before.get("gold", 0) or 0)
            if current_gold < cost:
                return await _respond(ctx, "❌ Không đủ gold!", ephemeral=True)

            user_before["gold"] = current_gold - cost
            data_user.save_user(user_id, user_before)
            try:
                data_user.save_data()
            except Exception:
                pass
            spent = cost

        rank = roll_rank(mode, luck)
        if not rank:
            if spent > 0:
                await _rollback_user_snapshot(user_id, user_before)
            return await _respond(ctx, "❌ Roll thất bại.", ephemeral=True)

        waifu_id = get_random_waifu(waifu_data, rank)
        if not waifu_id:
            if spent > 0:
                await _rollback_user_snapshot(user_id, user_before)
            return await _respond(ctx, "❌ Không có waifu phù hợp!", ephemeral=True)

        waifu = waifu_data.get(waifu_id, {})
        inv_before = copy.deepcopy(inventory)
        waifu_before = copy.deepcopy(waifu_data)

        try:
            if waifu_id in user_inv["waifus"]:
                user_inv["bag"][waifu_id] = user_inv["bag"].get(waifu_id, 0) + 1
            else:
                user_inv["waifus"][waifu_id] = 1

            if waifu.get("quantity", -1) != -1:
                waifu["claimed"] = int(waifu.get("claimed", 0) or 0) + 1
                waifu_data[waifu_id] = waifu

            save_inventory(inventory)
            save_waifu_data(waifu_data)

            if free_consumed:
                user_now = data_user.get_user(user_id)
                user_now["last_free"] = time.time()
                data_user.save_user(user_id, user_now)

            try:
                data_user.save_data()
            except Exception:
                raise

        except Exception:
            if spent > 0:
                await _rollback_user_snapshot(user_id, user_before)

            try:
                save_inventory(inv_before)
                save_waifu_data(waifu_before)
            except Exception:
                pass

            if free_consumed:
                try:
                    data_user.save_user(user_id, user_before)
                    data_user.save_data()
                except Exception:
                    pass

            return await _respond(ctx, "❌ Lỗi khi lưu dữ liệu, đã rollback.", ephemeral=True)

        result_text = f"✅ Bạn đã roll ra **{waifu_id}** với rank **{rank}**."
        return await _respond(ctx, result_text, ephemeral=True)


# =========================
# PERSISTENT ROLL VIEW
# =========================
class RollView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Free", style=discord.ButtonStyle.green, emoji="💚", custom_id="roll_free")
    async def roll_free(self, interaction: discord.Interaction, button: Button):
        await roll_waifu_logic(interaction, "free")

    @discord.ui.button(label="200", style=discord.ButtonStyle.secondary, emoji="💰", custom_id="roll_200")
    async def roll_200(self, interaction: discord.Interaction, button: Button):
        await roll_waifu_logic(interaction, "200")

    @discord.ui.button(label="500", style=discord.ButtonStyle.blurple, emoji="💰", custom_id="roll_500")
    async def roll_500(self, interaction: discord.Interaction, button: Button):
        await roll_waifu_logic(interaction, "500")

    @discord.ui.button(label="1000", style=discord.ButtonStyle.primary, emoji="💰", custom_id="roll_1000")
    async def roll_1000(self, interaction: discord.Interaction, button: Button):
        await roll_waifu_logic(interaction, "1000")

    @discord.ui.button(label="2000", style=discord.ButtonStyle.danger, emoji="💰", custom_id="roll_2000")
    async def roll_2000(self, interaction: discord.Interaction, button: Button):
        await roll_waifu_logic(interaction, "2000")


async def send_roll_embed_logic(interaction, channel_id: str):
    await _defer_if_needed(interaction, ephemeral=True)

    if not interaction.guild:
        return await _respond(interaction, "❌ Chỉ dùng server", ephemeral=True)

    if not interaction.user.guild_permissions.administrator:
        return await _respond(interaction, "❌ Cần quyền admin", ephemeral=True)

    if not channel_id:
        return await _respond(interaction, "❌ Thiếu channel ID", ephemeral=True)

    try:
        ch_id = int(channel_id)
    except Exception:
        return await _respond(interaction, "❌ ID không hợp lệ", ephemeral=True)

    channel = interaction.guild.get_channel(ch_id)
    if channel is None:
        try:
            channel = await interaction.guild.fetch_channel(ch_id)
        except Exception:
            return await _respond(interaction, "❌ Không tìm thấy channel!", ephemeral=True)

    if not isinstance(channel, discord.TextChannel):
        return await _respond(interaction, "❌ Phải là text channel", ephemeral=True)

    embed = build_roll_embed()
    channels = load_channels()
    guild_key = str(interaction.guild.id)
    if guild_key not in channels or not isinstance(channels.get(guild_key), dict):
        channels[guild_key] = {}

    old_msg_id = channels[guild_key].get("roll_waifu_message_id")
    old_channel_id = channels[guild_key].get("roll_waifu_channel_id")
    sent_msg = None

    if old_msg_id:
        try:
            old_channel = channel
            if old_channel_id:
                try:
                    old_channel = interaction.guild.get_channel(int(old_channel_id)) or old_channel
                except Exception:
                    old_channel = channel

            old_msg = await old_channel.fetch_message(int(old_msg_id))
            sent_msg = await old_msg.edit(embed=embed, view=RollView())
        except Exception:
            sent_msg = None

    if not sent_msg:
        sent_msg = await channel.send(embed=embed, view=RollView())
        channels[guild_key]["roll_waifu_message_id"] = sent_msg.id
        channels[guild_key]["roll_waifu_channel_id"] = channel.id
        save_channels(channels)

    if interaction.response.is_done():
        await interaction.followup.send(f"✅ Đã gửi roll panel vào {channel.mention}", ephemeral=True)
    else:
        await interaction.response.send_message(f"✅ Đã gửi roll panel vào {channel.mention}", ephemeral=True)


# =========================
# SHOP LOGIC
# =========================
ITEM_META = {
    "soup": {
        "label": "Soup",
        "price": 100,
        "desc": "+5 love",
    },
    "pizza": {
        "label": "Pizza",
        "price": 200,
        "desc": "+10~30 love",
    },
    "drug": {
        "label": "Drug",
        "price": 300,
        "desc": "+30~50 love",
    },
    "health_potion": {
        "label": "Health Potion",
        "price": 1000,
        "desc": "Heal 10~20% max HP",
    },
    "damage_potion": {
        "label": "Damage Potion",
        "price": 1500,
        "desc": "+10~20% damage for 1 battle",
    },
}


class QuantityModal(Modal):
    def __init__(self, item_key: str):
        super().__init__(title=f"Mua {ITEM_META[item_key]['label']}")
        self.item_key = item_key
        self.price = ITEM_META[item_key]["price"]

        self.qty_input = TextInput(
            label="Nhập số lượng",
            placeholder="Số lượng...",
            required=True,
        )
        self.add_item(self.qty_input)

    async def on_submit(self, interaction: discord.Interaction):
        await _defer_if_needed(interaction, ephemeral=True)

        try:
            qty = int(self.qty_input.value)
        except Exception:
            return await _respond(interaction, "❌ Số lượng không hợp lệ.", ephemeral=True)

        if qty <= 0:
            return await _respond(interaction, "❌ Số lượng phải > 0", ephemeral=True)

        user_id = str(interaction.user.id)

        inv_before = load_inventory()
        inv_data = copy.deepcopy(inv_before)
        user_inv = _ensure_inventory_schema(inv_data, user_id)

        user_before = copy.deepcopy(data_user.get_user(user_id) or {})
        user_now = copy.deepcopy(user_before)

        total = self.price * qty
        gold = int(user_now.get("gold", 0) or 0)

        if gold < total:
            return await _respond(interaction, "❌ Không đủ gold!", ephemeral=True)

        user_now["gold"] = gold - total
        data_user.save_user(user_id, user_now)

        try:
            user_inv["bag_item"][self.item_key] = int(user_inv["bag_item"].get(self.item_key, 0) or 0) + qty
            save_inventory(inv_data)
            data_user.save_data()
        except Exception:
            try:
                data_user.save_user(user_id, user_before)
                data_user.save_data()
            except Exception:
                pass

            try:
                save_inventory(inv_before)
            except Exception:
                pass

            return await _respond(interaction, "❌ Lỗi, đã hoàn gold.", ephemeral=True)

        await _respond(
            interaction,
            f"✅ Mua {qty} {ITEM_META[self.item_key]['label']} (-{total} gold)",
            ephemeral=True,
        )


class ShopItemSelect(Select):
    def __init__(self):
        options = []
        for key in ["soup", "pizza", "drug", "health_potion", "damage_potion"]:
            meta = ITEM_META[key]
            options.append(
                discord.SelectOption(
                    label=f"{meta['label']} - {meta['price']} gold",
                    value=key,
                    description=meta["desc"],
                )
            )

        super().__init__(
            placeholder="Chọn vật phẩm để mua",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction):
        item_key = self.values[0]
        await interaction.response.send_modal(QuantityModal(item_key))


class ShopView(View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(ShopItemSelect())


async def send_shop_embed_logic(interaction, channel_id: str):
    await _defer_if_needed(interaction, ephemeral=True)

    if not interaction.guild:
        return await _respond(interaction, "❌ Lệnh chỉ dùng trong server!", ephemeral=True)

    if not interaction.user.guild_permissions.administrator:
        return await _respond(interaction, "❌ Cần quyền admin!", ephemeral=True)

    if not channel_id:
        return await _respond(interaction, "❌ Thiếu channel ID!", ephemeral=True)

    try:
        ch_id = int(channel_id)
    except Exception:
        return await _respond(interaction, "❌ ID không hợp lệ!", ephemeral=True)

    ch = interaction.guild.get_channel(ch_id)
    if not ch:
        try:
            ch = await interaction.guild.fetch_channel(ch_id)
        except Exception:
            return await _respond(interaction, "❌ Không tìm thấy channel!", ephemeral=True)

    if not isinstance(ch, discord.TextChannel):
        return await _respond(interaction, "❌ Phải là text channel!", ephemeral=True)

    embed = discord.Embed(
        title="Shop waifu",
        description=(
            "> Soup | 100 gold\n"
            "> Pizza | 200 gold\n"
            "> Drug | 300 gold\n"
            "> Health Potion | 1000 gold\n"
            "> Damage Potion | 1500 gold"
        ),
        color=discord.Color.purple(),
    )
    embed.set_footer(text="Chọn vật phẩm trong menu để mua")

    sent = await ch.send(embed=embed, view=ShopView())

    channels = load_channels()
    guild_key = str(interaction.guild.id)
    if guild_key not in channels or not isinstance(channels.get(guild_key), dict):
        channels[guild_key] = {}

    channels[guild_key]["shop_channel_id"] = ch.id
    channels[guild_key]["shop_message_id"] = sent.id
    save_channels(channels)

    return await _respond(interaction, f"✅ Đã gửi shop panel vào {ch.mention}", ephemeral=True)

# =========================
# BOT SETUP
# =========================
async def setup(bot):
    bot.add_view(ShopView())
    bot.add_view(RollView())


__all__ = [
    "setup_channel_logic",
    "send_roll_embed_logic",
    "send_shop_embed_logic",
    "RollView",
    "ShopView",
    "roll_waifu_logic",
]

print("Loaded setup has success")