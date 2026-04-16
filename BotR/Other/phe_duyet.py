import discord
from discord.ext import commands
import json
import os
import re
import asyncio


BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "Data")

from Data.data_admin import ADMINS

USER_FILE = os.path.join(DATA_DIR, "user.json")

WAIFU_FILE = os.path.join(DATA_DIR, "waifu_data.json")
CHANNELS_FILE = os.path.join(DATA_DIR, "phe_duyet_channels.json")

DEFAULT_SUBMISSION_CHANNEL_ID = 1490212883940774059
DEFAULT_APPROVAL_CHANNEL_ID = 1490214192203038801

save_lock = asyncio.Lock()


# ================= SAFE SEND =================

async def safe_send(target, **kwargs):
    for _ in range(3):
        try:
            return await target.send(**kwargs)
        except Exception as e:
            print(f"[SEND ERROR] {e}")
            await asyncio.sleep(1)
    return None


# ================= JSON =================

def load_json(path):
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"[JSON ERROR] {path}: {e}")
    return {}


def save_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)


# ================= UTILS =================

def parse_block(content):
    fields = {}
    for line in content.splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            fields[k.strip().lower()] = v.strip()
    return fields


def valid_id(x):
    return bool(re.fullmatch(r"[A-Za-z0-9_\-]+", x))


def valid_image(url):
    if not url.startswith("https://cdn.discordapp.com/"):
        return False

    clean_url = url.split("?")[0]
    return any(clean_url.lower().endswith(ext) for ext in (
        ".png", ".jpg", ".jpeg", ".webp", ".gif"
    ))


def is_admin(user_id):
    return str(user_id) in {str(x) for x in ADMINS}


def make_embed(title, desc, color=discord.Color.red()):
    return discord.Embed(title=title, description=desc, color=color)


# ================= CHANNEL =================

def get_guild_channels(guild_id):
    db = load_json(CHANNELS_FILE)
    cfg = db.get(str(guild_id), {})
    return (
        int(cfg.get("submission_channel_id", DEFAULT_SUBMISSION_CHANNEL_ID)),
        int(cfg.get("approval_channel_id", DEFAULT_APPROVAL_CHANNEL_ID))
    )


def set_guild_channels(guild_id, submission_channel_id, approval_channel_id):
    db = load_json(CHANNELS_FILE)
    db[str(guild_id)] = {
        "submission_channel_id": int(submission_channel_id),
        "approval_channel_id": int(approval_channel_id)
    }
    save_json(CHANNELS_FILE, db)


async def resolve_channel(bot, cid):
    ch = bot.get_channel(int(cid))
    if ch:
        return ch
    try:
        return await bot.fetch_channel(int(cid))
    except:
        return None


# ================= EMBED =================

def build_submission_embed(wid, name, bio, image):
    embed = discord.Embed(
        title="Waifu chờ duyệt",
        description=f"Id: {wid}\nname: {name}\nBio: {bio}",
        color=discord.Color.orange()
    )
    embed.set_image(url=image)
    embed.set_footer(text="Waifu của bạn đang được chờ để duyệt")
    return embed


def parse_embed_meta(embed):
    if embed is None:
        return None

    footer_text = getattr(embed.footer, "text", "") or ""
    if footer_text:
        try:
            data = json.loads(footer_text)
            if isinstance(data, dict):
                return data
        except:
            pass

    desc = embed.description or ""
    lines = desc.splitlines()
    data = {}

    for line in lines:
        lower = line.lower().strip()
        if lower.startswith("id:"):
            data["id"] = line.split(":", 1)[1].strip()
        elif lower.startswith("name:"):
            data["name"] = line.split(":", 1)[1].strip()
        elif lower.startswith("bio:"):
            data["bio"] = line.split(":", 1)[1].strip()

    if embed.image and embed.image.url:
        data["image"] = embed.image.url

    return data if data else None


