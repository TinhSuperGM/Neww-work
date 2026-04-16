import discord
import json
import os
import math
import asyncio
from typing import Any, Dict, List, Optional, Union

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INV_FILE = os.path.join(BASE_DIR, "Data", "inventory.json")
WAIFU_FILE = os.path.join(BASE_DIR, "Data", "waifu_data.json")

RANK_ORDER = {
    "limited": 0,
    "toi_thuong": 1,
    "truyen_thuyet": 2,
    "huyen_thoai": 3,
    "anh_hung": 4,
    "thuong": 5,
}

VIEW_TIMEOUT = 600
PER_PAGE = 10
PAGE_SELECT_LIMIT = 25

# =====================
# JSON CACHE / SAFE LOAD
# =====================
_JSON_CACHE: Dict[str, Dict[str, Any]] = {}


def _ensure_json_file(path: str, default_obj):
    folder = os.path.dirname(path)
    os.makedirs(folder, exist_ok=True)

    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(default_obj, f, ensure_ascii=False, indent=2)


def load_json_safe(path: str, default_obj):
    _ensure_json_file(path, default_obj)
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, (dict, list)):
            return data
    except (json.JSONDecodeError, OSError):
        pass
    return default_obj.copy() if isinstance(default_obj, dict) else list(default_obj)


def load_json_cached(path: str, default_obj):
    _ensure_json_file(path, default_obj)

    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return default_obj.copy() if isinstance(default_obj, dict) else list(default_obj)

    cached = _JSON_CACHE.get(path)
    if cached and cached.get("mtime") == mtime:
        data = cached.get("data")
        if isinstance(data, (dict, list)):
            return data

    data = load_json_safe(path, default_obj)
    _JSON_CACHE[path] = {"mtime": mtime, "data": data}
    return data


def save_json_atomic(path: str, data):
    folder = os.path.dirname(path)
    os.makedirs(folder, exist_ok=True)

    tmp_path = f"{path}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, path)

    try:
        mtime = os.path.getmtime(path)
    except OSError:
        mtime = None
    _JSON_CACHE[path] = {"mtime": mtime, "data": data}


def load_inv():
    return load_json_cached(INV_FILE, {})


def load_waifu_data():
    data = load_json_cached(WAIFU_FILE, {})
    return data if isinstance(data, dict) else {}


# =====================
# NORMALIZE / SORT
# =====================
def _clean_text(value: Any) -> str:
    return str(value).strip().lower() if value is not None else ""


def _get_target_display_name(user: Union[discord.User, discord.Member]) -> str:
    return getattr(user, "display_name", None) or getattr(user, "name", "Unknown")


