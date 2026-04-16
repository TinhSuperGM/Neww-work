import asyncio
import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Union
from Data import data_user
import discord
from discord.ext import commands

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COUPLE_FILE = os.path.join(BASE_DIR, "Data", "couple.json")

VN_TZ = timezone(timedelta(hours=7))


# ===== LOAD / SAVE =====
def load_json(file_path: str) -> Dict[str, Any]:
    if not os.path.exists(file_path):
        return {}
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_json(file_path: str, data: Dict[str, Any]) -> None:
    tmp = file_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)
    os.replace(tmp, file_path)


# ===== TIME =====
def now_vn() -> datetime:
    return datetime.now(VN_TZ)


def iso_now_vn() -> str:
    return now_vn().isoformat()


def parse_iso_dt(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=VN_TZ)
        return dt
    except Exception:
        return None


# ===== CORE =====
def create_couple(data: Dict[str, Any], u1: int, u2: int) -> None:
    now = now_vn().strftime("%Y-%m-%d")

    data[str(u1)] = {
        "partner": str(u2),
        "since": now,
        "points": 0,
        "pending_break": False,
        "break_time": None,
        "break_initiator": None,
    }

    data[str(u2)] = {
        "partner": str(u1),
        "since": now,
        "points": 0,
        "pending_break": False,
        "break_time": None,
        "break_initiator": None,
    }


def remove_couple(data: Dict[str, Any], u1: Any, u2: Any) -> None:
    data.pop(str(u1), None)
    data.pop(str(u2), None)


