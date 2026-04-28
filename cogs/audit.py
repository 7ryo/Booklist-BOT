import discord
from discord.ext import commands
from langfuse import get_client
from datetime import timedelta, timezone


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

    async def _get_notion_history(self, limit: int = 10):
        if not hasattr(self.langfuse, "async_api"):
            return []

        observations = await self.langfuse.async_api.legacy.observations_v1.get_many(
            name="Notion_ACTION",
            # name="ERP_ACTION",
            limit=limit,
        )
        data = getattr(observations, "data", []) or []
        return self._extract_history_items(data)

    @commands.command(name="history")
    async def history(self, ctx):
        async with ctx.typing():
            try:
                history_items = await self._get_notion_history(limit=10)
            except Exception as e:
                print(f"history command failed: {e}")
                return await ctx.send("目前無法取得動作紀錄，請稍後再試。")

            if not history_items:
                return await ctx.send("目前查不到任何動作紀錄。")

            embed = discord.Embed(title="Notion 動作紀錄", color=discord.Color.blue())

            for index, item in enumerate(history_items, start=1):
                embed.add_field(
                    name=f"{index}. {item['datetime']}",
                    value=f"使用者：`{item['user_id']}`\n動作：{item['display_text']}",
                    inline=False,
                )

            await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(Audit(bot))