def normalize_collection(collection: Any, waifu_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []

    if isinstance(collection, dict):
        for waifu_id, raw in collection.items():
            waifu_id = str(waifu_id)
            base = waifu_data.get(waifu_id, {})
            merged: Dict[str, Any] = {}
            if isinstance(base, dict):
                merged.update(base)
            if isinstance(raw, dict):
                merged.update(raw)
            merged["id"] = waifu_id
            merged.setdefault("name", waifu_id)
            merged.setdefault("rank", merged.get("rank", ""))
            items.append(merged)

    elif isinstance(collection, list):
        for raw in collection:
            if isinstance(raw, dict):
                waifu_id = str(raw.get("id") or raw.get("waifu_id") or raw.get("wid") or raw.get("name") or "")
                if not waifu_id:
                    continue
                base = waifu_data.get(waifu_id, {})
                merged: Dict[str, Any] = {}
                if isinstance(base, dict):
                    merged.update(base)
                merged.update(raw)
                merged["id"] = waifu_id
                merged.setdefault("name", waifu_id)
                merged.setdefault("rank", merged.get("rank", ""))
                items.append(merged)
            else:
                waifu_id = str(raw)
                if not waifu_id:
                    continue
                base = waifu_data.get(waifu_id, {})
                merged: Dict[str, Any] = {}
                if isinstance(base, dict):
                    merged.update(base)
                merged["id"] = waifu_id
                merged.setdefault("name", waifu_id)
                merged.setdefault("rank", merged.get("rank", ""))
                items.append(merged)

    return items


def sort_waifus(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    def sort_key(item: Dict[str, Any]):
        rank_raw = _clean_text(item.get("rank"))
        is_known_rank = 1 if rank_raw in RANK_ORDER else 0
        rank_index = RANK_ORDER.get(rank_raw, -1 if rank_raw not in RANK_ORDER else 999)
        name = _clean_text(item.get("name") or item.get("id"))
        wid = _clean_text(item.get("id"))
        return (is_known_rank, rank_index, name, wid)

    return sorted(items, key=sort_key)


def filter_waifus(items: List[Dict[str, Any]], query: str) -> List[Dict[str, Any]]:
    q = _clean_text(query)
    if not q:
        return items

    result = []
    for item in items:
        wid = _clean_text(item.get("id"))
        name = _clean_text(item.get("name"))
        if q in wid or q in name:
            result.append(item)
    return result


def _rank_label(rank: Any) -> str:
    rank_text = str(rank).strip()
    return rank_text if rank_text else "không xác định"


def _safe_edit_response(interaction: discord.Interaction, **kwargs):
    async def _inner():
        try:
            if not interaction.response.is_done():
                await interaction.response.edit_message(**kwargs)
            else:
                await interaction.edit_original_response(**kwargs)
        except (discord.NotFound, discord.HTTPException):
            pass

    return _inner()


# =====================
# UI
# =====================
class WaifuSearchModal(discord.ui.Modal, title="🔍 Tìm waifu"):
    query = discord.ui.TextInput(
        label="Tên hoặc ID",
        placeholder="Nhập tên waifu hoặc ID...",
        min_length=1,
        max_length=50,
        required=True,
    )

    def __init__(self, view: "WaifuListView"):
        super().__init__()
        self.view_ref = view

    async def on_submit(self, interaction: discord.Interaction):
        q = str(self.query.value).strip()
        await self.view_ref.apply_search(q)
        try:
            await interaction.response.send_message(
                f"✅ Đã tìm kiếm: **{discord.utils.escape_markdown(q)}**",
                ephemeral=True,
            )
        except discord.HTTPException:
            pass


class PageSelect(discord.ui.Select):
    def __init__(self, view: "WaifuListView"):
        self.parent_view = view
        super().__init__(
            placeholder="Chọn trang...",
            min_values=1,
            max_values=1,
            options=view.build_page_options(),
        )

    async def callback(self, interaction: discord.Interaction):
        try:
            self.parent_view.page = int(self.values[0])
            self.parent_view.clamp_page()
            self.parent_view.refresh_controls()
            await _safe_edit_response(
                interaction,
                embed=self.parent_view.get_embed(),
                view=self.parent_view,
            )
        except Exception as e:
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message(f"❌ Lỗi chọn trang: `{e}`", ephemeral=True)
                else:
                    await interaction.followup.send(f"❌ Lỗi chọn trang: `{e}`", ephemeral=True)
            except discord.HTTPException:
                pass


class WaifuListView(discord.ui.View):
    def __init__(
        self,
        author: Union[discord.User, discord.Member],
        target_user: Union[discord.User, discord.Member],
        waifu_items: List[Dict[str, Any]],
    ):
        super().__init__(timeout=VIEW_TIMEOUT)
        self.author = author
        self.target_user = target_user
        self.message: Optional[discord.Message] = None
        self.page = 0
        self.per_page = PER_PAGE
        self.search_query: Optional[str] = None
        self._lock = asyncio.Lock()
        self._last_render = 0.0

        self.all_items = list(waifu_items)
        self.filtered_items = list(self.all_items)
        self.max_page = max(1, math.ceil(len(self.filtered_items) / self.per_page))

        self.search_button = discord.ui.Button(
            label="Tìm",
            emoji="🔍",
            style=discord.ButtonStyle.primary,
        )
        self.search_button.callback = self.open_search_modal
        self.add_item(self.search_button)

        self.clear_button = discord.ui.Button(
            label="Bỏ lọc",
            emoji="♻️",
            style=discord.ButtonStyle.secondary,
        )
        self.clear_button.callback = self.clear_search
        self.add_item(self.clear_button)

        self.prev_button = discord.ui.Button(
            label="⬅️",
            style=discord.ButtonStyle.secondary,
        )
        self.prev_button.callback = self.go_prev
        self.add_item(self.prev_button)

        self.page_select = PageSelect(self)
        self.add_item(self.page_select)

        self.next_button = discord.ui.Button(
            label="➡️",
            style=discord.ButtonStyle.secondary,
        )
        self.next_button.callback = self.go_next
        self.add_item(self.next_button)

        self.first_button: Optional[discord.ui.Button] = discord.ui.Button(
            label="⏮️",
            style=discord.ButtonStyle.secondary,
        )
        self.first_button.callback = self.go_first

        self.last_button: Optional[discord.ui.Button] = discord.ui.Button(
            label="⏭️",
            style=discord.ButtonStyle.secondary,
        )
        self.last_button.callback = self.go_last

        self.refresh_controls()

    def clamp_page(self):
        self.max_page = max(1, math.ceil(len(self.filtered_items) / self.per_page))
        self.page = max(0, min(self.page, self.max_page - 1))

    def build_page_options(self):
        self.max_page = max(1, math.ceil(len(self.filtered_items) / self.per_page))

        if self.max_page <= PAGE_SELECT_LIMIT:
            start = 0
            end = self.max_page
        else:
            half = PAGE_SELECT_LIMIT // 2
            start = max(0, self.page - half)
            end = start + PAGE_SELECT_LIMIT
            if end > self.max_page:
                end = self.max_page
                start = max(0, end - PAGE_SELECT_LIMIT)

        options = []
        for idx in range(start, end):
            page_items = self.filtered_items[idx * self.per_page : (idx + 1) * self.per_page]
            count = len(page_items)
            if page_items:
                sample = page_items[0].get("name") or page_items[0].get("id") or "Trống"
            else:
                sample = "Trống"
            options.append(
                discord.SelectOption(
                    label=f"Trang {idx + 1}",
                    value=str(idx),
                    description=f"{count} waifu • {sample}"[:100],
                    default=(idx == self.page),
                )
            )

        if not options:
            options = [discord.SelectOption(label="Trang 1", value="0", default=True)]
        return options

    def _sync_first_last_buttons(self):
        should_show = self.max_page >= 4
        first_in_children = self.first_button in self.children if self.first_button else False
        last_in_children = self.last_button in self.children if self.last_button else False

        if should_show:
            if self.first_button and not first_in_children:
                self.add_item(self.first_button)
            if self.last_button and not last_in_children:
                self.add_item(self.last_button)
        else:
            if self.first_button and first_in_children:
                self.remove_item(self.first_button)
            if self.last_button and last_in_children:
                self.remove_item(self.last_button)

    def refresh_controls(self):
        self.clamp_page()

        has_items = len(self.filtered_items) > 0
        self.prev_button.disabled = (not has_items) or self.page <= 0
        self.next_button.disabled = (not has_items) or self.page >= self.max_page - 1
        self.search_button.disabled = not has_items
        self.clear_button.disabled = not bool(self.search_query)

        self.page_select.disabled = not has_items or self.max_page <= 1
        self.page_select.options = self.build_page_options()
        self.page_select.placeholder = f"Trang {self.page + 1}/{self.max_page}"

        self._sync_first_last_buttons()

        if self.first_button is not None:
            self.first_button.disabled = (not has_items) or self.page <= 0
        if self.last_button is not None:
            self.last_button.disabled = (not has_items) or self.page >= self.max_page - 1

    def get_current_items(self):
        start = self.page * self.per_page
        end = start + self.per_page
        return self.filtered_items[start:end]

    def get_embed(self):
        self.clamp_page()
        current_items = self.get_current_items()

        lines = []
        for idx, item in enumerate(current_items, start=1):
            wid = item.get("id", "unknown")
            name = item.get("name", wid)
            rank = _rank_label(item.get("rank"))
            global_index = self.page * self.per_page + idx
            lines.append(f"{global_index}. 🩷 **{name}** (`{wid}`) | 🎖️ `{rank}`")

        if not current_items:
            body = "Không tìm thấy waifu phù hợp."
        else:
            body = "\n".join(lines)

        filter_line = f"\n🔎 Lọc: **{discord.utils.escape_markdown(self.search_query)}**" if self.search_query else ""
        total_line = f"🎁 Tổng cộng: **{len(self.filtered_items)}** waifu{filter_line}"

        embed = discord.Embed(
            title=f"🗂️ Waifu của {_get_target_display_name(self.target_user)}",
            description=f"{total_line}\n━━━━━━━━━━━━━━\n{body}",
            color=0xFF66CC,
        )

        try:
            embed.set_thumbnail(url=self.target_user.display_avatar.url)
        except Exception:
            pass

        embed.set_footer(text=f"Trang {self.page + 1}/{self.max_page}")
        return embed

    async def _maybe_edit_message(self):
        now = asyncio.get_event_loop().time()
        if now - self._last_render < 0.35:
            return
        self._last_render = now

        if not self.message:
            return

        try:
            await self.message.edit(embed=self.get_embed(), view=self)
        except (discord.NotFound, discord.HTTPException):
            pass

    async def apply_search(self, query: str):
        async with self._lock:
            self.search_query = query.strip() if query else None
            self.filtered_items = filter_waifus(self.all_items, self.search_query or "")
            self.page = 0
            self.refresh_controls()
            await self._maybe_edit_message()

    async def clear_search(self, interaction: discord.Interaction):
        async with self._lock:
            self.search_query = None
            self.filtered_items = list(self.all_items)
            self.page = 0
            self.refresh_controls()
            await _safe_edit_response(
                interaction,
                embed=self.get_embed(),
                view=self,
            )
            if self.message:
                try:
                    await self.message.edit(embed=self.get_embed(), view=self)
                except (discord.NotFound, discord.HTTPException):
                    pass

    async def open_search_modal(self, interaction: discord.Interaction):
        try:
            await interaction.response.send_modal(WaifuSearchModal(self))
        except discord.HTTPException:
            pass

    async def go_first(self, interaction: discord.Interaction):
        async with self._lock:
            self.page = 0
            self.refresh_controls()
            await _safe_edit_response(
                interaction,
                embed=self.get_embed(),
                view=self,
            )

    async def go_last(self, interaction: discord.Interaction):
        async with self._lock:
            self.clamp_page()
            self.page = self.max_page - 1
            self.refresh_controls()
            await _safe_edit_response(
                interaction,
                embed=self.get_embed(),
                view=self,
            )

    async def go_prev(self, interaction: discord.Interaction):
        async with self._lock:
            self.page = max(0, self.page - 1)
            self.refresh_controls()
            await _safe_edit_response(
                interaction,
                embed=self.get_embed(),
                view=self,
            )

    async def go_next(self, interaction: discord.Interaction):
        async with self._lock:
            self.clamp_page()
            self.page = min(self.max_page - 1, self.page + 1)
            self.refresh_controls()
            await _safe_edit_response(
                interaction,
                embed=self.get_embed(),
                view=self,
            )

    async def interaction_check(self, interaction: discord.Interaction):
        if interaction.user.id != self.author.id:
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message(
                        "❌ Bạn không phải người đã mở bảng này.",
                        ephemeral=True,
                    )
                else:
                    await interaction.followup.send(
                        "❌ Bạn không phải người đã mở bảng này.",
                        ephemeral=True,
                    )
            except discord.HTTPException:
                pass
            return False
        return True

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except (discord.NotFound, discord.HTTPException):
                pass


# =====================
# TARGET RESOLVE
# =====================
def resolve_target_user(ctx_or_interaction, target_user=None):
    if target_user is not None:
        return target_user

    if hasattr(ctx_or_interaction, "message"):
        msg = ctx_or_interaction.message

        if getattr(msg, "mentions", None):
            if msg.mentions:
                return msg.mentions[0]

        ref = getattr(msg, "reference", None)
        if ref and getattr(ref, "resolved", None):
            resolved = ref.resolved
            if hasattr(resolved, "author") and resolved.author:
                return resolved.author

    if hasattr(ctx_or_interaction, "user"):
        return ctx_or_interaction.user

    return None


# =====================
# MAIN
# =====================
async def waifu_list_run(ctx_or_interaction, target_user=None):
    inv = load_inv()
    waifu_data = load_waifu_data()
    if not isinstance(inv, dict):
        inv = {}
    if not isinstance(waifu_data, dict):
        waifu_data = {}

    invoker = ctx_or_interaction.user if hasattr(ctx_or_interaction, "user") else ctx_or_interaction.author
    target = resolve_target_user(ctx_or_interaction, target_user) or invoker

    uid = str(target.id)
    raw_collection = inv.get(uid, {}).get("waifus", [])

    waifu_items = normalize_collection(raw_collection, waifu_data)
    waifu_items = sort_waifus(waifu_items)

    if not waifu_items:
        msg = f"📦 {getattr(target, 'display_name', target.name)} chưa có waifu nào."
        try:
            if hasattr(ctx_or_interaction, "response"):
                if not ctx_or_interaction.response.is_done():
                    await ctx_or_interaction.response.send_message(msg, ephemeral=True)
                else:
                    await ctx_or_interaction.followup.send(msg, ephemeral=True)
            else:
                await ctx_or_interaction.send(msg)
        except discord.HTTPException:
            pass
        return

    view = WaifuListView(invoker, target, waifu_items)
    embed = view.get_embed()

    if hasattr(ctx_or_interaction, "response"):
        try:
            if ctx_or_interaction.response.is_done():
                sent = await ctx_or_interaction.followup.send(embed=embed, view=view, wait=True)
                view.message = sent
            else:
                await ctx_or_interaction.response.send_message(embed=embed, view=view)
                try:
                    view.message = await ctx_or_interaction.original_response()
                except discord.HTTPException:
                    view.message = None
        except discord.HTTPException:
            pass
    else:
        try:
            view.message = await ctx_or_interaction.send(embed=embed, view=view)
        except discord.HTTPException:
            pass


# =====================
# OPTIONAL COMMAND WRAPPERS
# =====================
# Prefix:
# @bot.command(name="waifulist")
# async def waifulist_cmd(ctx):
#     await waifu_list_run(ctx)
#
# Slash:
# @bot.tree.command(name="waifulist", description="Xem danh sách waifu")
# async def waifulist_slash(interaction: discord.Interaction):
#     await waifu_list_run(interaction)
print("Loaded waifu list has successs")