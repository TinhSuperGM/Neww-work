import discord

def build_help_embed(prefix="/"):
    embed = discord.Embed(
        title="📜 Danh sách các lệnh sau khi prefix",
        description=f"Dùng `{prefix}` để sử dụng lệnh",
        color=discord.Color.blue()
    )

    embed.add_field(
        name="💰 Kinh tế",
        value=f"""
{prefix}gold : Xem số dư hiện tại.
{prefix}daily: Điểm danh và nhận thưởng mỗi ngày.
{prefix}cf: Quay đồng xu ( Cú pháp: .cf <sap/ngua> <tiền cược>)
{prefix}bc: Chơi Bầu cua ( Cú pháp: .bc <nai/bau/ga/ca/cua/tom> <tiền cược>)
{prefix}work: đưa waifu của bạn đi làm và nhận gold
{prefix}code: Nhập code ( Cú pháp: {prefix}code <mã>)
""",
        inline=False
    )

    embed.add_field(
        name="💖 Waifu",
        value=f"""
{prefix}rw: roll waifu
{prefix}wl: Xem bộ sưu tập
{prefix}ws: Chọn waifu mặc định
{prefix}sell: bán waifu
{prefix}bag: Xem waifu và vật phẩm trong kho
""",
        inline=False
    )

    embed.add_field(
        name="💍 Couple",
        value=f"""
{prefix}cp: tỏ tình ai đó
{prefix}cpr: Gửi lời đề nghị chia tay
{prefix}cpc: Hủy lời đề nghị chia tay
{prefix}cpi: xem thông tin cặp đôi
{prefix}cpg: Tặng quà cho nữa kia
""",
        inline=False
    )

    embed.add_field(
        name="🏷 Đấu giá",
        value=f"""
{prefix}dg: Tạo bài đấu giá
{prefix}hdg: Hủy bài đấu giá
""",
        inline=False
    )

    embed.add_field(
        name="Khác",
        value=f"""
{prefix}h: lệnh hướng dẫn member
{prefix}me: xem profile của bản thân hoặc người khác.
{prefix}gift: Tặng quà cho người khác ( {prefix}gift <waifu/gold> <waifu_id/amount> <user_name>)
""",
        inline=False
    )

    embed.add_field(
        name="Battle Waifu",
        value=f"""
{prefix}fight: Chọn ai đó để đấu với bạn hoặc random ( {prefix}fight [mention] )
{prefix}team: Cài đặt team đấu của bạn ( {prefix}team [set/show/remove/clear] <waifu_id>)
{prefix}lock: Khóa trạng thái fight nhằm trách bị người khác mention và fight ( nếu Random thì không có tác dụng )
{prefix}zombie: Đưa team đấu của bạn đi chiến với lũ zombie và nhận thưởng!
""",
        inline=False
    )

    embed.set_footer(text="Hướng dẫn dùng bot: Bạn chỉ cần nhập đúng theo trên hoặc thay . thành / để dùng. ( Dấu <> là bắt buộc, [] là tùy chọn.")

    return embed

# ===== SLASH =====

async def help_slash(interaction: discord.Interaction):
    embed = build_help_embed("/")
    await interaction.response.send_message(embed=embed)


# ===== PREFIX =====
async def help_prefix(message):
    embed = build_help_embed(".")
    await message.channel.send(embed=embed)
print("Loaded help has successs")