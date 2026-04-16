import json
import os
import asyncio

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FILE_PATH = os.path.join(BASE_DIR, "Data", "user.json")

# ===== CACHE =====
DATA_CACHE = None
DIRTY = False

USER_LOCKS = {}

def get_lock(user_id: str):
    user_id = str(user_id)
    if user_id not in USER_LOCKS:
        USER_LOCKS[user_id] = asyncio.Lock()
    return USER_LOCKS[user_id]


# ===== LOAD =====
def load_data():
    global DATA_CACHE

    if DATA_CACHE is not None:
        return DATA_CACHE

    if not os.path.exists(FILE_PATH):
        with open(FILE_PATH, "w", encoding="utf-8") as f:
            json.dump({}, f)

    try:
        with open(FILE_PATH, "r", encoding="utf-8") as f:
            DATA_CACHE = json.load(f)
    except:
        DATA_CACHE = {}

    return DATA_CACHE


# ===== SAVE =====
def save_data(data=None):
    global DATA_CACHE

    if data is not None:
        DATA_CACHE = data

    tmp = FILE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(DATA_CACHE, f, indent=4, ensure_ascii=False)
    os.replace(tmp, FILE_PATH)


# ===== AUTO SAVE =====
async def auto_save_loop():
    global DIRTY
    while True:
        await asyncio.sleep(5)
        if DIRTY:
            save_data()
            DIRTY = False


# ===== GET USER =====
def get_user(user_id):
    data = load_data()
    user_id = str(user_id)

    if user_id not in data:
        data[user_id] = {
            "gold": 0,
            "last_free": 0
        }

    return data[user_id]


# ===== GET GOLD =====
def get_gold(user_id):
    user = get_user(user_id)
    return int(user.get("gold", 0))


# ===== ADD GOLD (LOCKED) =====
async def add_gold(user_id, amount):
    global DIRTY

    lock = get_lock(user_id)
    async with lock:
        user = get_user(user_id)

        user["gold"] = int(user.get("gold", 0)) + int(amount)

        if user["gold"] < 0:
            user["gold"] = 0

        DIRTY = True


# ===== REMOVE GOLD (LOCKED) =====
async def remove_gold(user_id, amount):
    global DIRTY

    lock = get_lock(user_id)
    async with lock:
        user = get_user(user_id)

        if user["gold"] < amount:
            return False

        user["gold"] -= int(amount)
        DIRTY = True
        return True


# ===== TRANSFER GOLD (ANTI-MINT CORE) =====
async def transfer_gold(from_user, to_user, amount):
    global DIRTY

    u1 = str(from_user)
    u2 = str(to_user)

    # lock theo thứ tự để tránh deadlock
    first, second = sorted([u1, u2])

    async with get_lock(first):
        async with get_lock(second):

            data = load_data()

            if u1 not in data:
                data[u1] = {"gold": 0}

            if u2 not in data:
                data[u2] = {"gold": 0}

            if data[u1]["gold"] < amount:
                return False

            data[u1]["gold"] -= amount
            data[u2]["gold"] += amount

            DIRTY = True
            return True


# ===== SAVE USER =====
def save_user(user_id, user_data):
    global DIRTY
    data = load_data()
    user_id = str(user_id)

    data[user_id] = user_data
    DIRTY = True


print("Loaded data user has success")