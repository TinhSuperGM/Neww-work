from __future__ import annotations

import asyncio
import random
import time
from collections import Counter
from typing import Optional

import discord
from discord.ui import Button, Select, View

try:
    # Optional future module for role definitions / actions.
    from Commands.role import ROLE_DEFINITIONS, build_role_assignments, build_night_actions
except Exception:  # pragma: no cover - optional module may not exist yet
    ROLE_DEFINITIONS = None
    build_role_assignments = None
    build_night_actions = None


MIN_PLAYERS = 5
MAX_PLAYERS = 16
DAY_DISCUSSION_SECONDS = 60
DAY_VOTE_SECONDS = 30
NIGHT_VOTE_SECONDS = 60

GAME: dict[int, "WerewolfSession"] = {}


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


def _bot_member(guild: discord.Guild, bot: discord.Client) -> Optional[discord.Member]:
    if bot.user is None:
        return None
    return guild.get_member(bot.user.id)


def _display_name(user: discord.abc.User) -> str:
    return getattr(user, "display_name", None) or getattr(user, "name", "Unknown")


def _is_admin(user: discord.abc.User | None) -> bool:
    perms = getattr(user, "guild_permissions", None)
    return bool(perms and perms.administrator)


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


def _fmt_ts(ts: int | float | None, style: str = "R") -> str:
    if not ts:
        return "—"
    return f"<t:{int(ts)}:{style}>"


