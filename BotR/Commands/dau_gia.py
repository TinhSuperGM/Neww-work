import asyncio
import discord
import json
import os
import time
import uuid
from typing import Any, Dict, Optional, Union

from discord.ext import commands
from Data import data_user

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

WAIFU_FILE = os.path.join(BASE_DIR, "Data", "waifu_data.json")
INV_FILE = os.path.join(BASE_DIR, "Data", "inventory.json")
AUCTION_FILE = os.path.join(BASE_DIR, "Data", "auction.json")
CHANNEL_FILE = os.path.join(BASE_DIR, "Data", "auction_channels.json")

ALLOWED_AUCTION_RANKS = {"truyen_thuyet", "toi_thuong", "limited"}

# ===== LOCK =====
GLOBAL_LOCK = asyncio.Lock()
auction_locks: Dict[str, asyncio.Lock] = {}


def get_auction_lock(aid: str):
    if aid not in auction_locks:
        auction_locks[aid] = asyncio.Lock()
    return auction_locks[aid]


# ===== COOLDOWN =====
last_bid_time: Dict[str, float] = {}


def check_cooldown(uid: str, aid: str):
    key = f"{uid}:{aid}"
    now = time.time()
    if key in last_bid_time and now - last_bid_time[key] < 2:
        return False
    last_bid_time[key] = now
    return True


# ===== FILE =====
def load_json(path):
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_json(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)
    os.replace(tmp, path)


# ===== CACHE =====
WAIFU_CACHE: Dict[str, Any] = {}
WAIFU_LAST = 0.0


def get_waifu_data():
    global WAIFU_CACHE, WAIFU_LAST
    if time.time() - WAIFU_LAST < 10:
        return WAIFU_CACHE
    WAIFU_CACHE = load_json(WAIFU_FILE)
    WAIFU_LAST = time.time()
    return WAIFU_CACHE


CHANNEL_CACHE: Dict[str, Any] = {}
CHANNEL_LAST = 0.0


def get_channels():
    global CHANNEL_CACHE, CHANNEL_LAST
    if time.time() - CHANNEL_LAST < 10:
        return CHANNEL_CACHE
    CHANNEL_CACHE = load_json(CHANNEL_FILE)
    CHANNEL_LAST = time.time()
    return CHANNEL_CACHE


# ===== UPDATE CONTROL =====
LAST_UPDATE: Dict[tuple, float] = {}


# ===== CTX HELPERS =====
def _get_user(ctx):
    return ctx.user if isinstance(ctx, discord.Interaction) else ctx.author


def _get_client(ctx):
    return ctx.client if isinstance(ctx, discord.Interaction) else ctx.bot


async def _send(
    ctx: Union[commands.Context, discord.Interaction],
    content: Optional[str] = None,
    embed: Optional[discord.Embed] = None,
    view: Optional[discord.ui.View] = None,
    ephemeral: bool = False,
):
    try:
        if isinstance(ctx, discord.Interaction):
            try:
                if not ctx.response.is_done():
                    await ctx.response.send_message(
                        content=content,
                        embed=embed,
                        view=view,
                        ephemeral=ephemeral,
                    )
                    try:
                        return await ctx.original_response()
                    except Exception:
                        return None

                return await ctx.followup.send(
                    content=content,
                    embed=embed,
                    view=view,
                    ephemeral=ephemeral,
                )
            except discord.InteractionResponded:
                return await ctx.followup.send(
                    content=content,
                    embed=embed,
                    view=view,
                    ephemeral=ephemeral,
                )

        return await ctx.send(content=content, embed=embed, view=view)
    except Exception as e:
        print("[AUCTION SEND ERROR]", e)
        return None


async def _defer(ctx: Union[commands.Context, discord.Interaction], ephemeral: bool = False):
    if isinstance(ctx, discord.Interaction) and not ctx.response.is_done():
        try:
            await ctx.response.defer(ephemeral=ephemeral)
        except Exception:
            pass


