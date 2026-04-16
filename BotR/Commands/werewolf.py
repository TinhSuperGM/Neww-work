import discord
from discord.ext import commands
from discord.ui import View, Button, Modal, TextInput
import asyncio
import random
import json
import os
from collections import Counter

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_FILE = os.path.join(BASE_DIR, "Data", "werewolf.json")

GAME = {}  # 1 game / channel


# ===== JSON =====
def load_data():
    if not os.path.exists(DATA_FILE):
        return {}
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)


# ===== SESSION =====
class WerewolfSession:
    def __init__(self, bot, channel):
        self.bot = bot
        self.channel = channel
        self.players = {}  # uid -> {name, role, alive}
        self.phase = "lobby"
        self.day = 0

        self.day_votes = {}
        self.night_votes = {}
        self.wolf_chat = []

        self.wolf_panel_messages = {}

    def add_player(self, user):
        uid = str(user.id)
        if uid not in self.players:
            self.players[uid] = {
                "name": user.display_name,
                "role": None,
                "alive": True,
            }

    def alive_players(self):
        return [uid for uid, p in self.players.items() if p["alive"]]

    def alive_wolves(self):
        return [uid for uid, p in self.players.items() if p["alive"] and p["role"] == "wolf"]

    def alive_villagers(self):
        return [uid for uid, p in self.players.items() if p["alive"] and p["role"] != "wolf"]

    def get_player(self, uid):
        return self.players.get(str(uid))

    def assign_roles(self):
        ids = list(self.players.keys())
        random.shuffle(ids)

        wolf_count = max(1, int(len(ids) * 0.25))

        wolves = set(ids[:wolf_count])

        for uid in ids:
            self.players[uid]["role"] = "wolf" if uid in wolves else "villager"

    async def reveal_roles(self):
        for uid, p in self.players.items():
            try:
                user = self.bot.get_user(int(uid)) or await self.bot.fetch_user(int(uid))
                await user.send(f"🐺 Bạn là **{p['role']}**")
            except:
                pass

    async def start(self):
        self.assign_roles()
        await self.reveal_roles()

        self.phase = "day"
        self.day = 1

        await self.loop()

    async def loop(self):
        while True:
            if self.check_win():
                break

            await self.day_phase()
            if self.check_win():
                break

            await self.night_phase()

    def check_win(self):
        wolves = len(self.alive_wolves())
        villagers = len(self.alive_villagers())

        if wolves == 0:
            asyncio.create_task(self.channel.send("🏆 Dân thắng!"))
            return True
        if wolves >= villagers:
            asyncio.create_task(self.channel.send("🐺 Sói thắng!"))
            return True
        return False

    async def day_phase(self):
        self.phase = "day"
        self.day_votes = {}

        await self.channel.set_permissions(self.channel.guild.default_role, send_messages=True)

        embed = discord.Embed(
            title=f"🌞 Ngày {self.day}",
            description="Thảo luận 60s, sau đó vote 30s",
            color=discord.Color.gold()
        )
        msg = await self.channel.send(embed=embed, view=VoteView(self))

        await asyncio.sleep(60)

        await msg.edit(content="🗳️ Bắt đầu vote!", view=VoteView(self))

        await asyncio.sleep(30)

        await self.resolve_day()

        self.day += 1

    async def resolve_day(self):
        if not self.day_votes:
            await self.channel.send("❌ Không ai bị vote.")
            return

        count = Counter(self.day_votes.values())
        top = max(count.values())
        targets = [u for u, c in count.items() if c == top]

        if len(targets) > 1:
            await self.channel.send("⚖️ Hòa phiếu, không ai chết.")
            return

        uid = targets[0]
        self.players[uid]["alive"] = False

        await self.channel.send(f"💀 {self.players[uid]['name']} bị treo cổ.")

    async def night_phase(self):
        self.phase = "night"
        self.night_votes = {}

        await self.channel.set_permissions(self.channel.guild.default_role, send_messages=False)

        await self.channel.send("🌙 Đêm xuống...")

        await self.send_wolf_panel()

        await asyncio.sleep(90)

        await self.resolve_night()

    async def resolve_night(self):
        if not self.night_votes:
            await self.channel.send("🌙 Không ai chết đêm nay.")
            return

        count = Counter(self.night_votes.values())
        top = max(count.values())
        targets = [u for u, c in count.items() if c == top]

        uid = random.choice(targets)
        self.players[uid]["alive"] = False

        await self.channel.send(f"☠️ {self.players[uid]['name']} bị giết trong đêm.")

    async def send_wolf_panel(self):
        for uid in self.alive_wolves():
            user = self.bot.get_user(int(uid))
            if not user:
                continue

            embed = self.render_wolf_panel()
            view = WolfView(self, uid)

            try:
                await user.send(embed=embed, view=view)
            except:
                pass

    def render_wolf_panel(self):
        text = "\n".join(self.wolf_chat[-10:]) or "Chưa có chat"
        return discord.Embed(
            title="🐺 Sói Chat",
            description=text,
            color=discord.Color.dark_red()
        )

    def add_chat(self, uid, msg):
        name = self.players[uid]["name"]
        self.wolf_chat.append(f"{name}: {msg}")


