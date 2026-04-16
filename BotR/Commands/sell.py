import discord
import json
import os
import re
import copy
from Data import data_user

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INV_FILE = os.path.join(BASE_DIR, "Data", "inventory.json")
WAIFU_FILE = os.path.join(BASE_DIR, "Data", "waifu_data.json")


# =========================
# LOAD / SAVE (ATOMIC)
# =========================
def ensure_file(path: str, default_obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(default_obj, f, indent=4, ensure_ascii=False)


def load():
    ensure_file(INV_FILE, {})
    ensure_file(WAIFU_FILE, {})

    with open(INV_FILE, encoding="utf-8") as f:
        inv = json.load(f)

    with open(WAIFU_FILE, encoding="utf-8") as f:
        w = json.load(f)

    return inv, w


def save(inv, w):
    tmp1 = INV_FILE + ".tmp"
    tmp2 = WAIFU_FILE + ".tmp"

    with open(tmp1, "w", encoding="utf-8") as f:
        json.dump(inv, f, indent=4, ensure_ascii=False)

    with open(tmp2, "w", encoding="utf-8") as f:
        json.dump(w, f, indent=4, ensure_ascii=False)

    os.replace(tmp1, INV_FILE)
    os.replace(tmp2, WAIFU_FILE)


# =========================
# PRICE
# =========================
PRICE = {
    "thuong": 180,
    "anh_hung": 360,
    "huyen_thoai": 680,
    "truyen_thuyet": 1080,
    "toi_thuong": 1750,
    "limited": 10000
}


# =========================
# HELPERS
# =========================
def normalize(text: str) -> str:
    if text is None:
        return ""
    text = str(text).strip().lower()
    text = text.replace(" ", "_")
    text = re.sub(r"_+", "_", text)
    return text


def ensure_user_struct(inv: dict, uid: str):
    if uid not in inv or not isinstance(inv.get(uid), dict):
        inv[uid] = {}

    if not isinstance(inv[uid].get("waifus"), dict):
        inv[uid]["waifus"] = {}

    if not isinstance(inv[uid].get("bag"), dict):
        inv[uid]["bag"] = {}

    if "bag_item" not in inv[uid] or not isinstance(inv[uid].get("bag_item"), dict):
        inv[uid]["bag_item"] = {}

    inv[uid].setdefault("default_waifu", None)


def find_waifu_id(query: str, inv_waifus: dict, wdata: dict):
    q = normalize(query)

    if q in wdata:
        return q

    if q in inv_waifus:
        return q

    for wid, info in wdata.items():
        if isinstance(info, dict):
            name = info.get("name")
            if isinstance(name, str) and normalize(name) == q:
                return wid

    for wid in wdata.keys():
        if q in normalize(wid):
            return wid

    return None


async def _respond(interaction: discord.Interaction, content=None, **kwargs):
    try:
        if interaction.response.is_done():
            return await interaction.followup.send(content, **kwargs)
        return await interaction.response.send_message(content, **kwargs)
    except discord.InteractionResponded:
        return await interaction.followup.send(content, **kwargs)


# =========================
# CONFIRM VIEW
# =========================
class ConfirmView(discord.ui.View):
    def __init__(self, owner_id, waifu_id, gold, callback):
        super().__init__(timeout=30)
        self.owner_id = owner_id
        self.waifu_id = waifu_id
        self.gold = gold
        self.callback = callback
        self.done = False

    @discord.ui.button(label="Chắc chắn", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.owner_id:
            return await interaction.response.send_message("❌ Không phải của bạn!", ephemeral=True)

        if self.done:
            return await interaction.response.send_message("❌ Giao dịch đã xử lý.", ephemeral=True)

        self.done = True
        await interaction.response.defer(ephemeral=True)

        try:
            sold, total = await self.callback()
        except Exception as e:
            self.done = False
            return await interaction.followup.send(
                f"❌ Giao dịch thất bại: {e}",
                ephemeral=True
            )

        for item in self.children:
            item.disabled = True

        try:
            await interaction.edit_original_response(
                content=f"💰 Đã bán **{self.waifu_id}**! +{total} gold",
                view=self
            )
        except Exception:
            try:
                await interaction.followup.send(
                    f"💰 Đã bán **{self.waifu_id}**! +{total} gold",
                    ephemeral=True
                )
            except Exception:
                pass

    @discord.ui.button(label="Hủy", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.owner_id:
            return await interaction.response.send_message("❌ Không phải của bạn!", ephemeral=True)

        for item in self.children:
            item.disabled = True

        await interaction.response.edit_message(
            content="❌ Đã hủy.",
            view=self
        )


# =========================
# LOGIC (FIXED)
# =========================
async def sell_logic(interaction, waifu_id: str, source: str = None, amount: int = 1):
    uid = str(interaction.user.id)

    inv, w = load()

    if uid not in inv:
        return await _respond(interaction, "❌ Không có dữ liệu!", ephemeral=True)

    ensure_user_struct(inv, uid)

    waifu_id = find_waifu_id(waifu_id, inv[uid]["waifus"], w)
    if not waifu_id:
        return await _respond(interaction, "❌ Waifu không tồn tại!", ephemeral=True)

    rank = w.get(waifu_id, {}).get("rank")
    if not rank:
        return await _respond(interaction, "❌ Không có rank!", ephemeral=True)

    price = PRICE.get(rank, 0)
    if price <= 0:
        return await _respond(interaction, "❌ Không có giá!", ephemeral=True)

    bag_count = inv[uid]["bag"].get(waifu_id, 0)
    has_collection = waifu_id in inv[uid]["waifus"]

    if bag_count <= 0 and not has_collection:
        return await _respond(interaction, "❌ Không có waifu!", ephemeral=True)

    async def do_sell():
        lock = data_user.get_lock(uid)

        async with lock:
            inv2, w2 = load()
            ensure_user_struct(inv2, uid)

            user_data = data_user.get_user(uid)
            if not isinstance(user_data, dict):
                user_data = {}

            user_before = copy.deepcopy(user_data)
            inv_before = copy.deepcopy(inv2)
            w_before = copy.deepcopy(w2)

            bag_count2 = inv2[uid]["bag"].get(waifu_id, 0)
            has_collection2 = waifu_id in inv2[uid]["waifus"]

            sold = 0

            if source == "bag":
                take = min(amount, bag_count2)
                if take <= 0:
                    raise Exception("Hết waifu trong bag")

                inv2[uid]["bag"][waifu_id] -= take
                if inv2[uid]["bag"][waifu_id] <= 0:
                    del inv2[uid]["bag"][waifu_id]

                sold = take

            elif source == "collection":
                if not has_collection2:
                    raise Exception("Không còn trong collection")

                del inv2[uid]["waifus"][waifu_id]
                sold = 1

            else:
                if bag_count2 > 0:
                    take = min(amount, bag_count2)
                    inv2[uid]["bag"][waifu_id] -= take
                    if inv2[uid]["bag"][waifu_id] <= 0:
                        del inv2[uid]["bag"][waifu_id]
                    sold += take

                if sold == 0 and has_collection2:
                    del inv2[uid]["waifus"][waifu_id]
                    sold = 1

            if sold <= 0:
                raise Exception("Không còn waifu")

            total = sold * price

            current_gold = int(user_data.get("gold", 0) or 0)
            user_data["gold"] = current_gold + total

            try:
                save(inv2, w2)
                data_user.save_user(uid, user_data)
                data_user.save_data()
            except Exception:
                try:
                    save(inv_before, w_before)
                except Exception:
                    pass
                try:
                    data_user.save_user(uid, user_before)
                    data_user.save_data()
                except Exception:
                    pass
                raise

            return sold, total

    if rank in ["truyen_thuyet", "toi_thuong", "limited"]:
        view = ConfirmView(interaction.user.id, waifu_id, price, do_sell)
        return await interaction.response.send_message(
            f"⚠️ Bán {waifu_id} để nhận {price} gold?",
            view=view,
            ephemeral=True
        )

    await interaction.response.defer(thinking=True)

    sold, total = await do_sell()

    if interaction.response.is_done():
        await interaction.followup.send(
            f"💰 Đã bán {waifu_id}, nhận {total} gold!"
        )
    else:
        await interaction.response.send_message(
            f"💰 Đã bán {waifu_id}, nhận {total} gold!"
        )


# =========================
# SETUP
# =========================
async def setup(bot):
    pass


print("Loaded sell has success")