def _tally(votes: dict[str, str]) -> Counter:
    return Counter(votes.values()) if votes else Counter()


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

        self.base_name = channel.name
        self.base_topic = channel.topic
        self.base_nsfw = channel.is_nsfw()
        self.base_slowmode = channel.slowmode_delay
        self.base_category = channel.category
        self.base_position = channel.position
        self.base_overwrites = dict(channel.overwrites)

        self.players: dict[str, dict] = {}
        self.dead_members: set[str] = set()
        self.phase: str = "lobby"
        self.round_no: int = 1
        self.host_id: Optional[str] = None

        self.day_votes: dict[str, str] = {}
        self.night_votes: dict[str, str] = {}
        self.special_actions: list[dict] = []

        self.lobby_message: Optional[discord.Message] = None
        self.day_vote_message: Optional[discord.Message] = None
        self.night_vote_message: Optional[discord.Message] = None
        self.wolf_panel_message: Optional[discord.Message] = None
        self.wolf_channel: Optional[discord.TextChannel] = None

        self.last_join_at: Optional[int] = None
        self.day_deadline_at: Optional[int] = None
        self.night_deadline_at: Optional[int] = None
        self.vote_deadline_at: Optional[int] = None
        self.discussion_deadline_at: Optional[int] = None

        self.active = True
        self._lock = asyncio.Lock()

    def add_player(self, user: discord.abc.User) -> bool:
        uid = str(user.id)
        if uid in self.players:
            return False
        if len(self.players) >= MAX_PLAYERS:
            return False

        self.players[uid] = {
            "name": _display_name(user),
            "role": None,
            "alive": True,
        }
        if self.host_id is None:
            self.host_id = uid
        self.last_join_at = int(time.time())
        return True

    def get_player(self, uid: object) -> Optional[dict]:
        return self.players.get(str(uid))

    def alive_players(self) -> list[str]:
        return [uid for uid, data in self.players.items() if data.get("alive")]

    def alive_wolves(self) -> list[str]:
        return [uid for uid, data in self.players.items() if data.get("alive") and data.get("role") == "wolf"]

    def alive_villagers(self) -> list[str]:
        return [uid for uid, data in self.players.items() if data.get("alive") and data.get("role") != "wolf"]

    def is_alive(self, uid: object) -> bool:
        p = self.get_player(uid)
        return bool(p and p.get("alive"))

    def is_alive_wolf(self, uid: object) -> bool:
        p = self.get_player(uid)
        return bool(p and p.get("alive") and p.get("role") == "wolf")

    def can_start(self) -> bool:
        return MIN_PLAYERS <= len(self.players) <= MAX_PLAYERS

    def assign_roles(self) -> None:
        ids = list(self.players.keys())
        random.shuffle(ids)

        if callable(build_role_assignments):
            try:
                role_map = build_role_assignments(ids, self.players)
                if isinstance(role_map, dict) and role_map:
                    for uid, role_key in role_map.items():
                        if uid in self.players:
                            self.players[uid]["role"] = role_key
                    return
            except Exception:
                pass

        wolf_count = max(1, len(ids) // 4)
        wolf_count = min(wolf_count, len(ids) - 1) if len(ids) > 1 else 1
        wolves = set(ids[:wolf_count])

        for uid in ids:
            self.players[uid]["role"] = "wolf" if uid in wolves else "villager"

    def _role_name(self, role_key: str) -> str:
        if ROLE_DEFINITIONS and role_key in ROLE_DEFINITIONS:
            role = ROLE_DEFINITIONS[role_key]
            name = role.get("name") if isinstance(role, dict) else None
            if name:
                return str(name)
        return "🐺 Ma Sói" if role_key == "wolf" else "🧑 Dân làng"

    async def reveal_roles(self) -> None:
        for uid, data in self.players.items():
            try:
                user = self.bot.get_user(int(uid)) or await self.bot.fetch_user(int(uid))
                if not user:
                    continue
                await user.send(
                    f"🎭 Vai trò của bạn là: **{self._role_name(data['role'])}**\n"
                    f"Phòng chơi: **#{self.base_name}**."
                )
            except Exception:
                pass

    def _alive_names(self, uid_list: list[str]) -> list[str]:
        out = []
        for uid in uid_list:
            p = self.players.get(uid)
            if p and p.get("alive"):
                out.append(p["name"])
        return out

    def _vote_summary(self, votes: dict[str, str], phase: str) -> str:
        if not votes:
            return "Chưa có phiếu nào."
        counts = _tally(votes)
        lines = []
        for target_id, amount in counts.most_common():
            target = self.players.get(target_id)
            if not target:
                continue
            lines.append(f"• **{target['name']}** — {amount} phiếu")
        if phase == "night":
            lines.insert(0, "Chỉ sói còn sống mới được vote.")
        else:
            lines.insert(0, "Tất cả người còn sống đều có thể vote.")
        return "\n".join(lines)

    def render_lobby_embed(self) -> discord.Embed:
        embed = discord.Embed(
            title="🐺 Wolvesville Lobby",
            description=(
                "Bấm **Join** để tham gia.\n"
                "Người vào đầu tiên sẽ là **chủ phòng**.\n"
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

    def render_night_embed(self, announcement: str) -> discord.Embed:
        embed = discord.Embed(
            title=f"🌙 Đêm {self.round_no}",
            description=announcement,
            color=discord.Color.dark_red(),
        )
        embed.add_field(name="Người còn sống", value=str(len(self.alive_players())), inline=True)
        embed.add_field(name="Sói còn sống", value=str(len(self.alive_wolves())), inline=True)
        embed.add_field(name="Dân còn sống", value=str(len(self.alive_villagers())), inline=True)
        embed.add_field(name="Kênh sói", value=self.wolf_channel.mention if self.wolf_channel else "Đang tạo...", inline=True)
        embed.add_field(name="Kết thúc vote", value=_fmt_ts(self.night_deadline_at), inline=True)
        embed.set_footer(text="Ban đêm • public channel bị khóa")
        return embed

    def render_day_embed(self, announcement: str) -> discord.Embed:
        embed = discord.Embed(
            title=f"🌞 Ngày {self.round_no}",
            description=announcement,
            color=discord.Color.gold(),
        )
        embed.add_field(name="Người còn sống", value=str(len(self.alive_players())), inline=True)
        embed.add_field(name="Sói còn sống", value=str(len(self.alive_wolves())), inline=True)
        embed.add_field(name="Dân còn sống", value=str(len(self.alive_villagers())), inline=True)
        embed.add_field(name="Kênh sói", value=self.wolf_channel.mention if self.wolf_channel else "Đã khóa", inline=True)
        embed.add_field(name="Kết thúc thảo luận", value=_fmt_ts(self.discussion_deadline_at), inline=True)
        embed.add_field(name="Kết thúc vote", value=_fmt_ts(self.vote_deadline_at), inline=True)
        embed.set_footer(text="Ban ngày • dân thường có thể chat")
        return embed

    def render_vote_embed(self, phase: str) -> discord.Embed:
        if phase == "night":
            votes = self.night_votes
            title = f"🐺 Vote ban đêm — Đêm {self.round_no}"
            description = "Sói chọn mục tiêu. Hòa sẽ random trong nhóm hòa."
            color = discord.Color.dark_red()
        else:
            votes = self.day_votes
            title = f"🗳️ Vote ban ngày — Ngày {self.round_no}"
            description = "Dân làng vote người muốn loại. Hòa hoặc không vote thì không ai chết."
            color = discord.Color.orange()

        embed = discord.Embed(title=title, description=description, color=color)
        embed.add_field(name="Tình hình vote", value=self._vote_summary(votes, phase), inline=False)
        embed.add_field(name="Người còn sống", value=str(len(self.alive_players())), inline=True)
        embed.add_field(name="Sói còn sống", value=str(len(self.alive_wolves())), inline=True)
        embed.add_field(name="Dân còn sống", value=str(len(self.alive_villagers())), inline=True)
        if phase == "night":
            embed.add_field(name="Kết thúc", value=_fmt_ts(self.night_deadline_at), inline=True)
        else:
            embed.add_field(name="Kết thúc", value=_fmt_ts(self.vote_deadline_at), inline=True)
        return embed

    def render_wolf_panel(self) -> discord.Embed:
        wolves = self._alive_names(self.alive_wolves())
        targets = self._alive_names(self.alive_villagers())
        embed = discord.Embed(
            title="🐺 Phòng của bầy sói",
            description=(
                "Đây là phòng riêng của Ma Sói.\n"
                "Ban đêm chat được, ban ngày chỉ xem."
            ),
            color=discord.Color.dark_red(),
        )
        embed.add_field(
            name="Sói còn sống",
            value="\n".join(f"• {n}" for n in wolves) if wolves else "Không còn sói.",
            inline=False,
        )
        embed.add_field(
            name="Mục tiêu có thể chọn",
            value="\n".join(f"• {n}" for n in targets) if targets else "Không còn ai.",
            inline=False,
        )
        embed.add_field(name="Pha hiện tại", value=self.phase.title(), inline=True)
        embed.add_field(name="Đêm", value=str(self.round_no), inline=True)
        embed.add_field(name="Kết thúc vote", value=_fmt_ts(self.night_deadline_at), inline=True)
        return embed

    async def refresh_lobby_panel(self) -> None:
        if not self.lobby_message:
            return
        try:
            await self.lobby_message.edit(embed=self.render_lobby_embed(), view=JoinView(self))
        except Exception:
            pass

    async def refresh_day_panel(self) -> None:
        if not self.day_vote_message:
            return
        try:
            await self.day_vote_message.edit(embed=self.render_vote_embed("day"), view=VoteSelectView(self, "day"))
        except Exception:
            pass

    async def refresh_night_panel(self) -> None:
        if not self.night_vote_message:
            return
        try:
            await self.night_vote_message.edit(embed=self.render_vote_embed("night"), view=VoteSelectView(self, "night"))
        except Exception:
            pass

    async def refresh_wolf_panel(self) -> None:
        if not self.wolf_panel_message:
            return
        try:
            await self.wolf_panel_message.edit(embed=self.render_wolf_panel(), view=VoteSelectView(self, "night"))
        except Exception:
            pass

    async def ensure_wolf_channel(self) -> Optional[discord.TextChannel]:
        if self.wolf_channel and self.wolf_channel.guild == self.guild:
            return self.wolf_channel

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

        for uid in self.alive_wolves():
            member = self.guild.get_member(int(uid))
            if member:
                overwrites[member] = discord.PermissionOverwrite(
                    view_channel=True,
                    send_messages=True,
                    read_message_history=True,
                    embed_links=True,
                    attach_files=True,
                    add_reactions=True,
                )

        try:
            self.wolf_channel = await self.guild.create_text_channel(
                name=f"wolves-{self.base_name}",
                category=self.base_category,
                topic="Phòng riêng của bầy sói",
                slowmode_delay=0,
                nsfw=False,
                overwrites=overwrites,
                reason="Create private wolf channel",
            )
            if self.base_position is not None:
                try:
                    await self.wolf_channel.edit(position=self.base_position + 1)
                except Exception:
                    pass
        except Exception:
            self.wolf_channel = None

        return self.wolf_channel

    async def sync_public_permissions(self, phase: str) -> None:
        try:
            await self.channel.set_permissions(
                self.guild.default_role,
                send_messages=(phase == "day"),
                read_message_history=True,
                view_channel=True,
                reason="Werewolf: sync public channel permissions",
            )
        except Exception:
            pass

        for member in self.guild.members:
            if member.bot:
                continue
            is_alive_player = str(member.id) in self.players and self.is_alive(member.id)
            send_ok = (phase == "day") and is_alive_player
            try:
                await self.channel.set_permissions(
                    member,
                    send_messages=send_ok,
                    read_message_history=True,
                    view_channel=True,
                    reason="Werewolf: restrict dead/non-player/night chat",
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
                reason="Werewolf: keep wolf channel hidden",
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
                    reason="Werewolf: bot access to wolf channel",
                )
            except Exception:
                pass

        for uid, data in self.players.items():
            member = self.guild.get_member(int(uid))
            if not member:
                continue

            if data.get("role") == "wolf" and data.get("alive"):
                perms = dict(
                    view_channel=True,
                    read_message_history=True,
                    send_messages=(phase == "night"),
                    embed_links=True,
                    attach_files=True,
                    add_reactions=True,
                )
            else:
                perms = dict(
                    view_channel=False,
                    read_message_history=False,
                    send_messages=False,
                )

            try:
                await self.wolf_channel.set_permissions(member, reason="Werewolf: sync wolf perms", **perms)
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
        if member is None:
            return

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
            if member is None:
                continue
            try:
                await member.remove_roles(role, reason="Werewolf: cleanup after match")
            except Exception:
                pass

        self.dead_members.clear()

    async def queue_role_actions(self, phase: str) -> None:
        """
        Placeholder cho role.py sau này.
        Khi role.py có mặt, action ban đêm sẽ đẩy vào đây trước khi resolve.
        """
        self.special_actions.clear()

        if callable(build_night_actions):
            try:
                actions = build_night_actions(self)
                if actions:
                    self.special_actions.extend(actions)
            except Exception:
                pass

    async def apply_special_actions(self) -> None:
        """
        Placeholder. Khi role.py có mặt, xử lý các action theo priority ở đây.
        Hiện tại chưa có role đặc biệt nên vẫn là no-op.
        """
        if not self.special_actions:
            return

    async def kill_player(self, uid: str, announce_reason: str) -> Optional[dict]:
        p = self.get_player(uid)
        if not p or not p.get("alive"):
            return None
        p["alive"] = False
        await self.apply_dead_role(uid)
        await self.sync_public_permissions(self.phase)
        await self.sync_wolf_permissions(self.phase)
        await self.refresh_wolf_panel()
        return p

    async def resolve_night(self) -> Optional[str]:
        await self.apply_special_actions()

        if not self.night_votes:
            await self.channel.send("🌙 Đêm qua không có ai bị giết.")
            return None

        counts = _tally(self.night_votes)
        top = max(counts.values())
        targets = [uid for uid, cnt in counts.items() if cnt == top]
        victim_id = random.choice(targets)

        victim = await self.kill_player(victim_id, "bị Ma Sói giết vào ban đêm.")
        if victim:
            await self.channel.send(f"💀 **{victim['name']}** đã chết trong đêm.")
            return victim["name"]
        return None

    async def resolve_day(self) -> Optional[str]:
        if not self.day_votes:
            await self.channel.send("☀️ Không ai vote nên không ai chết.")
            return None

        counts = _tally(self.day_votes)
        top = max(counts.values())
        targets = [uid for uid, cnt in counts.items() if cnt == top]
        if len(targets) != 1:
            await self.channel.send("⚖️ Phiếu bị hòa nên không ai chết.")
            return None

        victim = await self.kill_player(targets[0], "bị treo cổ vào ban ngày.")
        if victim:
            await self.channel.send(f"💀 **{victim['name']}** đã chết vì bị treo cổ.")
            return victim["name"]
        return None

    def check_win(self) -> bool:
        wolves = len(self.alive_wolves())
        villagers = len(self.alive_villagers())

        if wolves == 0:
            asyncio.create_task(self.channel.send("🏆 **Dân làng thắng!**"))
            return True
        if villagers == 0 or wolves >= villagers:
            asyncio.create_task(self.channel.send("🐺 **Ma Sói thắng!**"))
            return True
        return False

    async def end_and_restart_lobby(self) -> None:
        self.active = False

        try:
            await self.clear_dead_role()
        except Exception:
            pass

        old_channel = self.channel

        if self.wolf_channel:
            try:
                await self.wolf_channel.delete(reason="Werewolf: cleanup wolf channel")
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

        if old_channel:
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
        GAME[new_channel.id] = fresh
        await fresh.post_lobby_panel()
        await new_channel.send("🧼 Phòng đã được làm mới để bắt đầu ván mới.")

    async def post_lobby_panel(self, ctx=None) -> None:
        if ctx is None:
            self.lobby_message = await self.channel.send(embed=self.render_lobby_embed(), view=JoinView(self))
        else:
            self.lobby_message = await send(ctx, embed=self.render_lobby_embed(), view=JoinView(self))

    async def start(self) -> None:
        async with self._lock:
            if self.phase != "lobby":
                return
            if not self.can_start():
                return

            self.assign_roles()
            await self.reveal_roles()
            self.phase = "night"

        await self.ensure_wolf_channel()
        await self.sync_public_permissions("night")
        await self.sync_wolf_permissions("night")

        self.night_deadline_at = int(time.time()) + NIGHT_VOTE_SECONDS
        await self.channel.send(embed=self.render_night_embed("🌙 Màn đêm bắt đầu. Kênh chính đã bị khóa."))

        await self.send_or_refresh_night_ui()
        await self.run_game_loop()

    async def send_or_refresh_night_ui(self) -> None:
        if self.wolf_channel:
            if self.wolf_panel_message is None:
                self.wolf_panel_message = await self.wolf_channel.send(
                    embed=self.render_wolf_panel(),
                    view=VoteSelectView(self, "night"),
                )
            else:
                try:
                    await self.wolf_panel_message.edit(
                        embed=self.render_wolf_panel(),
                        view=VoteSelectView(self, "night"),
                    )
                except Exception:
                    pass

        if self.night_vote_message is None:
            self.night_vote_message = await self.channel.send(
                embed=self.render_vote_embed("night"),
                view=VoteSelectView(self, "night"),
            )
        else:
            try:
                await self.night_vote_message.edit(
                    embed=self.render_vote_embed("night"),
                    view=VoteSelectView(self, "night"),
                )
            except Exception:
                pass

    async def send_or_refresh_day_ui(self, announcement: str) -> None:
        if self.day_vote_message is None:
            self.day_vote_message = await self.channel.send(embed=self.render_day_embed(announcement))
        else:
            try:
                await self.day_vote_message.edit(embed=self.render_day_embed(announcement))
            except Exception:
                self.day_vote_message = None

    async def run_game_loop(self) -> None:
        while self.active:
            if self.check_win():
                break

            self.night_deadline_at = int(time.time()) + NIGHT_VOTE_SECONDS
            await self.sync_public_permissions("night")
            await self.sync_wolf_permissions("night")
            await self.send_or_refresh_night_ui()

            await self.queue_role_actions("night")
            await asyncio.sleep(NIGHT_VOTE_SECONDS)
            await self.resolve_night()
            if self.check_win():
                break

            self.phase = "day"
            self.discussion_deadline_at = int(time.time()) + DAY_DISCUSSION_SECONDS
            self.vote_deadline_at = self.discussion_deadline_at + DAY_VOTE_SECONDS

            await self.sync_public_permissions("day")
            await self.sync_wolf_permissions("day")
            await self.channel.send(
                embed=self.render_day_embed(
                    "☀️ Ban ngày bắt đầu. Mọi người có thể thảo luận, sau đó sẽ chuyển sang vote."
                )
            )

            await self.send_or_refresh_day_ui(
                "☀️ Ban ngày bắt đầu. Thảo luận trước khi vote."
            )
            await asyncio.sleep(DAY_DISCUSSION_SECONDS)

            self.day_votes = {}
            if self.day_vote_message is None:
                self.day_vote_message = await self.channel.send(
                    embed=self.render_vote_embed("day"),
                    view=VoteSelectView(self, "day"),
                )
            else:
                try:
                    await self.day_vote_message.edit(
                        embed=self.render_vote_embed("day"),
                        view=VoteSelectView(self, "day"),
                    )
                except Exception:
                    self.day_vote_message = None

            await asyncio.sleep(DAY_VOTE_SECONDS)
            await self.resolve_day()
            if self.check_win():
                break

            self.round_no += 1
            self.phase = "night"
            self.day_votes = {}
            self.night_votes = {}

        await self.end_and_restart_lobby()


class JoinView(View):
    def __init__(self, session: WerewolfSession):
        super().__init__(timeout=None)
        self.session = session

    @discord.ui.button(label="Join", style=discord.ButtonStyle.success, emoji="✅")
    async def join_button(self, interaction: discord.Interaction, button: Button):
        if self.session.phase != "lobby":
            return await interaction.response.send_message("❌ Ván đã bắt đầu rồi.", ephemeral=True)
        if len(self.session.players) >= MAX_PLAYERS:
            return await interaction.response.send_message("❌ Phòng đã đủ 16 người.", ephemeral=True)

        added = self.session.add_player(interaction.user)
        if not added:
            return await interaction.response.send_message("❌ Bạn đã tham gia rồi.", ephemeral=True)

        await interaction.response.send_message("✅ Đã tham gia phòng.", ephemeral=True)
        await self.session.refresh_lobby_panel()

    @discord.ui.button(label="Start", style=discord.ButtonStyle.danger, emoji="🚀")
    async def start_button(self, interaction: discord.Interaction, button: Button):
        if self.session.phase != "lobby":
            return await interaction.response.send_message("❌ Ván đã bắt đầu rồi.", ephemeral=True)
        if not self.session.can_start():
            return await interaction.response.send_message(
                f"❌ Cần ít nhất {MIN_PLAYERS} người để bắt đầu.",
                ephemeral=True,
            )
        if self.session.host_id != str(interaction.user.id):
            return await interaction.response.send_message("❌ Chỉ chủ phòng mới được bấm Start.", ephemeral=True)

        await interaction.response.send_message("🚀 Đang khởi động ván đấu...", ephemeral=True)
        asyncio.create_task(self.session.start())


class VoteSelect(Select):
    def __init__(self, session: WerewolfSession, phase: str):
        self.session = session
        self.phase = phase

        if phase == "night":
            target_ids = session.alive_villagers()
            placeholder = "Chọn người bị Ma Sói giết"
        else:
            target_ids = session.alive_players()
            placeholder = "Chọn người bị vote"

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

        target_id = self.values[0]
        target = self.session.players.get(target_id)
        if not target or not target.get("alive"):
            return await interaction.response.send_message("❌ Người này đã chết rồi.", ephemeral=True)

        if self.phase == "night":
            if not self.session.is_alive_wolf(uid):
                return await interaction.response.send_message("❌ Chỉ sói còn sống mới được vote vào ban đêm.", ephemeral=True)
            self.session.night_votes[uid] = target_id
            await interaction.response.send_message(f"✅ Bạn đã chọn **{target['name']}**.", ephemeral=True)
            await self.session.refresh_night_panel()
            return

        self.session.day_votes[uid] = target_id
        await interaction.response.send_message(f"✅ Bạn đã vote cho **{target['name']}**.", ephemeral=True)
        await self.session.refresh_day_panel()


class VoteSelectView(View):
    def __init__(self, session: WerewolfSession, phase: str):
        super().__init__(timeout=120)
        self.add_item(VoteSelect(session, phase))


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
        role = discord.utils.find(
            lambda r: r.name.lower() == "dead",
            guild.roles,
        )
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

    await send(ctx, embed=session.render_lobby_embed(), view=JoinView(session))
