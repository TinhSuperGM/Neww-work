import discord
from discord.ext import commands
import asyncio
import time
import json
import os
from dotenv import load_dotenv

load_dotenv()

from Data.level import sync_all
from Commands.work import init_work  # 🔥 FIX QUAN TRỌNG

class MyBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True

        super().__init__(
            command_prefix=".",
            intents=intents,
            help_command=None
        )

    async def setup_hook(self):
        from Commands.slash import setup as slash_setup
        from Commands.prefix import setup as prefix_setup
        from Other.ranking import setup as ranking_setup
        from Other.phe_duyet import setup as phe_duyet_setup
        from bot_queue import start_workers
        from Data import data_user

        # ===== LOAD MODULE =====
        await ranking_setup(self)
        await slash_setup(self)
        await prefix_setup(self)
        await phe_duyet_setup(self)

        # ===== START WORKERS =====
        start_workers(self, 5)  # 🔥 FIX: đặt đúng chỗ

        # ===== BACKGROUND TASK =====
        self.loop.create_task(self.auto_sync_level())
        self.loop.create_task(self.auction_loop())
        self.loop.create_task(data_user.auto_save_loop())

        # ===== SYNC SLASH =====
        await self.tree.sync()

    async def auto_sync_level(self):
        await self.wait_until_ready()

        while not self.is_closed():
            try:
                await sync_all()
            except Exception as e:
                print(f"❌ Sync lỗi: {e}")

            await asyncio.sleep(30)

    async def auction_loop(self):
        from Data import data_user
        from Commands.dau_gia import get_channels as load_channels

        await self.wait_until_ready()

        while not self.is_closed():
            await asyncio.sleep(30)

            base = os.path.dirname(os.path.abspath(__file__))
            data_path = os.path.join(base, "Data")

            auction_file = os.path.join(data_path, "auction.json")
            inv_file = os.path.join(data_path, "inventory.json")

            if not os.path.exists(auction_file):
                continue

            try:
                with open(auction_file, encoding="utf-8") as f:
                    auctions = json.load(f)

                with open(inv_file, encoding="utf-8") as f:
                    inv = json.load(f)
            except:
                continue

            channels = load_channels()
            now = time.time()
            remove_list = []

            for aid, a in list(auctions.items()):
                if now < a.get("end_time", 0):
                    continue

                seller = str(a["seller"])
                winner = a.get("highest_bidder")
                waifu = a["waifu_id"]
                love = a.get("love", 0)
                price = a.get("current_bid", 0)

                # ===== RESULT =====
                if winner:
                    winner = str(winner)

                    user = inv.setdefault(winner, {})
                    waifus = user.setdefault("waifus", {})
                    bag = user.setdefault("bag", {})

                    if waifu in waifus:
                        bag[waifu] = bag.get(waifu, 0) + 1
                    else:
                        waifus[waifu] = love

                    # 🔥 FIX ASYNC
                    await data_user.add_gold(seller, price)

                    result_text = f"🏆 <@{winner}> thắng đấu giá **{waifu}** ({price} 🪙)"

                else:
                    user = inv.setdefault(seller, {})
                    waifus = user.setdefault("waifus", {})
                    waifus[waifu] = love

                    result_text = f"❌ Không ai mua **{waifu}** → trả lại <@{seller}>"

                # ===== DELETE MESSAGES =====
                for msg_info in a.get("messages", []):
                    ch = self.get_channel(int(msg_info["channel_id"]))
                    if ch:
                        try:
                            msg = await ch.fetch_message(int(msg_info["message_id"]))
                            await msg.delete()
                        except:
                            pass

                # ===== SEND RESULT =====
                for gid, ch_data in channels.items():
                    ch_id = ch_data.get("channel_id") if isinstance(ch_data, dict) else ch_data

                    if not ch_id:
                        continue

                    ch = self.get_channel(int(ch_id))
                    if ch:
                        try:
                            await ch.send(result_text)
                        except:
                            pass

                remove_list.append(aid)

            # ===== SAVE =====
            for aid in remove_list:
                auctions.pop(aid, None)

            try:
                with open(auction_file, "w", encoding="utf-8") as f:
                    json.dump(auctions, f, indent=4, ensure_ascii=False)

                with open(inv_file, "w", encoding="utf-8") as f:
                    json.dump(inv, f, indent=4, ensure_ascii=False)
            except:
                pass


bot = MyBot()


@bot.event
async def on_ready():
    # 🔥 FIX QUAN TRỌNG NHẤT
    init_work(bot)

    print(f"✅ Bot online: {bot.user}")


@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        return
    raise error


TOKEN = os.getenv("DISCORD_TOKEN")

print("Token OK:", bool(TOKEN))

bot.run(TOKEN)