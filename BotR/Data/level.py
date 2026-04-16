import os
import json
import asyncio

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
INV_FILE = os.path.join(BASE_DIR, "inventory.json")
LEVEL_FILE = os.path.join(BASE_DIR, "level.json")

LEVEL_DIV = 100

# ===== CACHE =====
LEVEL_CACHE = None
LOCK = asyncio.Lock()


# ===== LOAD =====
def load_json(path):
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except:
        return {}


# ===== SAVE (ATOMIC) =====
def save_json(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)
    os.replace(tmp, path)


# ===== LEVEL CALC =====
def calc_level(love: int) -> int:
    return love // LEVEL_DIV


# ===== GET LOVE =====
def get_love_from_inv(user_id: str, waifu_id: str) -> int:
    inv = load_json(INV_FILE)
    user = inv.get(user_id, {})
    waifus = user.get("waifus", {})

    val = waifus.get(waifu_id)

    if isinstance(val, int):
        return val
    elif isinstance(val, dict):
        return val.get("love", 0)

    return 0


# ===== GET LEVEL (REALTIME - KHÔNG SAVE) =====
def get_level(user_id: str, waifu_id: str) -> int:
    love = get_love_from_inv(user_id, waifu_id)
    return calc_level(love)


# ===== OPTIONAL CACHE SYNC =====
async def sync_all():
    global LEVEL_CACHE

    async with LOCK:
        inv = load_json(INV_FILE)
        new_cache = {}

        for user_id, user_info in inv.items():
            waifus = user_info.get("waifus", {})
            new_cache[user_id] = {}

            for w_id, w_val in waifus.items():
                if isinstance(w_val, int):
                    love = w_val
                elif isinstance(w_val, dict):
                    love = w_val.get("love", 0)
                else:
                    love = 0

                new_cache[user_id][w_id] = calc_level(love)

        LEVEL_CACHE = new_cache


# ===== GET FROM CACHE =====
def get_level_cached(user_id: str, waifu_id: str) -> int:
    if LEVEL_CACHE is None:
        return get_level(user_id, waifu_id)

    return LEVEL_CACHE.get(user_id, {}).get(waifu_id, 0)


# ===== FORCE SAVE (HIẾM DÙNG) =====
async def save_all_levels():
    async with LOCK:
        if LEVEL_CACHE is not None:
            save_json(LEVEL_FILE, LEVEL_CACHE)


print("Loaded level has success")