# ===== EMBED =====
def get_color(rank):
    return {
        "truyen_thuyet": 0x00FFFF,
        "toi_thuong": 0xFF0000,
        "limited": 0xFF00FF,
    }.get(rank, 0xFFD700)


def get_info(a):
    return get_waifu_data().get(a["waifu_id"], {})


def build_active_embed(a):
    info = get_info(a)

    name = (
        info.get("name")
        or info.get("bio")
        or info.get("description")
        or a["waifu_id"]
    )

    bio = info.get("Bio") or info.get("bio") or info.get("description") or "Không có mô tả"
    rank = str(info.get("rank", "unknown")).strip().lower()
    highest = a.get("highest_bidder")

    e = discord.Embed(
        title="⚖️ BUỔI ĐẤU GIÁ ⚖️",
        description=(
            f"🌹 **{name}**\n"
            f"📝 {bio}\n\n"
            f"🎖️ Rank: **{rank}**\n"
            f"👤 Seller: <@{a['seller']}>\n"
            f"💰 Giá: **{a.get('current_bid', 0)}**\n"
            f"🏆 {f'<@{highest}>' if highest else 'Chưa có'}\n\n"
            f"⏳ <t:{int(a['end_time'])}:R>"
        ),
        color=get_color(rank),
    )

    e.set_footer(text=f"Auction ID: {a.get('id')}")

    if info.get("image"):
        e.set_image(url=info["image"])

    return e


def build_end_embed(a):
    info = get_info(a)

    name = (
        info.get("name")
        or info.get("bio")
        or info.get("description")
        or a["waifu_id"]
    )

    bio = info.get("bio") or info.get("description") or "Không có mô tả"

    winner = a.get("highest_bidder")
    seller = a["seller"]
    bid = a.get("current_bid", 0)

    e = discord.Embed(color=discord.Color.green())

    if winner and winner != seller:
        e.description = f"<@{winner}> thắng **{name}** với **{bid} <a:gold:1492792339436142703>**"
    else:
        e.description = f"Không ai mua **{name}**, trả về <@{seller}>"

    e.add_field(name="📝 Thông tin", value=bio, inline=False)
    e.set_footer(text=f"Auction ID: {a.get('id')}")

    if info.get("image"):
        e.set_image(url=info["image"])

    return e


# ===== VIEW =====
class BidModal(discord.ui.Modal, title="Đặt giá"):
    amount = discord.ui.TextInput(label="Gold", required=True)

    def __init__(self, aid):
        super().__init__()
        self.aid = aid

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        uid = str(interaction.user.id)

        if not check_cooldown(uid, self.aid):
            return await interaction.followup.send("⏳ Spam ít thôi!", ephemeral=True)

        try:
            bid = int(self.amount.value)
        except Exception:
            return await interaction.followup.send("❌ Sai số", ephemeral=True)

        async with get_auction_lock(self.aid):
            auctions = load_json(AUCTION_FILE)
            a = auctions.get(self.aid)

            if not a:
                return await interaction.followup.send("❌ Không tồn tại", ephemeral=True)

            if time.time() >= a["end_time"]:
                return await interaction.followup.send("❌ Đã kết thúc", ephemeral=True)

            if uid == a["seller"]:
                return await interaction.followup.send("❌ Không thể tự bid", ephemeral=True)

            cur = a.get("current_bid", 0)

            if cur == 0:
                if bid < a["min_price"]:
                    return await interaction.followup.send("❌ Chưa đạt giá", ephemeral=True)
            else:
                if bid < cur + a["step"]:
                    return await interaction.followup.send("❌ Không đủ bước", ephemeral=True)

            if not await data_user.remove_gold(uid, bid):
                return await interaction.followup.send("❌ Không đủ gold", ephemeral=True)

            prev = a.get("highest_bidder")
            prev_bid = a.get("current_bid", 0)

            try:
                if prev and prev != uid and prev_bid > 0:
                    await data_user.add_gold(prev, prev_bid)
            except Exception:
                # rollback current bidder nếu refund thất bại
                try:
                    await data_user.add_gold(uid, bid)
                except Exception:
                    pass
                return await interaction.followup.send("❌ Lỗi hoàn gold cho người bid trước", ephemeral=True)

            a["highest_bidder"] = uid
            a["current_bid"] = bid

            if a["end_time"] - time.time() < 10:
                a["end_time"] += 15

            auctions[self.aid] = a
            save_json(AUCTION_FILE, auctions)

        await update_all_embeds(interaction.client, self.aid, a, False)
        await interaction.followup.send("✅ Đã bid", ephemeral=True)


