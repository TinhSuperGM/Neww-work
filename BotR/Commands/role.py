# role.py

# ===== TEAM =====
TEAM_VILLAGE = "village"
TEAM_WOLF = "wolf"


# ===== BASE ROLE =====
class Role:
    def __init__(self, player):
        self.player = player
        self.name = "Unknown"
        self.team = None
        self.alive = True

    # ===== EVENTS =====
    async def on_game_start(self, game):
        """Khi game bắt đầu"""
        pass

    async def on_night_start(self, game):
        """Khi bắt đầu ban đêm"""
        pass

    async def night_action(self, game, target):
        """Hành động ban đêm"""
        pass

    async def on_day_start(self, game):
        """Khi bắt đầu ban ngày"""
        pass

    async def on_death(self, game):
        """Khi chết"""
        pass

    # ===== HELPER =====
    async def send(self, message):
        """Gửi DM cho player"""
        try:
            await self.player.send(message)
        except:
            pass


# ===== VILLAGE =====
class Village(Role):
    def __init__(self, player):
        super().__init__(player)
        self.name = "Villager"
        self.team = TEAM_VILLAGE

    async def on_game_start(self, game):
        await self.send("👤 Bạn là **Dân làng**.\nHãy tìm ra Sói!")


# ===== WOLF =====
class Wolf(Role):
    def __init__(self, player):
        super().__init__(player)
        self.name = "Werewolf"
        self.team = TEAM_WOLF

    async def on_game_start(self, game):
        wolves = [
            p for p in game.players
            if hasattr(p, "role") and p.role.team == TEAM_WOLF
        ]

        names = ", ".join([p.display_name for p in wolves if p != self.player])

        msg = "🐺 Bạn là **Sói**.\n"
        if names:
            msg += f"Đồng đội của bạn: {names}\n"
        msg += "Hãy tiêu diệt tất cả dân làng!"

        await self.send(msg)

    async def night_action(self, game, target):
        """Sói chọn người để giết"""
        game.add_action({
            "type": "kill",
            "actor": self.player,
            "target": target,
            "priority": 3
        })


# ===== ROLE MAP =====
ROLE_MAP = {
    "village": Village,
    "wolf": Wolf
}
