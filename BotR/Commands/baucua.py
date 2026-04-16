import asyncio
import random
import time
from typing import Any, Dict, Union

import discord
from discord.ext import commands
from Data import data_user
from Commands.prayer import get_luck

animals = ["nai", "bau", "ga", "ca", "cua", "tom"]

# ===== EMOJI =====
CUSTOM_EMOJI = {
    # "ga": "<a:ga:123456>"
}

UNICODE_EMOJI = {
    "nai": "<:nai:1490383428322070739>",
    "bau": "<:bau:1490383478829879406>",
    "ga": "<:ga:1490383569556865044>",
    "ca": "<:ca:1490383383166193835>",
    "cua": "<:cua:1490383517182591127>",
    "tom": "<:tom:1490382978189099108>",
}


def get_emoji(x):
    return CUSTOM_EMOJI.get(x) or UNICODE_EMOJI.get(x, "❔")


def format_result(result):
    return " ".join(get_emoji(x) for x in result)


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


def _safe_int(v):
    try:
        return int(v)
    except Exception:
        return 0


def _get_user(ctx):
    return ctx.user if isinstance(ctx, discord.Interaction) else ctx.author


async def _defer_if_needed(ctx):
    if isinstance(ctx, discord.Interaction) and not ctx.response.is_done():
        try:
            await ctx.response.defer()
        except Exception:
            pass


# ===== SEND HELPER (FIX CHÍNH) =====
async def send_message(
    ctx: Union[commands.Context, discord.Interaction],
    *,
    content=None,
    embed=None,
):
    if isinstance(ctx, discord.Interaction):
        try:
            if not ctx.response.is_done():
                await ctx.response.send_message(content=content, embed=embed)
                return await ctx.original_response()
            return await ctx.followup.send(content=content, embed=embed)
        except discord.InteractionResponded:
            return await ctx.followup.send(content=content, embed=embed)
        except Exception as e:
            print("[SEND ERROR]", e)
            return None

    try:
        return await ctx.send(content=content, embed=embed)
    except Exception as e:
        print("[SEND ERROR]", e)
        return None


# ===== EMBED CHỜ =====
def build_wait_embed(user):
    embed = discord.Embed(
        description="<a:gacha:1490382513388912740> <a:gacha:1490382513388912740> <a:gacha:1490382513388912740>",
        color=0xf1c40f
    )

    embed.set_author(name="Bầu Cua", icon_url=None)
    embed.set_image(url="")
    embed.set_footer(text="")

    return embed


# ===== EMBED KẾT QUẢ =====
def build_result_embed(user, result, choice, count, amount, reward, win, gold, spam, scale):
    embed = discord.Embed()

    embed.set_author(name="Bầu Cua", icon_url=None)

    result_line = f"Kết quả: {format_result(result)}"

    if win:
        embed.color = 0x2ecc71
        embed.description = (
            f"{result_line}\n\n"
            f"🎉 Bạn đã trúng {count} mặt {get_emoji(choice)}\n"
            f"💰 đã cộng thêm {reward} <a:gold:1492792339436142703>"
        )

        if spam >= 2:
            embed.description += f"\n⚠️ Spam → giảm thưởng x{scale:.2f}"

    else:
        embed.color = 0xe74c3c
        embed.description = (
            f"{result_line}\n\n"
            f"💔 Bạn không trúng mặt nào. Đã trừ {amount} <a:gold:1492792339436142703>"
        )

    embed.set_footer(text=f"Số dư hiện tại: {gold} <a:gold:1492792339436142703>")

    return embed


# ===== MAIN =====
async def baucua_logic(ctx, choice: str, amount: Any):
    await _defer_if_needed(ctx)

    user = _get_user(ctx)
    uid = user.id

    choice = str(choice).strip().lower()
    amount = _safe_int(amount)

    if choice not in animals:
        return await send_message(ctx, content="❌ Sai lựa chọn!")

    if amount <= 0:
        return await send_message(ctx, content="❌ Gold phải > 0")

    if not await data_user.remove_gold(uid, amount):
        return await send_message(ctx, content="❌ Không đủ gold!")

    delay, scale, spam = spam_control(uid)

    msg = await send_message(ctx, embed=build_wait_embed(user))

    wait_time = random.uniform(1.5, 3) + delay
    await asyncio.sleep(wait_time)

    luck = _safe_int(get_luck(uid))

    weights = {a: 1.0 for a in animals}
    weights[choice] *= (1 + max(0, (luck - 1) / 100) * 5)

    result = random.choices(list(weights.keys()), weights=list(weights.values()), k=3)
    count = result.count(choice)

    if count > 0:
        base = int(amount * (count + 0.9))
        reward = int(base * scale)
        await data_user.add_gold(uid, reward)
        win = True
    else:
        reward = 0
        win = False

    gold = data_user.get_user(uid).get("gold", 0)

    embed = build_result_embed(
        user, result, choice, count, amount, reward, win, gold, spam, scale
    )

    try:
        if msg:
            await msg.edit(embed=embed)
    except Exception:
        pass


print("Loaded bầu cua has successs")