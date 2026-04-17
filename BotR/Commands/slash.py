from __future__ import annotations

import asyncio
from typing import Optional

import discord
from discord import app_commands

from Commands.bag import bag_logic
from Commands.baucua import baucua_logic
from Commands.code import code_logic
from Commands.coinflip import coinflip_logic
from Commands.couple import (
    couple_cancel_logic,
    couple_gift_logic,
    couple_info_logic,
    couple_logic,
    couple_release_logic,
    start_couple_loop,
)
from Commands.daily import daily_logic
from Commands.dau_gia import (
    AUCTION_FILE,
    BidView,
    dau_gia_logic,
    load_json as load_auction_json,
)
from Commands.gift_waifu_ad import gift_waifu_ad_logic
from Commands.give import gift_logic
from Commands.gold import gold_logic
from Commands.huy_dau_gia import huy_dau_gia_logic
from Commands.setup import send_roll_embed_logic
from Commands.select_waifu import select_waifu_logic
from Commands.sell import sell_logic
from Commands.setup import setup_channel_logic
from Commands.setup import ShopView, send_shop_embed_logic
from Commands.use import use_logic
from Commands.view_waifu import view_waifu_logic
from Commands.waifu_list import waifu_list_run
from Commands.work import work
from Commands.help import help_slash
from Commands.profile import get_profile_embed
from Commands.prayer import prayer_logic
from Commands.fight import fight_logic
from Commands.team import team_logic
from Commands.lock import lock_logic
from Commands.zombie import zombie_logic
from Commands.werewolf import werewolf_logic


def _resolve_user(user: Optional[discord.User]) -> Optional[discord.User]:
    return user


async def _send_embed_like(interaction: discord.Interaction, embed_data: dict):
    embed = discord.Embed(
        title=embed_data.get("title", ""),
        description=embed_data.get("description", ""),
        color=discord.Color.pink(),
    )
    image = embed_data.get("image")
    footer = embed_data.get("footer")
    if image:
        embed.set_image(url=image)
    if footer:
        embed.set_footer(text=footer)
    return await interaction.response.send_message(embed=embed)


