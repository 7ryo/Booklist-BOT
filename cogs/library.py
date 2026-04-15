import os
import ast
import discord
from discord.ext import commands
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_community.utilities import SQLDatabase
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser

class Library(commands.Cog):

    sql_prompt = ChatPromptTemplate.from_template("""
    你是一個專門為圖書館開發的PostgreSQL專家。
    請根據提供的資料表結構，將使用者問題轉換成精確的SQL query。
                                                
    ### 規範守則：
    1. 輸出格式：只能輸出純SQL格式，絕對不可包含```sql等code block標籤
    2. 地點匹配：地點欄位請使用'LIKE %地點%'，以增加靈活性
    3. 嚴禁：絕對不要執行DROP, DELETE, UPDATE, INSERT指令
    4. 欄位選擇：
    - 務必包含使用者要求的所有資訊（如：作者、出版社、狀態等）。
    - **不論使用者是否要求，SELECT 語句中必須永遠包含 `book.title` 和 `inventory.call_number`。**

    ### 資料表結構(Schema)：
    {table_info}      
                                                
    ### Schema欄位詳細定義與範例 (Column Glossary):
    - 'year': 這是【出版年份】，不是出版社。範例: 2024
    - 'publisher': 這是【出版社名稱】。範例: 遠流、時報

    ### 使用者隱私規範：
    1. 在生成查詢book資料表的SQL query時，永遠必須包含discord_user_id = '{discord_user_id}'，避免使用者看到其他使用者的資料。
    2. 如果使用者沒有提供discord_user_id，則不應該生成SQL query。

    ### 使用者問題：  
    {input}   

    SQL Query:                                                                                  
    """)


    def __init__(self, bot):
        self.bot = bot

        # 因為在main.py已經跑過load_dotenv()了
        # 這邊可以直接在os抓東西

        # database: read-only user
        db_url = os.getenv("USER_DB_CONNECT_URI")
        if not db_url:
            print("請在.env檔案中設定USER_DB_CONNECT_URI")
        self.db = SQLDatabase.from_uri(db_url)

        self.table_info = self.db.get_table_info()

        

        # LCEL chain
        self.sql_generator = self.sql_prompt | self.bot.llm | StrOutputParser()

    # 意圖: 查書
    # 這個func的名字就是我們自己取的了～
    @commands.command(name="lib")
    async def search(self, ctx, *, question):

        async with ctx.typing(): # 會顯示：正在輸入中...
            try:
                discord_user_id = str(ctx.author.id)
                sql_query = self.sql_generator.invoke({
                    "table_info": self.table_info,
                    "discord_user_id": discord_user_id,
                    "input": question
                }, config=self.bot.get_langchain_config(
                    trace_name="discord.!lib",
                    user_id=discord_user_id
                ))

                print(sql_query)

                raw_results = self.db.run(sql_query, fetch='all') # list of tuples

                # 因為langchain抓回來的type是str
                # 先用 ast.literal_eval() 轉成python可以用的list
                try:
                    list_results = ast.literal_eval(raw_results)
                except:
                    list_results = []
                

                if not list_results:
                    await ctx.send("沒有找到東西。可能是關鍵字不對或是程式抽風。請再試一次。")
                    return
            
                
                embed = discord.Embed(title="圖書狀況", color=discord.Color.green())

                for i, row in enumerate(list_results[:10]):
                    title = row[0]
                    details = "\n".join(f"．{item}" for item in row[1:])

                    embed.add_field(
                        name=f"{i+1}. {title}",
                        value=details,
                        inline=False
                    )

                await ctx.send(embed=embed)

            
            except Exception as e:
                await ctx.send(f"遇到問題：`{str(e)[:100]}`")

async def setup(bot):
    await bot.add_cog(Library(bot))
    


# table_info = """
# Table 'book' contains the following columns:
# - book_id: The unique id of the book.
# - title: The name of the book (書名).
# - author: The person who wrote the book (作者).
# - publisher: The company that published the book (出版社).
# - year: The year that book published (出版年份). 


# Table 'inventory' contains the following columns:
# - book_id: The unique id of the book.
# - location: The specific library branch where the book is kept (館藏分館，例如：'鼓山分館', '南鼓山分館', '左營分館').
# - call_number: The library classification number (索書號/索取號).
# - status: Current availability of the book (狀態，例如：'在架', '借出', '預約中').

# """