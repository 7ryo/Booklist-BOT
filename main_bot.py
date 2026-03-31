import os
import discord
from discord.ext import commands
from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI

from utils.chains import create_intent_chain
from utils.web_tools import SearchService


load_dotenv()

class Bot(commands.Bot):
    def __init__(self):
        # 1. Intent
        intents = discord.Intents.default()
        intents.message_content = True # allow bot to "read" the messages

        # 2. init Parent Class
        # 原本些在class外面的話是這樣
        # bot = commands.Bot(command_prefix="!", intents=intents)
        super().__init__(command_prefix="!", intents=intents)

        # 3. init LLM
        # llm: Gemma 3 4b
        self.llm = ChatGoogleGenerativeAI(model="gemma-3-4b-it")
        self.intent_parser = create_intent_chain(self.llm)

        # 4. 其他tools
        self.search_service = SearchService()


    # load cogs
    async def setup_hook(self):
        for extention in ['cogs.library', 'cogs.notion']:
            try:
                await self.load_extension(extention)
                print(f"成功載入{extention}")
            except Exception as e:
                print(f"{extention}載入失敗: {e}")


    # on_ready(): discord > Event Reference > Gateway
    async def on_ready(self):
        print(f"已登入為{self.user}")


# -- 先實例化＋執行 -----------------------------------
# 這樣下面的@bot.event才能聽到
bot = Bot()


# 當使用者輸入出錯的時候
# discord.ext.commands > Event Reference > on_command_error()
@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        await ctx.send("找不到指令。請確認是否有打錯。")
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send("請在指令後方加上關鍵字。")
    else:
        await ctx.send(f"預期外的錯誤：{error}")

# admin 專用重新整理機器人
# (當Cogs有更動的時候，不需要重開main)
@bot.command()
@commands.is_owner()
async def reload(ctx, name):
    try:
        await bot.reload_extension(f"cogs.{name}")
        await ctx.send(f"cogs.{name}已重新讀取")
    except Exception as e:
        await ctx.send(f"重新讀取失敗: {e}")



# -- 總程式 -----------------------------------------
if __name__ == "__main__":

    bot.run(os.getenv("DISCORD_TOKEN"))