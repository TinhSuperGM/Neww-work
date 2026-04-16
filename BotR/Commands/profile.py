import json
import os
import discord
from typing import Any, Dict, Union

from Data import data_user  # ✅ dùng cache

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

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "Data")

INV_FILE = os.path.join(DATA_DIR, "inventory.json")
LEVEL_FILE = os.path.join(DATA_DIR, "level.json")
COUPLE_FILE = os.path.join(DATA_DIR, "couple.json")
WAIFU_FILE = os.path.join(DATA_DIR, "waifu_data.json")


# ===== LOAD JSON SAFE =====
def load_json(path: str) -> Dict[str, Any]:
    if not os.path.exists(path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump({}, f)

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}


# ===== UTILS =====
def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _get_waifu_amount(raw_value: Any) -> int:
    if isinstance(raw_value, dict):
        return _safe_int(raw_value.get("love", 0))
    return _safe_int(raw_value, 0)


def _count_total_waifu(waifus: Dict[str, Any]) -> int:
    return sum(_get_waifu_amount(v) for v in waifus.values())


def _sanitize(text: str) -> str:
    return discord.utils.escape_mentions(discord.utils.escape_markdown(text))


def _truncate(text: str, limit=300):
    return text if len(text) <= limit else text[:limit - 3] + "..."


# ===== MAIN =====
def get_profile_embed(bot, user: Union[discord.Member, discord.User]):
    uid = str(user.id)

    # ===== LOAD =====
    inv = load_json(INV_FILE)
    levels = load_json(LEVEL_FILE)
    couples = load_json(COUPLE_FILE)
    waifu_data = load_json(WAIFU_FILE)

    # ✅ GOLD từ cache
    user_data = data_user.get_user(uid)
    gold = _safe_int(user_data.get("gold"))

    inv_data = inv.get(uid, {})
    level_data = levels.get(uid, {})
    couple_data = couples.get(uid, {})

    # ===== WAIFU =====
    waifus = inv_data.get("waifus") or {}

    # ✅ FIX: đảm bảo đúng kiểu
    if not isinstance(waifus, dict):
        waifus = {}

    # ✅ FIX: count + total rõ ràng
    count = len(waifus)
    total = _count_total_waifu(waifus)

    default = inv_data.get("default_waifu")

    if default and default in waifus and default in waifu_data:
        wid = default
        info = waifu_data.get(wid, {})
        love = _get_waifu_amount(waifus.get(wid))
        level = _safe_int(level_data.get(wid, 0))
    else:
        wid, info, love, level = None, {}, 0, 0

    name = info.get("name", "None")
    bio = _truncate(_sanitize(info.get("Bio", "No bio")))
    image = info.get("image")

    # ===== COUPLE =====
    partner_id = couple_data.get("partner")
    points = _safe_int(couple_data.get("points"))

    if partner_id:
        partner = bot.get_user(int(partner_id))
        partner_name = partner.display_name if partner else f"<@{partner_id}>"
    else:
        partner_name = "Single"

    # ===== EMBED =====
    embed = discord.Embed(
        color=discord.Color.pink() if partner_id else discord.Color.blurple()
    )

    embed.set_author(
        name=f"{user.display_name} ✨",
        icon_url=user.display_avatar.url
    )

    embed.set_thumbnail(url=user.display_avatar.url)

    # ✅ FIX: hiển thị rõ count + total
    embed.add_field(
        name="💰 Economy",
        value=f"Gold: **{gold:,}**\nWaifu: **{count}** | ❤️ {total}",
        inline=True
    )

    embed.add_field(
        name="💖 Main Waifu",
        value=f"**{name}**\n❤️ {love} | Lv {level}",
        inline=True
    )

    embed.add_field(
        name="💍 Relationship",
        value=f"{partner_name}\nPoint: **{points}**",
        inline=True
    )

    embed.add_field(
        name="📖 Description",
        value=bio,
        inline=False
    )

    if image:
        embed.set_image(url=image)

    embed.set_footer(text=f"User ID: {uid}")

    return embed


print("Loaded profile has success")