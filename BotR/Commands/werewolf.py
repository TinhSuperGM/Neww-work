from __future__ import annotations

import asyncio
import json
import os
import random
from collections import Counter
from typing import Optional

import discord
from discord.ui import Button, Modal, Select, TextInput, View

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "Data")
DATA_FILE = os.path.join(DATA_DIR, "werewolf.json")

GAME: dict[int, "WerewolfSession"] = {}

DAY_DISCUSSION_SECONDS = 60
DAY_VOTE_SECONDS = 30
NIGHT_SECONDS = 90
MAX_CHAT_LINES = 10
MAX_SELECT_OPTIONS = 25
MAX_SELECT_ROWS = 5  # 25 options x 5 selects = 125 players max in one screen


async def send(ctx, *args, **kwargs):
    """
    Dùng chung cho prefix context và slash interaction.
    Trả về message nếu có thể.
    """
    if hasattr(ctx, "response"):
        if not ctx.response.is_done():
            await ctx.response.send_message(*args, **kwargs)
            try:
                return await ctx.original_response()
            except Exception:
                return None
        return await ctx.followup.send(*args, **kwargs)

    return await ctx.send(*args, **kwargs)


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


def _chunk(items: list[str], size: int) -> list[list[str]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def _bot_member(guild: discord.Guild, bot: discord.Client) -> Optional[discord.Member]:
    if bot.user is None:
        return None
    return guild.get_member(bot.user.id)


class WerewolfSession:
    def __init__(
        self,
        bot: discord.Client,
        guild: discord.Guild,
        channel: discord.TextChannel,
        dead_role_id: Optional[int] = None,
    ):
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
        self.wolf_chat_channel: Optional[discord.TextChannel] = None
        self.wolf_control_message: Optional[discord.Message] = None

        self.lobby_message: Optional[discord.Message] = None
        self.day_vote_message: Optional[discord.Message] = None
        self.night_vote_message: Optional[discord.Message] = None

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

    def is_alive_wolf(self, uid: object) -> bool:
        player = self.get_player(uid)
        return bool(player and player.get("alive") and player.get("role") == "wolf")

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
                await user.send(
                    f"🐺 Vai trò của bạn là: **{_role_name(data['role'])}**\n"
                    f"Bạn đã được thêm vào ván chơi ở **#{self.channel.name}**."
                )
            except Exception:
                pass

    async def refresh_lobby_panel(self) -> None:
        if not self.lobby_message:
            return
        try:
            await self.lobby_message.edit(embed=self.render_lobby_embed(), view=JoinView(self))
        except Exception:
            pass

    async def ensure_wolf_chat_channel(self) -> Optional[discord.TextChannel]:
        if self.wolf_chat_channel and self.wolf_chat_channel.guild == self.guild:
            return self.wolf_chat_channel

        channel_name = f"wolf-chat-{self.channel.id}"

        overwrites: dict[discord.abc.Snowflake, discord.PermissionOverwrite] = {
            self.guild.default_role: discord.PermissionOverwrite(
                view_channel=False,
                send_messages=False,
                read_message_history=False,
            )
        }

        me = _bot_member(self.guild, self.bot)
        if me:
            overwrites[me] = discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                embed_links=True,
                attach_files=True,
            )

        for uid in self.alive_wolves():
            member = self.guild.get_member(int(uid))
            if member:
                overwrites[member] = discord.PermissionOverwrite(
                    view_channel=True,
                    send_messages=True,
                    read_message_history=True,
                    embed_links=True,
                    attach_files=True,
                )

        try:
            self.wolf_chat_channel = await self.guild.create_text_channel(
                name=channel_name,
                category=self.channel.category,
                overwrites=overwrites,
                reason="Werewolf private wolf chat",
            )
        except Exception:
            self.wolf_chat_channel = None

        return self.wolf_chat_channel

    async def refresh_wolf_chat_permissions(self) -> None:
        if not self.wolf_chat_channel:
            return

        overwrites: dict[discord.abc.Snowflake, discord.PermissionOverwrite] = {
            self.guild.default_role: discord.PermissionOverwrite(
                view_channel=False,
                send_messages=False,
                read_message_history=False,
            )
        }

        me = _bot_member(self.guild, self.bot)
        if me:
            overwrites[me] = discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                embed_links=True,
                attach_files=True,
            )

        for uid in self.alive_wolves():
            member = self.guild.get_member(int(uid))
            if member:
                overwrites[member] = discord.PermissionOverwrite(
                    view_channel=True,
                    send_messages=True,
                    read_message_history=True,
                    embed_links=True,
                    attach_files=True,
                )

        try:
            await self.wolf_chat_channel.edit(overwrites=overwrites)
        except Exception:
            pass

    def render_lobby_embed(self) -> discord.Embed:
        embed = discord.Embed(
            title="🐺 Werewolf Lobby",
            description=(
                "Bấm **Join** để tham gia.\n"
                "Bấm **Start** khi đủ người.\n\n"
                "Mỗi người sẽ nhận DM báo vai trò của mình."
            ),
            color=discord.Color.blurple(),
        )
        embed.add_field(name="Người chơi", value=str(len(self.players)), inline=True)
        embed.add_field(name="Trạng thái", value=self.phase.title(), inline=True)
        embed.add_field(name="Kênh chính", value=f"#{self.channel.name}", inline=True)
        embed.set_footer(text="Ma Sói • lobby")
        return embed

    def render_day_embed(self) -> discord.Embed:
        alive = len(self.alive_players())
        wolves = len(self.alive_wolves())
        villagers = len(self.alive_villagers())

        embed = discord.Embed(
            title=f"🌞 Ngày {self.day}",
            description=(
                "Mọi người thảo luận rồi vote bằng menu chọn.\n"
                "Ai nhiều phiếu nhất sẽ bị loại. Hòa phiếu thì không ai chết."
            ),
            color=discord.Color.gold(),
        )
        embed.add_field(name="Còn sống", value=str(alive), inline=True)
        embed.add_field(name="Sói", value=str(wolves), inline=True)
        embed.add_field(name="Dân", value=str(villagers), inline=True)
        embed.set_footer(text="Ma Sói • ban ngày")
        return embed

    def render_night_embed(self) -> discord.Embed:
        alive = len(self.alive_players())
        wolves = len(self.alive_wolves())

        embed = discord.Embed(
            title=f"🌙 Đêm {self.day}",
            description=(
                "Dân làng không được nói trong kênh chính.\n"
                "Ma Sói có phòng chat riêng và panel chọn mục tiêu."
            ),
            color=discord.Color.dark_red(),
        )
        embed.add_field(name="Còn sống", value=str(alive), inline=True)
        embed.add_field(name="Sói còn sống", value=str(wolves), inline=True)
        embed.add_field(name="Pha", value=self.phase.title(), inline=True)
        embed.set_footer(text="Ma Sói • ban đêm")
        return embed

    def render_wolf_panel(self) -> discord.Embed:
        lines = self.wolf_chat[-MAX_CHAT_LINES:]
        description = "\n".join(lines) if lines else "Chưa có tin nhắn nào."

        embed = discord.Embed(
            title="🐺 Phòng chat ma sói",
            description=description,
            color=discord.Color.dark_red(),
        )
        embed.add_field(name="Pha", value=self.phase.title(), inline=True)
        embed.add_field(name="Sói còn sống", value=str(len(self.alive_wolves())), inline=True)
        embed.add_field(name="Kênh chính", value=f"#{self.channel.name}", inline=True)
        embed.set_footer(text="Chat nội bộ của bầy sói")
        return embed

    def build_vote_view(self, phase: str) -> View:
        return VoteSelectView(self, phase=phase)

    async def post_lobby_panel(self, ctx) -> None:
        self.lobby_message = await send(ctx, embed=self.render_lobby_embed(), view=JoinView(self))

    async def start(self) -> None:
        async with self._lock:
            if self.phase != "lobby":
                return

            self.assign_roles()
            await self.reveal_roles()

            self.phase = "day"
            self.day = 1

        await send(self.channel, content="🎮 Ván Ma Sói bắt đầu!")
        await self.ensure_wolf_chat_channel()
        await self.refresh_wolf_chat_permissions()
        await self.send_wolf_panels()
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

        if self.wolf_chat_channel:
            try:
                await self.wolf_chat_channel.send("🏁 Ván chơi đã kết thúc.")
            except Exception:
                pass

    def check_win(self) -> bool:
        wolves = len(self.alive_wolves())
        villagers = len(self.alive_villagers())

        if wolves == 0:
            asyncio.create_task(send(self.channel, content="🏆 Dân làng thắng!"))
            return True

        if villagers == 0 or wolves >= villagers:
            asyncio.create_task(send(self.channel, content="🐺 Ma Sói thắng!"))
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

    async def refresh_vote_panels(self) -> None:
        if self.phase == "day" and self.day_vote_message:
            try:
                await self.day_vote_message.edit(
                    embed=self.render_day_embed(),
                    view=self.build_vote_view(phase="day"),
                )
            except Exception:
                pass

        if self.phase == "night" and self.night_vote_message:
            try:
                await self.night_vote_message.edit(
                    embed=self.render_night_embed(),
                    view=self.build_vote_view(phase="night"),
                )
            except Exception:
                pass

        if self.wolf_control_message:
            try:
                await self.wolf_control_message.edit(
                    embed=self.render_wolf_panel(),
                    view=WolfControlView(self),
                )
            except Exception:
                pass

    async def kill_player(self, uid: str, reason: str) -> Optional[dict]:
        player = self.get_player(uid)
        if not player or not player.get("alive"):
            return None

        player["alive"] = False
        await self.set_dead_role(str(uid))
        await send(self.channel, content=f"💀 {player['name']} {reason}")
        await self.refresh_wolf_chat_permissions()
        await self.refresh_vote_panels()
        return player

    async def day_phase(self) -> None:
        self.phase = "day"
        self.day_votes = {}
        self.night_votes = {}

        try:
            await self.channel.set_permissions(self.guild.default_role, send_messages=True)
        except Exception:
            pass

        if self.day_vote_message:
            try:
                await self.day_vote_message.edit(
                    content="🗳️ Vote ban ngày đang mở.",
                    embed=self.render_day_embed(),
                    view=self.build_vote_view(phase="day"),
                )
            except Exception:
                self.day_vote_message = None

        if not self.day_vote_message:
            self.day_vote_message = await send(
                self.channel,
                content="🗳️ Vote ban ngày đang mở.",
                embed=self.render_day_embed(),
                view=self.build_vote_view(phase="day"),
            )

        await asyncio.sleep(DAY_DISCUSSION_SECONDS)

        try:
            await self.day_vote_message.edit(
                content="🗳️ Bắt đầu vote ban ngày!",
                embed=self.render_day_embed(),
                view=self.build_vote_view(phase="day"),
            )
        except Exception:
            pass

        await asyncio.sleep(DAY_VOTE_SECONDS)
        await self.resolve_day()
        self.day += 1

    async def resolve_day(self) -> None:
        if not self.day_votes:
            await send(self.channel, content="❌ Không ai vote nên không ai chết.")
            return

        count = Counter(self.day_votes.values())
        top = max(count.values())
        targets = [uid for uid, votes in count.items() if votes == top]

        if len(targets) != 1:
            await send(self.channel, content="⚖️ Hòa phiếu nên không ai chết.")
            return

        await self.kill_player(targets[0], "bị treo cổ vào ban ngày.")

    async def night_phase(self) -> None:
        self.phase = "night"
        self.night_votes = {}

        try:
            await self.channel.set_permissions(self.guild.default_role, send_messages=False)
        except Exception:
            pass

        await send(self.channel, content="🌙 Đêm xuống. Dân thường không được nói trong kênh chính.")
        await self.send_wolf_panels()

        if self.night_vote_message:
            try:
                await self.night_vote_message.edit(
                    content="🐺 Vote ban đêm đang mở.",
                    embed=self.render_night_embed(),
                    view=self.build_vote_view(phase="night"),
                )
            except Exception:
                self.night_vote_message = None

        if not self.night_vote_message:
            self.night_vote_message = await send(
                self.channel,
                content="🐺 Vote ban đêm đang mở.",
                embed=self.render_night_embed(),
                view=self.build_vote_view(phase="night"),
            )

        await asyncio.sleep(NIGHT_SECONDS)
        await self.resolve_night()

    async def resolve_night(self) -> None:
        if not self.night_votes:
            await send(self.channel, content="🌙 Không ai chết trong đêm.")
            return

        count = Counter(self.night_votes.values())
        top = max(count.values())
        targets = [uid for uid, votes in count.items() if votes == top]
        victim = random.choice(targets)

        await self.kill_player(victim, "bị ma sói giết trong đêm.")

    async def send_wolf_panels(self) -> None:
        """
        Tạo hoặc cập nhật panel sói trong channel riêng.
        """
        await self.ensure_wolf_chat_channel()
        await self.refresh_wolf_chat_permissions()

        if self.wolf_chat_channel is None:
            return

        try:
            if self.wolf_control_message:
                await self.wolf_control_message.edit(
                    embed=self.render_wolf_panel(),
                    view=WolfControlView(self),
                )
            else:
                self.wolf_control_message = await self.wolf_chat_channel.send(
                    embed=self.render_wolf_panel(),
                    view=WolfControlView(self),
                )
        except Exception:
            pass

    async def refresh_wolf_panels(self) -> None:
        await self.refresh_wolf_chat_permissions()
        if self.wolf_control_message:
            try:
                await self.wolf_control_message.edit(
                    embed=self.render_wolf_panel(),
                    view=WolfControlView(self),
                )
            except Exception:
                pass

    async def send_wolf_chat_message(self, uid: str, text: str) -> None:
        name = self.players[uid]["name"]
        self.wolf_chat.append(f"**{name}**: {text}")

        if self.wolf_chat_channel:
            try:
                await self.wolf_chat_channel.send(f"🐺 **{name}**: {text}")
            except Exception:
                pass

        await self.refresh_wolf_panels()


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
        await self.session.refresh_lobby_panel()

    @discord.ui.button(label="Start", style=discord.ButtonStyle.danger)
    async def start_button(self, interaction: discord.Interaction, button: Button):
        if self.session.phase != "lobby":
            return await interaction.response.send_message("❌ Ván chơi đã bắt đầu.", ephemeral=True)

        if len(self.session.players) < 5:
            return await interaction.response.send_message("❌ Cần ít nhất 5 người để bắt đầu.", ephemeral=True)

        await interaction.response.send_message("🚀 Bắt đầu game!", ephemeral=True)
        asyncio.create_task(self.session.start())


