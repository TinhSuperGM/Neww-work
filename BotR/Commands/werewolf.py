from __future__ import annotations

import asyncio
import json
import os
import random
from collections import Counter
from typing import Optional

import discord
from discord.ui import Button, Modal, TextInput, View

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "Data")
DATA_FILE = os.path.join(DATA_DIR, "werewolf.json")

GAME: dict[int, "WerewolfSession"] = {}

DAY_DISCUSSION_SECONDS = 60
DAY_VOTE_SECONDS = 30
NIGHT_SECONDS = 90
MAX_CHAT_LINES = 10


def _ensure_data_file() -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    if not os.path.exists(DATA_FILE):
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump({}, f, indent=4, ensure_ascii=False)


def _parse_id(token: object | None) -> Optional[int]:
    if token is None:
        return None

    if isinstance(token, int):
        return token

    if hasattr(token, "id"):
        try:
            return int(getattr(token, "id"))
        except Exception:
            pass

    text = str(token).strip()
    if not text:
        return None

    if text.startswith("<#") and text.endswith(">"):
        text = text[2:-1]
    elif text.startswith("<@&") and text.endswith(">"):
        text = text[3:-1]
    elif text.startswith("<@") and text.endswith(">"):
        text = text[2:-1]
        if text.startswith("!"):
            text = text[1:]

    try:
        return int(text)
    except Exception:
        return None


def _role_name(role_key: str) -> str:
    return "🐺 Ma Sói" if role_key == "wolf" else "🧑 Dân làng"


