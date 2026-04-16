import discord
from discord.ext import commands
from Data import data_user
import random
import time
import json
import os
import asyncio
from typing import Union, Optional

from Commands.prayer import get_luck

COOLDOWN = 64800  # 18 giờ

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "Data")
RECORD_FILE = os.path.join(DATA_DIR, "reaction_record.json")

RECORD_LOCK = asyncio.Lock()


# ===== FILE =====
def load_record():
    if not os.path.exists(RECORD_FILE):
        return []
    try:
        with open(RECORD_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, list) else []
    except Exception as e:
        print(f"[ERROR] load_record: {e}")
        return []


def save_record(records):
    os.makedirs(os.path.dirname(RECORD_FILE), exist_ok=True)
    temp_file = RECORD_FILE + ".tmp"
    with open(temp_file, "w", encoding="utf-8") as f:
        json.dump(records, f, indent=4, ensure_ascii=False)
    os.replace(temp_file, RECORD_FILE)


# ===== FORMAT =====
def format_time(seconds: int) -> str:
    seconds = max(0, int(seconds))
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    return f"{h}H {m}M {s}S"


def _avatar_url(user_obj) -> str:
    try:
        return user_obj.display_avatar.url
    except Exception:
        return ""


def _safe_name(user_obj) -> str:
    return getattr(user_obj, "display_name", None) or getattr(user_obj, "name", None) or "Unknown"


# ===== SEND (SAFE) =====
async def send_message(
    ctx: Union[commands.Context, discord.Interaction],
    *,
    content=None,
    embed=None,
    view=None
):
    try:
        kwargs = {
            "content": content,
            "embed": embed
        }

        # ✅ chỉ add view nếu hợp lệ
        if view is not None:
            kwargs["view"] = view

        if isinstance(ctx, discord.Interaction):
            if not ctx.response.is_done():
                await ctx.response.send_message(**kwargs)
                try:
                    return await ctx.original_response()
                except Exception:
                    return None

            return await ctx.followup.send(**kwargs)

        return await ctx.send(**kwargs)

    except Exception as e:
        print("[SEND ERROR]", e)
        return None
def get_user(ctx):
    return ctx.user if isinstance(ctx, discord.Interaction) else ctx.author


# ===== ROLL =====
def roll_gold(luck: float) -> int:
    tiers = [
        (10, 100, 0.40),
        (100, 300, 0.30),
        (300, 600, 0.20),
        (600, 900, 0.08),
        (900, 1200, 0.02),
    ]

    shift_percent = max(0, (luck - 1) / 25)
    rates = [t[2] for t in tiers]

    for i in range(len(rates) - 1):
        shift = rates[i] * shift_percent
        rates[i] -= shift
        rates[i + 1] += shift

    r = random.random()
    current = 0.0

    for (low, high, _), rate in zip(tiers, rates):
        current += rate
        if r <= current:
            return random.randint(low, high)

    return random.randint(tiers[-1][0], tiers[-1][1])


# ===== EMBEDS =====
def build_daily_reward_embed(user_obj, total_reward: int, reward: int, streak_bonus: int, streak: int, luck: float, next_time: int) -> discord.Embed:
    embed = discord.Embed(
        title="<a:AstraNova_bag_money:1494196298360819832> Điểm danh thành công",
        description=(
            f"Chúc mừng **{_safe_name(user_obj)}** đã nhận thưởng hàng ngày.\n"
            f"Bạn vừa nhận được **{total_reward:,} <a:AstraNova_gold:1492792339436142703>**."
        ),
        color=discord.Color.gold(),
    )
    try:
        embed.set_author(name=f"{_safe_name(user_obj)}", icon_url=_avatar_url(user_obj))
    except Exception:
        pass

    try:
        if _avatar_url(user_obj):
            embed.set_thumbnail(url=_avatar_url(user_obj))
    except Exception:
        pass

    embed.add_field(
        name="<a:AstraNova_Gift_Box:1494197009584885831> Phần thưởng gốc",
        value=f"**{reward:,} <a:AstraNova_gold:1492792339436142703>**",
        inline=True
    )
    embed.add_field(
        name="<a:flame:1494195561656746014> Streak bonus",
        value=f"**+{streak_bonus:,} <a:AstraNova_gold:1492792339436142703>**\nChuỗi: **{streak} ngày**",
        inline=True
    )
    embed.add_field(
        name="<a:AstraNova_Hourglass:1494197546518708365> Điểm danh lần tới",
        value=f"<t:{next_time}:R>\n<t:{next_time}:F>",
        inline=False
    )
    embed.set_footer(text="Quay lại mỗi ngày để giữ streak và tăng thưởng nhé!")
    return embed


