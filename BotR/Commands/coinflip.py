import asyncio
import random
import time
from typing import Dict, Any, Union

import discord
from discord.ext import commands

from Data import data_user
from Commands.prayer import get_luck


# ===== SIDE =====
choices = ["ngua", "sap"]


# ===== EMOJI =====
CUSTOM_EMOJI = {
    # "ngua": "<a:ngua:123456>",
    # "sap": "<a:sap:123456>",
}

UNICODE_EMOJI = {
    "ngua": "<:ngua:1490580499582681088>",
    "sap": "<:sap:1490580475172098178>",
}


def get_emoji(x):
    return CUSTOM_EMOJI.get(x) or UNICODE_EMOJI.get(x, "❔")


def pretty_side(x: str):
    x = str(x).lower()
    if x == "ngua":
        return "Ngửa"
    if x == "sap":
        return "Sấp"
    return x


def _safe_int(v):
    try:
        return int(v)
    except Exception:
        return 0


def _get_user(ctx):
    return ctx.user if isinstance(ctx, discord.Interaction) else ctx.author


# ===== ANTI SPAM =====
_LAST_PLAY: Dict[int, float] = {}
_SPAM_COUNT: Dict[int, int] = {}


def spam_control(uid):
    now = time.time()
    last = _LAST_PLAY.get(uid, 0)

    diff = now - last

    if diff < 2:
        _SPAM_COUNT[uid] = _SPAM_COUNT.get(uid, 0) + 1
    else:
        _SPAM_COUNT[uid] = 0

    _LAST_PLAY[uid] = now

    spam = _SPAM_COUNT[uid]

    delay = min(spam * 0.5, 2)
    scale = max(1 - spam * 0.1, 0.5)

    return delay, scale, spam


async def _defer_if_needed(ctx, *, ephemeral: bool = False):
    if isinstance(ctx, discord.Interaction) and not ctx.response.is_done():
        try:
            await ctx.response.defer(ephemeral=ephemeral)
        except Exception:
            pass


# ===== SEND SAFE (FIX CHÍNH) =====
async def _send(
    ctx: Union[commands.Context, discord.Interaction],
    content=None,
    embed=None,
    ephemeral: bool = False
):
    try:
        if isinstance(ctx, discord.Interaction):
            try:
                if not ctx.response.is_done():
                    await ctx.response.send_message(
                        content=content,
                        embed=embed,
                        ephemeral=ephemeral
                    )
                    return await ctx.original_response()
                return await ctx.followup.send(
                    content=content,
                    embed=embed,
                    ephemeral=ephemeral
                )
            except discord.InteractionResponded:
                return await ctx.followup.send(
                    content=content,
                    embed=embed,
                    ephemeral=ephemeral
                )

        return await ctx.send(content=content, embed=embed)

    except Exception as e:
        print("[SEND ERROR]", e)
        return None


# ===== EMBED CHỜ =====
def build_wait_embed(user):
    embed = discord.Embed(
        description="<a:coinflip:1490580450668838962>",
        color=0xf1c40f
    )

    embed.set_author(
        name="Tung đồng xu",
        icon_url=None
    )

    return embed


# ===== EMBED KẾT QUẢ =====
def build_result_embed(user, choice, result, amount, reward, win, gold, spam, scale, luck):
    embed = discord.Embed()

    embed.set_author(
        name="Tung đồng xu",
        icon_url=None
    )

    result_line = f"Kết quả: {get_emoji(result)} {pretty_side(result)}"

    if win:
        embed.color = 0x2ecc71
        embed.description = (
            f"{result_line}\n\n"
            f"🎉 Bạn đã trúng {pretty_side(choice)}\n"
            f"💰 Đã cộng thêm {reward} <a:gold:1492792339436142703>"
        )

        if spam >= 2:
            embed.description += f"\n⚠️ Spam → giảm thưởng x{scale:.2f}"

    else:
        embed.color = 0xe74c3c
        embed.description = (
            f"{result_line}\n\n"
            f"💔 Bạn không trúng mặt nào. Đã trừ đi {amount} <a:gold:1492792339436142703>"
        )

    embed.set_footer(text=f"Số dư hiện tại: {gold} <a:gold:1492792339436142703>")

    return embed


# ===== MAIN =====
async def coinflip_logic(ctx, choice: str, amount: Any):
    await _defer_if_needed(ctx, ephemeral=isinstance(ctx, discord.Interaction))

    user = _get_user(ctx)
    uid = user.id

    choice = str(choice).strip().lower()
    amount = _safe_int(amount)

    is_slash = isinstance(ctx, discord.Interaction)

    if choice not in choices:
        return await _send(
            ctx,
            "❌ Chỉ được nhập: Ngua hoặc Sap!",
            ephemeral=is_slash
        )

    if amount <= 0:
        return await _send(
            ctx,
            "❌ Gold phải > 0!",
            ephemeral=is_slash
        )

    if not await data_user.remove_gold(uid, amount):
        return await _send(
            ctx,
            "❌ Không đủ gold!",
            ephemeral=is_slash
        )

    delay, scale, spam = spam_control(uid)

    wait_msg = await _send(ctx, embed=build_wait_embed(user))
    if wait_msg is None:
        return

    wait_time = random.uniform(3, 5) + delay
    await asyncio.sleep(wait_time)

    luck = _safe_int(get_luck(uid))

    weights = {
        "ngua": 1.0,
        "sap": 1.0
    }

    weights[choice] *= (1 + max(0, (luck - 1) / 100) * 5)

    result = random.choices(
        ["ngua", "sap"],
        weights=[weights["ngua"], weights["sap"]],
        k=1
    )[0]

    if choice == result:
        reward = int(amount * 1.7)
        reward = int(reward * scale)

        await data_user.add_gold(uid, reward)
        win = True
    else:
        reward = 0
        win = False

    user_data = data_user.get_user(uid) or {}
    gold = user_data.get("gold", 0)

    embed = build_result_embed(
        user=user,
        choice=choice,
        result=result,
        amount=amount,
        reward=reward,
        win=win,
        gold=gold,
        spam=spam,
        scale=scale,
        luck=luck
    )

    try:
        if wait_msg:
            await wait_msg.edit(embed=embed)
    except Exception:
        pass


print("Loaded coinflip has success")