from __future__ import annotations

import asyncio
import json
import random
import re
from sqlite3.dbapi2 import PARSE_COLNAMES
import sys
import tempfile
import time
from collections import Counter
from pathlib import Path
from typing import Any, Optional



import discord
from discord.ui import Button, Modal, Select, TextInput, View

class MediumAnonymousModal(Modal):
    def __init__(self, session: "WerewolfSession"):
        super().__init__(title="Nhắn ẩn danh tới kênh người chết")
        self.session = session
        self.text = TextInput(label="Nội dung", style=discord.TextStyle.paragraph, max_length=1500)
        self.add_item(self.text)

    async def on_submit(self, interaction: discord.Interaction):
        my_id = interaction.user.id
        if not self.session.is_alive(my_id):
            return await interaction.response.send_message("❌ Chỉ Thầy đồng còn sống mới gửi được.", ephemeral=True)
        pdata = self.session.players.get(str(my_id), {})
        if pdata.get("role") != "medium" or self.session.phase != "night" or self.session.round_no < 2:
            return await interaction.response.send_message("❌ Chỉ Thầy đồng, đêm 2 trở đi.", ephemeral=True)
        ch = await self.session.ensure_dead_channel()
        if not ch:
            return await interaction.response.send_message("❌ Không tìm thấy kênh người chết.", ephemeral=True)
        msg = str(self.text.value).strip()
        if not msg:
            return await interaction.response.send_message("❌ Tin nhắn trống.", ephemeral=True)
        try:
            await ch.send(f"🔮 **Thầy đồng:** {msg}")
            await interaction.response.send_message("✅ Đã gửi.", ephemeral=True)
        except Exception:
            await interaction.response.send_message("❌ Không gửi được.", ephemeral=True)

class MediumAnonymousView(View):
    def __init__(self, session: "WerewolfSession"):
        super().__init__(timeout=180)
        self.session = session

    @discord.ui.button(label="Nhắn tới người chết", style=discord.ButtonStyle.primary, emoji="🔮")
    async def medium_anon_button(self, interaction: discord.Interaction, button: Button):
        my_id = interaction.user.id
        if not self.session.is_alive(my_id):
            return await interaction.response.send_message("❌ Chỉ Thầy đồng còn sống mới gửi được.", ephemeral=True)
        pdata = self.session.players.get(str(my_id), {})
        if pdata.get("role") != "medium" or self.session.phase != "night" or self.session.round_no < 2:
            return await interaction.response.send_message("❌ Chỉ Thầy đồng, đêm 2 trở đi.", ephemeral=True)
        await interaction.response.send_modal(MediumAnonymousModal(self.session))

try:
    from Commands.role import (
        TEAM_WOLF,
        TEAM_SOLO,
        TEAM_VILLAGE,
        ROLE_DEFINITIONS,
        DEFAULT_ROLE_KEY,
        role_name as _role_name,
        role_description as _role_desc,
        role_team as _role_team,
        team_label as _team_label,
        create_role,
        build_role_assignments,
        build_night_actions,
        resolve_actions,
        apply_action_plan,
    )
except Exception:
    TEAM_WOLF = "wolf"
    TEAM_SOLO = "solo"
    TEAM_VILLAGE = "village"
    DEFAULT_ROLE_KEY = "civilian"
    ROLE_DEFINITIONS = {}
    def _role_name(role_key: str) -> str:
        return role_key
    def _role_desc(role_key: str) -> str:
        return "Không có mô tả."
    def _role_team(role_key: str) -> str:
        return TEAM_VILLAGE
    def _team_label(team: str) -> str:
        return {TEAM_WOLF: "Ma Sói", TEAM_SOLO: "Solo"}.get(team, "Dân làng")
    create_role = None
    build_role_assignments = None
    build_night_actions = None
    resolve_actions = None
    apply_action_plan = None

MIN_PLAYERS = 5
MAX_PLAYERS = 16
DAY_DISCUSSION_SECONDS = 60
DAY_VOTE_SECONDS = 30
NIGHT_VOTE_SECONDS = 60

GAME: dict[int, "WerewolfSession"] = {}

_AGENT_LOG_PATHS = (
    Path(__file__).resolve().parent.parent / "debug-8e1d58.log",
    Path.cwd() / "debug-8e1d58.log",
    Path(tempfile.gettempdir()) / "botr-werewolf-debug-8e1d58.log",
)


def _skill_agent_log(hypothesis_id: str, message: str, data: dict[str, Any]) -> None:
    #region agent log
    line = (
        json.dumps(
            {
                "sessionId": "8e1d58",
                "hypothesisId": hypothesis_id,
                "message": message,
                "data": data,
                "timestamp": int(time.time() * 1000),
            },
            ensure_ascii=False,
        )
        + "\n"
    )
    try:
        sys.stderr.write(f"[botr-werewolf] {hypothesis_id} {message}\n")
    except Exception:
        pass
    for path in _AGENT_LOG_PATHS:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "a", encoding="utf-8") as f:
                f.write(line)
                f.flush()
        except Exception:
            continue
    #endregion


def _slug_text_channel_name(name: str, max_len: int = 96) -> str:
    """Tên kênh Discord: chữ thường, [a-z0-9_-], tối đa max_len."""
    s = name.lower().strip()
    s = re.sub(r"[^a-z0-9_-]+", "-", s)
    s = re.sub(r"-+", "-", s).strip("-")
    return (s or "room")[:max_len]


def _prefixed_channel_name(prefix: str, base_name: str) -> str:
    """prefix + slug, tổng độ dài tối đa 100 (giới hạn Discord)."""
    max_body = max(1, 100 - len(prefix))
    return prefix + _slug_text_channel_name(base_name, max_len=max_body)


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


def _display_name(user: discord.abc.User | None) -> str:
    if user is None:
        return "Unknown"
    return getattr(user, "display_name", None) or getattr(user, "name", "Unknown")


def _is_admin(user: discord.abc.User | None) -> bool:
    perms = getattr(user, "guild_permissions", None)
    return bool(perms and perms.administrator)


def _bot_member(guild: discord.Guild, bot: discord.Client) -> Optional[discord.Member]:
    if bot.user is None:
        return None
    return guild.get_member(bot.user.id)


def _fmt_ts(ts: int | float | None, style: str = "R") -> str:
    if not ts:
        return "—"
    return f"<t:{int(ts)}:{style}>"


def _tally(votes: dict[str, str]) -> Counter:
    return Counter(votes.values()) if votes else Counter()


async def send(ctx, *args, **kwargs):
    if hasattr(ctx, "response"):
        if not ctx.response.is_done():
            await ctx.response.send_message(*args, **kwargs)
            try:
                return await ctx.original_response()
            except Exception:
                return None
        return await ctx.followup.send(*args, **kwargs)
    return await ctx.send(*args, **kwargs)


async def safe_delete(message: Optional[discord.Message]) -> None:
    if message is None:
        return
    try:
        await message.delete()
    except Exception:
        pass


async def safe_edit(message: Optional[discord.Message], **kwargs) -> Optional[discord.Message]:
    if message is None:
        return None
    try:
        return await message.edit(**kwargs)
    except Exception:
        return None


class JailAnonymousModal(Modal):
    def __init__(self, session: "WerewolfSession"):
        super().__init__(title="Nhắn ẩn danh trong phòng giam")
        self.session = session
        self.text = TextInput(label="Nội dung", style=discord.TextStyle.paragraph, max_length=1500)
        self.add_item(self.text)

    async def on_submit(self, interaction: discord.Interaction):
        if self.session.jailer_id is None or interaction.user.id != self.session.jailer_id:
            return await interaction.response.send_message("❌ Chỉ quản ngục mới dùng được nút này.", ephemeral=True)
        if self.session.jail_channel is None:
            return await interaction.response.send_message("❌ Phòng giam đã đóng.", ephemeral=True)

        msg = str(self.text.value).strip()
        if not msg:
            return await interaction.response.send_message("❌ Tin nhắn trống.", ephemeral=True)

        try:
            await self.session.jail_channel.send(f"📮 **Quản ngục:** {msg}")
            await interaction.response.send_message("✅ Đã gửi.", ephemeral=True)
        except Exception:
            await interaction.response.send_message("❌ Không gửi được.", ephemeral=True)