def build_event_prepare_embed(user_obj, preview_reward: int) -> discord.Embed:
    embed = discord.Embed(
        title="<a:AstraNova_Turn:1494199642420940962> EVENT ĐẶC BIỆT!",
        description=(
            f"**{_safe_name(user_obj)}** vừa kích hoạt event phản xạ.\n"
            f"Phần thưởng nền: **{preview_reward:,} <a:AstraNova_gold:1492792339436142703>**\n\n"
            f"<a:AstraNova_Lighting:1494199271053066331> Hãy chờ tín hiệu và click càng chuẩn càng tốt."
        ),
        color=discord.Color.blurple(),
    )
    try:
        embed.set_author(name=f"{_safe_name(user_obj)}", icon_url=_avatar_url(user_obj))
    except Exception:
        pass

    try:
        if _avatar_url(user_obj):
            embed.set_thumbnail(url=_avatar_url(user_obj))
    except Exception:
        pass

    embed.add_field(
        name="📌 Luật event",
        value=(
            "• Click càng nhanh càng có thưởng cao\n"
            "• Quá nhanh có thể bị xem là macro\n"
            "• Có combo và jackpot"
        ),
        inline=False
    )
    embed.set_footer(text="Bạn chỉ có một cơ hội. Chuẩn bị thật nhanh.")
    return embed


def build_event_clicking_embed(user_obj) -> discord.Embed:
    embed = discord.Embed(
        title="⚡ CLICK NGAY!",
        description=(
            f"**{_safe_name(user_obj)}** hãy click vào nút bên dưới ngay bây giờ.\n"
            f"Phần thưởng sẽ thay đổi theo tốc độ phản xạ."
        ),
        color=discord.Color.orange(),
    )
    try:
        embed.set_author(name=f"{_safe_name(user_obj)}", icon_url=_avatar_url(user_obj))
    except Exception:
        pass

    try:
        if _avatar_url(user_obj):
            embed.set_thumbnail(url=_avatar_url(user_obj))
    except Exception:
        pass

    embed.add_field(
        name="🏁 Mục tiêu",
        value="Phản xạ chuẩn, không quá sớm, không quá chậm.",
        inline=False
    )
    embed.set_footer(text="Bấm ngay khi nhìn thấy nút để tối ưu phần thưởng.")
    return embed


def build_event_result_embed(user_obj, reaction_time: float, multiplier: float, note: str, reward: int, combo: int, combo_bonus: int, is_new: bool, is_cheat: bool) -> discord.Embed:
    if is_cheat:
        color = discord.Color.red()
        title = "🚫 Macro detected"
    elif reaction_time <= 0.7:
        color = discord.Color.gold()
        title = "⚡ GODLIKE!"
    elif reaction_time <= 1:
        color = discord.Color.green()
        title = "💎 PERFECT!"
    elif reaction_time <= 1.7:
        color = discord.Color.blurple()
        title = "🔥 Nhanh!"
    else:
        color = discord.Color.dark_teal()
        title = "🐢 Chậm"

    embed = discord.Embed(
        title=title,
        description=note,
        color=color
    )
    try:
        embed.set_author(name=f"{_safe_name(user_obj)}", icon_url=_avatar_url(user_obj))
    except Exception:
        pass

    try:
        if _avatar_url(user_obj):
            embed.set_thumbnail(url=_avatar_url(user_obj))
    except Exception:
        pass

    embed.add_field(
        name="⏱️ Thời gian phản xạ",
        value=f"**{reaction_time:.3f}s**",
        inline=True
    )
    embed.add_field(
        name="🔥 Hệ số",
        value=f"**x{multiplier}**",
        inline=True
    )
    embed.add_field(
        name="💰 Phần thưởng",
        value=f"**+{reward:,} <a:gold:1492792339436142703>**",
        inline=True
    )
    embed.add_field(
        name="📈 Combo",
        value=f"**{combo}**\nBonus: **+{combo_bonus:,} <a:gold:1492792339436142703>**",
        inline=True
    )
    embed.add_field(
        name="🏅 Kỷ lục",
        value="Có" if is_new else "Không",
        inline=True
    )
    embed.add_field(
        name="🧠 Đánh giá",
        value=note,
        inline=False
    )
    embed.set_footer(text="Event phản xạ kết thúc.")
    return embed


