import json
import os
import tempfile
import threading

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

WAIFU_FILE = os.path.join(BASE_DIR, "Data", "waifu_data.json")
INV_FILE = os.path.join(BASE_DIR, "Data", "inventory.json")
LEVEL_FILE = os.path.join(BASE_DIR, "Data", "level.json")

# FIX: Helper gửi message an toàn với None và interaction
async def safe_send(ctx, *, content=None, embed=None, view=None, ephemeral=False):
    kwargs = {}
    if content is not None:
        kwargs["content"] = content
    if embed is not None:
        kwargs["embed"] = embed
    if view is not None:
        kwargs["view"] = view

    if hasattr(ctx, "response"):
        if not ctx.response.is_done():
            return await ctx.response.send_message(**kwargs, ephemeral=ephemeral)
        return await ctx.followup.send(**kwargs)

    return await ctx.send(**kwargs)

# FIX: Helper edit message an toàn với None
async def safe_edit(msg, *, content=None, embed=None, view=None):
    kwargs = {}
    if content is not None:
        kwargs["content"] = content
    if embed is not None:
        kwargs["embed"] = embed
    if view is not None:
        kwargs["view"] = view
    return await msg.edit(**kwargs)

_FILE_LOCK = threading.RLock()


# ===== SAFE FILE HELPERS =====
def ensure_files():
    os.makedirs(os.path.join(BASE_DIR, "Data"), exist_ok=True)

    for path in (WAIFU_FILE, INV_FILE, LEVEL_FILE):
        if not os.path.exists(path):
            save_json_atomic(path, {})


def safe_load(path):
    try:
        with _FILE_LOCK:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)

        return data if isinstance(data, dict) else {}

    except (FileNotFoundError, json.JSONDecodeError, OSError, ValueError):
        return {}
    except Exception:
        return {}


def save_json_atomic(path, data):
    folder = os.path.dirname(path)
    os.makedirs(folder, exist_ok=True)

    tmp_path = None

    try:
        with _FILE_LOCK:
            fd, tmp_path = tempfile.mkstemp(dir=folder, prefix=".tmp_", suffix=".json")

            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=4, ensure_ascii=False)
                    f.flush()
                    os.fsync(f.fileno())

                os.replace(tmp_path, path)

            finally:
                if tmp_path and os.path.exists(tmp_path):
                    try:
                        os.remove(tmp_path)
                    except OSError:
                        pass

        return True

    except Exception:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass

        return False


def load_data():
    ensure_files()
    return safe_load(WAIFU_FILE), safe_load(INV_FILE), safe_load(LEVEL_FILE)


# ===== SAFE CONVERTERS =====
def to_int(value, default=0):
    try:
        return int(value) if value is not None else default
    except (TypeError, ValueError):
        return default


# ===== LEVEL =====
def get_level(level_data, user_id, waifu_id):
    try:
        user_lv = level_data.get(str(user_id), {})

        if not isinstance(user_lv, dict):
            return 1

        data = user_lv.get(str(waifu_id))

        if isinstance(data, dict):
            return max(1, to_int(data.get("level", 1), 1))

        if isinstance(data, int):
            return max(1, data)

        return 1

    except Exception:
        return 1


# ===== INVENTORY NORMALIZER =====
def normalize_waifus_field(user_data):
    changed = False

    if not isinstance(user_data, dict):
        return {}, True

    waifus = user_data.get("waifus", {})

    # list -> dict
    if isinstance(waifus, list):
        new_waifus = {}

        for item in waifus:
            if isinstance(item, str):
                new_waifus[str(item)] = 0

            elif isinstance(item, dict):
                w_id = item.get("id") or item.get("waifu_id") or item.get("name")

                if w_id is not None:
                    new_waifus[str(w_id)] = max(
                        0, to_int(item.get("love", item.get("amount", 0)), 0)
                    )

        user_data["waifus"] = new_waifus
        waifus = new_waifus
        changed = True

    elif not isinstance(waifus, dict):
        user_data["waifus"] = {}
        waifus = {}
        changed = True

    # ép key + fix value
    fixed = {}
    for k, v in waifus.items():
        k = str(k)

        if isinstance(v, dict):
            v["love"] = max(0, to_int(v.get("love", v.get("amount", 0)), 0))
            fixed[k] = v
        else:
            fixed[k] = max(0, to_int(v, 0))

    if fixed != waifus:
        user_data["waifus"] = fixed
        waifus = fixed
        changed = True

    # fix default
    default = user_data.get("default_waifu")
    if default is not None and str(default) not in waifus:
        user_data["default_waifu"] = None
        changed = True

    return waifus, changed


# ===== CLEANUP =====
def cleanup_missing_waifu(inventory, user_id, user_data, waifu_id):
    changed = False
    waifus = user_data.get("waifus", {})

    waifu_id = str(waifu_id)

    if isinstance(waifus, dict) and waifu_id in waifus:
        waifus.pop(waifu_id, None)
        changed = True

    if str(user_data.get("default_waifu")) == waifu_id:
        user_data["default_waifu"] = None
        changed = True

    if changed:
        inventory[user_id] = user_data

    return changed


# ===== CORE =====
async def view_waifu_logic(user, send, send_embed, waifu_id: str):
    waifu_id = str(waifu_id)

    try:
        waifu_data, inventory, level_data = load_data()
        user_id = str(user.id)

        if user_id not in inventory or not isinstance(inventory.get(user_id), dict):
            return await safe_send(user, content="❌ Bạn chưa có waifu nào!")

        user_data = inventory[user_id]

        # normalize
        waifus, changed = normalize_waifus_field(user_data)

        if changed:
            inventory[user_id] = user_data
            if not save_json_atomic(INV_FILE, inventory):
                print("[WARN] Failed to save inventory after normalize")

        if waifu_id not in waifus:
            return await safe_send(user, content="❌ Bạn không sở hữu waifu này!")

        if waifu_id not in waifu_data or not isinstance(waifu_data.get(waifu_id), dict):
            if cleanup_missing_waifu(inventory, user_id, user_data, waifu_id):
                if not save_json_atomic(INV_FILE, inventory):
                    print("[WARN] Failed to save inventory after cleanup")

            return await safe_send(user, content="❌ Waifu này không tồn tại!")

        waifu = waifu_data[waifu_id]
        waifu_inv = waifus.get(waifu_id, 0)

        name = waifu.get("name") or waifu_id
        rank = waifu.get("rank") or "Unknown"
        bio = waifu.get("Bio") or "Không có tiểu sử."
        image = waifu.get("image") or ""

        if isinstance(waifu_inv, dict):
            love_point = waifu_inv.get("love", waifu_inv.get("amount", 0))
        else:
            love_point = waifu_inv

        love_point = max(0, to_int(love_point, 0))

        level = get_level(level_data, user_id, waifu_id)

        embed_data = {
            "title": "💖 Waifu của bạn 💖",
            "description": (
                f"🩷 Tên waifu: **{name}** (id: `{waifu_id}`)\n"
                f"🎖️ Level: **{level}**\n"
                f"🎖️ Rank: **{rank}** | ❤️ Love: **{love_point}**\n"
                f"📖 Tiểu sử: {bio}"
            ),
            "footer": f"Waifu thuộc sở hữu của {user.name}",
        }

        if isinstance(image, str) and image.startswith(("http://", "https://")):
            embed_data["image"] = image

        return await send_embed(embed_data)

    except Exception as e:
        print(f"[view_waifu_logic] ERROR: {e}")
        return await safe_send(user, content="❌ Đã xảy ra lỗi khi đọc dữ liệu waifu!")
print("Loaded view waifu has successs")