async def setup(bot):
    """
    Register slash commands and startup hooks.
    """
    if getattr(bot, "_slash_commands_ready", False):
        return
    bot._slash_commands_ready = True

    # Persistent views / boot-time hooks
    try:
        bot.add_view(ShopView())
    except Exception:
        pass

    try:
        auctions = load_auction_json(AUCTION_FILE)
        for auction_id in auctions.keys():
            try:
                bot.add_view(BidView(auction_id))
            except Exception:
                pass
    except Exception:
        pass

    if not getattr(bot, "_couple_loop_started", False):
        bot._couple_loop_started = True
        asyncio.create_task(start_couple_loop(bot))

    @bot.tree.command(name="setup", description="Thiết lập kênh đấu giá, BXH, Roll hoặc Shop")
    @app_commands.rename(type_="type")
    @app_commands.describe(type_="auction, ranking, roll hoặc shop", channel_id="ID hoặc mention của kênh")
    async def setup_cmd(interaction: discord.Interaction, type_: str, channel_id: str):
        type_lower = type_.lower()

        # ===== SETUP CHANNEL =====
        await setup_channel_logic(interaction, type_lower, channel_id)

        # ===== GỬI PANEL CHO ROLL WAIFU =====
        if type_lower == "roll":
            await send_roll_embed_logic(interaction, channel_id)

        # ===== GỬI SHOP EMBED =====
        elif type_lower == "shop":
            await send_shop_embed_logic(interaction, channel_id)
    # ===== gold =====
    @bot.tree.command(name="gold", description="Xem số gold của bạn hoặc của người khác")
    @app_commands.describe(user="Người cần xem gold")
    async def gold_cmd(interaction: discord.Interaction, user: Optional[discord.Member] = None):
        await gold_logic(interaction, user)

    # ===== daily / work =====
    @bot.tree.command(name="daily", description="Nhận gold hằng ngày")
    async def daily_cmd(interaction: discord.Interaction):
        await daily_logic(interaction)

    @bot.tree.command(name="work", description="Cho waifu đi làm để kiếm gold")
    async def work_cmd(interaction: discord.Interaction):
        await work(interaction)

    # ===== select waifu =====
    @bot.tree.command(name="select-waifu", description="Chọn waifu mặc định")
    @app_commands.describe(waifu_id="ID waifu")
    async def select_waifu_cmd(interaction: discord.Interaction, waifu_id: str):
        await select_waifu_logic(interaction, waifu_id)

    # ===== waifu list / view / bag =====
    @bot.tree.command(name="waifu-list", description="Xem danh sách waifu của bạn hoặc người khác")
    @app_commands.describe(user="Người cần xem waifu")
    async def waifu_list_cmd(interaction: discord.Interaction, user: Optional[discord.Member] = None):
        await waifu_list_run(interaction, user)

    @bot.tree.command(name="view-waifu", description="Xem chi tiết waifu")
    @app_commands.describe(waifu_id="ID waifu")
    async def view_waifu_cmd(interaction: discord.Interaction, waifu_id: str):
        async def send(msg, ephemeral=False):
            return await interaction.response.send_message(msg, ephemeral=ephemeral)

        async def send_embed(embed_data):
            return await _send_embed_like(interaction, embed_data)

        await view_waifu_logic(interaction.user, send, send_embed, waifu_id)

    @bot.tree.command(name="bag", description="Xem kho đồ của bạn hoặc người khác")
    @app_commands.describe(user="Người cần xem kho đồ")
    async def bag_cmd(interaction: discord.Interaction, user: Optional[discord.Member] = None):
        await bag_logic(interaction, user or interaction.user)

    @bot.tree.command(name="use", description="Dùng waifu hoặc vật phẩm")
    @app_commands.describe(
        waifu_id="Waifu muốn đưa vào bộ sưu tập",
        item_id="Vật phẩm muốn dùng",
        qty="Số lượng vật phẩm",
    )
    async def use_cmd(
        interaction: discord.Interaction,
        waifu_id: Optional[str] = None,
        item_id: Optional[str] = None,
        qty: int = 1,
    ):
        await use_logic(interaction.user, lambda msg, ephemeral=False: interaction.response.send_message(msg, ephemeral=ephemeral), waifu_id, item_id, qty)

    @bot.tree.command(name="sell", description="Bán waifu")
    @app_commands.describe(waifu_id="ID waifu", source="bag hoặc collection", amount="Số lượng")
    async def sell_cmd(
        interaction: discord.Interaction,
        waifu_id: str,
        source: Optional[str] = None,
        amount: int = 1,
    ):
        await sell_logic(interaction, waifu_id, source, amount)

    @bot.tree.command(name="give", description="Tặng gold hoặc waifu cho người khác")
    @app_commands.rename(type_="type")
    @app_commands.describe(
        type_="gold hoặc waifu",
        user="Người nhận",
        amount="Số gold",
        waifu_id="ID waifu",
    )
    async def give_cmd(
        interaction: discord.Interaction,
        type_: str,
        user: discord.Member,
        amount: Optional[int] = None,
        waifu_id: Optional[str] = None,
    ):
        await gift_logic(interaction, type_, user, amount, waifu_id)

    # ===== couple =====
    @bot.tree.command(name="couple", description="Tỏ tình với người khác")
    @app_commands.describe(user="Người bạn muốn tỏ tình")
    async def couple_cmd(interaction: discord.Interaction, user: discord.Member):
        await couple_logic(bot, interaction, user)

    @bot.tree.command(name="couple-release", description="Chia tay người yêu")
    async def couple_release_cmd(interaction: discord.Interaction):
        await couple_release_logic(bot, interaction)

    @bot.tree.command(name="couple-cancel", description="Hủy yêu cầu chia tay")
    async def couple_cancel_cmd(interaction: discord.Interaction):
        await couple_cancel_logic(interaction)

    @bot.tree.command(name="couple-info", description="Xem thông tin couple")
    async def couple_info_cmd(interaction: discord.Interaction):
        await couple_info_logic(interaction)

    @bot.tree.command(name="couple-gift", description="Tặng quà cho người yêu")
    @app_commands.describe(item="rose hoặc cake")
    async def couple_gift_cmd(interaction: discord.Interaction, item: str):
        await couple_gift_logic(interaction, item)

    # ===== games =====
    @bot.tree.command(name="coinflip", description="Đánh coinflip")
    @app_commands.describe(choice="ngua hoặc sap", amount="Số gold cược")
    async def coinflip_cmd(interaction: discord.Interaction, choice: str, amount: int):
        await coinflip_logic(interaction, choice, amount)

    @bot.tree.command(name="baucua", description="Chơi bầu cua")
    @app_commands.describe(choice="nai/bau/ga/ca/cua/tom", amount="Số gold cược")
    async def baucua_cmd(interaction: discord.Interaction, choice: str, amount: int):
        await baucua_logic(interaction, choice, amount)

    @bot.tree.command(name="code", description="Nhập code nhận quà")
    @app_commands.describe(code="Mã code")
    async def code_cmd(interaction: discord.Interaction, code: str):
        await code_logic(interaction, code)

    # ===== auction =====
    @bot.tree.command(name="dau-gia", description="Đăng waifu lên sàn đấu giá")
    @app_commands.describe(
        waifu_id="ID waifu",
        min_price="Giá khởi điểm",
        step="Bước giá",
    )
    async def dau_gia_cmd(interaction: discord.Interaction, waifu_id: str, min_price: int, step: int):
        await dau_gia_logic(interaction, waifu_id, min_price, step)

    @bot.tree.command(name="huy-dau-gia", description="Hủy buổi đấu giá")
    @app_commands.describe(auction_id="ID đấu giá")
    async def huy_dau_gia_cmd(interaction: discord.Interaction, auction_id: str):
        await huy_dau_gia_logic(interaction, auction_id)

    # ===== admin gift =====
    @bot.tree.command(name="gift-waifu-ad", description="Admin tặng waifu")
    @app_commands.describe(waifu_id="ID waifu", user="Người nhận")
    async def gift_waifu_ad_cmd(
        interaction: discord.Interaction,
        waifu_id: str,
        user: Optional[discord.Member] = None,
    ):
        await gift_waifu_ad_logic(interaction, waifu_id, user)
    #========== help ==========
    @bot.tree.command(name="help", description="Xem danh sách lệnh")
    async def help_cmd(interaction: discord.Interaction):
        await help_slash(interaction)

    @bot.tree.command(name="profile", description="Xem hồ sơ")
    @app_commands.describe(user="Người cần xem profile")
    async def profile_cmd(
        interaction: discord.Interaction,
        user: Optional[discord.Member] = None,
    ):
        target = user or interaction.user
        embed = get_profile_embed(bot, target)
        await interaction.response.send_message(embed=embed)
    @bot.tree.command(name="pray")
    async def prayer(interaction: discord.Interaction):
        ctx = interaction
        await prayer_logic(ctx)
    @bot.tree.command(name="fight", description="Đấu với người khác")
    @app_commands.describe(user="Người bạn muốn đấu (để trống để random trong team.json)")
    async def fight_cmd(interaction: discord.Interaction, user: Optional[discord.Member] = None):
        await fight_logic(interaction, user)
    @bot.tree.command(name="team", description="Quản lý team waifu")
    @app_commands.describe(
        action="set / add / remove / view",
        waifu_id="ID waifu"
    )
    async def team_cmd(
        interaction: discord.Interaction,
        action: str,
        waifu_id: Optional[str] = None
    ):
        await team_logic(interaction, action, waifu_id)
    @bot.tree.command(name="lock", description="Bật/tắt lock thách đấu")
    @app_commands.describe(state="true/false, bỏ trống để toggle")
    async def lock_cmd(interaction: discord.Interaction, state: Optional[bool] = None):
        await lock_logic(interaction, state)
    @bot.tree.command(name="zombie", description="Săn zombie bằng team hiện tại")
    async def zombie_cmd(interaction: discord.Interaction):
        await zombie_logic(interaction)
    @bot.tree.command(name="werewolf", description="Tạo phòng Ma Sói")
    @app_commands.describe(
        channel_id="ID hoặc mention channel",
        role_dead="ID hoặc mention role dead"
    )
    async def werewolf_cmd(
        interaction: discord.Interaction,
        channel_id: str,
        role_dead: str
    ):
        await werewolf_logic(interaction, channel_id, role_dead)
print("Loaded slash has successs")