# ===== VIEW =====
class ClickEventView(discord.ui.View):
    def __init__(self, user_id: str, base_reward: int):
        super().__init__(timeout=5)
        self.user_id = user_id
        self.base_reward = base_reward
        self.start_time: Optional[float] = None
        self.clicked = False
        self.message: Optional[discord.Message] = None

    @discord.ui.button(label="⚡ CLICK NGAY!", style=discord.ButtonStyle.success)
    async def click(self, interaction: discord.Interaction, button: discord.ui.Button):
        if str(interaction.user.id) != self.user_id:
            return await interaction.response.send_message("❌ Không phải event của bạn!", ephemeral=True)

        if self.clicked:
            return await interaction.response.send_message("⚠️ Bạn đã click rồi!", ephemeral=True)

        self.clicked = True
        button.disabled = True
        await interaction.response.edit_message(view=self)

        reaction_time = time.perf_counter() - (self.start_time or time.perf_counter())

        if reaction_time < 0.5:
            multiplier = 0
            note = "🚫 Macro detected"
            reward = 0
            is_cheat = True
        else:
            is_cheat = False

            if reaction_time < 0.7:
                multiplier = 1
                note = "⚠️ Suspicious"
            elif reaction_time <= 1:
                multiplier = 6
                note = "⚡ GODLIKE!"
            elif reaction_time <= 1.3:
                multiplier = 4
                note = "💎 PERFECT!"
            elif reaction_time <= 1.7:
                multiplier = 2.5
                note = "🔥 Nhanh!"
            elif reaction_time <= 2.3:
                multiplier = 1.5
                note = "👍 Ổn"
            else:
                multiplier = 1
                note = "🐢 Chậm"

            reward = int(self.base_reward * multiplier + 0.5)

        combo = 0
        combo_bonus = 0
        is_new = False

        async with data_user.get_lock(self.user_id):
            user = data_user.get_user(self.user_id)

            combo = int(user.get("reaction_combo", 0))

            if not is_cheat:
                if reaction_time <= 0.6:
                    combo += 1
                elif reaction_time <= 1:
                    combo = max(0, combo - 1)
                else:
                    combo = 0
            else:
                combo = 0

            combo_bonus = min(combo * 50, 500)
            reward += combo_bonus

            if not is_cheat and reaction_time <= 0.35 and combo >= 3:
                reward += 200
                note += "\n🔥 PERFECT CHAIN!"

            if not is_cheat and reaction_time <= 0.25 and random.random() < 0.1:
                reward *= 3
                note += "\n💥 ULTRA JACKPOT x3"

            if not is_cheat:
                best = user.get("best_reaction")
                if not best or reaction_time < best:
                    user["best_reaction"] = reaction_time

            if not is_cheat:
                async with RECORD_LOCK:
                    records = load_record()

                    existing = next((r for r in records if r.get("user_id") == self.user_id), None)
                    if not existing or reaction_time < float(existing.get("time", 999999)):
                        records = [r for r in records if r.get("user_id") != self.user_id]
                        records.append({"user_id": self.user_id, "time": reaction_time})

                    records = sorted(records, key=lambda x: float(x.get("time", 999999)))[:5]
                    save_record(records)

                    is_new = bool(records) and records[0].get("user_id") == self.user_id and float(records[0].get("time", 0)) == reaction_time

                if is_new:
                    reward += 500

            user["reaction_combo"] = combo
            data_user.save_user(self.user_id, user)

        # FIX: cộng gold bên ngoài lock để tránh deadlock do add_gold() tự lock cùng user
        try:
            await data_user.add_gold(self.user_id, reward)
        except Exception as e:
            print(f"[daily.click] add_gold error: {e}")

        result_embed = build_event_result_embed(
            interaction.user,
            reaction_time,
            multiplier,
            note,
            reward,
            combo,
            combo_bonus,
            is_new,
            is_cheat
        )

        try:
            await interaction.message.edit(embed=result_embed)
        except Exception:
            try:
                await interaction.edit_original_response(embed=result_embed)
            except Exception:
                pass

    async def on_timeout(self):
        if not self.clicked and self.message:
            try:
                embed = discord.Embed(
                    title="⌛ EVENT KẾT THÚC",
                    description="Bạn đã bỏ lỡ event đặc biệt này (1% xuất hiện) 😢",
                    color=discord.Color.red()
                )
                embed.set_footer(text="Hẹn bạn ở lần sau.")
                await self.message.edit(embed=embed, view=None)
            except Exception:
                pass


