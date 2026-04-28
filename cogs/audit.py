import discord
from discord.ext import commands
from langfuse import get_client
from datetime import timedelta, timezone


class HistoryPaginationView(discord.ui.View):
    def __init__(self, cog, history_items, author_id, page_size: int = 10):
        super().__init__(timeout=180)
        self.cog = cog
        self.history_items = history_items
        self.author_id = author_id
        self.page_size = page_size
        self.current_page = 0
        self.total_pages = max(1, (len(history_items) + page_size - 1) // page_size)
        self._sync_buttons()

    def _sync_buttons(self):
        self.prev_button.disabled = self.current_page <= 0
        self.next_button.disabled = self.current_page >= self.total_pages - 1

    async def _refresh(self, interaction: discord.Interaction):
        self._sync_buttons()
        embed = await self.cog.build_history_embed(
            history_items=self.history_items,
            page=self.current_page,
            page_size=self.page_size,
            guild=interaction.guild,
        )
        await interaction.response.edit_message(embed=embed, view=self)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("這個分頁按鈕只能由指令發送者操作。", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="上一頁", style=discord.ButtonStyle.secondary)
    async def prev_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_page -= 1
        await self._refresh(interaction)

    @discord.ui.button(label="下一頁", style=discord.ButtonStyle.secondary)
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_page += 1
        await self._refresh(interaction)


class Audit(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.langfuse = get_client()

    def _format_history_time(self, value):
        if not value:
            return "未知時間"

        utc_plus_8 = timezone(timedelta(hours=8))

        for attr in ("start_time", "timestamp", "created_at"):
            candidate = getattr(value, attr, None)
            if candidate:
                if candidate.tzinfo is None:
                    candidate = candidate.replace(tzinfo=timezone.utc)
                candidate = candidate.astimezone(utc_plus_8)
                return candidate.strftime("%Y-%m-%d %H:%M:%S UTC+8")

        if hasattr(value, "strftime"):
            if value.tzinfo is None:
                value = value.replace(tzinfo=timezone.utc)
            value = value.astimezone(utc_plus_8)
            return value.strftime("%Y-%m-%d %H:%M:%S UTC+8")

        return str(value)

    def _extract_history_items(self, observations):
        items = []

        for observation in observations:
            metadata = getattr(observation, "metadata", None) or {}
            user_id = getattr(observation, "user_id", None) or metadata.get("user_id") or "未知使用者"
            display_text = metadata.get("display_text")

            if not display_text:
                continue

            items.append(
                {
                    "datetime": self._format_history_time(observation),
                    "user_id": str(user_id),
                    "display_text": display_text,
                }
            )
        return items

    async def _get_notion_history(self, limit: int = 50):
        if not hasattr(self.langfuse, "async_api"):
            return []

        observations = await self.langfuse.async_api.legacy.observations_v1.get_many(
            name="Notion_ACTION",
            limit=limit,
        )
        data = getattr(observations, "data", []) or []
        return self._extract_history_items(data)

    async def build_history_embed(self, history_items, page: int, page_size: int = 10, guild: discord.Guild | None = None):
        start_index = page * page_size
        page_items = history_items[start_index:start_index + page_size]
        total_pages = max(1, (len(history_items) + page_size - 1) // page_size)

        embed = discord.Embed(title="Notion 動作紀錄", color=discord.Color.blue())
        embed.set_footer(text=f"第 {page + 1} / {total_pages} 頁")

        for offset, item in enumerate(page_items, start=1):
            global_index = start_index + offset
            user = await self.bot.fetch_user(item['user_id'])
            print(user)
            embed.add_field(
                name=f"{global_index}. {item['datetime']}",
                value=f"使用者：`{user.name}`\n動作：{item['display_text']}",
                inline=False,
            )

        return embed

    @commands.command(name="history")
    async def history(self, ctx):
        async with ctx.typing():
            try:
                history_items = await self._get_notion_history(limit=50)
            except Exception as e:
                print(f"history command failed: {e}")
                return await ctx.send("目前無法取得動作紀錄，請稍後再試。")

            if not history_items:
                return await ctx.send("目前查不到任何動作紀錄。")

            embed = await self.build_history_embed(
                history_items=history_items,
                page=0,
                page_size=10,
                guild=ctx.guild,
            )

            if len(history_items) > 10:
                view = HistoryPaginationView(self, history_items, author_id=ctx.author.id, page_size=10)
                await ctx.send(embed=embed, view=view)
            else:
                await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(Audit(bot))