def get_couple_level(points: int) -> int:
    points = max(0, int(points))
    return max(1, points // 50 + 1)


def format_remaining_time(break_time_iso: Any) -> str:
    bt = parse_iso_dt(break_time_iso)
    if not bt:
        return "Không rõ"

    remain = timedelta(days=7) - (now_vn() - bt)
    if remain.total_seconds() <= 0:
        return "Đã quá hạn, đang chờ xử lý..."

    total_seconds = int(remain.total_seconds())
    days = total_seconds // 86400
    hours = (total_seconds % 86400) // 3600
    minutes = (total_seconds % 3600) // 60

    parts = []
    if days > 0:
        parts.append(f"{days} ngày")
    if hours > 0:
        parts.append(f"{hours} giờ")
    if minutes > 0 and days == 0:
        parts.append(f"{minutes} phút")

    return " ".join(parts) if parts else "Dưới 1 phút"


def check_auto_break(data: Dict[str, Any], uid: str) -> bool:
    info = data.get(uid)
    if not info:
        return False

    if not info.get("pending_break"):
        return False

    bt = parse_iso_dt(info.get("break_time"))
    if not bt:
        return False

    if now_vn() - bt >= timedelta(days=7):
        partner = info.get("partner")
        if partner is not None:
            remove_couple(data, uid, partner)
        else:
            data.pop(uid, None)
        return True

    return False


# ===== CTX HELPERS =====
def _get_user(ctx):
    return ctx.user if isinstance(ctx, discord.Interaction) else ctx.author


def _get_channel(ctx):
    return ctx.channel


def _get_message(ctx):
    return getattr(ctx, "message", None)


# ===== RESOLVE =====
def _resolve_replied_user(ctx):
    msg = _get_message(ctx)
    if not msg:
        return None

    ref = getattr(msg, "reference", None)
    if not ref:
        return None

    resolved = getattr(ref, "resolved", None)
    if resolved and hasattr(resolved, "author"):
        return resolved.author

    return None


def _resolve_mentioned_user(ctx):
    msg = _get_message(ctx)
    if not msg:
        return None

    mentions = getattr(msg, "mentions", None) or []
    for m in mentions:
        if getattr(m, "bot", False):
            continue
        return m

    return None


def resolve_target_from_ctx(ctx, explicit_target: Optional[Any] = None):
    if explicit_target is not None:
        return explicit_target

    replied = _resolve_replied_user(ctx)
    if replied is not None:
        return replied

    mentioned = _resolve_mentioned_user(ctx)
    if mentioned is not None:
        return mentioned

    return None


# ===== SEND SAFE (FIX CHÍNH) =====
async def _send(
    ctx: Union[commands.Context, discord.Interaction],
    content=None,
    embed=None,
    ephemeral: bool = False,
):
    try:
        if isinstance(ctx, discord.Interaction):
            try:
                if not ctx.response.is_done():
                    await ctx.response.send_message(
                        content=content,
                        embed=embed,
                        ephemeral=ephemeral,
                    )
                    return await ctx.original_response()
                else:
                    return await ctx.followup.send(
                        content=content,
                        embed=embed,
                        ephemeral=ephemeral,
                    )
            except discord.InteractionResponded:
                return await ctx.followup.send(
                    content=content,
                    embed=embed,
                    ephemeral=ephemeral,
                )

        return await ctx.send(content=content, embed=embed)

    except Exception as e:
        print("[COUPLE SEND ERROR]", e)
        return None


# ===== EMBEDS =====
def build_couple_request_embed(user, target) -> discord.Embed:
    embed = discord.Embed(
        title="💖 Lời tỏ tình",
        description=(
            f"{user.mention} muốn trở thành một cặp với {target.mention}.\n\n"
            f"Nhắn `yes` để đồng ý.\n"
            f"Nhắn `no` để từ chối."
        ),
        color=discord.Color.from_rgb(255, 182, 193),
    )
    embed.set_footer(text="Một quyết định nhỏ, nhưng có thể đổi cả câu chuyện ❤️")
    return embed


def build_release_request_embed(user, partner_id: str) -> discord.Embed:
    embed = discord.Embed(
        title="💔 Yêu cầu chia tay",
        description=(
            f"{user.mention} muốn kết thúc mối quan hệ với <@{partner_id}>.\n\n"
            f"Nhắn `yes` để chia tay ngay.\n"
            f"Nhắn `no` để giữ mối quan hệ thêm 7 ngày.\n"
            f"Nếu không phản hồi, yêu cầu vẫn được lưu và hệ thống sẽ tự động chia tay sau 7 ngày."
        ),
        color=discord.Color.dark_gray(),
    )
    embed.set_footer(text="Tình yêu đôi khi cần một khoảng lặng.")
    return embed


def build_cancel_embed(user, partner_id: str) -> discord.Embed:
    embed = discord.Embed(
        title="💖 Hủy yêu cầu chia tay",
        description=(
            f"{user.mention} đã suy nghĩ lại và muốn tiếp tục với <@{partner_id}>.\n"
            f"Mối quan hệ đã được khôi phục như cũ."
        ),
        color=discord.Color.gold(),
    )
    embed.set_footer(text="Vẫn còn cơ hội để giữ nhau lại ❤️")
    return embed


def build_info_embed(owner, info: Dict[str, Any]) -> discord.Embed:
    partner = info.get("partner")
    since = info.get("since", "Unknown")
    points = int(info.get("points", 0))
    level = get_couple_level(points)
    pending = bool(info.get("pending_break"))
    break_initiator = info.get("break_initiator")
    break_time = info.get("break_time")

    if pending:
        status = (
            "⏳ Đang chờ chia tay\n"
            f"⌛ Còn lại: {format_remaining_time(break_time)}"
        )
        if break_initiator:
            status += f"\n👤 Người yêu cầu: <@{break_initiator}>"
    else:
        status = "💖 Đang yêu"

    embed = discord.Embed(
        title="💖 Thông tin cặp đôi",
        color=discord.Color.purple(),
    )

    embed.description = (
        f"💑 Chủ sở hữu: {owner.mention}\n"
        f"💞 Người yêu: <@{partner}>\n"
        f"📅 Kết đôi từ: `{since}`\n\n"
        f"⭐ Điểm: `{points}`\n"
        f"🏆 Level: `{level}`\n\n"
        f"📌 Trạng thái:\n{status}"
    )
    embed.set_footer(text="Tình yêu được lưu lại ❤️")
    return embed


def build_gift_embed(user, partner_id: str, name: str, points: int) -> discord.Embed:
    embed = discord.Embed(
        title="🎁 Tặng quà thành công",
        description=(
            f"{user.mention} đã tặng **{name}** cho <@{partner_id}>.\n"
            f"💞 Cộng thêm `{points}` điểm tình cảm cho cả hai."
        ),
        color=discord.Color.pink(),
    )
    embed.set_footer(text="Yêu thương được vun đắp từng chút một ❤️")
    return embed


# ===== LOGIC =====
async def couple_logic(bot, ctx, target: Optional[Any] = None):
    data = load_json(COUPLE_FILE)
    send = _send

    user = _get_user(ctx)
    channel = _get_channel(ctx)

    target = resolve_target_from_ctx(ctx, target)

    if target is None:
        return await send(
            ctx,
            "❌ Hãy mention hoặc reply người bạn muốn tỏ tình.",
            ephemeral=True if hasattr(ctx, "response") else False,
        )

    u1 = str(user.id)
    u2 = str(target.id)

    if u1 == u2:
        return await send(
            ctx,
            "❌ Bạn không thể tỏ tình với chính mình đâu nha.",
            ephemeral=True if hasattr(ctx, "response") else False,
        )

    if u1 in data:
        return await send(
            ctx,
            "❌ Bạn đã có người yêu rồi.",
            ephemeral=True if hasattr(ctx, "response") else False,
        )

    if u2 in data:
        return await send(
            ctx,
            "❌ Người này đã có đôi có cặp rồi.",
            ephemeral=True if hasattr(ctx, "response") else False,
        )

    await send(ctx, target.mention, embed=build_couple_request_embed(user, target))

    def check(m):
        return m.author.id == target.id and m.channel == channel

    try:
        while True:
            msg = await bot.wait_for("message", timeout=60, check=check)
            content = msg.content.lower().strip()

            if content == "yes":
                create_couple(data, user.id, target.id)
                save_json(COUPLE_FILE, data)

                embed = discord.Embed(
                    title="💖 Couple thành công",
                    description=f"{user.mention} và {target.mention} đã chính thức trở thành một cặp đôi.",
                    color=discord.Color.from_rgb(255, 105, 180),
                )
                embed.set_footer(text="Chúc hai bạn luôn vui vẻ và bền lâu ❤️")
                return await send(ctx, embed=embed)

            if content == "no":
                embed = discord.Embed(
                    title="💔 Bị từ chối",
                    description=f"{target.mention} đã từ chối lời tỏ tình của {user.mention}.",
                    color=discord.Color.red(),
                )
                embed.set_footer(text="Không sao, vẫn còn nhiều cơ hội khác.")
                return await send(ctx, embed=embed)

            await send(ctx, f"❌ {target.mention} chỉ cần nhắn `yes` hoặc `no`.")

    except asyncio.TimeoutError:
        embed = discord.Embed(
            title="⌛ Hết thời gian",
            description=f"{target.mention} đã không phản hồi kịp lời tỏ tình của {user.mention}.",
            color=discord.Color.orange(),
        )
        embed.set_footer(text="Đôi khi chờ đợi cũng là một phần của câu chuyện.")
        return await send(ctx, embed=embed)


async def couple_release_logic(bot, ctx):
    data = load_json(COUPLE_FILE)
    send = _send

    user = _get_user(ctx)
    channel = _get_channel(ctx)
    u1 = str(user.id)

    if u1 not in data:
        return await send(ctx, "❌ Bạn chưa có người yêu.")

    # Auto break realtime trước
    if check_auto_break(data, u1):
        save_json(COUPLE_FILE, data)
        return await send(ctx, "💔 Mối quan hệ này đã tự động kết thúc.")

    if data[u1].get("pending_break"):
        return await send(ctx, "❌ Bạn đang ở trong trạng thái chờ chia tay rồi.")

    u2 = data[u1].get("partner")
    if not u2 or u2 not in data:
        remove_couple(data, u1, u2 or "")
        save_json(COUPLE_FILE, data)
        return await send(ctx, "❌ Dữ liệu couple bị lỗi và đã được dọn lại.")

    await send(ctx, f"<@{u2}>", embed=build_release_request_embed(user, u2))

    def check(m):
        return m.author.id == int(u2) and m.channel == channel

    try:
        while True:
            msg = await bot.wait_for("message", timeout=60, check=check)
            content = msg.content.lower().strip()

            if content == "yes":
                remove_couple(data, u1, u2)
                save_json(COUPLE_FILE, data)

                embed = discord.Embed(
                    title="💔 Đã chia tay",
                    description=f"{user.mention} và <@{u2}> đã chính thức chia tay.",
                    color=discord.Color.dark_red(),
                )
                embed.set_footer(text="Mỗi hành trình đều có một đoạn kết.")
                return await send(ctx, embed=embed)

            if content == "no":
                now = iso_now_vn()

                for uid in (u1, u2):
                    data[uid]["pending_break"] = True
                    data[uid]["break_time"] = now
                    data[uid]["break_initiator"] = u1

                save_json(COUPLE_FILE, data)

                embed = discord.Embed(
                    title="💖 Tạm hoãn chia tay",
                    description=(
                        f"<@{u2}> không đồng ý chia tay ngay.\n"
                        f"Yêu cầu đã được lưu, sau **7 ngày** hệ thống sẽ tự động chia tay nếu không được hủy."
                    ),
                    color=discord.Color.blurple(),
                )
                embed.set_footer(text="Còn 7 ngày để suy nghĩ lại.")
                return await send(ctx, embed=embed)

            await send(ctx, f"❌ <@{u2}> chỉ cần nhắn `yes` hoặc `no`.")

    except asyncio.TimeoutError:
        now = iso_now_vn()

        for uid in (u1, u2):
            data[uid]["pending_break"] = True
            data[uid]["break_time"] = now
            data[uid]["break_initiator"] = u1

        save_json(COUPLE_FILE, data)

        embed = discord.Embed(
            title="⌛ Hết thời gian phản hồi",
            description=(
                f"<@{u2}> đã không trả lời kịp.\n"
                f"Yêu cầu chia tay đã được lưu và sẽ tự động xử lý sau **7 ngày**."
            ),
            color=discord.Color.orange(),
        )
        embed.set_footer(text="Thời gian sẽ trả lời thay cho lời nói.")
        return await send(ctx, embed=embed)


async def couple_cancel_logic(ctx):
    data = load_json(COUPLE_FILE)
    send = _send

    user = _get_user(ctx)
    u1 = str(user.id)

    if u1 not in data or not data[u1].get("pending_break"):
        return await send(ctx, "❌ Bạn chưa ở trạng thái chờ chia tay.")

    if data[u1].get("break_initiator") != u1:
        return await send(ctx, "❌ Bạn không phải người khởi tạo yêu cầu chia tay nên không thể hủy.")

    u2 = data[u1].get("partner")
    if not u2 or u2 not in data:
        remove_couple(data, u1, u2 or "")
        save_json(COUPLE_FILE, data)
        return await send(ctx, "❌ Dữ liệu couple bị lỗi và đã được dọn lại.")

    for uid in (u1, u2):
        data[uid]["pending_break"] = False
        data[uid]["break_time"] = None
        data[uid]["break_initiator"] = None

    save_json(COUPLE_FILE, data)
    return await send(ctx, embed=build_cancel_embed(user, u2))


async def couple_info_logic(ctx, target: Optional[Any] = None):
    data = load_json(COUPLE_FILE)
    send = _send

    viewer = _get_user(ctx)
    target = resolve_target_from_ctx(ctx, target)

    if target is None:
        target = viewer

    uid = str(target.id)

    if uid not in data:
        if uid == str(viewer.id):
            return await send(ctx, "❌ Bạn chưa có người yêu.")
        return await send(ctx, "❌ Người này chưa có người yêu.")

    # Auto break realtime trước khi hiển thị
    if check_auto_break(data, uid):
        save_json(COUPLE_FILE, data)
        return await send(ctx, "💔 Cặp đôi này đã tự động chia tay.")

    info = data[uid]
    partner = info.get("partner")

    if not partner or partner not in data:
        remove_couple(data, uid, partner or "")
        save_json(COUPLE_FILE, data)
        return await send(ctx, "❌ Dữ liệu couple bị lỗi và đã được dọn lại.")

    return await send(ctx, embed=build_info_embed(target, info))


async def couple_gift_logic(ctx, item: str):
    couple_data = load_json(COUPLE_FILE)
    send = _send

    user = _get_user(ctx)
    u1 = str(user.id)

    if u1 not in couple_data:
        return await send(ctx, "❌ Bạn chưa có người yêu.")

    # Auto break realtime trước
    if check_auto_break(couple_data, u1):
        save_json(COUPLE_FILE, couple_data)
        return await send(ctx, "💔 Hai bạn đã tự động chia tay.")

    if couple_data[u1].get("pending_break"):
        return await send(ctx, "❌ Hai bạn đang trong trạng thái chờ chia tay, chưa thể tặng quà.")

    u2 = couple_data[u1].get("partner")
    if not u2 or u2 not in couple_data:
        remove_couple(couple_data, u1, u2 or "")
        save_json(COUPLE_FILE, couple_data)
        return await send(ctx, "❌ Dữ liệu couple bị lỗi và đã được dọn lại.")

    item = str(item).lower().strip()

    if item == "rose":
        price, points, name = 1000, 5, "🌹 Hoa hồng"
    elif item == "cake":
        price, points, name = 2000, 10, "🎂 Bánh kem"
    else:
        return await send(ctx, "❌ Item không hợp lệ. Chỉ có `rose` hoặc `cake`.")

    # ===== ✅ FIX: DÙNG data_user =====
    # trừ gold an toàn (atomic hơn)
    success = await data_user.remove_gold(u1, price)

    if not success:
        return await send(ctx, f"❌ Bạn không đủ gold để mua {name}.")

    # ===== couple points vẫn giữ nguyên =====
    couple_data[u1]["points"] = int(couple_data[u1].get("points", 0)) + points
    couple_data[u2]["points"] = int(couple_data.get(u2, {}).get("points", 0)) + points

    save_json(COUPLE_FILE, couple_data)

    return await send(ctx, embed=build_gift_embed(user, u2, name, points))
# ===== AUTO BREAK BACKUP =====
async def start_couple_loop(bot):
    if getattr(bot, "_couple_loop_started", False):
        return
    bot._couple_loop_started = True

    async def auto_break():
        await bot.wait_until_ready()

        while not bot.is_closed():
            try:
                data = load_json(COUPLE_FILE)
                changed = False
                processed = set()

                for u1, info in list(data.items()):
                    if u1 in processed:
                        continue

                    if not info.get("pending_break"):
                        continue

                    u2 = info.get("partner")
                    if not u2:
                        continue

                    bt_time = parse_iso_dt(info.get("break_time"))
                    if not bt_time:
                        continue

                    if now_vn() - bt_time >= timedelta(days=7):
                        remove_couple(data, u1, u2)
                        processed.add(u1)
                        processed.add(str(u2))
                        changed = True

                        try:
                            user1 = bot.get_user(int(u1))
                            user2 = bot.get_user(int(u2))

                            if user1:
                                await user1.send("💔 Mối quan hệ đã tự động kết thúc sau 7 ngày chờ chia tay.")
                            if user2:
                                await user2.send("💔 Mối quan hệ đã tự động kết thúc sau 7 ngày chờ chia tay.")
                        except Exception:
                            pass

                if changed:
                    save_json(COUPLE_FILE, data)

            except Exception as e:
                print("[COUPLE AUTO ERROR]", e)

            await asyncio.sleep(60)

    bot.loop.create_task(auto_break())


print("Loaded couple has success")