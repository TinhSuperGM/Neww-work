import discord
from Data import data_user


# ===== LOGIC =====
async def gold_logic(interaction, user: discord.User = None):
    target = user if user else interaction.user
    user_id = str(target.id)

    data = data_user.load_data()

    # ===== USER CHƯA CÓ DATA =====
    if user_id not in data:
        if target.id == interaction.user.id:
            data[user_id] = {"gold": 100, "last_free": 0}
            data_user.save_data(data)

            return await interaction.response.send_message(
                "🎉 Chào người mới! Bạn nhận 100 🪙 để bắt đầu!"
            )
        else:
            return await interaction.response.send_message(
                "❌ Người này chưa đăng ký tài khoản!"
            )

    gold_amount = data[user_id].get("gold", 0)

    # ===== HIỂN THỊ =====
    if target.id != interaction.user.id:
        return await interaction.response.send_message(
            f"💰 Số dư của <@{target.id}>: {gold_amount} <a:gold:1492792339436142703>"
        )
    else:
        return await interaction.response.send_message(
            f"💰 Số dư của bạn: {gold_amount} <a:gold:1492792339436142703>"
        )


# ===== SETUP =====
async def setup(bot):
    pass


print("Loaded gold has success")