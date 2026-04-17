from __future__ import annotations

import asyncio
import shlex
from typing import Optional

import discord

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
)
from Commands.daily import daily_logic
from Commands.dau_gia import dau_gia_logic
from Commands.gift_waifu_ad import gift_waifu_ad_logic
from Commands.give import gift_logic
from Commands.gold import gold_logic
from Commands.huy_dau_gia import huy_dau_gia_logic
from Commands.setup import send_roll_embed_logic
from Commands.select_waifu import select_waifu_logic
from Commands.sell import sell_logic
from Commands.setup import setup_channel_logic
from Commands.setup import send_shop_embed_logic
from Commands.use import use_logic
from Commands.view_waifu import view_waifu_logic
from Commands.waifu_list import waifu_list_run
from Commands.work import work
from Commands.help import help_prefix
from Commands.profile import get_profile_embed
from Commands.prayer import prayer_logic
from Commands.fight import fight_logic
from Commands.team import team_logic
from Commands.lock import lock_logic
from Commands.zombie import zombie_logic


def _normalize_name(name: str) -> str:
    return name.strip().lower().replace("_", "-")


def _parse_mention_id(token: str) -> Optional[int]:
    if not token:
        return None
    token = token.strip()
    if token.startswith("<@") and token.endswith(">"):
        token = token[2:-1]
        if token.startswith("!"):
            token = token[1:]
    if token.startswith("<#") and token.endswith(">"):
        token = token[2:-1]
    try:
        return int(token)
    except Exception:
        return None


async def _resolve_user(bot, message: discord.Message, token: Optional[str]) -> Optional[discord.abc.User]:
    if not token:
        return None

    uid = _parse_mention_id(token)
    if uid is None:
        return None

    if message.guild:
        member = message.guild.get_member(uid)
        if member:
            return member

    user = bot.get_user(uid)
    if user:
        return user

    try:
        return await bot.fetch_user(uid)
    except Exception:
        return None


async def _resolve_replied_user(message: discord.Message) -> Optional[discord.abc.User]:
    if not message.reference:
        return None

    try:
        if message.reference.resolved and isinstance(message.reference.resolved, discord.Message):
            return message.reference.resolved.author

        if message.reference.message_id:
            ref_msg = await message.channel.fetch_message(message.reference.message_id)
            return ref_msg.author
    except Exception:
        return None

    return None


async def _smart_target(
    bot,
    message: discord.Message,
    args,
    *,
    fallback_author: bool = True,
):
    """
    Ưu tiên:
    1) mention trong message
    2) người đang được reply
    3) token trong args (mention / ID)
    4) fallback về author hoặc None
    """
    if message.mentions:
        return message.mentions[0]

    replied = await _resolve_replied_user(message)
    if replied:
        return replied

    for token in args or []:
        user = await _resolve_user(bot, message, token)
        if user:
            return user

    return message.author if fallback_author else None


def _resolve_channel(message: discord.Message, token: Optional[str]) -> Optional[discord.abc.GuildChannel]:
    if not token or not message.guild:
        return None
    cid = _parse_mention_id(token)
    if cid is None:
        return None
    return message.guild.get_channel(cid)


class _PrefixResponse:
    def __init__(self, ctx: "PrefixContext"):
        self.ctx = ctx
        self.last_message: Optional[discord.Message] = None

    async def send_message(self, *args, **kwargs):
        kwargs.pop("ephemeral", None)
        self.last_message = await self.ctx.channel.send(*args, **kwargs)
        return self.last_message

    async def edit_message(self, *args, **kwargs):
        if not self.last_message:
            raise RuntimeError("No message to edit")
        return await self.last_message.edit(*args, **kwargs)

    async def defer(self, *args, **kwargs):
        return None

    async def send_modal(self, modal):
        raise RuntimeError("Modal không hỗ trợ trong prefix command")
    def is_done(self):  # 🔥 thêm dòng này
        return self.last_message is not None