class BidButton(discord.ui.Button):
    def __init__(self, aid):
        super().__init__(
            label="Đấu giá",
            style=discord.ButtonStyle.green,
            custom_id=f"bid:{aid}",
        )

    async def callback(self, interaction: discord.Interaction):
        aid = self.custom_id.split(":", 1)[1]
        await interaction.response.send_modal(BidModal(aid))


class BidView(discord.ui.View):
    def __init__(self, aid):
        super().__init__(timeout=None)
        self.add_item(BidButton(aid))


# ===== UPDATE =====
async def _ensure_panel_for_guild(bot, aid: str, a: Dict[str, Any], gid: str, ch_id: str):
    try:
        ch = bot.get_channel(int(ch_id)) or await bot.fetch_channel(int(ch_id))
        if ch is None:
            return

        embed = build_active_embed(a)
        view = BidView(aid)
        msg_key = f"message_id_{gid}"
        msg_id = a.get(msg_key)

        if msg_id:
            try:
                msg = await ch.fetch_message(int(msg_id))
                await msg.edit(embed=embed, view=view)
                return
            except Exception:
                pass

        msg = await ch.send(embed=embed, view=view)
        a[msg_key] = msg.id
    except Exception:
        return


async def update_all_embeds(bot, aid, a, ended=False):
    channels = get_channels()

    for gid, ch_data in channels.items():
        ch_id = ch_data.get("auction_channel_id") if isinstance(ch_data, dict) else ch_data
        msg_id = a.get(f"message_id_{gid}")

        if not ch_id or not msg_id:
            continue

        now = time.time()
        key = (aid, gid)

        if not ended:
            if now - LAST_UPDATE.get(key, 0) < 2:
                continue
            LAST_UPDATE[key] = now

        try:
            ch = bot.get_channel(int(ch_id)) or await bot.fetch_channel(int(ch_id))
            if ch is None:
                continue

            msg = await ch.fetch_message(int(msg_id))
            embed = build_end_embed(a) if ended else build_active_embed(a)
            view = None if ended else BidView(aid)

            await msg.edit(embed=embed, view=view)
        except Exception:
            continue


async def _bootstrap_auctions(bot):
    await bot.wait_until_ready()

    while not bot.is_closed():
        try:
            auctions = load_json(AUCTION_FILE)
            channels = get_channels()

            changed = False

            for aid, a in list(auctions.items()):
                if not isinstance(a, dict):
                    continue

                # buttons sống lại sau restart
                bot.add_view(BidView(aid))

                # tự gửi / tự gắn panel vào mọi server đã set channel
                for gid, ch_data in channels.items():
                    ch_id = ch_data.get("auction_channel_id") if isinstance(ch_data, dict) else ch_data
                    if not ch_id:
                        continue

                    msg_key = f"message_id_{gid}"
                    if a.get(msg_key):
                        continue

                    await _ensure_panel_for_guild(bot, aid, a, str(gid), str(ch_id))
                    changed = True

            if changed:
                save_json(AUCTION_FILE, auctions)

            break
        except Exception:
            await asyncio.sleep(2)


