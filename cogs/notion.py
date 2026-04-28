import os
import discord
import json
from discord.ext import commands
from langfuse import observe

import importlib
import utils.ui, utils.chains
from utils.notion_service import NotionService, NotionServiceError

importlib.reload(utils.ui)
importlib.reload(utils.chains)
importlib.reload(utils.notion_service)

from utils.ui import ConfirmAddView, ConfirmUpdateView, AddInfoModal, NotionConfigSetupView
from utils.chains import create_intent_chain, create_recommend_chain

class Notion(commands.Cog):

    def __init__(self, bot):
        self.bot = bot
        self.db_url = os.getenv("USER_DB_CONNECT_URI")
        self.notion_service = NotionService(db_url=self.db_url)
        self.recommend_chain = create_recommend_chain(
            llm=bot.llm,
            search_service=bot.search_service,
            get_notion_func=self._get_page_content
        )
        if not self.db_url:
            print("請在.env檔案中設定USER_DB_CONNECT_URI")

    async def save_user_notion_config(self, user_id: str, notion_api_key: str, notion_database_id: str):
        await self.notion_service.save_user_notion_config(
            user_id=user_id,
            notion_api_key=notion_api_key,
            notion_database_id=notion_database_id,
        )

    async def _ensure_user_runtime(self, ctx):
        user_id = str(ctx.author.id)
        try:
            runtime = self.notion_service.get_user_runtime(user_id)
            if runtime:
                return runtime
        except NotionServiceError as e:
            await ctx.send(f"Notion 連線失敗：{e}")
            return None

        view = NotionConfigSetupView(self)
        await ctx.send(
            "你還沒設定 Notion 連線資訊。請先點按鈕提供 Notion API Key 與 Database ID。",
            view=view,
        )
        return None

    @commands.command(name="test_notion")
    async def test_notion(self, ctx): # 因為沒有要輸入什麼所以不需要後面的 ＊question
        async with ctx.typing():
            try:
                response = await self.notion_service.test_connection(user_id=str(ctx.author.id), page_size=1)

                print(json.dumps(response, indent=2, ensure_ascii=False))

                if not response['results']:
                    await ctx.send("連線成功，但目前資料庫是空的")
                    return
                
                # 抓第一筆資料
                first_page = response['results'][0]
                properties = first_page.get("properties", {})

            except NotionServiceError as e:
                await ctx.send(f"Notion 連線失敗：{e}")
            except Exception as e:
                print(f"test_notion出問題: {e}")
                await ctx.send("test_notion 執行失敗：Notion 暫時無法連線或發生未知錯誤，請稍後再試。")


    @commands.command(name="note")
    @observe(name="能看到這個!note嗎", as_type="span")
    async def smart_note(self, ctx, *, user_input: str):
        runtime = await self._ensure_user_runtime(ctx)
        if not runtime:
            return

        user_id = str(ctx.author.id)
        # 首先要分析intent
        # call 掛載在bot上的intent_parser
        # ainvoke = async invoke
        # return type: JSON
        # 因為是 async function -> 記得加 await
        try:
            result = await self.bot.intent_parser.ainvoke(
                {"input": user_input},
                config=self.bot.get_langchain_config(
                    trace_name="discord.!note",
                    user_id=ctx.author.id
                )
            )
        except Exception:
            return await ctx.send("我現在無法判斷你的指令意圖（LLM 暫時無法使用或連線異常），請稍後再試。")
        print(result)

        if result['intent'] == 'SEARCH':
            await self.handle_notion_search(ctx, result['params'], user_id=user_id)
        elif result['intent'] == 'ADD':
            await self.handle_notion_add(ctx, result['params'], user_id=user_id)
        elif result['intent'] == 'UPDATE':
            await self.handle_update(ctx, result['params'], user_id=user_id)

    # in smart_note
    async def handle_notion_search(self, ctx, params, user_id: str):
        try:
            response = await self._notion_search(
                title=params.get("title"),
                author=params.get("author"),
                status=params.get("status"),
                user_id=user_id,
            )
        except NotionServiceError as e:
            return await ctx.send(f"Notion 操作失敗：{e}")
        except Exception:
            return await ctx.send("Notion 搜尋失敗：目前 Notion 可能無法連線，請稍後再試。")

        # print(f"response type: {type(response)}")
        # type: dict
        # print(f"results type: {type(response['results'])}")
        # type: list

        results = response.get("results", [])
        # print(f"results長這樣 {results}")
        if  not results:
            await ctx.send("沒有在Notion找到東西")
        else:
            titles = [p['properties']['題名']['title'][0]['plain_text'] for p in results]
            await ctx.send(f"找到了\n" + "\n".join(t for t in titles))

        return 0
    
    # in smart_note
    async def handle_notion_add(self, ctx, params, user_id: str):
        title = params.get("title")
        content = params.get("content")
        status = params.get("status")
        author = params.get("author")
        source = params.get("source")

        # 首先要確定有沒有書名
        if not title:
            return await ctx.send("你沒有給我書名QAQ")
        
        # 先search看有沒有已經建立過了，如果建立過了就變成修改欄位內容
        try:
            search_result = await self._notion_search(title=title, user_id=user_id)
        except NotionServiceError as e:
            return await ctx.send(f"Notion 操作失敗：{e}")
        except Exception:
            return await ctx.send("Notion 搜尋失敗：目前 Notion 可能無法連線，請稍後再試。")
        if search_result.get("results"):
            page_id = search_result["results"][0]["id"]
            view = ConfirmUpdateView(self, page_id=page_id, title=title, content=content, status=status)
            return await ctx.send(f"《{title}》已經存在資料庫中，要改成更新嗎？", view=view)

        # 檢查欄位是否完整
        if not author or not source:
            # 因為modal只能透過Interaction觸發，所以需要補個按鈕
            view = discord.ui.View()
            btn = discord.ui.Button(label="補全資料並新增", style=discord.ButtonStyle.blurple)

            async def open_modal(interaction):
                await interaction.response.send_modal(AddInfoModal(self, title, content, status))

            btn.callback = open_modal
            view.add_item(btn)
            return await ctx.send(f"點下方按鈕補充資訊", view=view)


        # create new page
        try:
            new_page = await self._notion_create_note(
                title=title,
                author=author,
                status=status,
                source=source,
                user_id=user_id,
                # 日期
            )
        except NotionServiceError as e:
            return await ctx.send(f"Notion 新增失敗：{e}")
        except Exception:
            return await ctx.send("Notion 新增失敗：目前 Notion 可能無法連線，請稍後再試。")
        # await ctx.send(f"已在資料庫中新建{title}！\n連結: {new_page['url']}")

        page_id = new_page['id']

        if content:
            try:
                await self._append_content(page_id=page_id, content=content, user_id=user_id)
            except NotionServiceError as e:
                return await ctx.send(f"已新增《{title}》，但追加心得失敗：{e}")
            except Exception:
                return await ctx.send(f"已新增《{title}》，但追加心得失敗：Notion 可能暫時無法連線，請稍後再試。")
            await ctx.send(f"已新增{title}和心得。")
        else:
            await ctx.send(f"已新增《{title}》。")
    
    # in smart_note
    # 讀完後 更新閱讀狀態、日期、可能還有心得
    # 也有可能看到一半棄了
    async def handle_update(self, ctx, params, user_id: str):
        title=params.get("title")
        status=params.get("status")
        content=params.get("content")

        # 1. 先搜尋有沒有這本書，有的話才能update
        try:
            response = await self._notion_search(title=title, user_id=user_id)
        except NotionServiceError as e:
            return await ctx.send(f"Notion 操作失敗：{e}")
        except Exception:
            return await ctx.send("Notion 搜尋失敗：目前 Notion 可能無法連線，請稍後再試。")
        results = response.get("results", [])
        print(results)

        if not results:
            print("no books found, trigger view")
            view = ConfirmAddView(self, title, content, status)
            return await ctx.send(f"沒有找到《{title}》這本書，要幫你改成『新增』嗎？", view=view)

        page_id = results[0]['id']

        # 2. 更新properties
        if status:
            try:
                await self._notion_update_properties(page_id=page_id, status=status, user_id=user_id)
            except NotionServiceError as e:
                return await ctx.send(f"Notion 更新失敗：{e}")
            except Exception:
                return await ctx.send("Notion 更新失敗：目前 Notion 可能無法連線，請稍後再試。")
    
        # 3. 有心得(content)的話也要更新
        if content:
            try:
                await self._append_content(page_id=page_id, content=content, user_id=user_id)
            except NotionServiceError as e:
                return await ctx.send(f"Notion 追加心得失敗：{e}")
            except Exception:
                return await ctx.send("Notion 追加心得失敗：目前 Notion 可能無法連線，請稍後再試。")

        #
        await ctx.send(f"已更新《{title}》")

    #
    @commands.command(name="recommend")
    async def recommend_books(self, ctx, *, title: str):
        runtime = await self._ensure_user_runtime(ctx)
        if not runtime:
            return

        await ctx.typing()
        user_id = str(ctx.author.id)

        response = await self.recommend_chain.ainvoke(
            {"input": title, "user_id": user_id},
            config=self.bot.get_langchain_config(
                trace_name="discord.!recommend",
                user_id=user_id
            )
        )
        await ctx.send(response)



    # ------------------------------------------------
    # search
    async def _notion_search(self, title=None, author=None, status=None, user_id=None):
        return await self.notion_service.query_database(
            user_id=str(user_id) if user_id else "",
            title=title,
            author=author,
            status=status,
        )

    # create new note
    async def _notion_create_note(self, title, author=None, status="待閱讀", source=None, readdate=None, remark=None, user_id=None):
        return await self.notion_service.create_page(
            user_id=str(user_id) if user_id else "",
            title=title,
            author=author,
            status=status,
            source=source,
            remark=remark,
        )

    # 新增notion children (心得等)
    async def _append_content(self, page_id, content, user_id=None):
        return await self.notion_service.append_content(
            user_id=str(user_id) if user_id else "",
            page_id=page_id,
            content=content,
        )

    # 更新或修改 properties
    async def _notion_update_properties(self, page_id, status, user_id=None):
        return await self.notion_service.update_page_properties(
            user_id=str(user_id) if user_id else "",
            page_id=page_id,
            status=status,
        )

    # 獲取notion children
    async def _get_page_content(self, title, user_id=None):
        try:
            if not user_id:
                return None
            return await self.notion_service.get_page_content(user_id=str(user_id), title=title)
        except Exception as e:
            print(f"Error at _get_page_content: {e}")
            return ""


async def setup(bot):
    await bot.add_cog(Notion(bot))