class VoteSelect(Select):
    def __init__(self, session: WerewolfSession, phase: str, options_chunk: list[str], chunk_index: int, total_chunks: int):
        self.session = session
        self.phase = phase

        options: list[discord.SelectOption] = []
        for uid in options_chunk:
            player = session.players.get(uid)
            if not player or not player.get("alive"):
                continue
            options.append(
                discord.SelectOption(
                    label=player["name"][:100],
                    value=uid,
                    description="Chọn mục tiêu này",
                )
            )

        placeholder = "Chọn người bị vote" if phase == "day" else "Sói chọn mục tiêu"
        if total_chunks > 1:
            placeholder = f"{placeholder} ({chunk_index + 1}/{total_chunks})"

        super().__init__(
            placeholder=placeholder,
            min_values=1,
            max_values=1,
            options=options,
            row=chunk_index if chunk_index < 5 else 4,
        )

    async def callback(self, interaction: discord.Interaction):
        uid = str(interaction.user.id)
        player = self.session.get_player(uid)

        if not player or not player.get("alive"):
            return await interaction.response.send_message("❌ Bạn đã chết.", ephemeral=True)

        target_id = self.values[0]
        target = self.session.players.get(target_id)
        if not target or not target.get("alive"):
            return await interaction.response.send_message("❌ Người này đã chết rồi.", ephemeral=True)

        if self.phase == "day":
            self.session.day_votes[uid] = target_id
            await interaction.response.send_message(
                f"✅ Bạn đã vote cho **{target['name']}**.",
                ephemeral=True,
            )
            await self.session.refresh_vote_panels()
            return

        if not self.session.is_alive_wolf(uid):
            return await interaction.response.send_message("❌ Ban đêm chỉ ma sói mới được vote.", ephemeral=True)

        self.session.night_votes[uid] = target_id
        await interaction.response.send_message(
            f"✅ Ma Sói đã chọn **{target['name']}**.",
            ephemeral=True,
        )
        await self.session.refresh_vote_panels()


