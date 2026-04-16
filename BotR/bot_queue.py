import asyncio

# ===== CONFIG =====
RATE_LIMIT = 1.0  # seconds giữa mỗi request (chống spam API Discord)

queue = asyncio.Queue()
workers_started = False


# ===== TASK WRAPPER =====
class QueueTask:
    def __init__(self, func):
        self.func = func
        self.future = asyncio.get_event_loop().create_future()


# ===== WORKER =====
async def worker():
    while True:
        task: QueueTask = await queue.get()

        try:
            result = await task.func()
            task.future.set_result(result)
        except Exception as e:
            task.future.set_exception(e)

        await asyncio.sleep(RATE_LIMIT)
        queue.task_done()


# ===== PUBLIC API =====
async def paced_call(func):
    """
    Dùng thay cho:
    await channel.send(...)
    await message.edit(...)
    """
    task = QueueTask(func)
    await queue.put(task)
    return await task.future


def start_workers(bot=None, amount=2):
    """
    Gọi trong setup_hook (main.py)
    """
    global workers_started

    if workers_started:
        return

    loop = asyncio.get_event_loop()

    for _ in range(amount):
        loop.create_task(worker())

    workers_started = True
print("Loaded bot queue has successs")