# ===== MAIN =====
async def daily_logic(ctx):
    # FIX: defer sớm cho slash command để tránh timeout khi flow hơi lâu
    if isinstance(ctx, discord.Interaction) and not ctx.response.is_done():
        try:
            await ctx.response.defer(thinking=True)
        except Exception as e:
            print(f"[daily_logic] defer error: {e}")

    user_obj = get_user(ctx)
    user_id = str(user_obj.id)
    now = int(time.time())

    # Chỉ giữ lock cho phần đọc/ghi state, không gọi add_gold() bên trong lock
    async with data_user.get_lock(user_id):
        user = data_user.get_user(user_id)

        last = int(user.get("last_daily", 0))
        remaining = COOLDOWN - (now - last)

        if remaining > 0:
            next_time = now + remaining
            embed = discord.Embed(
                title="⏱️ Điểm danh chưa sẵn sàng",
                description=(
                    f"Ô **{_safe_name(user_obj)}** à, bạn cần chờ thêm **{format_time(remaining)}** nữa trước khi điểm danh lại."
                ),
                color=discord.Color.orange()
            )
            try:
                embed.set_author(name=f"{_safe_name(user_obj)}", icon_url=_avatar_url(user_obj))
            except Exception:
                pass
            embed.add_field(
                name="⏳ Có thể nhận lại vào",
                value=f"<t:{next_time}:R>\n<t:{next_time}:F>",
                inline=False
            )
            embed.set_footer(text="Quay lại sau khi cooldown kết thúc.")
            return await send_message(ctx, embed=embed)

        streak = int(user.get("daily_streak", 0))
        if now - last > COOLDOWN * 2:
            streak = 0

        streak += 1
        streak_bonus = min(streak * 20, 500)

        luck = float(get_luck(user_obj.id))
        reward = roll_gold(luck)
        total_reward = reward + streak_bonus

        user["last_daily"] = now
        user["daily_streak"] = streak
        data_user.save_user(user_id, user)

    # FIX: add_gold ra ngoài lock để không tự chờ lock của chính nó
    try:
        await data_user.add_gold(user_id, total_reward)
    except Exception as e:
        print(f"[daily_logic] add_gold error: {e}")

    # ===== EVENT =====
    if random.random() < 0.1:
        preview_reward = max(200, total_reward // 2)
        preparing_embed = build_event_prepare_embed(user_obj, preview_reward)
        msg = await send_message(ctx, embed=preparing_embed)

        await asyncio.sleep(random.uniform(0.8, 2.5))

        view = ClickEventView(user_id, preview_reward)
        click_embed = build_event_clicking_embed(user_obj)
        try:
            msg = await msg.edit(embed=click_embed, view=view)
        except Exception:
            msg = await send_message(ctx, embed=click_embed, view=view)

        await asyncio.sleep(0.05)
        view.start_time = time.perf_counter()
        view.message = msg
        return

    success_embed = build_daily_reward_embed(
        user_obj=user_obj,
        total_reward=total_reward,
        reward=reward,
        streak_bonus=streak_bonus,
        streak=streak,
        luck=luck,
        next_time=now + COOLDOWN
    )
    await send_message(ctx, embed=success_embed)


print("Loaded daily has successs")