# ================= MODAL =================

class RankModal(discord.ui.Modal, title="Nhập Rank Waifu"):
    rank = discord.ui.TextInput(label="Rank", placeholder="VD: thuong / S / SS")

    def __init__(self, cog, author_id, data, message_id, approval_channel_id):
        super().__init__()
        self.cog = cog
        self.author_id = author_id
        self.data = data
        self.message_id = message_id
        self.approval_channel_id = approval_channel_id

    async def on_submit(self, interaction: discord.Interaction):
        waifu_db = load_json(WAIFU_FILE)
        user_db = load_json(USER_FILE)

        wid = self.data["id"]
        name = self.data["name"]
        bio = self.data["bio"]
        image = self.data["image"]
        rank = str(self.rank.value).strip()

        if wid in waifu_db:
            return await interaction.response.send_message("❌ Waifu đã tồn tại!", ephemeral=True)

        waifu_db[wid] = {
            "name": name,
            "rank": rank,
            "quantity": -1,
            "claimed": 0,
            "Bio": bio,
            "image": image
        }

        async with save_lock:
            save_json(WAIFU_FILE, waifu_db)
            # Thêm gold vào user.json
            user_id = str(self.author_id)
            user = user_db.setdefault(user_id, {})
            user["gold"] = user.get("gold", 0) + 400
            save_json(USER_FILE, user_db)

        approval_ch = await resolve_channel(self.cog.bot, self.approval_channel_id)
        if approval_ch is None:
            approval_ch = interaction.channel

        if approval_ch is not None:
            embed = discord.Embed(
                title="Xét duyệt Waifu",
                description=(
                    "Chúc mừng, waifu của bạn đã được phê duyệt. "
                    "Sắp tới đây nó sẽ được thêm vào danh sách waifu của bot. "
                    "Số gold tương ứng của bạn sẽ được cộng vào sau, cố gắng đợi nhé."
                ),
                color=discord.Color.green()
            )
            embed.add_field(name="ID", value=wid, inline=True)
            embed.add_field(name="Tên", value=name, inline=True)
            embed.add_field(name="Rank", value=rank, inline=True)
            embed.add_field(name="Bio", value=bio, inline=False)
            embed.set_image(url=image)

            await safe_send(
                approval_ch,
                content=f"Chúc mừng <@{self.author_id}>. Waifu {name} của bạn đã được phê duyệt.",
                embed=embed
            )

        try:
            original_msg = await approval_ch.fetch_message(self.message_id)
            await original_msg.delete()
        except:
            pass

        await interaction.response.send_message("✅ Đã duyệt!", ephemeral=True)


# ================= VIEW =================