class JailAnonymousView(View):
    def __init__(self, session: "WerewolfSession"):
        super().__init__(timeout=180)
        self.session = session

    @discord.ui.button(label="Nhắn ẩn danh", style=discord.ButtonStyle.primary, emoji="✉️")
    async def anonymous_button(self, interaction: discord.Interaction, button: Button):
        if self.session.jailer_id is None or interaction.user.id != self.session.jailer_id:
            return await interaction.response.send_message("❌ Chỉ quản ngục mới dùng được nút này.", ephemeral=True)
        await interaction.response.send_modal(JailAnonymousModal(self.session))

    @discord.ui.button(label="Bắn", style=discord.ButtonStyle.danger, emoji="🔫")
    async def shoot_button(self, interaction: discord.Interaction, button: Button):

        # ACK ngay lập tức
        await interaction.response.defer(ephemeral=True)

        # Chỉ Jailer được bấm
        if self.session.jailer_id is None or interaction.user.id != self.session.jailer_id:
            return await interaction.followup.send("❌ Chỉ quản ngục mới dùng được nút này.", ephemeral=True)

        if getattr(self.session, "jail_shot_used", False):
            return await interaction.followup.send("❌ Bạn chỉ được bắn 1 lần/ván.", ephemeral=True)

        prisoner_id = self.session.jail_target_id
        if not prisoner_id:
            return await interaction.followup.send("❌ Không có tù nhân để bắn.", ephemeral=True)

        prisoner = self.session.players.get(str(prisoner_id))
        if not prisoner or not prisoner.get("alive"):
            return await interaction.followup.send("❌ Tù nhân đã chết hoặc không hợp lệ.", ephemeral=True)

        # Đánh dấu đã bắn
        self.session.jail_shot_used = True

        member = self.session.guild.get_member(int(prisoner_id))

        # DM
        try:
            if member:
                await member.send(
                    embed=discord.Embed(
                        title="💀 Bạn đã bị hành quyết",
                        description="Bạn đã bị **Quản ngục xử bắn trong phòng giam**.",
                        color=discord.Color.dark_red(),
                    )
                )
        except:
            pass

        # Public
        try:
            if self.session.public_channel:
                await self.session.public_channel.send(
                    embed=discord.Embed(
                        title="⚖️ Hành quyết",
                        description=f"Quản ngục đã hành quyết **{prisoner['name']}**.",
                        color=discord.Color.dark_red(),
                    )
                )
        except:
            pass

        # Kill
        await self.session.kill_player(
            str(prisoner_id),
            "bị Quản ngục xử bắn trong phòng giam!",
            cause="jailer_shoot",
        )

        # Reply cho jailer
        await interaction.followup.send(
            f"✅ Đã bắn tù nhân **{prisoner['name']}**.",
            ephemeral=True
        )