# ===== VOTE =====
class VoteView(View):
    def __init__(self, session):
        super().__init__(timeout=None)
        self.session = session

        for uid, p in session.players.items():
            if p["alive"]:
                self.add_item(VoteButton(session, uid, p["name"]))


class VoteButton(Button):
    def __init__(self, session, target_id, name):
        super().__init__(label=name, style=discord.ButtonStyle.primary)
        self.session = session
        self.target_id = target_id

    async def callback(self, interaction: discord.Interaction):
        uid = str(interaction.user.id)
        player = self.session.get_player(uid)

        if not player or not player["alive"]:
            return await interaction.response.send_message("❌ Bạn đã chết.", ephemeral=True)

        if self.session.phase == "day":
            self.session.day_votes[uid] = self.target_id
        else:
            if player["role"] != "wolf":
                return await interaction.response.send_message("❌ Không phải sói.", ephemeral=True)
            self.session.night_votes[uid] = self.target_id

        await interaction.response.send_message("✅ Đã vote.", ephemeral=True)


# ===== WOLF =====
class WolfView(View):
    def __init__(self, session, uid):
        super().__init__(timeout=None)
        self.session = session
        self.uid = uid

    @discord.ui.button(label="Chat", style=discord.ButtonStyle.secondary)
    async def chat(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_modal(WolfModal(self.session, self.uid))


class WolfModal(Modal):
    def __init__(self, session, uid):
        super().__init__(title="Chat sói")
        self.session = session
        self.uid = uid

        self.text = TextInput(label="Nhập nội dung")
        self.add_item(self.text)

    async def on_submit(self, interaction: discord.Interaction):
        self.session.add_chat(self.uid, self.text.value)
        await interaction.response.send_message("✅ Đã gửi", ephemeral=True)


# ===== COMMAND =====
async def werewolf_logic(ctx, channel_id: int):
    channel = ctx.guild.get_channel(channel_id)
    if not channel:
        return await ctx.send("❌ Không tìm thấy channel.")

    session = WerewolfSession(ctx.bot, channel)
    GAME[channel_id] = session

    embed = discord.Embed(title="🐺 Werewolf", description="Nhấn join!", color=discord.Color.blurple())
    view = JoinView(session)

    await ctx.send(embed=embed, view=view)


class JoinView(View):
    def __init__(self, session):
        super().__init__(timeout=60)
        self.session = session

    @discord.ui.button(label="Join", style=discord.ButtonStyle.success)
    async def join(self, interaction: discord.Interaction, button: Button):
        self.session.add_player(interaction.user)
        await interaction.response.send_message("✅ Đã tham gia", ephemeral=True)

    @discord.ui.button(label="Start", style=discord.ButtonStyle.danger)
    async def start(self, interaction: discord.Interaction, button: Button):
        if len(self.session.players) < 5:
            return await interaction.response.send_message("❌ Cần ít nhất 5 người.", ephemeral=True)

        await interaction.response.send_message("🚀 Bắt đầu game!")
        await self.session.start()