class ApproveView(discord.ui.View):
    def __init__(self, cog):
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(label="DUYỆT", style=discord.ButtonStyle.green, custom_id="approve_btn")
    async def approve(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_admin(interaction.user.id):
            return await interaction.response.send_message("❌ Bạn không có quyền!", ephemeral=True)

        if not interaction.message.embeds:
            return await interaction.response.send_message("❌ Không tìm thấy embed dữ liệu.", ephemeral=True)

        embed = interaction.message.embeds[0]
        meta = parse_embed_meta(embed)

        if not meta:
            return await interaction.response.send_message("❌ Lỗi dữ liệu embed", ephemeral=True)

        wid = meta.get("id")
        name = meta.get("name")
        bio = meta.get("bio")
        image = meta.get("image", "")

        match = re.search(r"<@!?(\d+)>", interaction.message.content or "")
        if not match:
            return await interaction.response.send_message("❌ Không tìm thấy user", ephemeral=True)

        author_id = int(match.group(1))

        guild = interaction.guild
        approval_channel_id = DEFAULT_APPROVAL_CHANNEL_ID
        if guild is not None:
            _, approval_channel_id = get_guild_channels(guild.id)

        data = {
            "id": wid,
            "name": name,
            "bio": bio,
            "image": image
        }

        await interaction.response.send_modal(
            RankModal(self.cog, author_id, data, interaction.message.id, approval_channel_id)
        )

    @discord.ui.button(label="TỪ CHỐI", style=discord.ButtonStyle.red, custom_id="reject_btn")
    async def reject(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_admin(interaction.user.id):
            return await interaction.response.send_message("❌ Bạn không có quyền!", ephemeral=True)

        try:
            await interaction.message.delete()
        except:
            pass

        await interaction.response.send_message("❌ Đã từ chối!", ephemeral=True)


# ================= COG =================

class PheDuyet(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        if not getattr(bot, "_approve_view_added", False):
            self.bot.add_view(ApproveView(self))
            self.bot._approve_view_added = True

    @commands.command(name="add")
    async def add_waifu(self, ctx, *, content=None):
        if ctx.guild is None:
            return await safe_send(ctx, content="❌ Chỉ dùng trong server")

        content = (content or "").strip()
        if not content:
            return await safe_send(ctx, content="❌ Sai cú pháp")

        parts = content.split()

        if parts and parts[0].lower() == "channels":
            if not is_admin(ctx.author.id):
                return await safe_send(ctx, content="❌ Bạn không có quyền!")

            if len(parts) < 3:
                return await safe_send(ctx, content="❌ Thiếu dữ liệu: .add channels <submission_id> <approval_id>")

            sub_id = parts[1]
            app_id = parts[2]

            if not sub_id.isdigit() or not app_id.isdigit():
                return await safe_send(ctx, content="❌ ID channel phải là số")

            sub_ch = await resolve_channel(self.bot, int(sub_id))
            app_ch = await resolve_channel(self.bot, int(app_id))

            if sub_ch is None or app_ch is None:
                return await safe_send(ctx, content="❌ Không tìm thấy một hoặc cả hai channel trong server này")

            set_guild_channels(ctx.guild.id, int(sub_id), int(app_id))

            return await safe_send(
                ctx,
                content=f"✅ Đã cấu hình xong.\nNhận message: <#{int(sub_id)}>\nPhê duyệt: <#{int(app_id)}>"
            )

        sub_id, app_id = get_guild_channels(ctx.guild.id)

        if ctx.channel.id != sub_id:
            return

        if content.lower() == "add":
            return await safe_send(ctx, content="❌ Sai cú pháp")

        waifu_db = load_json(WAIFU_FILE)
        data = parse_block(content)

        wid = data.get("id", "").replace(" ", "_")
        name = data.get("name")
        bio = data.get("bio")
        image = data.get("image")

        if not all([wid, name, bio, image]):
            return await safe_send(ctx, content="❌ Thiếu dữ liệu")

        if not valid_id(wid):
            return await safe_send(ctx, content="❌ Id không hợp lệ")

        if wid in waifu_db:
            return await safe_send(ctx, content="❌ Waifu đã tồn tại")

        if not (150 <= len(bio.strip()) <= 200):
            return await safe_send(ctx, content="❌ Bio phải 150-200 ký tự")

        if not valid_image(image):
            return await safe_send(ctx, content="❌ Link ảnh sai")

        ch = await resolve_channel(self.bot, app_id)
        if not ch:
            return await safe_send(ctx, content="❌ Không tìm thấy channel duyệt")

        embed = build_submission_embed(wid, name, bio, image)
        admin_mentions = " ".join(f"<@{uid}>" for uid in ADMINS)

        await safe_send(
            ch,
            content=f"{ctx.author.mention}\n🔔 WAIFU CHỜ DUYỆT\n{admin_mentions}",
            embed=embed,
            view=ApproveView(self)
        )

        await safe_send(ctx, content="📨 Đã gửi chờ duyệt!")


# ================= SETUP =================

async def setup(bot):
    await bot.add_cog(PheDuyet(bot))

print("Loaded phê duyệt has success")