class WerewolfSession:

    # --- UI ẩn danh cho Medium gửi vào kênh người chết ---
    class MediumAnonymousModal(Modal):
        def __init__(self, session: "WerewolfSession"):
            super().__init__(title="Nhắn ẩn danh tới kênh người chết")
            self.session = session
            self.text = TextInput(label="Nội dung", style=discord.TextStyle.paragraph, max_length=1500)
            self.add_item(self.text)

        async def on_submit(self, interaction: discord.Interaction):
            my_id = interaction.user.id
            if not self.session.is_alive(my_id):
                return await interaction.response.send_message("❌ Chỉ Thầy đồng còn sống mới gửi được.", ephemeral=True)
            pdata = self.session.players.get(str(my_id), {})
            if pdata.get("role") != "medium" or self.session.phase != "night" or self.session.round_no < 2:
                return await interaction.response.send_message("❌ Chỉ Thầy đồng, đêm 2 trở đi.", ephemeral=True)
            ch = await self.session.ensure_dead_channel()
            if not ch:
                return await interaction.response.send_message("❌ Không tìm thấy kênh người chết.", ephemeral=True)
            msg = str(self.text.value).strip()
            if not msg:
                return await interaction.response.send_message("❌ Tin nhắn trống.", ephemeral=True)
            try:
                await ch.send(f"🔮 **Thầy đồng:** {msg}")
                await interaction.response.send_message("✅ Đã gửi.", ephemeral=True)
            except Exception:
                await interaction.response.send_message("❌ Không gửi được.", ephemeral=True)

    class MediumAnonymousView(View):
        def __init__(self, session: "WerewolfSession"):
            super().__init__(timeout=180)
            self.session = session

        @discord.ui.button(label="Nhắn tới người chết", style=discord.ButtonStyle.primary, emoji="🔮")
        async def medium_anon_button(self, interaction: discord.Interaction, button: Button):
            my_id = interaction.user.id
            if not self.session.is_alive(my_id):
                return await interaction.response.send_message("❌ Chỉ Thầy đồng còn sống mới gửi được.", ephemeral=True)
            pdata = self.session.players.get(str(my_id), {})
            if pdata.get("role") != "medium" or self.session.phase != "night" or self.session.round_no < 2:
                return await interaction.response.send_message("❌ Chỉ Thầy đồng, đêm 2 trở đi.", ephemeral=True)
            await interaction.response.send_modal(MediumAnonymousModal(self.session))

    async def show_medium_view(session: "WerewolfSession"):
        # Gửi view cho Medium vào dead channel vào đêm 2+
        if session.phase != "night" or session.round_no < 2:
            return
        ch = await session.ensure_dead_channel()
        if not ch:
            return
        for uid, pdata in session.players.items():
            if pdata.get("role") == "medium" and pdata.get("alive"):
                member = session.guild.get_member(int(uid))
                if member is None:
                    try:
                        member = await session.guild.fetch_member(int(uid))
                    except Exception:
                        member = None
                if member:
                    try:
                        await ch.send(content=f"🔮 **Thầy đồng** có thể nhắn ẩn danh:", view=MediumAnonymousView(session))
                    except Exception:
                        pass
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

        self.base_name = channel.name
        self.base_topic = channel.topic
        self.base_nsfw = channel.is_nsfw()
        self.base_slowmode = channel.slowmode_delay
        self.base_category = channel.category
        self.base_position = channel.position
        self.base_overwrites = dict(channel.overwrites)

        self.players: dict[str, dict[str, Any]] = {}
        self.dead_members: set[str] = set()
        self.phase: str = "lobby"
        self.round_no: int = 1
        self.host_id: Optional[str] = None

        self.day_votes: dict[str, str] = {}
        self._last_day_vote_state = None
        self.night_votes: dict[str, str] = {}

        self.lobby_message: Optional[discord.Message] = None
        self.phase_message: Optional[discord.Message] = None
        self.wolf_channel: Optional[discord.TextChannel] = None
        self.jail_channel: Optional[discord.TextChannel] = None
        self.dead_channel: Optional[discord.TextChannel] = None

        self.last_join_at: Optional[int] = None
        self.day_deadline_at: Optional[int] = None
        self.night_deadline_at: Optional[int] = None
        self.vote_deadline_at: Optional[int] = None
        self.discussion_deadline_at: Optional[int] = None

        self.nightmare_token_target_id: Optional[int] = None
        self.wolf_shaman_cover_target_id: Optional[int] = None
        self.wolf_shaman_cover_round: Optional[int] = None

        self.protector_id: Optional[str] = None  # ai là BV
        self.protector_target_id: Optional[str] = None  # BV đang protect ai
        self.shield_used: bool = False  # Khiên BV

        self.jailer_id: Optional[int] = None
        self.jail_target_id: Optional[int] = None

        self.active = True
        self.finished = False
        self._lock = asyncio.Lock()

        self.dead_channel = next((c for c in guild.text_channels if c.name.lower() == "dead"), None)
        self.wolf_vote_message: Optional[discord.Message] = None
    def role_label(self, role_key: str) -> str:
        return _role_name(role_key)

    def role_description(self, role_key: str) -> str:
        return _role_desc(role_key)

    def role_team(self, role_key: str) -> str:
        return _role_team(role_key)

    def team_label(self, role_key: str) -> str:
        return _team_label(self.role_team(role_key))

    def add_player(self, user: discord.abc.User) -> bool:
        uid = str(user.id)
        if uid in self.players or len(self.players) >= MAX_PLAYERS:
            return False

        self.players[uid] = {
            "name": _display_name(user),
            "member": user if isinstance(user, discord.Member) else None,
            "role": DEFAULT_ROLE_KEY,
            "role_obj": None,
            "alive": True,
            "revealed_role": False,
            "nightmare_locked": False,
            "guard_day_skill_round": None,
            "guard_day_skill_key": None,
        }
        if self.host_id is None:
            self.host_id = uid
        self.last_join_at = int(time.time())
        return True

    def get_player(self, uid: object) -> Optional[dict[str, Any]]:
        return self.players.get(str(uid))

    def alive_players(self) -> list[str]:
        return [uid for uid, p in self.players.items() if p.get("alive")]

    def alive_wolves(self) -> list[str]:
        return [
            uid
            for uid, p in self.players.items()
            if p.get("alive") and self.role_team(p.get("role", DEFAULT_ROLE_KEY)) == TEAM_WOLF
        ]

    def alive_villagers(self) -> list[str]:
        return [
            uid
            for uid, p in self.players.items()
            if p.get("alive") and self.role_team(p.get("role", DEFAULT_ROLE_KEY)) == TEAM_VILLAGE
        ]

    def alive_solos(self) -> list[str]:
        return [
            uid
            for uid, p in self.players.items()
            if p.get("alive") and self.role_team(p.get("role", DEFAULT_ROLE_KEY)) == TEAM_SOLO
        ]

    def is_alive(self, uid: object) -> bool:
        p = self.get_player(uid)
        return bool(p and p.get("alive"))

    def is_alive_wolf(self, uid: object) -> bool:
        p = self.get_player(uid)
        return bool(p and p.get("alive") and self.role_team(p.get("role", DEFAULT_ROLE_KEY)) == TEAM_WOLF)

    def is_jailed(self, uid: object) -> bool:
        if self.phase != "night":
            return False

        try:
            check = str(int(uid))
        except Exception:
            return False

        ids = set()

        if self.jailer_id is not None:
            ids.add(str(self.jailer_id))

        if self.jail_target_id is not None:
            ids.add(str(self.jail_target_id))

        return check in ids

    def can_start(self) -> bool:
        return MIN_PLAYERS <= len(self.players) <= MAX_PLAYERS

    def _panel_counts_text(self) -> str:
        return (
            f"**Còn sống:** {len(self.alive_players())}\n"
            f"**Sói:** {len(self.alive_wolves())}\n"
            f"**Dân:** {len(self.alive_villagers())}\n"
            f"**Solo:** {len(self.alive_solos())}"
        )

    async def notify_host_join(self, joiner: discord.abc.User) -> None:

        host = self.guild.get_member(int(self.host_id)) if self.host_id is not None else None

        if host is None and self.host_id is not None:

            try:

                host = await self.guild.fetch_member(int(self.host_id))

            except Exception:

                host = None


        if host is None:

            return


        try:

            await host.send(

                f"📣 **{_display_name(joiner)}** vừa tham gia phòng của bạn ở channels **#{self.base_name}**.\n"

                f"Phòng này hiện có **{len(self.players)}** người tham gia."

            )

            return

        except Exception:

            pass


        try:

            await self.channel.send(

                f"📣 <@{host.id}>, **{_display_name(joiner)}** vừa tham gia phòng."

            )

        except Exception:

            pass


    async def refresh_lobby_panel(self) -> None:


        embed = self.render_lobby_embed()


        view = LobbyView(self)



        if self.lobby_message is None:


            try:


                self.lobby_message = await self.channel.send(embed=embed, view=view)


            except Exception:


                self.lobby_message = None


            return



        try:


            await self.lobby_message.edit(embed=embed, view=view)


        except Exception:


            try:


                self.lobby_message = await self.channel.send(embed=embed, view=view)


            except Exception:


                pass


    async def assign_roles(self):
        ids = list(self.players.keys())
        random.shuffle(ids)

        role_map = build_role_assignments(ids, self.players) if callable(build_role_assignments) else {}
        for uid in ids:
            role_key = role_map.get(uid, DEFAULT_ROLE_KEY)
            member = self.guild.get_member(int(uid))
            if member is None:
                try:
                    member = await self.guild.fetch_member(int(uid))
                except Exception:
                    member = None

            self.players[uid]["role"] = role_key
            self.players[uid]["role_obj"] = create_role(role_key, member or self.bot.get_user(int(uid))) if create_role else None

    async def call_role_start_hooks(self) -> None:
        for pdata in list(self.players.values()):
            role_obj = pdata.get("role_obj")
            if role_obj is None:
                continue
            try:
                await role_obj.on_game_start(self)
            except Exception:
                pass

    async def _call_phase_hook(self, method_name: str) -> None:
        for pdata in list(self.players.values()):
            role_obj = pdata.get("role_obj")
            if role_obj is None:
                continue
            try:
                await getattr(role_obj, method_name)(self)
            except Exception:
                pass

    def render_lobby_embed(self) -> discord.Embed:
        embed = discord.Embed(
            title="🐺 Wolvesville Lobby",
            description=(
                "Bấm **Join** để tham gia.\n"
                "Người vào đầu tiên sẽ hiện ở mục **Chủ phòng**.\n"
                f"Chủ phòng có thể bấm **Start** khi đủ từ **{MIN_PLAYERS}** đến **{MAX_PLAYERS}** người."
            ),
            color=discord.Color.blurple(),
        )
        player_lines = [f"• {data['name']}" for data in self.players.values()]
        embed.add_field(
            name=f"Người chơi ({len(self.players)}/{MAX_PLAYERS})",
            value="\n".join(player_lines) if player_lines else "Chưa có ai.",
            inline=False,
        )
        # Thống kê role và số người sở hữu
        from collections import Counter
        role_counts = Counter(p.get("role", DEFAULT_ROLE_KEY) for p in self.players.values())
        role_lines = []
        for rk, cnt in role_counts.items():
            if rk in ROLE_DEFINITIONS:
                role_lines.append(f"{ROLE_DEFINITIONS[rk]['name']}: {cnt}")
            else:
                role_lines.append(f"{rk}: {cnt}")
        embed.add_field(
            name="Phân bố vai trò",
            value="\n".join(role_lines) if role_lines else "Chưa chia vai trò.",
            inline=False,
        )
        embed.add_field(
            name="Chủ phòng",
            value=self.players[self.host_id]["name"] if self.host_id and self.host_id in self.players else "Chưa có",
            inline=True,
        )
        embed.add_field(name="Trạng thái", value="Đang chờ tham gia", inline=True)
        embed.add_field(name="Kênh", value=f"#{self.base_name}", inline=True)
        embed.add_field(name="Cập nhật mới nhất", value=_fmt_ts(self.last_join_at), inline=True)
        embed.set_footer(text="Ma Sói • lobby")
        return embed

    def render_role_catalog_embed(self) -> discord.Embed:
        used: list[str] = []
        for p in self.players.values():
            rk = p.get("role", DEFAULT_ROLE_KEY)
            if rk not in used:
                used.append(rk)

        e = discord.Embed(
            title="📜 Role trong phòng",
            description="Danh sách role và chức năng có mặt trong ván này. Không hiển thị người sở hữu.",
            color=discord.Color.orange(),
        )
        for rk in used:
            d = ROLE_DEFINITIONS.get(rk)
            if not d:
                continue
            e.add_field(
                name=f"{d.get('name', rk)} • {_team_label(d.get('team', TEAM_VILLAGE))}",
                value=d.get("description", "Không có mô tả."),
                inline=False,
            )
        return e

    def render_phase_embed(self, phase: str, announcement: str) -> discord.Embed:
        if phase == "night":
            e = discord.Embed(
                title=f"🌙 Đêm {self.round_no}",
                description=announcement,
                color=discord.Color.dark_red()
            )

            e.add_field(
                name="Thời gian còn lại trước bình minh:",
                value=_fmt_ts(self.night_deadline_at),
                inline=True
            )

            e.set_footer(text="Màn đêm dần buông xuống!")

        else:
            e = discord.Embed(
                title=f"🌞 Ngày {self.round_no}",
                description=announcement,
                color=discord.Color.gold()
            )

            e.add_field(
                name="Vote hiện tại",
                value=self._vote_summary(self.day_votes, phase),
                inline=False
            )

            e.add_field(
                name="Thời gian còn lại trước hoàng hôn:",
                value=_fmt_ts(self.vote_deadline_at),
                inline=True
            )

            e.set_footer(text="Ban ngày • thảo luận + vote + kỹ năng")

        # =========================
        # Alive / Dead list (giữ nguyên)
        # =========================
        alive_lines = []
        dead_lines = []

        for uid, pdata in self.players.items():
            if pdata.get("alive"):
                alive_lines.append(f"🟢 {pdata['name']}")
            else:
                role = pdata.get("role", DEFAULT_ROLE_KEY)
                role_label = self.role_label(role)
                dead_lines.append(f"⚰️ {pdata['name']} ({role_label})")

        e.add_field(
            name="Còn sống",
            value="\n".join(alive_lines) if alive_lines else "Không còn ai.",
            inline=False
        )

        if dead_lines:
            e.add_field(
                name="Đã chết",
                value="\n".join(dead_lines),
                inline=False
            )
        return e
    def _vote_summary(self, votes: dict[str, str], phase: str) -> str:
        if not votes:
            return "Chưa có phiếu nào."
        c = _tally(votes)
        out = ["Chỉ sói còn sống mới được vote." if phase == "night" else "Tất cả người còn sống đều có thể vote."]
        for target_id, amount in c.most_common():
            target = self.players.get(target_id)
            if target:
                voters = [self.players[uid]["name"] for uid, t in votes.items() if t == target_id and uid in self.players]
                out.append(f"• **{target['name']}** — {amount} phiếu (bởi: {', '.join(voters)})")
        return "\n".join(out)
    def _day_vote_snapshot(self) -> tuple[tuple[str, str], ...]:
        return tuple(sorted((voter_id, target_id) for voter_id, target_id in self.day_votes.items()))

    async def _refresh_day_vote_panel_if_changed(self, announcement: str) -> None:
        current_state = self._day_vote_snapshot()
        if current_state == self._last_day_vote_state:
            return

        self._last_day_vote_state = current_state
        await self.refresh_phase_message("day", announcement)

    async def _refresh_wolf_vote_panel(self, fresh: bool = False) -> None:
        if not self.wolf_channel:
            return

        embed = self._wolf_vote_embed()

        # Nếu chưa có message hoặc yêu cầu tạo mới
        if fresh or self.wolf_vote_message is None:
            try:
                if self.wolf_vote_message:
                    await self.wolf_vote_message.delete()
            except Exception:
                pass

            try:
                self.wolf_vote_message = await self.wolf_channel.send(embed=embed)
            except Exception:
                self.wolf_vote_message = None
            return

        # Nếu đã có thì edit
        try:
            await self.wolf_vote_message.edit(embed=embed)
        except Exception:
            try:
                self.wolf_vote_message = await self.wolf_channel.send(embed=embed)
            except Exception:
                self.wolf_vote_message = None
    async def replace_phase_message(self, phase: str, announcement: str) -> None:
        await safe_delete(self.phase_message)
        self.phase_message = await self.channel.send(
            embed=self.render_phase_embed(phase, announcement),
            view=GameActionView(self, phase),
        )

        if phase != "night":
            await self.close_jail_room()
            await safe_delete(self.wolf_vote_message)
            self.wolf_vote_message = None
            return

        await self.sync_dead_channel(phase)
        await self._refresh_wolf_vote_panel(fresh=True)
    def _wolf_vote_embed(self) -> discord.Embed:
        # Embed riêng cho kênh sói, hiện vote sói chi tiết
        
        e = discord.Embed(title=f"🐺 Vote sói - Đêm {self.round_no}", color=discord.Color.dark_red())
        e.add_field(name="Vote hiện tại", value=self._vote_summary(self.night_votes, "night"), inline=False)
        return e

    async def refresh_phase_message(self, phase: str, announcement: str) -> None:
        if self.phase_message is None:
            await self.replace_phase_message(phase, announcement)
            return

        await safe_edit(
            self.phase_message,
            embed=self.render_phase_embed(phase, announcement),
            view=GameActionView(self, phase),
        )

        if phase == "night":
            await self.sync_dead_channel(phase)
            await self._refresh_wolf_vote_panel(fresh=False)

            # 🔥 MỞ PHÒNG GIAM TẠI ĐÂY
            if self.jailer_id is not None and self.jail_target_id is not None:
                await self.open_jail_room()

        else:
            # ❌ KHÔNG reset state
            await self.close_jail_room(clear_state=False)

            await safe_delete(self.wolf_vote_message)
            self.wolf_vote_message = None
    async def ensure_private_channel(
        self,
        name: str,
        members: list[discord.Member],
        *,
        category=None,
        topic: Optional[str] = None,
    ) -> discord.TextChannel | None:
        overwrites: dict[discord.abc.Snowflake, discord.PermissionOverwrite] = {
            self.guild.default_role: discord.PermissionOverwrite(
                view_channel=False,
                send_messages=False,
                read_message_history=False,
            )
        }

        bot_member = _bot_member(self.guild, self.bot)
        if bot_member:
            overwrites[bot_member] = discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                embed_links=True,
                attach_files=True,
                add_reactions=True,
            )

        for member in members:
            overwrites[member] = discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                embed_links=True,
                attach_files=True,
                add_reactions=True,
            )

        try:
            return await self.guild.create_text_channel(
                name=name,
                category=category or self.base_category,
                topic=topic,
                overwrites=overwrites,
                reason="Werewolf private room",
            )
        except Exception:
            return None

    async def ensure_wolf_channel(self) -> Optional[discord.TextChannel]:
        wolves: list[discord.Member] = []
        for uid in self.alive_wolves():
            member = self.guild.get_member(int(uid))
            if member is None:
                try:
                    member = await self.guild.fetch_member(int(uid))
                except Exception:
                    member = None
            if member:
                wolves.append(member)

        ch = await self.ensure_private_channel(
            name=_prefixed_channel_name("wolves-", self.base_name),
            members=wolves,
            category=self.base_category,
            topic="Phòng riêng của bầy sói",
        )
        self.wolf_channel = ch
        if self.wolf_channel and self.base_position is not None:
            try:
                await self.wolf_channel.edit(position=self.base_position + 1)
            except Exception:
                pass
        
        await self.ensure_dead_channel()
        await self.sync_dead_channel("night")

        return self.wolf_channel

    async def ensure_dead_channel(self) -> Optional[discord.TextChannel]:
        guild = self.guild

        # 1) nếu chưa cache thì tìm
        if self.dead_channel is None:
            self.dead_channel = next(
                (c for c in guild.text_channels if c.name.lower() == "dead"),
                None
            )

        # 2) nếu vẫn không có → tạo mới
        if self.dead_channel is None:
            overwrites = {
                guild.default_role: discord.PermissionOverwrite(
                    read_messages=False
                ),
                guild.me: discord.PermissionOverwrite(
                    read_messages=True,
                    send_messages=True
                )
            }

            # role Dead luôn được vào
            dead_role = discord.utils.get(guild.roles, name="Dead")
            if dead_role:
                overwrites[dead_role] = discord.PermissionOverwrite(
                    read_messages=True,
                    send_messages=True
                )

            self.dead_channel = await guild.create_text_channel(
                name="dead",
                overwrites=overwrites
            )

        return self.dead_channel

    async def sync_dead_channel(self, phase: str) -> None:
        ch = await self.ensure_dead_channel()
        if ch is None:
            return

        try:
            await ch.set_permissions(
                self.guild.default_role,
                view_channel=False,
                send_messages=False,
                read_message_history=False,
                reason="Werewolf dead channel lock",
            )
        except Exception:
            pass

        if self.dead_role_id:
            role = self.guild.get_role(self.dead_role_id)
            if role:
                try:
                    await ch.set_permissions(
                        role,
                        view_channel=True,
                        send_messages=True,
                        read_message_history=True,
                        reason="Werewolf dead channel dead-role access",
                    )
                except Exception:
                    pass

        medium_ids = [
            uid for uid, pdata in self.players.items()
            if pdata.get("alive") and pdata.get("role") == "medium" and self.round_no >= 2 and phase == "night"
        ]
        for uid in medium_ids:
            member = self.guild.get_member(int(uid))
            if member is None:
                try:
                    member = await self.guild.fetch_member(int(uid))
                except Exception:
                    member = None
            if member:
                try:
                    await ch.set_permissions(
                        member,
                        view_channel=True,
                        send_messages=True,
                        read_message_history=True,
                        reason="Werewolf medium dead-channel access",
                    )
                except Exception:
                    pass

    async def close_jail_room(self, clear_state: bool = True):
        if self.jail_channel:
            try:
                await self.jail_channel.delete(reason="Werewolf: close jail room")
            except Exception:
                pass

        self.jail_channel = None

        if clear_state:
            self.jailer_id = None
            self.jail_target_id = None

    async def open_jail_room(self) -> None:
        # Chỉ gỡ kênh giam cũ; không gọi close_jail_room() — hàm đó xóa jail_target_id
        # mà apply_action_plan vừa gán, khiến phòng giam không mở và is_jailed sai.
        if self.jail_target_id is None:
            return

        target = self.players.get(str(self.jail_target_id))
        if not target or not target.get("alive"):
            return

        jailer_uid = next((uid for uid, p in self.players.items() if p.get("alive") and p.get("role") == "jailer"), None)
        if jailer_uid is None:
            return
        self.jailer_id = int(jailer_uid)

        jailer = self.guild.get_member(int(jailer_uid))
        if jailer is None:
            try:
                jailer = await self.guild.fetch_member(int(jailer_uid))
            except Exception:
                jailer = None

        prisoner = self.guild.get_member(int(self.jail_target_id))
        if prisoner is None:
            try:
                prisoner = await self.guild.fetch_member(int(self.jail_target_id))
            except Exception:
                prisoner = None

        members = [m for m in (jailer, prisoner) if m is not None]
        if not members:
            return

        self.jail_channel = await self.ensure_private_channel(
            name=_prefixed_channel_name("jail-", self.base_name),
            members=members,
            category=self.base_category,
            topic="Phòng giam riêng cho quản ngục và tù nhân",
        )
        if self.jail_channel and self.base_position is not None:
            try:
                await self.jail_channel.edit(position=self.base_position + 2)
            except Exception:
                pass

        if self.jail_channel:
            try:
                target_name = target.get("name", "Unknown")
                await self.jail_channel.send(
                    embed=discord.Embed(
                        title="🔒 Phòng giam đã mở",
                        description=(
                            f"**{target_name}** đã bị **Quản ngục** giam trong đêm nay.\n"
                            "Quản ngục có thể nhắn ẩn danh bằng nút bên dưới.\n"
                            "Người bị giam không thể dùng kỹ năng trong đêm này."
                        ),
                        color=discord.Color.dark_grey(),
                    ),
                    view=JailAnonymousView(self),
                )
            except Exception:
                pass
    async def apply_dead_role(self, uid: str) -> None:
        self.dead_members.add(uid)
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
        if member:
            try:
                await member.add_roles(role, reason="Werewolf: player died")
            except Exception:
                pass

    async def clear_dead_role(self) -> None:
        if not self.dead_role_id:
            return
        role = self.guild.get_role(self.dead_role_id)
        if not role:
            return
        for uid in list(self.dead_members):
            member = self.guild.get_member(int(uid))
            if member is None:
                try:
                    member = await self.guild.fetch_member(int(uid))
                except Exception:
                    member = None
            if member:
                try:
                    await member.remove_roles(role, reason="Werewolf: cleanup after match")
                except Exception:
                    pass
        self.dead_members.clear()

    async def _send_death_reveal(self, uid: str, reason: str) -> None:
        p = self.players.get(uid)
        if not p:
            return
        e = discord.Embed(
            title="💀 Người chơi đã chết",
            description=f"**{p['name']}** {reason}",
            color=discord.Color.dark_red(),
        )
        e.add_field(name="Vai trò", value=self.role_label(p.get("role", DEFAULT_ROLE_KEY)), inline=True)
        e.add_field(name="Phe", value=self.team_label(p.get("role", DEFAULT_ROLE_KEY)), inline=True)
        try:
            await self.channel.send(embed=e)
        except Exception:
            pass

    async def kill_player(self, uid: str, announce_reason: str, *, cause: str | None = None, reveal: bool = True) -> Optional[dict[str, Any]]:
        p = self.players.get(uid)
        if not p or not p.get("alive"):
            return None

        p["alive"] = False
        p["nightmare_locked"] = False
        # self.active_protections.pop(uid, None)
        await self.apply_dead_role(uid)

        ro = p.get("role_obj")
        if ro is not None:
            try:
                await ro.on_death(self)
            except Exception:
                pass

        if reveal and not p.get("revealed_role"):
            p["revealed_role"] = True
            await self._send_death_reveal(uid, announce_reason)

        await self.sync_public_permissions(self.phase)
        await self.sync_wolf_permissions(self.phase)
        await self.sync_dead_channel(self.phase)
        return p

    async def revive_player(self, uid: str, source_role_key: str | None = None) -> bool:
        p = self.players.get(str(uid))
        if not p or p.get("alive"):
            return False
        # Bỏ giới hạn chỉ revive phe village
        p["alive"] = True
        p["nightmare_locked"] = False
        p["revealed_role"] = False

        if self.dead_role_id:
            role = self.guild.get_role(self.dead_role_id)
            if role:
                member = self.guild.get_member(int(uid))
                if member is None:
                    try:
                        member = await self.guild.fetch_member(int(uid))
                    except Exception:
                        member = None
                if member:
                    try:
                        await member.remove_roles(role, reason="Werewolf: revived")
                    except Exception:
                        pass

        try:
            await self.channel.send(f"✨ **{p['name']}** đã được hồi sinh bởi Thầy Đồng.")
        except Exception:
            pass

        await self.sync_public_permissions(self.phase)
        await self.sync_wolf_permissions(self.phase)
        await self.sync_dead_channel(self.phase)
        return True

    async def _notify_wolves(self, embed: discord.Embed) -> None:
        if self.wolf_channel:
            try:
                await self.wolf_channel.send(embed=embed)
            except Exception:
                pass
    async def _wolf_cannot_kill_embed(self) -> None:
        e = discord.Embed(
            title="🛡️ Mục tiêu không thể bị giết",
            description="Người này không thể bị giết bởi ma sói.",
            color=discord.Color.dark_red(),
        )
        try:
            await self._notify_wolves(e)
        except Exception:
            pass
    async def _notify_protector_shield_broken(self, protector_id):
        try:
            user = self.bot.get_user(int(protector_id))

            # 🔥 fallback nếu không có trong cache
            if user is None:
                user = await self.bot.fetch_user(int(protector_id))

            if user:
                await user.send(
                    embed=discord.Embed(
                        title="🛡️ Khiên bị phá",
                        description="Khiên của bạn đã bị phá! Nếu bị tấn công lần nữa, bạn sẽ chết.",
                        color=discord.Color.orange(),
                    )
                )
        except Exception as e:
            print(f"[DM ERROR] Cannot send to protector: {e}")
    async def resolve_kill_event(
        self,
        target_id: object,
        source_role_key: str | None = None,
        actor_id: object | None = None,
    ) -> bool:
        try:
            tid = str(int(target_id))
        except Exception:
            return False

        victim = self.players.get(tid)
        if not victim or not victim.get("alive"):
            return False

        victim_role = victim.get("role", DEFAULT_ROLE_KEY)
        is_wolf_attack = source_role_key in {"wolf", "wolf_vote", "wolf_attack"}

        # Nếu là serial_killer bị sói cắn thì miễn nhiễm
        if is_wolf_attack and victim_role == "serial_killer":
            await self._wolf_cannot_kill_embed()
            return False
        
        # 🔒 Nếu đang bị giam → miễn nhiễm với kill bên ngoài
        if self.is_jailed(target_id):
            if source_role_key != "jailer":
                return

        # --- Protector redirect logic ---
        # Nếu có BV còn sống và đang bảo vệ ai đó
        if self.protector_id and self.protector_target_id:
            bv = self.players.get(self.protector_id)
            bv_alive = bv and bv.get("alive")
            # Nếu target là người được bảo vệ và BV còn sống
            if tid == self.protector_target_id and bv_alive:
                # Nếu cùng đêm BV cũng bị tấn công: BV chỉ tự cứu mình, target không được redirect
                if hasattr(self, "_attacked_this_night") and self._attacked_this_night.get(self.protector_id):
                    # Không redirect, target vẫn chết bình thường
                    pass
                else:
                    # Redirect damage về BV
                    # Nếu BV còn khiên: mất khiên, không chết
                    if not self.shield_used:
                        self.shield_used = True
                        await self._notify_protector_shield_broken(self.protector_id)
                        try:
                            if is_wolf_attack:
                                await self._wolf_cannot_kill_embed()
                        except Exception:
                            pass
                            if is_wolf_attack:
                                await self._wolf_cannot_kill_embed()
                        return False
                    # Nếu BV đã mất khiên: BV chết luôn
                    else:
                        await self.kill_player(self.protector_id, f"đã chết khi bảo vệ **{victim['name']}**.", cause=source_role_key)
                        self.protector_target_id = None
                        return True

        # Nếu target là BV
        if self.protector_id and tid == self.protector_id:
            # Nếu còn khiên: không chết, mất khiên
            if not self.shield_used:
                self.shield_used = True
                await self._notify_protector_shield_broken(self.protector_id)
                try:
                    if is_wolf_attack:
                        await self._wolf_cannot_kill_embed()
                except Exception:
                    pass
                if is_wolf_attack:
                    if is_wolf_attack:
                        await self._wolf_cannot_kill_embed()
                return False
            # Nếu đã mất khiên: chết
            else:
                bv_name = bv["name"]
                target_name = victim["name"]

                await self.channel.send(
                    embed=discord.Embed(
                        title="💀 Bảo vệ đã chết",
                        description=f"**{bv_name}** đã chết khi cố bảo vệ **{target_name}**.",
                        color=discord.Color.orange(),
                    )
                )

                await self.kill_player(
                    self.protector_id,
                    f"đã chết khi bảo vệ **{victim['name']}**.",
                    cause=source_role_key
                )
                # Khi BV chết, xóa trạng thái bảo vệ
                self.protector_target_id = None
                return True

        # Nếu không dính các trường hợp trên, xử lý giết bình thường
        await self.kill_player(tid, f"đã chết do {source_role_key or 'một đòn tấn công'}.", cause=source_role_key)
        # Nếu BV chết, xóa trạng thái bảo vệ
        if self.protector_id and tid == self.protector_id:
            self.protector_target_id = None
        return True

    def _resolve_wolf_vote(self) -> Optional[str]:
        if not self.night_votes:
            return None
        counts = _tally(self.night_votes)
        top = max(counts.values())
        targets = [uid for uid, amount in counts.items() if amount == top]
        return random.choice(targets) if targets else None

    async def resolve_night(self) -> list[str]:
        before_alive = {uid for uid, p in self.players.items() if p.get("alive")}

        actions = build_night_actions(self) if callable(build_night_actions) else []
        wolf_target = self._resolve_wolf_vote()
        if wolf_target is not None:
            actions.append(
                {
                    "type": "kill",
                    "actor": None,
                    "actor_id": None,
                    "target_id": wolf_target,
                    "priority": 3,
                    "role_key": "wolf_vote",
                }
            )

        plan = resolve_actions(self, actions) if callable(resolve_actions) else {
            "kills": [],
            "public_messages": [],
            "private_dms": [],
            "inspect_results": [],
            "protects": [],
            "revives": [],
            "jail_target_id": None,
            "wolf_shaman_cover_target_id": None,
            "nightmare_token_target_id": None,
        }

        # --- Protector: xác định ai bị attack trong đêm ---
        self._attacked_this_night = {}
        for kill in plan.get("kills", []):
            tid = str(kill.get("target_id"))
            self._attacked_this_night[tid] = True

        if callable(apply_action_plan):
            await apply_action_plan(self, plan)

        after_alive = {uid for uid, p in self.players.items() if p.get("alive")}
        dead_ids = [uid for uid in before_alive if uid not in after_alive]

        if not dead_ids:
            await self.channel.send("🌙 Đêm qua không có ai bị giết.")
            return []

        names = [self.players[uid]["name"] for uid in dead_ids if uid in self.players]
        if names:
            await self.channel.send("💀 " + ", ".join(f"**{n}**" for n in names) + " đã chết trong đêm.")
        return dead_ids

    async def resolve_day(self) -> Optional[str]:
        if not self.day_votes:
            await self.channel.send("☀️ Không ai vote nên không ai chết.")
            return None

        counts = _tally(self.day_votes)
        top = max(counts.values())
        targets = [uid for uid, amount in counts.items() if amount == top]

        if len(targets) != 1:
            await self.channel.send("⚖️ Phiếu bị hòa nên không ai chết.")
            return None

        victim_id = targets[0]
        victim = self.players.get(victim_id)
        if victim is None:
            return None

        if victim.get("role") == "jester":
            await self.kill_player(victim_id, "đã bị treo cổ và thắng ván đấu.", cause="day_hang")
            await self._end_game("🎭 **Thằng ngố** đã bị treo cổ và thắng ván đấu!")
            return victim["name"]

        await self.kill_player(victim_id, "đã chết vì bị treo cổ.", cause="day_hang")
        try:
            await self.channel.send(f"💀 **{victim['name']}** đã chết vì bị treo cổ.")
        except Exception:
            pass
        return victim["name"]

    def _solo_survivor(self) -> Optional[str]:
        alive = self.alive_players()
        if len(alive) != 1:
            return None
        uid = alive[0]
        if self.players[uid].get("role") == "serial_killer":
            return uid
        return None

    def check_win(self) -> bool:

        if self.finished:

            return True


        wolves = len(self.alive_wolves())

        villagers = len(self.alive_villagers())

        serial_killer_alive = any(

            p.get("alive") and p.get("role") == "serial_killer"

            for p in self.players.values()

        )

        alive_players = self.alive_players()


        # Chỉ còn 1 người sống thì chốt luôn kết quả.

        if len(alive_players) == 1:

            only_uid = alive_players[0]

            only_role = self.players.get(only_uid, {}).get("role")

            if only_role == "serial_killer":

                asyncio.create_task(

                    self._end_game(f"🏆 **{self.players[only_uid]['name']}** (Phe Solo) đã thắng!")

                )

            elif self.role_team(only_role) == TEAM_WOLF:

                asyncio.create_task(self._end_game("🐺 **Ma Sói thắng!**"))

            else:

                asyncio.create_task(self._end_game("🏆 **Dân làng thắng!**"))

            return True


        # Hết sói

        if wolves == 0:

            if serial_killer_alive:

                # Solo vẫn còn sống cùng người khác thì để game tiếp tục.

                if villagers == 0:

                    solo_survivor = self._solo_survivor()

                    if solo_survivor is not None:

                        asyncio.create_task(

                            self._end_game(f"🏆 **{self.players[solo_survivor]['name']}** (Solo) đã thắng!")

                        )

                    else:

                        asyncio.create_task(self._end_game("🏆 Ván đấu kết thúc."))

                    return True

                return False


            if villagers > 0:

                asyncio.create_task(self._end_game("🏆 **Dân làng thắng!**"))

                return True


            asyncio.create_task(self._end_game("🏆 Ván đấu kết thúc."))

            return True


        # Hết dân làng

        if villagers == 0:

            if serial_killer_alive:

                return False

            asyncio.create_task(self._end_game("🐺 **Ma Sói thắng!**"))

            return True


        # Sói đạt áp đảo

        if wolves >= villagers:

            asyncio.create_task(self._end_game("🐺 **Ma Sói thắng!**"))

            return True


        return False


    async def _end_game(self, message: str) -> None:


        if self.finished:


            return


        self.finished = True


        self.active = False


        try:


            await self.channel.send(message)


        except Exception:


            pass



        try:


            await self.end_and_restart_lobby()


        except Exception:


            pass


    async def end_and_restart_lobby(self) -> None:


        self.active = False



        try:


            await self.clear_dead_role()


        except Exception:


            pass


        try:


            await self.close_jail_room()


        except Exception:


            pass



        old_channel = self.channel


        old_dead_channel = self.dead_channel


        old_wolf_channel = self.wolf_channel



        self.wolf_channel = None


        self.dead_channel = None


        self.wolf_vote_message = None


        self.lobby_message = None



        if old_wolf_channel:


            try:


                await old_wolf_channel.delete(reason="Werewolf: cleanup wolf channel")


            except Exception:


                pass



        if old_dead_channel and old_dead_channel != old_channel:


            try:


                await old_dead_channel.delete(reason="Werewolf: cleanup dead channel")


            except Exception:


                pass



        new_channel = None


        try:


            new_channel = await self.guild.create_text_channel(


                name=self.base_name,


                category=self.base_category,


                topic=self.base_topic,


                slowmode_delay=self.base_slowmode,


                nsfw=self.base_nsfw,


                overwrites=self.base_overwrites,


                reason="Werewolf: recreate lobby channel cleanly",


            )


            if self.base_position is not None:


                try:


                    await new_channel.edit(position=self.base_position)


                except Exception:


                    pass


        except Exception:


            new_channel = None



        if old_channel and old_channel != new_channel:


            try:


                await old_channel.delete(reason="Werewolf: nuke old lobby channel")


            except Exception:


                pass



        if new_channel is None:


            return



        bot_member = _bot_member(self.guild, self.bot)


        if bot_member:


            try:


                await new_channel.set_permissions(


                    bot_member,


                    view_channel=True,


                    send_messages=True,


                    read_message_history=True,


                    embed_links=True,


                    attach_files=True,


                    add_reactions=True,


                    reason="Werewolf: ensure bot access",


                )


            except Exception:


                pass



        fresh = WerewolfSession(self.bot, self.guild, new_channel, self.dead_role_id)


        if old_channel is not None:


            GAME.pop(old_channel.id, None)


        GAME[new_channel.id] = fresh


        await fresh.post_lobby_panel()


        try:


            await new_channel.send("🧼 Phòng đã được làm mới để bắt đầu ván mới.")


        except Exception:


            pass


    async def post_lobby_panel(self, ctx=None) -> None:
        if ctx is None:
            self.lobby_message = await self.channel.send(embed=self.render_lobby_embed(), view=LobbyView(self))
        else:
            self.lobby_message = await send(ctx, embed=self.render_lobby_embed(), view=LobbyView(self))

    async def send_role_catalog(self) -> None:
        try:
            await self.channel.send(embed=self.render_role_catalog_embed())
        except Exception:
            pass

    async def start(self) -> None:
        async with self._lock:
            if self.phase != "lobby":
                return
            if not self.can_start():
                return

            await self.assign_roles()
            await self.call_role_start_hooks()
            self.phase = "night"

        await self.send_role_catalog()
        await self.ensure_wolf_channel()
        await self.sync_public_permissions("night")
        await self.sync_wolf_permissions("night")
        await self.sync_dead_channel("night")
        await self._call_phase_hook("on_night_start")

        self.night_deadline_at = int(time.time()) + NIGHT_VOTE_SECONDS
        await self.replace_phase_message("night", "🌙 Màn đêm bắt đầu. Kênh chính đã bị khóa.")
        await self.run_game_loop()

    async def _sync_day_start(self) -> None:
        await self.close_jail_room()
        await self.sync_public_permissions("day")
        await self.sync_wolf_permissions("day")
        await self.sync_dead_channel("day")
        await self._call_phase_hook("on_day_start")

    async def _sync_night_start(self) -> None:
        await self.sync_public_permissions("night")
        await self.sync_wolf_permissions("night")
        await self.sync_dead_channel("night")
        await self._call_phase_hook("on_night_start")

    async def run_game_loop(self) -> None:
        while self.active:
            if self.check_win():
                break

            self.phase = "night"
            self.night_deadline_at = int(time.time()) + NIGHT_VOTE_SECONDS
            self.night_votes = {}
            self.day_votes = {}

            await self._sync_night_start()
            await self.replace_phase_message("night", "🌙 Đêm xuống. Sói có thể vote và dùng kỹ năng.")
            while time.time() < self.night_deadline_at and self.active:
                await asyncio.sleep(1)

            if not self.active:
                break

            await self.resolve_night()
            if self.check_win() or not self.active:
                break

            self.phase = "day"
            self.discussion_deadline_at = int(time.time()) + DAY_DISCUSSION_SECONDS
            self.vote_deadline_at = self.discussion_deadline_at + DAY_VOTE_SECONDS
            await self._sync_day_start()
            await self.replace_phase_message("day", "☀️ Ban ngày bắt đầu.\nThảo luận trước khi vote.")
            while time.time() < self.discussion_deadline_at and self.active:
                await asyncio.sleep(1)

            if not self.active:
                break
            vote_announcement = "Bắt đầu vote ban ngày."
            await self.refresh_phase_message("day", vote_announcement)
            self._last_day_vote_state = self._day_vote_snapshot()

            while time.time() < self.vote_deadline_at and self.active:
                await asyncio.sleep(1)
                await self._refresh_day_vote_panel_if_changed(vote_announcement)

            # 🔥 QUAN TRỌNG NHẤT
            await self.resolve_day()

            self.day_votes.clear()

            if self.check_win() or not self.active:
                break

            self.round_no += 1
    async def sync_public_permissions(self, phase: str) -> None:
        # 1. Default role (mọi người)
        try:
         await self.channel.set_permissions(
                self.guild.default_role,
                view_channel=True,                  # vẫn thấy channel
                send_messages=False,                # không cho chat mặc định
                read_message_history=True,
                reason="Werewolf public base lock",
            )
        except Exception:
            pass

        # 2. Player override
        for uid, pdata in self.players.items():
            member = self.guild.get_member(int(uid))
            if member is None:
                try:
                    member = await self.guild.fetch_member(int(uid))
                except Exception:
                    continue

            alive = pdata.get("alive", False)

            try:
                await self.channel.set_permissions(
                    member,
                    view_channel=True,
                    send_messages=(phase == "day" and alive),
                    read_message_history=True,
                    reason="Werewolf player override",
                )
            except Exception:
                pass
    async def sync_wolf_permissions(self, phase: str) -> None:
        if not self.wolf_channel:
            return
        try:
            await self.wolf_channel.set_permissions(
                self.guild.default_role,
                view_channel=False,
                send_messages=False,
                read_message_history=False,
                reason="Werewolf wolf channel lock",
            )
        except Exception:
            pass

        for uid, pdata in self.players.items():
            member = self.guild.get_member(int(uid))
            if member is None:
                try:
                    member = await self.guild.fetch_member(int(uid))
                except Exception:
                    member = None
            if member is None:
                continue
            is_wolf = pdata.get("alive") and self.role_team(pdata.get("role", DEFAULT_ROLE_KEY)) == TEAM_WOLF
            try:
                await self.wolf_channel.set_permissions(
                    member,
                    view_channel=is_wolf,
                    send_messages=is_wolf and phase == "night",
                    read_message_history=is_wolf,
                    embed_links=is_wolf,
                    attach_files=is_wolf,
                    add_reactions=is_wolf,
                    reason="Werewolf wolf channel sync",
                )
            except Exception:
                pass

        bot_member = _bot_member(self.guild, self.bot)
        if bot_member:
            try:
                await self.wolf_channel.set_permissions(
                    bot_member,
                    view_channel=True,
                    send_messages=True,
                    read_message_history=True,
                    embed_links=True,
                    attach_files=True,
                    add_reactions=True,
                    reason="Werewolf bot access wolf channel",
                )
            except Exception:
                pass

    async def sync_dead_channel(self, phase: str) -> None:
        ch = await self.ensure_dead_channel()
        if ch is None:
            return

        try:
            await ch.set_permissions(
                self.guild.default_role,
                view_channel=False,
                send_messages=False,
                read_message_history=False,
                reason="Werewolf dead channel lock",
            )
        except Exception:
            pass

        if self.dead_role_id:
            role = self.guild.get_role(self.dead_role_id)
            if role:
                try:
                    await ch.set_permissions(
                        role,
                        view_channel=True,
                        send_messages=True,
                        read_message_history=True,
                        reason="Werewolf dead channel dead-role access",
                    )
                except Exception:
                    pass

        if phase == "night" and self.round_no >= 2:
            for uid, pdata in self.players.items():
                if pdata.get("alive") and pdata.get("role") == "medium":
                    member = self.guild.get_member(int(uid))
                    if member is None:
                        try:
                            member = await self.guild.fetch_member(int(uid))
                        except Exception:
                            member = None
                    if member:
                        try:
                            await ch.set_permissions(
                                member,
                                view_channel=True,
                                send_messages=True,
                                read_message_history=True,
                                reason="Werewolf medium dead-channel access",
                            )
                        except Exception:
                            pass