# ===== CREATE =====
async def dau_gia_logic(ctx, waifu_id, min_price, step):
    await _defer(ctx, ephemeral=True)
    uid = str(_get_user(ctx).id)
    client = _get_client(ctx)

    waifu_data = get_waifu_data()
    waifu_info = waifu_data.get(waifu_id, {})

    rank = str(waifu_info.get("rank", "")).strip().lower()
    if rank not in ALLOWED_AUCTION_RANKS:
        return await _send(ctx, "❌ Chỉ rank truyen_thuyet / toi_thuong / limited mới được tạo đấu giá", ephemeral=True)

    async with GLOBAL_LOCK:
        inv = load_json(INV_FILE)

        if waifu_id not in inv.get(uid, {}).get("waifus", {}):
            return await _send(ctx, "❌ Không có", ephemeral=True)

        love = inv[uid]["waifus"].pop(waifu_id)
        save_json(INV_FILE, inv)

    aid = str(uuid.uuid4())

    a = {
        "id": aid,
        "waifu_id": waifu_id,
        "seller": uid,
        "min_price": min_price,
        "step": step,
        "current_bid": 0,
        "highest_bidder": None,
        "end_time": time.time() + 86400,
        "love": love,
    }

    channels = get_channels()

    for gid, ch_data in channels.items():
        ch_id = ch_data.get("auction_channel_id") if isinstance(ch_data, dict) else ch_data
        if not ch_id:
            continue

        try:
            ch = client.get_channel(int(ch_id)) or await client.fetch_channel(int(ch_id))
            if ch is None:
                continue

            msg = await ch.send(embed=build_active_embed(a), view=BidView(aid))
            a[f"message_id_{gid}"] = msg.id
        except Exception:
            continue

    auctions = load_json(AUCTION_FILE)
    auctions[aid] = a
    save_json(AUCTION_FILE, auctions)

    await _send(ctx, "✅ Tạo đấu giá", ephemeral=True if isinstance(ctx, discord.Interaction) else False)


# ===== LOOP =====
async def auction_realtime_loop(bot):
    await bot.wait_until_ready()

    while not bot.is_closed():
        try:
            auctions = load_json(AUCTION_FILE)
            inv = load_json(INV_FILE)

            ended = []

            for aid, a in list(auctions.items()):
                if not isinstance(a, dict):
                    continue

                if time.time() < a.get("end_time", 0):
                    continue

                async with get_auction_lock(aid):
                    if aid not in auctions:
                        continue

                    waifu = a["waifu_id"]
                    seller = a["seller"]
                    winner = a.get("highest_bidder")
                    bid = a.get("current_bid", 0)

                    if winner and winner != seller:
                        inv.setdefault(winner, {"waifus": {}, "bag": {}})
                        inv[winner].setdefault("waifus", {})
                        inv[winner].setdefault("bag", {})

                        if waifu not in inv[winner]["waifus"]:
                            inv[winner]["waifus"][waifu] = a["love"]
                        else:
                            inv[winner]["bag"][waifu] = inv[winner]["bag"].get(waifu, 0) + 1

                        await data_user.add_gold(seller, bid)

                    else:
                        inv.setdefault(seller, {"waifus": {}, "bag": {}})
                        inv[seller].setdefault("waifus", {})
                        inv[seller].setdefault("bag", {})

                        if waifu not in inv[seller]["waifus"]:
                            inv[seller]["waifus"][waifu] = a["love"]
                        else:
                            inv[seller]["bag"][waifu] = inv[seller]["bag"].get(waifu, 0) + 1

                    ended.append(aid)

                    await update_all_embeds(bot, aid, a, True)

            for aid in ended:
                auctions.pop(aid, None)

            if ended:
                save_json(INV_FILE, inv)
                save_json(AUCTION_FILE, auctions)

        except Exception as e:
            print("[AUCTION LOOP ERROR]", e)

        await asyncio.sleep(5)
# ===== SETUP =====
async def setup(bot):
    auctions = load_json(AUCTION_FILE)

    for aid in auctions:
        bot.add_view(BidView(aid))

    bot.loop.create_task(auction_realtime_loop(bot))
    bot.loop.create_task(_bootstrap_auctions(bot))


print("Loaded auction has success")