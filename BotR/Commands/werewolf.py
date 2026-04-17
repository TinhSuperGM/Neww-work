# BotR/Commands/werewolf.py
from __future__ import annotations

import asyncio
import random
import time
from collections import Counter
from typing import Optional

import discord
from discord.ui import Button, Select, View

try:
    from Commands.role import (
        TEAM_WOLF,
        ROLE_DEFINITIONS,
        create_role,
        build_role_assignments,
        build_night_actions,
        resolve_actions,
        apply_action_plan,
    )
except Exception:
    TEAM_WOLF = "wolf"
    ROLE_DEFINITIONS = {}
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


def _display_name(user: discord.abc.User) -> str:
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

        self.lobby_message: Optional[discord.Message] = None
        self.phase_message: Optional[discord.Message] = None
        self.wolf_channel: Optional[discord.TextChannel] = None

        self.last_join_at: Optional[int] = None
        self.day_deadline_at: Optional[int] = None
        self.night_deadline_at: Optional[int] = None
        self.vote_deadline_at: Optional[int] = None
        self.discussion_deadline_at: Optional[int] = None

        self.nightmare_token_target_id: Optional[int] = None

        self.active = True
        self._lock = asyncio.Lock()

    def role_label(self, role_key: str) -> str:
        data = ROLE_DEFINITIONS.get(role_key, {})
        return data.get("name", "👤 Dân làng")

    def role_description(self, role_key: str) -> str:
        data = ROLE_DEFINITIONS.get(role_key, {})
        return data.get("description", "Không có kỹ năng chủ động.")

    def role_team(self, role_key: str) -> str:
        data = ROLE_DEFINITIONS.get(role_key, {})
        return data.get("team", "village")

    def add_player(self, user: discord.abc.User) -> bool:
        uid = str(user.id)
        if uid in self.players:
            return False
        if len(self.players) >= MAX_PLAYERS:
            return False

        self.players[uid] = {
            "name": _display_name(user),
            "member": user if isinstance(user, discord.Member) else None,
            "role": "civilian",
            "role_obj": None,
            "alive": True,
            "revealed_role": False,
            "nightmare_locked": False,
        }
        if self.host_id is None:
            self.host_id = uid
        self.last_join_at = int(time.time())
        return True

    def get_player(self, uid: object) -> Optional[dict]:
        return self.players.get(str(uid))

    def alive_players(self) -> list[str]:
        return [uid for uid, data in self.players.items() if data.get("alive")]

    def alive_wolf_team(self) -> list[str]:
        return [
            uid
            for uid, data in self.players.items()
            if data.get("alive") and self.role_team(data.get("role", "civilian")) == TEAM_WOLF
        ]

    def alive_villagers(self) -> list[str]:
        return [
            uid
            for uid, data in self.players.items()
            if data.get("alive") and self.role_team(data.get("role", "civilian")) != TEAM_WOLF
        ]

    def is_alive(self, uid: object) -> bool:
        p = self.get_player(uid)
        return bool(p and p.get("alive"))

    def is_alive_wolf(self, uid: object) -> bool:
        p = self.get_player(uid)
        return bool(p and p.get("alive") and self.role_team(p.get("role", "civilian")) == TEAM_WOLF)

    def can_start(self) -> bool:
        return MIN_PLAYERS <= len(self.players) <= MAX_PLAYERS

    def _panel_counts_text(self) -> str:
        return (
            f"**Còn sống:** {len(self.alive_players())}\n"
            f"**Sói:** {len(self.alive_wolf_team())}\n"
            f"**Dân:** {len(self.alive_villagers())}"
        )

    async def notify_host_join(self, joiner: discord.abc.User) -> None:
        if not self.host_id:
            return

        host = self.guild.get_member(int(self.host_id))
        if host is None:
            try:
                host = await self.guild.fetch_member(int(self.host_id))
            except Exception:
                host = None

        if host is not None:
            try:
                await host.send(
                    f"📣 **{_display_name(joiner)}** vừa tham gia phòng **#{self.base_name}**.\n"
                    f"Hiện có **{len(self.players)}** người."
                )
            except Exception:
                try:
                    await self.channel.send(f"📣 <@{host.id}>, **{_display_name(joiner)}** vừa tham gia phòng.")
                except Exception:
                    pass

    async def refresh_lobby_panel(self) -> None:
        if not self.lobby_message:
            return
        try:
            await self.lobby_message.edit(embed=self.render_lobby_embed(), view=LobbyView(self))
        except Exception:
            pass

    async def assign_roles(self):
        ids = list(self.players.keys())
        random.shuffle(ids)

        role_map = build_role_assignments(ids, self.players) if callable(build_role_assignments) else {}
        for uid in ids:
            role_key = role_map.get(uid, "civilian")
            member = self.guild.get_member(int(uid))
            if member is None:
                try:
                    member = await self.guild.fetch_member(int(uid))
                except Exception:
                    member = None

            player = self.players[uid]
            player["role"] = role_key
            if create_role is not None:
                player["role_obj"] = create_role(role_key, member or self.bot.get_user(int(uid)))
            else:
                player["role_obj"] = None

    async def call_role_start_hooks(self) -> None:
        for pdata in self.players.values():
            role_obj = pdata.get("role_obj")
            if role_obj is None:
                continue
            try:
                await role_obj.on_game_start(self)
            except Exception:
                pass

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

    def render_phase_embed(self, phase: str, announcement: str) -> discord.Embed:
        if phase == "night":
            color = discord.Color.dark_red()
            title = f"🌙 Đêm {self.round_no}"
            footer = "Ban đêm • vote sói + kỹ năng"
            vote_count = self._vote_summary(self.night_votes, phase)
            deadline = self.night_deadline_at
        else:
            color = discord.Color.gold()
            title = f"🌞 Ngày {self.round_no}"
            footer = "Ban ngày • thảo luận + vote + kỹ năng"
            vote_count = self._vote_summary(self.day_votes, phase)
            deadline = self.vote_deadline_at

        embed = discord.Embed(title=title, description=announcement, color=color)
        embed.add_field(name="Tình hình", value=self._panel_counts_text(), inline=True)
        embed.add_field(name="Kết thúc", value=_fmt_ts(deadline), inline=True)
        embed.add_field(name="Vote hiện tại", value=vote_count, inline=False)
        embed.add_field(name="Kênh sói", value=self.wolf_channel.mention if self.wolf_channel else "Đang tạo...", inline=True)
        embed.set_footer(text=footer)
        return embed

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

    async def replace_phase_message(self, phase: str, announcement: str) -> None:
        await safe_delete(self.phase_message)
        self.phase_message = None
        self.phase_message = await self.channel.send(
            embed=self.render_phase_embed(phase, announcement),
            view=GameActionView(self, phase),
        )

    async def refresh_phase_message(self, phase: str, announcement: str) -> None:
        if self.phase_message is None:
            await self.replace_phase_message(phase, announcement)
            return
        await safe_edit(self.phase_message, embed=self.render_phase_embed(phase, announcement), view=GameActionView(self, phase))

    async def ensure_private_channel(self, name: str, members: list[discord.Member], *, category=None, topic: Optional[str] = None) -> discord.TextChannel | None:
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
            ch = await self.guild.create_text_channel(
                name=name,
                category=category or self.base_category,
                topic=topic,
                overwrites=overwrites,
                reason="Werewolf private room",
            )
            return ch
        except Exception:
            return None

    async def ensure_wolf_channel(self) -> Optional[discord.TextChannel]:
        if self.wolf_channel and self.wolf_channel.guild == self.guild:
            return self.wolf_channel

        wolves: list[discord.Member] = []
        for uid in self.alive_wolf_team():
            member = self.guild.get_member(int(uid))
            if member is None:
                try:
                    member = await self.guild.fetch_member(int(uid))
                except Exception:
                    member = None
            if member:
                wolves.append(member)

        ch = await self.ensure_private_channel(
            name=f"wolves-{self.base_name}",
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
        return self.wolf_channel

    async def sync_public_permissions(self, phase: str) -> None:
        for uid, pdata in self.players.items():
            member = self.guild.get_member(int(uid))
            if member is None:
                try:
                    member = await self.guild.fetch_member(int(uid))
                except Exception:
                    member = None
            if member is None:
                continue

            alive = bool(pdata.get("alive"))
            send_ok = phase == "day" and alive
            try:
                await self.channel.set_permissions(
                    member,
                    view_channel=alive,
                    send_messages=send_ok,
                    read_message_history=alive,
                    reason="Werewolf public channel sync",
                )
            except Exception:
                pass

        try:
            await self.channel.set_permissions(
                self.guild.default_role,
                view_channel=False,
                send_messages=False,
                read_message_history=False,
                reason="Werewolf public channel lock",
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

            is_wolf = pdata.get("alive") and self.role_team(pdata.get("role", "civilian")) == TEAM_WOLF
            perms = dict(
                view_channel=is_wolf,
                send_messages=is_wolf and phase == "night",
                read_message_history=is_wolf,
                embed_links=is_wolf,
                attach_files=is_wolf,
                add_reactions=is_wolf,
            )
            try:
                await self.wolf_channel.set_permissions(member, reason="Werewolf wolf channel sync", **perms)
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

    async def kill_player(self, uid: str, announce_reason: str) -> Optional[dict]:
        player = self.players.get(uid)
        if not player or not player.get("alive"):
            return None

        player["alive"] = False
        player["nightmare_locked"] = False
        await self.apply_dead_role(uid)

        role_obj = player.get("role_obj")
        if role_obj is not None:
            try:
                await role_obj.on_death(self)
            except Exception:
                pass

        await self.sync_public_permissions(self.phase)
        await self.sync_wolf_permissions(self.phase)
        return player

    def _resolve_wolf_vote(self) -> Optional[str]:
        if not self.night_votes:
            return None

        counts = _tally(self.night_votes)
        top = max(counts.values())
        targets = [uid for uid, amount in counts.items() if amount == top]
        if not targets:
            return None
        return random.choice(targets)

    async def resolve_night(self) -> list[str]:
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
            "killed": [],
            "public_messages": [],
            "private_dms": [],
            "nightmare_token_target_id": None,
        }

        if callable(apply_action_plan):
            await apply_action_plan(self, plan)

        killed_ids = list(dict.fromkeys(plan.get("killed", [])))

        if not killed_ids:
            await self.channel.send("🌙 Đêm qua không có ai bị giết.")
            return []

        names = []
        for uid in killed_ids:
            player = self.players.get(str(uid))
            if player and not player.get("alive"):
                names.append(player["name"])

        if names:
            await self.channel.send("💀 " + ", ".join(f"**{n}**" for n in names) + " đã chết trong đêm.")
        return killed_ids

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

        victim = await self.kill_player(targets[0], "bị treo cổ vào ban ngày.")
        if victim:
            await self.channel.send(f"💀 **{victim['name']}** đã chết vì bị treo cổ.")
            return victim["name"]
        return None

    def check_win(self) -> bool:
        wolves = len(self.alive_wolf_team())
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
            self.lobby_message = await self.channel.send(embed=self.render_lobby_embed(), view=LobbyView(self))
        else:
            self.lobby_message = await send(ctx, embed=self.render_lobby_embed(), view=LobbyView(self))

    async def _call_phase_hook(self, method_name: str) -> None:
        for pdata in self.players.values():
            role_obj = pdata.get("role_obj")
            if role_obj is None:
                continue
            try:
                await getattr(role_obj, method_name)(self)
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

        await self.ensure_wolf_channel()
        await self.sync_public_permissions("night")
        await self.sync_wolf_permissions("night")
        await self._call_phase_hook("on_night_start")

        self.night_deadline_at = int(time.time()) + NIGHT_VOTE_SECONDS
        await self.replace_phase_message("night", "🌙 Màn đêm bắt đầu. Kênh chính đã bị khóa.")
        await self.run_game_loop()

    async def _sync_day_start(self) -> None:
        await self.sync_public_permissions("day")
        await self.sync_wolf_permissions("day")
        await self._call_phase_hook("on_day_start")

    async def _sync_night_start(self) -> None:
        await self.sync_public_permissions("night")
        await self.sync_wolf_permissions("night")
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
            while time.time() < self.night_deadline_at:
                await asyncio.sleep(1)

            await self.resolve_night()

            if self.check_win():
                break

            self.phase = "day"
            self.discussion_deadline_at = int(time.time()) + DAY_DISCUSSION_SECONDS
            self.vote_deadline_at = self.discussion_deadline_at + DAY_VOTE_SECONDS

            await self._sync_day_start()
            await self.replace_phase_message("day", "☀️ Ban ngày bắt đầu. Thảo luận trước khi vote.")
            # Discussion phase
            while time.time() < self.discussion_deadline_at:
                await asyncio.sleep(1)

            await self.refresh_phase_message("day", "🗳️ Bắt đầu vote ban ngày.")

            # Vote phase
            while time.time() < self.vote_deadline_at:
                await asyncio.sleep(1)

            await self.resolve_day()

            if self.check_win():
                break

            self.round_no += 1

        await self.end_and_restart_lobby()


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

        added = self.session.add_player(interaction.user)
        if not added:
            return await interaction.response.send_message("❌ Bạn đã tham gia rồi.", ephemeral=True)

        await interaction.response.send_message("✅ Đã tham gia phòng.", ephemeral=True)
        await self.session.refresh_lobby_panel()
        await self.session.notify_host_join(interaction.user)

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
            return await interaction.response.send_message("❌ Chỉ sói còn sống mới được vote vào ban đêm.", ephemeral=True)

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

        plan = resolve_actions(self.session, [action]) if callable(resolve_actions) else None
        if plan and callable(apply_action_plan):
            await apply_action_plan(self.session, plan)

        target = self.session.players.get(target_id)
        target_role_name = self.session.role_label(target["role"]) if target else "Unknown"

        if self.skill_key == "inspect":
            result_embed = discord.Embed(
                title="🔍 Kết quả soi",
                description=f"**{target['name']}** là **{target_role_name}**." if target else "Không xác định.",
                color=discord.Color.green(),
            )
        elif self.skill_key == "inspect_guard":
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
        await interaction.response.edit_message(embed=result_embed, view=None)


class SkillTargetView(View):
    def __init__(self, session: WerewolfSession, phase: str, role_obj, skill_key: str):
        super().__init__(timeout=120)
        self.add_item(SkillTargetSelect(session, phase, role_obj, skill_key))


class SkillChoiceSelect(Select):
    def __init__(self, session: WerewolfSession, phase: str, role_obj):
        self.session = session
        self.phase = phase
        self.role_obj = role_obj

        options = []
        for skill in role_obj.skill_options(phase, game=session):
            options.append(
                discord.SelectOption(
                    label=skill["label"],
                    value=skill["key"],
                    description=skill["description"][:100],
                )
            )

        super().__init__(
            placeholder=f"Chọn kỹ năng của {role_obj.name}",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction):
        skill_key = self.values[0]
        if not self.role_obj.set_skill(skill_key):
            return await interaction.response.send_message("❌ Kỹ năng không hợp lệ.", ephemeral=True)

        embed = discord.Embed(
            title=f"✨ Dùng kỹ năng — {self.role_obj.name}",
            description=f"Đã chọn **{skill_key}**. Bây giờ hãy chọn mục tiêu.",
            color=discord.Color.gold(),
        )
        await interaction.response.send_message(
            embed=embed,
            view=SkillTargetView(self.session, self.phase, self.role_obj, skill_key),
            ephemeral=True,
        )


class SkillChoiceView(View):
    def __init__(self, session: WerewolfSession, phase: str, role_obj):
        super().__init__(timeout=120)
        self.add_item(SkillChoiceSelect(session, phase, role_obj))


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
        if not player or not player.get("alive"):
            return await interaction.response.send_message("❌ Bạn đã chết rồi.", ephemeral=True)

        role_obj = player.get("role_obj")
        if role_obj is None:
            return await interaction.response.send_message("❌ Không có kỹ năng.", ephemeral=True)

        options = role_obj.skill_options(self.phase, game=self.session)
        if not options:
            return await interaction.response.send_message("❌ Vai trò này không có kỹ năng ở pha hiện tại.", ephemeral=True)

        if len(options) == 1:
            skill_key = options[0]["key"]
            role_obj.set_skill(skill_key)
            await interaction.response.send_message(
                embed=discord.Embed(
                    title=f"✨ Dùng kỹ năng — {role_obj.name}",
                    description=f"Chọn mục tiêu cho **{options[0]['label']}**.",
                    color=discord.Color.gold(),
                ),
                view=SkillTargetView(self.session, self.phase, role_obj, skill_key),
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            embed=discord.Embed(
                title=f"✨ Dùng kỹ năng — {role_obj.name}",
                description="Chọn kỹ năng bạn muốn dùng.",
                color=discord.Color.gold(),
            ),
            view=SkillChoiceView(self.session, self.phase, role_obj),
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