class _PrefixFollowup:
    def __init__(self, ctx: "PrefixContext"):
        self.ctx = ctx

    async def send(self, *args, **kwargs):
        kwargs.pop("ephemeral", None)
        return await self.ctx.channel.send(*args, **kwargs)


class PrefixContext:
    def __init__(self, bot: discord.Client, message: discord.Message):
        self.bot = bot
        self.client = bot
        self.message = message
        self.user = message.author
        self.author = message.author
        self.guild = message.guild
        self.channel = message.channel
        self.response = _PrefixResponse(self)
        self.followup = _PrefixFollowup(self)

    async def original_response(self):
        return self.response.last_message

    async def send(self, *args, **kwargs):
        return await self.channel.send(*args, **kwargs)


async def _send_embed_like(ctx: PrefixContext, embed_data: dict):
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
    return await ctx.channel.send(embed=embed)


async def setup(bot):
    """
    Install the prefix listener.
    """
    if getattr(bot, "_prefix_listener_ready", False):
        return
    bot._prefix_listener_ready = True

    async def on_message(message: discord.Message):
        if message.author.bot:
            return
        if not message.content.startswith("."):
            return

        try:
            parts = shlex.split(message.content[1:])
        except ValueError:
            return

        if not parts:
            return

        raw_name = _normalize_name(parts[0])
        args = parts[1:]
        ctx = PrefixContext(bot, message)

        async def reply(msg, ephemeral=False):
            return await ctx.response.send_message(msg, ephemeral=ephemeral)

        async def reply_embed(embed_data):
            return await _send_embed_like(ctx, embed_data)

        # ===== alias map =====
        aliases = {
            "setup": "setup",
            "gold": "gold",
            "daily": "daily",
            "work": "work",
            "select-waifu": "select-waifu",
            "waifu-list": "waifu-list",
            "view-waifu": "view-waifu",
            "bag": "bag",
            "use": "use",
            "sell": "sell",
            "give": "give",
            "couple": "couple",
            "couple-release": "couple-release",
            "couple-cancel": "couple-cancel",
            "couple-info": "couple-info",
            "couple-gift": "couple-gift",
            "coinflip": "coinflip",
            "baucua": "baucua",
            "code": "code",
            "dau-gia": "dau-gia",
            "huy-dau-gia": "huy-dau-gia",
            "gift-waifu-ad": "gift-waifu-ad",
            "help": "help",
            "profile": "profile",
            # 🔥 short alias
            "bc": "baucua",
            "bau": "baucua",
            "cf": "coinflip",
            "wl": "waifu-list",
            "vw": "view-waifu",
            "dg": "dau-gia",
            "hdg": "huy-dau-gia",
            "cp": "couple",
            "cpr": "couple-release",
            "cpc": "couple-cancel",
            "cpi": "couple-info",
            "cpg": "couple-gift",
            "gwa": "gift-waifu-ad",
            "h": "help",
            "s": "sell",
            "gift": "give",
            "coin": "coinflip",
            "ws": "select-waifu",
            "me": "profile",
            "pf": "profile",
            "prayer": "prayer",
            "pray": "prayer",
            "team": "team",
            "fight": "fight",
            "lock": "lock",
            "zombie": "zombie",
            "zom": "zombie",
            "wolf": "werewolf",
            "werewolf": "werewolf",
        }

        # ===== SMART PARSER =====
        cmd = None
        used_len = 1

        # thử 3 từ → 2 từ → 1 từ
        for i in (3, 2, 1):
            if len(parts) >= i:
                name = _normalize_name("-".join(parts[:i]))
                if name in aliases:
                    cmd = aliases[name]
                    used_len = i
                    break

        if cmd is None:
            return

        args = parts[used_len:]

        # ===== dispatch =====
        try:
            if cmd == "setup":
                if len(args) < 2:
                    return await reply("❌ Cú pháp: .setup <auction|ranking|shop|roll> <channel>")

                ch = _parse_mention_id(args[1])
                channel_id = str(ch) if ch is not None else args[1]

                type_ = args[0].lower()

                await setup_channel_logic(ctx, type_, channel_id)

                # 🔥 AUTO SEND PANEL
                if type_ == "shop":
                    return await send_shop_embed_logic(ctx, channel_id)

                if type_ in ["roll", "roll-waifu"]:
                    return await send_roll_embed_logic(ctx, channel_id)

                return

            if cmd == "gold":
                target = await _smart_target(bot, message, args, fallback_author=True)
                return await gold_logic(ctx, target)

            if cmd == "daily":
                return await daily_logic(ctx)

            if cmd == "work":
                return await work(ctx)

            if cmd == "select-waifu":
                if not args:
                    return await reply("❌ Cú pháp: .select-waifu <waifu_id>")
                return await select_waifu_logic(ctx, args[0])

            if cmd == "waifu-list":
                target = None
                if args or message.mentions or message.reference:
                    target = await _smart_target(bot, message, args, fallback_author=False)
                return await waifu_list_run(ctx, target)

            if cmd == "view-waifu":
                if not args:
                    return await reply("❌ Cú pháp: .view-waifu <waifu_id>")

                # Hỗ trợ thêm: .view-waifu @user <waifu_id>
                # Không phá cú pháp cũ .view-waifu <waifu_id>
                if message.mentions and len(args) >= 2:
                    return await view_waifu_logic(message.mentions[0], reply, reply_embed, args[1])

                return await view_waifu_logic(message.author, reply, reply_embed, args[0])

            if cmd == "bag":
                target = None

                if message.mentions:
                    target = message.mentions[0]
                elif args:
                    target = await _resolve_user(bot, message, args[0])
                elif message.reference:
                    ref = message.reference.resolved
                    if ref:
                        target = ref.author

                return await bag_logic(ctx, target or message.author)

            if cmd == "use":
                waifu_id = None
                item_id = None
                qty = 1

                if not args:
                    return await reply("❌ Cú pháp: .use <waifu_id>|item <item_id> [qty]")

                if args[0].lower() in {"waifu", "item"}:
                    mode = args[0].lower()
                    if mode == "waifu":
                        if len(args) < 2:
                            return await reply("❌ Cú pháp: .use waifu <waifu_id>")
                        waifu_id = args[1]
                    else:
                        if len(args) < 2:
                            return await reply("❌ Cú pháp: .use item <item_id> [qty]")
                        item_id = args[1]
                        if len(args) >= 3:
                            qty = int(args[2])
                else:
                    candidate = args[0]
                    if len(args) >= 2 and args[1].isdigit():
                        item_id = candidate
                        qty = int(args[1])
                    else:
                        waifu_id = candidate
                return await use_logic(message.author, reply, waifu_id, item_id, qty)

            if cmd == "sell":
                if not args:
                    return await reply("❌ Cú pháp: .sell <waifu_id> [bag|collection] [amount]")
                waifu_id = args[0]
                source = None
                amount = 1
                if len(args) >= 2:
                    if args[1].lower() in {"bag", "collection"}:
                        source = args[1].lower()
                        if len(args) >= 3:
                            amount = int(args[2])
                    elif args[1].isdigit():
                        amount = int(args[1])
                return await sell_logic(ctx, waifu_id, source, amount)

            if cmd == "give":
                if len(args) < 2:
                    return await reply("❌ Cú pháp: .give <gold|waifu> <user> <amount>")
                type_ = args[0]
                target = await _smart_target(bot, message, args[1:], fallback_author=False)
                if target is None:
                    return await reply("❌ Không tìm thấy người nhận.")
                amount = None
                waifu_id = None
                if type_ == "gold":
                    if len(args) < 3:
                        return await reply("❌ Cú pháp: .give gold <user> <amount>")
                    amount = int(args[2])
                elif type_ == "waifu":
                    if len(args) < 3:
                        return await reply("❌ Cú pháp: .give waifu <user> <waifu_id>")
                    waifu_id = args[2]
                else:
                    return await reply("❌ Type phải là gold hoặc waifu.")
                return await gift_logic(ctx, type_, target, amount, waifu_id)

            if cmd == "couple":
                if not args:
                    return await reply("❌ Cú pháp: .couple <user> | .couple release | .couple cancel | .couple info | .couple gift <rose|cake>")
                sub = _normalize_name(args[0])

                if sub == "release":
                    return await couple_release_logic(bot, ctx)
                if sub == "cancel":
                    return await couple_cancel_logic(ctx)
                if sub == "info":
                    return await couple_info_logic(ctx)
                if sub == "gift":
                    if len(args) < 2:
                        return await reply("❌ Cú pháp: .couple gift <rose|cake>")
                    return await couple_gift_logic(ctx, args[1])

                target = await _smart_target(bot, message, args, fallback_author=False)
                if target is None:
                    return await reply("❌ Không tìm thấy người dùng.")
                return await couple_logic(bot, ctx, target)

            if cmd == "couple-release":
                return await couple_release_logic(bot, ctx)

            if cmd == "couple-cancel":
                return await couple_cancel_logic(ctx)

            if cmd == "couple-info":
                return await couple_info_logic(ctx)

            if cmd == "couple-gift":
                if not args:
                    return await reply("❌ Cú pháp: .couple-gift <rose|cake>")
                return await couple_gift_logic(ctx, args[0])

            if cmd == "coinflip":
                if len(args) < 2:
                    return await reply("❌ Cú pháp: .coinflip <ngua|sap> <amount>")
                return await coinflip_logic(ctx, args[0], int(args[1]))

            if cmd == "baucua":
                if len(args) < 2:
                    return await reply("❌ Cú pháp: .baucua <nai|bau|ga|ca|cua|tom> <amount>")
                return await baucua_logic(ctx, args[0], int(args[1]))

            if cmd == "code":
                if not args:
                    return await reply("❌ Cú pháp: .code <mã>")
                return await code_logic(ctx, args[0])

            if cmd == "dau-gia":
                if len(args) < 3:
                    return await reply("❌ Cú pháp: .dau-gia <waifu_id> <min_price> <step>")
                return await dau_gia_logic(ctx, args[0], int(args[1]), int(args[2]))

            if cmd == "huy-dau-gia":
                if not args:
                    return await reply("❌ Cú pháp: .huy-dau-gia <auction_id>")
                return await huy_dau_gia_logic(ctx, args[0])

            if cmd == "gift-waifu-ad":
                if not args:
                    return await reply("❌ Cú pháp: .gift-waifu-ad <waifu_id> [user]")
                target = None
                if len(args) >= 2:
                    target = await _smart_target(bot, message, args[1:], fallback_author=False)
                return await gift_waifu_ad_logic(ctx, args[0], target)

            if cmd == "profile":
                target = await _smart_target(bot, message, args, fallback_author=True)
                embed = get_profile_embed(bot, target)
                return await ctx.send(embed=embed)
            if cmd == "prayer":
                return await prayer_logic(ctx)

            if cmd == "help":
                await help_prefix(message)
                return
            if cmd == "fight":
                target = await _smart_target(bot, message, args, fallback_author=False)
                return await fight_logic(ctx, target)
            if cmd == "team":
                if not args:
                    return await reply("❌ Cú pháp: .team <set/add/remove/show> [waifu_id]")

                action = args[0].lower()
                waifu_id = args[1] if len(args) >= 2 else None

                return await team_logic(ctx, action, waifu_id)
            if cmd == "lock":
                state = args[0] if args else None
                return await lock_logic(ctx, state)
            if cmd == "zombie":
                return await zombie_logic(ctx)
            if cmd == "werewolf":
                if len(args) < 2:
                    return await reply("❌ Cú pháp: .werewolf <channel_id> <role_dead>")
                return await werewolf_logic(ctx, args[0], args[1])
        except ValueError:
            return await reply("❌ Tham số số không hợp lệ.")
        except Exception as exc:
            print(f"[PREFIX ERROR] {cmd}: {exc}")
            return await reply("❌ Có lỗi khi xử lý lệnh.")

    bot.add_listener(on_message, "on_message")
print("Loaded prefix has successs")