class LobbyView(View):
    def __init__(self, session: WerewolfSession):
        super().__init__(timeout=None)
        self.session = session

    @discord.ui.button(label="Join", style=discord.ButtonStyle.success, emoji="✅")
    async def join_button(self, interaction: discord.Interaction, button: Button):
        if self.session.phase != "lobby":
            return await interaction.response.send_message("❌ Ván đã bắt đầu rồi.", ephemeral=True)
        if len(self.session.players) >= MAX_PLAYERS:
            return await interaction.response.send_message("❌ Phòng đã đủ 16 người.", ephemeral=True)
        if not self.session.add_player(interaction.user):
            return await interaction.response.send_message("❌ Bạn đã tham gia rồi.", ephemeral=True)
        await interaction.response.send_message("✅ Đã tham gia phòng.", ephemeral=True)
        await self.session.refresh_lobby_panel()
        await self.session.notify_host_join(interaction.user)

    @discord.ui.button(label="Start", style=discord.ButtonStyle.danger, emoji="🚀")
    async def start_button(self, interaction: discord.Interaction, button: Button):
        if self.session.phase != "lobby":
            return await interaction.response.send_message("❌ Ván đã bắt đầu rồi.", ephemeral=True)
        if not self.session.can_start():
            return await interaction.response.send_message(f"❌ Cần ít nhất {MIN_PLAYERS} người để bắt đầu.", ephemeral=True)
        if self.session.host_id != str(interaction.user.id):
            return await interaction.response.send_message("❌ Chỉ chủ phòng mới được bấm Start.", ephemeral=True)
        await interaction.response.send_message("🚀 Đang khởi động ván đấu...", ephemeral=True)
        asyncio.create_task(self.session.start())