class WerewolfSession:
    def __init__(self, bot: discord.Client, guild: discord.Guild, channel: discord.TextChannel, dead_role_id: Optional[int] = None):
        self.bot = bot
        self.guild = guild
        self.channel = channel
        self.dead_role_id = dead_role_id

        self.players: dict[str, dict] = {}
        self.phase: str = "lobby"
        self.day: int = 0

        self.day_votes: dict[str, str] = {}
        self.night_votes: dict[str, str] = {}

        self.wolf_chat: list[str] = []
        self.wolf_panels: dict[int, discord.Message] = {}
        self.day_panel: Optional[discord.Message] = None
        self.active: bool = True

        self._lock = asyncio.Lock()

    def add_player(self, user: discord.abc.User) -> bool:
        uid = str(user.id)
        if uid in self.players:
            return False

        display_name = getattr(user, "display_name", None) or getattr(user, "name", "Unknown")
        self.players[uid] = {
            "name": display_name,
            "role": None,
            "alive": True,
        }
        return True

    def get_player(self, uid: object) -> Optional[dict]:
        return self.players.get(str(uid))

    def alive_players(self) -> list[str]:
        return [uid for uid, data in self.players.items() if data.get("alive")]

    def alive_wolves(self) -> list[str]:
        return [uid for uid, data in self.players.items() if data.get("alive") and data.get("role") == "wolf"]

    def alive_villagers(self) -> list[str]:
        return [uid for uid, data in self.players.items() if data.get("alive") and data.get("role") != "wolf"]

    def assign_roles(self) -> None:
        ids = list(self.players.keys())
        random.shuffle(ids)

        wolf_count = max(1, len(ids) // 4)
        wolves = set(ids[:wolf_count])

        for uid in ids:
            self.players[uid]["role"] = "wolf" if uid in wolves else "villager"

    async def reveal_roles(self) -> None:
        for uid, data in self.players.items():
            try:
                user = self.bot.get_user(int(uid)) or await self.bot.fetch_user(int(uid))
                if not user:
                    continue
                role_text = _role_name(data["role"])
                await user.send(
                    f"🐺 Vai trò của bạn là: **{role_text}**\n"
                    f"Bạn đã được thêm vào ván chơi ở **#{self.channel.name}**."
                )
            except Exception:
                pass

    async def start(self) -> None:
        async with self._lock:
            if self.phase != "lobby":
                return

            self.assign_roles()
            await self.reveal_roles()

            self.phase = "day"
            self.day = 1

        await self.channel.send("🎮 Ván Ma Sói bắt đầu!")
        await self.run_loop()

    async def run_loop(self) -> None:
        while self.active:
            if self.check_win():
                break

            await self.day_phase()
            if self.check_win():
                break

            await self.night_phase()

        self.active = False
        GAME.pop(self.channel.id, None)

    def check_win(self) -> bool:
        wolves = len(self.alive_wolves())
        villagers = len(self.alive_villagers())

        if wolves == 0:
            asyncio.create_task(self.channel.send("🏆 Dân làng thắng!"))
            return True

        if wolves >= villagers and villagers > 0:
            asyncio.create_task(self.channel.send("🐺 Ma Sói thắng!"))
            return True

        if villagers == 0:
            asyncio.create_task(self.channel.send("🐺 Ma Sói thắng!"))
            return True

        return False

    async def set_dead_role(self, uid: str) -> None:
        if not self.dead_role_id:
            return

        role = self.guild.get_role(self.dead_role_id)
        if not role:
            return

        member = self.guild.get_member(int(uid))
        if member is None:
            try:
                member = await self.guild.fetch_member(int(uid))
            except Exception:
                member = None

        if member is None:
            return

        try:
            await member.add_roles(role, reason="Werewolf: player died")
        except Exception:
            pass

    async def kill_player(self, uid: str, reason: str) -> Optional[dict]:
        player = self.get_player(uid)
        if not player or not player.get("alive"):
            return None

        player["alive"] = False
        await self.set_dead_role(str(uid))
        await self.channel.send(f"💀 {player['name']} {reason}")
        return player

    async def day_phase(self) -> None:
        self.phase = "day"
        self.day_votes = {}

        await self.channel.set_permissions(self.guild.default_role, send_messages=True)

        embed = discord.Embed(
            title=f"🌞 Ngày {self.day}",
            description=(
                "Mọi người thảo luận rồi bấm nút vote.\n"
                "Ai nhiều phiếu nhất sẽ bị loại. Nếu bị hòa phiếu thì không ai chết."
            ),
            color=discord.Color.gold(),
        )

        view = DayVoteView(self)
        self.day_panel = await self.channel.send(embed=embed, view=view)

        await asyncio.sleep(DAY_DISCUSSION_SECONDS)

        try:
            await self.day_panel.edit(
                content="🗳️ Bắt đầu vote ban ngày!",
                embed=embed,
                view=DayVoteView(self),
            )
        except Exception:
            pass

        await asyncio.sleep(DAY_VOTE_SECONDS)
        await self.resolve_day()
        self.day += 1

    async def resolve_day(self) -> None:
        if not self.day_votes:
            await self.channel.send("❌ Không ai vote nên không ai chết.")
            return

        count = Counter(self.day_votes.values())
        top = max(count.values())
        targets = [uid for uid, votes in count.items() if votes == top]

        if len(targets) != 1:
            await self.channel.send("⚖️ Hòa phiếu nên không ai chết.")
            return

        await self.kill_player(targets[0], "bị treo cổ vào ban ngày.")

    async def night_phase(self) -> None:
        self.phase = "night"
        self.night_votes = {}

        await self.channel.set_permissions(self.guild.default_role, send_messages=False)
        await self.channel.send("🌙 Đêm xuống. Dân thường không được nói chuyện trong kênh.")

        await self.send_wolf_panels()

        await asyncio.sleep(NIGHT_SECONDS)
        await self.resolve_night()

    async def resolve_night(self) -> None:
        if not self.night_votes:
            await self.channel.send("🌙 Không ai chết trong đêm.")
            return

        count = Counter(self.night_votes.values())
        top = max(count.values())
        targets = [uid for uid, votes in count.items() if votes == top]
        victim = random.choice(targets)

        await self.kill_player(victim, "bị ma sói giết trong đêm.")

    async def send_wolf_panels(self) -> None:
        embed = self.render_wolf_panel()

        for uid in self.alive_wolves():
            try:
                user = self.bot.get_user(int(uid)) or await self.bot.fetch_user(int(uid))
                if not user:
                    continue

                msg = self.wolf_panels.get(int(uid))
                view = WolfControlView(self, uid)

                if msg:
                    await msg.edit(embed=embed, view=view)
                    continue

                sent = await user.send(embed=embed, view=view)
                self.wolf_panels[int(uid)] = sent
            except Exception:
                pass

    def render_wolf_panel(self) -> discord.Embed:
        lines = self.wolf_chat[-MAX_CHAT_LINES:]
        description = "\n".join(lines) if lines else "Chưa có tin nhắn nào."
        description += f"\n\n**Pha hiện tại:** {self.phase.title()}"
        return discord.Embed(
            title="🐺 Phòng chat ma sói",
            description=description,
            color=discord.Color.dark_red(),
        )

    async def refresh_wolf_panels(self) -> None:
        embed = self.render_wolf_panel()
        for uid, msg in list(self.wolf_panels.items()):
            try:
                data = self.players.get(str(uid), {})
                if data.get("alive") and data.get("role") == "wolf":
                    await msg.edit(embed=embed, view=WolfControlView(self, str(uid)))
                else:
                    await msg.edit(embed=embed, view=None)
            except Exception:
                pass

    def add_chat(self, uid: str, message: str) -> None:
        name = self.players[uid]["name"]
        self.wolf_chat.append(f"**{name}**: {message}")

    def is_alive_wolf(self, uid: str) -> bool:
        player = self.get_player(uid)
        return bool(player and player.get("alive") and player.get("role") == "wolf")


class JoinView(View):
    def __init__(self, session: WerewolfSession):
        super().__init__(timeout=None)
        self.session = session

    @discord.ui.button(label="Join", style=discord.ButtonStyle.success)
    async def join_button(self, interaction: discord.Interaction, button: Button):
        if self.session.phase != "lobby":
            return await interaction.response.send_message("❌ Ván chơi đã bắt đầu.", ephemeral=True)

        added = self.session.add_player(interaction.user)
        if not added:
            return await interaction.response.send_message("❌ Bạn đã tham gia rồi.", ephemeral=True)

        await interaction.response.send_message("✅ Đã tham gia ván Ma Sói.", ephemeral=True)

    @discord.ui.button(label="Start", style=discord.ButtonStyle.danger)
    async def start_button(self, interaction: discord.Interaction, button: Button):
        if self.session.phase != "lobby":
            return await interaction.response.send_message("❌ Ván chơi đã bắt đầu.", ephemeral=True)

        if len(self.session.players) < 5:
            return await interaction.response.send_message("❌ Cần ít nhất 5 người để bắt đầu.", ephemeral=True)

        await interaction.response.send_message("🚀 Bắt đầu game!", ephemeral=True)
        asyncio.create_task(self.session.start())


class DayVoteButton(Button):
    def __init__(self, session: WerewolfSession, target_id: str, target_name: str):
        super().__init__(label=target_name[:80], style=discord.ButtonStyle.primary)
        self.session = session
        self.target_id = target_id

    async def callback(self, interaction: discord.Interaction):
        uid = str(interaction.user.id)
        player = self.session.get_player(uid)

        if not player or not player.get("alive"):
            return await interaction.response.send_message("❌ Bạn đã chết.", ephemeral=True)

        if self.session.phase == "day":
            self.session.day_votes[uid] = self.target_id
            return await interaction.response.send_message(
                f"✅ Bạn đã vote cho **{self.session.players[self.target_id]['name']}**.",
                ephemeral=True,
            )

        if not self.session.is_alive_wolf(uid):
            return await interaction.response.send_message("❌ Ban đêm chỉ ma sói mới được vote.", ephemeral=True)

        self.session.night_votes[uid] = self.target_id
        await interaction.response.send_message(
            f"✅ Ma sói đã chọn **{self.session.players[self.target_id]['name']}**.",
            ephemeral=True,
        )


class DayVoteView(View):
    def __init__(self, session: WerewolfSession):
        super().__init__(timeout=None)
        self.session = session

        for uid in session.alive_players():
            data = session.players[uid]
            self.add_item(DayVoteButton(session, uid, data["name"]))


class WolfVoteButton(Button):
    def __init__(self, session: WerewolfSession, target_id: str, target_name: str):
        super().__init__(label=target_name[:80], style=discord.ButtonStyle.danger)
        self.session = session
        self.target_id = target_id

    async def callback(self, interaction: discord.Interaction):
        uid = str(interaction.user.id)

        if not self.session.is_alive_wolf(uid):
            return await interaction.response.send_message("❌ Chỉ ma sói mới dùng nút này.", ephemeral=True)

        if self.session.phase != "night":
            return await interaction.response.send_message("❌ Nút này chỉ dùng vào ban đêm.", ephemeral=True)

        self.session.night_votes[uid] = self.target_id
        await interaction.response.send_message(
            f"✅ Đã vote giết **{self.session.players[self.target_id]['name']}**.",
            ephemeral=True,
        )


class WolfVoteView(View):
    def __init__(self, session: WerewolfSession):
        super().__init__(timeout=120)
        self.session = session

        for uid in session.alive_players():
            data = session.players[uid]
            self.add_item(WolfVoteButton(session, uid, data["name"]))


class WolfChatModal(Modal):
    def __init__(self, session: WerewolfSession, wolf_uid: str):
        super().__init__(title="Nhắn cho bầy sói")
        self.session = session
        self.wolf_uid = wolf_uid
        self.message_input = TextInput(label="Tin nhắn", max_length=500)
        self.add_item(self.message_input)

    async def on_submit(self, interaction: discord.Interaction):
        if not self.session.is_alive_wolf(self.wolf_uid):
            return await interaction.response.send_message("❌ Bạn không còn là ma sói.", ephemeral=True)

        if self.session.phase != "night":
            return await interaction.response.send_message("❌ Chỉ chat được vào ban đêm.", ephemeral=True)

        self.session.add_chat(self.wolf_uid, self.message_input.value)
        await self.session.refresh_wolf_panels()
        await interaction.response.send_message("✅ Đã gửi tin nhắn cho bầy sói.", ephemeral=True)


class WolfControlView(View):
    def __init__(self, session: WerewolfSession, wolf_uid: str):
        super().__init__(timeout=120)
        self.session = session
        self.wolf_uid = str(wolf_uid)

    @discord.ui.button(label="Chat", style=discord.ButtonStyle.secondary)
    async def chat_button(self, interaction: discord.Interaction, button: Button):
        if not self.session.is_alive_wolf(self.wolf_uid):
            return await interaction.response.send_message("❌ Bạn không còn là ma sói.", ephemeral=True)

        if self.session.phase != "night":
            return await interaction.response.send_message("❌ Chỉ chat được vào ban đêm.", ephemeral=True)

        await interaction.response.send_modal(WolfChatModal(self.session, self.wolf_uid))

    @discord.ui.button(label="Vote", style=discord.ButtonStyle.danger)
    async def vote_button(self, interaction: discord.Interaction, button: Button):
        if not self.session.is_alive_wolf(self.wolf_uid):
            return await interaction.response.send_message("❌ Bạn không còn là ma sói.", ephemeral=True)

        if self.session.phase != "night":
            return await interaction.response.send_message("❌ Chỉ vote được vào ban đêm.", ephemeral=True)

        await interaction.response.send_message(
            "Chọn người muốn giết:",
            view=WolfVoteView(self.session),
            ephemeral=False,
        )


async def werewolf_logic(ctx, channel_id, dead_role=None):
    _ensure_data_file()

    channel_id_int = _parse_id(channel_id)
    dead_role_id = _parse_id(dead_role)

    if channel_id_int is None:
        return await ctx.send("❌ Không tìm thấy channel.")

    channel = ctx.guild.get_channel(channel_id_int)
    if channel is None:
        try:
            channel = await ctx.guild.fetch_channel(channel_id_int)
        except Exception:
            channel = None

    if channel is None or not isinstance(channel, discord.TextChannel):
        return await ctx.send("❌ Không tìm thấy channel.")

    if channel.id in GAME and GAME[channel.id].active:
        return await ctx.send("❌ Kênh này đang có ván Ma Sói chạy rồi.")

    session = WerewolfSession(ctx.bot, ctx.guild, channel, dead_role_id=dead_role_id)
    GAME[channel.id] = session

    embed = discord.Embed(
        title="🐺 Werewolf",
        description=(
            "Bấm **Join** để tham gia.\n"
            "Bấm **Start** khi đủ người.\n\n"
            "Mỗi người sẽ nhận DM báo vai trò của mình."
        ),
        color=discord.Color.blurple(),
    )

    await ctx.send(embed=embed, view=JoinView(session))