class VoteSelectView(View):
    def __init__(self, session: WerewolfSession, phase: str):
        super().__init__(timeout=120)
        self.session = session
        self.phase = phase

        alive_ids = session.alive_players()[: MAX_SELECT_OPTIONS * MAX_SELECT_ROWS]
        chunks = _chunk(alive_ids, MAX_SELECT_OPTIONS)

        for i, chunk_ids in enumerate(chunks):
            self.add_item(VoteSelect(session, phase, chunk_ids, i, len(chunks)))


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

        await self.session.send_wolf_chat_message(self.wolf_uid, self.message_input.value)
        await interaction.response.send_message("✅ Đã gửi tin nhắn cho bầy sói.", ephemeral=True)


class WolfControlView(View):
    def __init__(self, session: WerewolfSession):
        super().__init__(timeout=120)
        self.session = session

    @discord.ui.button(label="Chat", style=discord.ButtonStyle.secondary)
    async def chat_button(self, interaction: discord.Interaction, button: Button):
        uid = str(interaction.user.id)

        if not self.session.is_alive_wolf(uid):
            return await interaction.response.send_message("❌ Bạn không còn là ma sói.", ephemeral=True)

        if self.session.phase != "night":
            return await interaction.response.send_message("❌ Chỉ chat được vào ban đêm.", ephemeral=True)

        await interaction.response.send_modal(WolfChatModal(self.session, uid))

    @discord.ui.button(label="Vote", style=discord.ButtonStyle.danger)
    async def vote_button(self, interaction: discord.Interaction, button: Button):
        uid = str(interaction.user.id)

        if not self.session.is_alive_wolf(uid):
            return await interaction.response.send_message("❌ Bạn không còn là ma sói.", ephemeral=True)

        if self.session.phase != "night":
            return await interaction.response.send_message("❌ Chỉ vote được vào ban đêm.", ephemeral=True)

        await interaction.response.send_message(
            embed=discord.Embed(
                title="🐺 Chọn mục tiêu",
                description="Chọn người muốn giết bằng menu bên dưới.",
                color=discord.Color.dark_red(),
            ),
            view=VoteSelectView(self.session, phase="night"),
            ephemeral=True,
        )


async def werewolf_logic(ctx, channel_id, dead_role=None):
    _ensure_data_file()

    guild = ctx.guild
    if guild is None:
        return await send(ctx, content="❌ Lệnh này chỉ dùng trong server.")

    channel_id_int = _parse_id(channel_id)
    dead_role_id = _parse_id(dead_role)

    if channel_id_int is None:
        return await send(ctx, content="❌ Không tìm thấy channel.")

    channel = guild.get_channel(channel_id_int)
    if channel is None:
        try:
            channel = await guild.fetch_channel(channel_id_int)
        except Exception:
            channel = None

    if channel is None or not isinstance(channel, discord.TextChannel):
        return await send(ctx, content="❌ Không tìm thấy channel.")

    if channel.id in GAME and GAME[channel.id].active:
        return await send(ctx, content="❌ Kênh này đang có ván Ma Sói chạy rồi.")

    bot = getattr(ctx, "bot", None) or getattr(ctx, "client", None)
    if bot is None:
        return await send(ctx, content="❌ Không lấy được bot instance.")

    session = WerewolfSession(bot, guild, channel, dead_role_id=dead_role_id)
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

    await send(ctx, embed=embed, view=JoinView(session))