class VoteSelect(Select):
    def __init__(self, session: WerewolfSession, phase: str):
        self.session = session
        self.phase = phase

        if phase == "night":
            target_ids = [
                uid for uid in session.alive_players()
                if uid not in session.alive_wolves()
                and session.players[uid].get("role") != "serial_killer"
            ]
            placeholder = "Chọn người bị Ma Sói giết"
        else:
            target_ids = session.alive_players()
            placeholder = "Chọn người bị vote ban ngày"

        options = []
        for uid in target_ids[:25]:
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

        super().__init__(placeholder=placeholder, min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        uid = str(interaction.user.id)
        player = self.session.get_player(uid)
        if not player or not player.get("alive"):
            return await interaction.response.send_message("❌ Bạn đã chết rồi.", ephemeral=True)

        if self.phase == "night" and not self.session.is_alive_wolf(uid):
            return await interaction.response.send_message("❌ Chỉ sói mới được vote vào ban đêm.", ephemeral=True)

        target_id = self.values[0]
        target = self.session.players.get(target_id)
        if not target or not target.get("alive"):
            return await interaction.response.send_message("❌ Người này đã chết rồi.", ephemeral=True)

        if self.phase == "night":
            self.session.night_votes[uid] = target_id
            return await interaction.response.send_message(f"✅ Bạn đã chọn **{target['name']}**.", ephemeral=True)

        self.session.day_votes[uid] = target_id
        return await interaction.response.send_message(f"✅ Bạn đã vote cho **{target['name']}**.", ephemeral=True)


class VoteSelectView(View):
    def __init__(self, session: WerewolfSession, phase: str):
        super().__init__(timeout=120)
        self.add_item(VoteSelect(session, phase))


class SkillTargetSelect(Select):
    def __init__(self, session: WerewolfSession, phase: str, role_obj, skill_key: str):
        self.session = session
        self.phase = phase
        self.role_obj = role_obj
        self.skill_key = skill_key

        targets = role_obj.skill_targets(session, phase, skill_key=skill_key) if role_obj else []
        options = []
        for uid in targets[:25]:
            player = session.players.get(uid)
            if not player or not player.get("alive"):
                continue
            options.append(
                discord.SelectOption(
                    label=player["name"][:100],
                    value=uid,
                    description="Chọn mục tiêu dùng kỹ năng",
                )
            )

        super().__init__(
            placeholder=f"Chọn mục tiêu cho {skill_key}",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction):
        _skill_agent_log("H-enter", "SkillTargetSelect.callback", {"skill": self.skill_key})
        uid = str(interaction.user.id)
        player = self.session.get_player(uid)
        if not player or not player.get("alive"):
            return await interaction.response.send_message("❌ Bạn đã chết rồi.", ephemeral=True)

        role_obj = player.get("role_obj")
        if role_obj is None:
            return await interaction.response.send_message("❌ Không có kỹ năng.", ephemeral=True)

        target_id = self.values[0]
        if not role_obj.can_target(self.session, target_id, self.phase, skill_key=self.skill_key):
            return await interaction.response.send_message("❌ Mục tiêu này không hợp lệ.", ephemeral=True)

        action = role_obj.use_skill(self.session, self.skill_key, target_id)
        if action is None:
            return await interaction.response.send_message("❌ Không dùng được kỹ năng này.", ephemeral=True)

        loading_embed = discord.Embed(
            title="⏳ Đang xử lý...",
            description="Vui lòng chờ giây lát.",
            color=discord.Color.light_grey(),
        )
        # Phải ack trong ~3s: ưu tiên edit tin có Select; nếu API từ chối (ephemeral/edge) thì defer.
        ack_mode: str | None = None
        try:
            await interaction.response.edit_message(embed=loading_embed, view=None)
            ack_mode = "edit_message"
        except Exception as e:
            _skill_agent_log("H-ack", "edit_message_failed", {"exc_type": type(e).__name__})
            try:
                await interaction.response.defer()
                ack_mode = "defer"
            except Exception as e2:
                _skill_agent_log("H-ack", "defer_also_failed", {"exc_type": type(e2).__name__})
                role_obj.clear_selection()
                try:
                    await interaction.response.send_message(
                        "❌ Không phản hồi được tương tác. Hãy thử lại.",
                        ephemeral=True,
                    )
                except Exception:
                    pass
                return
        _skill_agent_log("H-ack", "skill_interaction_acked", {"mode": ack_mode, "skill": self.skill_key})

        try:
            plan = resolve_actions(self.session, [action]) if callable(resolve_actions) else None
            if plan and callable(apply_action_plan):
                await apply_action_plan(self.session, plan)
            _skill_agent_log("H-plan", "apply_action_plan_ok", {"has_plan": plan is not None})
        except Exception as e:
            _skill_agent_log(
                "H-plan",
                "apply_action_plan_failed",
                {"exc_type": type(e).__name__, "detail": str(e)[:200]},
            )
            role_obj.clear_selection()
            err_embed = discord.Embed(
                title="❌ Lỗi",
                description="Xử lý kỹ năng thất bại. Hãy báo admin nếu lặp lại.",
                color=discord.Color.red(),
            )
            try:
                await interaction.edit_original_response(embed=err_embed, view=None)
            except Exception:
                if interaction.message is not None:
                    try:
                        await interaction.message.edit(embed=err_embed, view=None)
                    except Exception:
                        try:
                            await interaction.followup.send(embed=err_embed, ephemeral=True)
                        except Exception:
                            pass
                else:
                    try:
                        await interaction.followup.send(embed=err_embed, ephemeral=True)
                    except Exception:
                        pass
            return

        target = self.session.players.get(target_id)
        target_role_name = self.session.role_label(target["role"]) if target else "Unknown"

        if self.skill_key in {"inspect", "inspect_guard"}:
            result_embed = discord.Embed(
                title="🔍 Kết quả soi",
                description=f"**{target['name']}** là **{target_role_name}**." if target else "Không xác định.",
                color=discord.Color.green(),
            )
        elif self.skill_key == "shoot":
            result_embed = discord.Embed(
                title="🔫 Đã bắn",
                description=f"Bạn đã bắn **{target['name']}**." if target else "Không xác định.",
                color=discord.Color.red(),
            )
        elif self.skill_key == "nightmare":
            result_embed = discord.Embed(
                title="🌑 Ác mộng đã gắn",
                description=f"Token ác mộng đã chuyển sang **{target['name']}**." if target else "Không xác định.",
                color=discord.Color.dark_red(),
            )
        else:
            result_embed = discord.Embed(
                title="✅ Kỹ năng đã dùng",
                description=f"Bạn đã dùng **{self.skill_key}** lên **{target['name']}**." if target else "Không xác định.",
                color=discord.Color.blurple(),
            )

        role_obj.clear_selection()
        edited = False
        edit_route = None
        try:
            await interaction.edit_original_response(embed=result_embed, view=None)
            edited = True
            edit_route = "edit_original_response"
        except Exception as e:
            _skill_agent_log("H-result", "edit_original_failed", {"exc_type": type(e).__name__})
        if not edited and interaction.message is not None:
            try:
                await interaction.message.edit(embed=result_embed, view=None)
                edited = True
                edit_route = "message.edit"
            except Exception as e:
                _skill_agent_log("H-result", "message_edit_failed", {"exc_type": type(e).__name__})
        if not edited:
            try:
                await interaction.followup.send(embed=result_embed, ephemeral=True)
                edited = True
                edit_route = "followup.send"
            except Exception as e:
                _skill_agent_log("H-result", "followup_failed", {"exc_type": type(e).__name__})
        if edit_route:
            _skill_agent_log("H-result", "result_shown", {"route": edit_route, "skill": self.skill_key})


class SkillTargetView(View):
    def __init__(self, session: WerewolfSession, phase: str, role_obj, skill_key: str):
        super().__init__(timeout=120)
        self.add_item(SkillTargetSelect(session, phase, role_obj, skill_key))


class SkillChoiceSelect(Select):
    def __init__(self, session, phase, role_obj, options):
        self.session = session
        self.phase = phase
        self.role_obj = role_obj

        select_options = [
            discord.SelectOption(
                label=opt["label"],
                description=opt["description"],
                value=opt["key"]
            )
            for opt in options
        ]

        super().__init__(
            placeholder="Chọn kỹ năng...",
            min_values=1,
            max_values=1,
            options=select_options
        )
    async def callback(self, interaction: discord.Interaction):
        skill_key = self.values[0]

        targets = self.role_obj.skill_targets(self.session, self.phase, skill_key)

        if not targets:
            return await interaction.response.send_message(
                "❌ Không có mục tiêu hợp lệ.",
                ephemeral=True
            )

        self.role_obj.set_skill(skill_key)

        await interaction.response.send_message(
            embed=discord.Embed(
                title=f"✨ {self.role_obj.name}",
                description="Chọn mục tiêu.",
                color=discord.Color.gold(),
            ),
            view=SkillTargetView(self.session, self.phase, self.role_obj, skill_key),
            ephemeral=True
        )

class SkillChoiceView(View):
    def __init__(self, session: WerewolfSession, phase: str, role_obj, options):
        super().__init__(timeout=120)
        self.add_item(SkillChoiceSelect(session, phase, role_obj, options))

class GameActionView(View):
    def __init__(self, session: WerewolfSession, phase: str):
        super().__init__(timeout=180)
        self.session = session
        self.phase = phase

    @discord.ui.button(label="Vote", style=discord.ButtonStyle.success, emoji="🗳️")
    async def vote_button(self, interaction: discord.Interaction, button: Button):
        if self.phase == "night" and not self.session.is_alive_wolf(interaction.user.id):
            return await interaction.response.send_message("❌ Chỉ sói còn sống mới vote vào ban đêm.", ephemeral=True)
        if self.phase == "day" and not self.session.is_alive(interaction.user.id):
            return await interaction.response.send_message("❌ Bạn đã chết rồi.", ephemeral=True)

        await interaction.response.send_message(
            embed=discord.Embed(
                title="Chọn mục tiêu vote",
                description="Hãy chọn một người trong danh sách bên dưới.",
                color=discord.Color.blurple(),
            ),
            view=VoteSelectView(self.session, self.phase),
            ephemeral=True,
        )

    @discord.ui.button(label="Skill", style=discord.ButtonStyle.primary, emoji="✨")
    async def skill_button(self, interaction: discord.Interaction, button: Button):
        player = self.session.get_player(interaction.user.id)

        # ❌ chết
        if not player or not player.get("alive"):
            return await interaction.response.send_message(
                "❌ Bạn đã chết rồi.",
                ephemeral=True
            )

        role_obj = player.get("role_obj")

        # ❌ không có role
        if role_obj is None:
            return await interaction.response.send_message(
                "❌ Không có kỹ năng.",
                ephemeral=True
            )

        # 🔹 lấy skill hợp lệ theo phase
        options = role_obj.skill_options(self.phase, game=self.session)

        if not options:
            return await interaction.response.send_message(
                "❌ Vai trò này không có kỹ năng ở pha hiện tại.",
                ephemeral=True
            )

        # 🔥 FILTER skill có target hợp lệ
        valid_options = []
        for opt in options:
            skill_key = opt["key"]
            targets = role_obj.skill_targets(self.session, self.phase, skill_key)

            if targets:
                valid_options.append(opt)

        # ❌ không có skill nào dùng được
        if not valid_options:
            return await interaction.response.send_message(
                "❌ Hiện tại không có kỹ năng nào có thể dùng (có thể do không có mục tiêu, bị khóa, hoặc điều kiện chưa thỏa).",
                ephemeral=True
            )

        # =========================
        # ✅ CHỈ CÓ 1 SKILL
        # =========================
        if len(valid_options) == 1:
            skill = valid_options[0]
            skill_key = skill["key"]

            role_obj.set_skill(skill_key)

            await interaction.response.send_message(
                embed=discord.Embed(
                    title=f"✨ Dùng kỹ năng — {role_obj.name}",
                    description=f"Chọn mục tiêu cho **{skill['label']}**.",
                    color=discord.Color.gold(),
                ),
                view=SkillTargetView(self.session, self.phase, role_obj, skill_key),
                ephemeral=True,
            )
            return

        # =========================
        # ✅ NHIỀU SKILL
        # =========================

        # custom view để truyền valid_options vào
        view = SkillChoiceView(self.session, self.phase, role_obj, valid_options)

        # ❌ double check tránh crash
        has_select = any(
            isinstance(child, Select) and getattr(child, "options", None)
            for child in view.children
        )

        if not has_select:
            return await interaction.response.send_message(
                "❌ Không có kỹ năng hợp lệ để chọn.",
                ephemeral=True
            )

        await interaction.response.send_message(
            embed=discord.Embed(
                title=f"✨ Dùng kỹ năng — {role_obj.name}",
                description="Chọn kỹ năng bạn muốn dùng.",
                color=discord.Color.gold(),
            ),
            view=view,
            ephemeral=True,
        )

async def werewolf_logic(ctx, channel_id, role_dead=None):
    guild = getattr(ctx, "guild", None)
    if guild is None:
        return await send(ctx, content="❌ Lệnh này chỉ dùng trong server.")
    if not _is_admin(getattr(ctx, "author", None) or getattr(ctx, "user", None)):
        return await send(ctx, content="❌ Chỉ admin mới được dùng lệnh này.")

    channel_id_int = _parse_id(channel_id)
    dead_role_id = _parse_id(role_dead)

    if channel_id_int is None:
        return await send(ctx, content="❌ Không tìm thấy kênh hợp lệ.")
    if dead_role_id is None:
        role = discord.utils.find(lambda r: r.name.lower() == "dead", guild.roles)
        if role is not None:
            dead_role_id = role.id

    channel = guild.get_channel(channel_id_int)
    if channel is None:
        try:
            channel = await guild.fetch_channel(channel_id_int)
        except Exception:
            channel = None

    if channel is None or not isinstance(channel, discord.TextChannel):
        return await send(ctx, content="❌ Kênh phải là text channel hợp lệ.")

    if channel.id in GAME and GAME[channel.id].active:
        return await send(ctx, content="❌ Kênh này đang có ván Ma Sói chạy rồi.")

    bot = getattr(ctx, "bot", None) or getattr(ctx, "client", None)
    if bot is None:
        return await send(ctx, content="❌ Không lấy được bot instance.")

    session = WerewolfSession(bot, guild, channel, dead_role_id=dead_role_id)
    GAME[channel.id] = session
    await send(ctx, embed=session.render_lobby_embed(), view=LobbyView(session))