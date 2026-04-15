import os
import discord
import json
import ast
from datetime import datetime, timedelta
from discord.ext import commands
from notion_client import Client
from langchain_community.utilities import SQLDatabase

import importlib
import utils.ui, utils.chains

importlib.reload(utils.ui)
importlib.reload(utils.chains)

from utils.ui import ConfirmAddView, ConfirmUpdateView, AddInfoModal, NotionConfigSetupView
from utils.chains import create_intent_chain, create_recommend_chain

class Notion(commands.Cog):

    def __init__(self, bot):
        self.bot = bot
        self.db_url = os.getenv("USER_DB_CONNECT_URI")
        self.sql_db = SQLDatabase.from_uri(self.db_url) if self.db_url else None
        self.notion_config_cache = {}
        self.cache_ttl = timedelta(minutes=10)
        self.recommend_chain = create_recommend_chain(
            llm=bot.llm,
            search_service=bot.search_service,
            get_notion_func=self._get_page_content
        )
        if not self.db_url:
            print("請在.env檔案中設定USER_DB_CONNECT_URI")

    def _get_cached_runtime(self, user_id: str):
        cached = self.notion_config_cache.get(user_id)
        if not cached:
            return None
        if cached["expires_at"] <= datetime.utcnow():
            self.notion_config_cache.pop(user_id, None)
            return None
        return cached

    def _load_user_config_from_db(self, user_id: str):
        if not self.sql_db:
            print("no sql_db")
            return None

        safe_user_id = str(user_id).replace("'", "''")
        sql = (
            "SELECT notion_token, database_id "
            "FROM user_notion_config "
            f"WHERE discord_user_id = '{safe_user_id}' "
            "LIMIT 1"
        )
        print(sql)
        raw_row = self.sql_db.run(sql, fetch="one")
        if not raw_row:
            return None

        try:
            row = ast.literal_eval(raw_row)[0] # list of tuples [0]
        except (SyntaxError, ValueError):
            return None

        if not isinstance(row, (tuple, list)) or len(row) < 2:
            return None

        notion_api_key = row[0]
        print(notion_api_key)
        notion_database_id = row[1]
        if not notion_api_key or not notion_database_id:
            return None
        return {
            "notion_api_key": notion_api_key,
            "notion_database_id": notion_database_id,
        }

    def _build_runtime(self, user_id: str, notion_api_key: str, notion_database_id: str):
        notion_client = Client(auth=notion_api_key)
        database = notion_client.databases.retrieve(database_id=notion_database_id)
        data_sources = database.get("data_sources", [])
        if not data_sources:
            raise ValueError("找不到 Notion data source，請確認 database id 是否正確。")

        runtime = {
            "notion": notion_client,
            "database_id": notion_database_id,
            "data_source_id": data_sources[0]["id"],
            "expires_at": datetime.utcnow() + self.cache_ttl,
        }
        self.notion_config_cache[user_id] = runtime
        return runtime

    def _get_user_runtime(self, user_id: str):
        cached = self._get_cached_runtime(user_id)
        if cached:
            return cached

        config = self._load_user_config_from_db(user_id)
        if not config:
            print("no config")
            return None

        try:
            return self._build_runtime(
                user_id=user_id,
                notion_api_key=config["notion_api_key"],
                notion_database_id=config["notion_database_id"],
            )
        except Exception as e:
            print(f"Notion runtime init失敗(user={user_id}): {e}")
            return None

    async def save_user_notion_config(self, user_id: str, notion_api_key: str, notion_database_id: str):
        if not self.sql_db:
            raise ValueError("資料庫連線未設定，請確認 USER_DB_CONNECT_URI")

        safe_user_id = str(user_id).replace("'", "''")
        safe_api_key = notion_api_key.replace("'", "''")
        safe_database_id = notion_database_id.replace("'", "''")
        upsert_sql = f"""
        INSERT INTO user_notion_config (discord_user_id, notion_api_key, notion_database_id)
        VALUES ('{safe_user_id}', '{safe_api_key}', '{safe_database_id}')
        ON CONFLICT (discord_user_id)
        DO UPDATE SET
            notion_api_key = EXCLUDED.notion_api_key,
            notion_database_id = EXCLUDED.notion_database_id
        """
        self.sql_db.run(upsert_sql)

        # refresh cache after write
        self.notion_config_cache.pop(str(user_id), None)
        self._build_runtime(
            user_id=str(user_id),
            notion_api_key=notion_api_key,
            notion_database_id=notion_database_id,
        )

    async def _ensure_user_runtime(self, ctx):
        user_id = str(ctx.author.id)
        runtime = self._get_user_runtime(user_id)
        if runtime:
            return runtime

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
                runtime = await self._ensure_user_runtime(ctx)
                if not runtime:
                    return

                # 3. query the "data source"

                response = runtime["notion"].data_sources.query(
                    data_source_id=runtime["data_source_id"],
                    page_size=1
                )

                print(json.dumps(response, indent=2, ensure_ascii=False))

                if not response['results']:
                    await ctx.send("連線成功，但目前資料庫是空的")
                    return
                
                # 抓第一筆資料
                first_page = response['results'][0]
                properties = first_page.get("properties", {})

            except Exception as e:
                print(f"test_notion出問題: {e}")


    @commands.command(name="note")
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
        result = await self.bot.intent_parser.ainvoke(
            {"input": user_input},
            config=self.bot.get_langchain_config(
                trace_name="discord.!note",
                user_id=ctx.author.id
            )
        )
        print(result)

        if result['intent'] == 'SEARCH':
            await self.handle_notion_search(ctx, result['params'], user_id=user_id)
        elif result['intent'] == 'ADD':
            await self.handle_notion_add(ctx, result['params'], user_id=user_id)
        elif result['intent'] == 'UPDATE':
            await self.handle_update(ctx, result['params'], user_id=user_id)

    # in smart_note
    async def handle_notion_search(self, ctx, params, user_id: str):
        response = await self._notion_search(
            title=params.get("title"),
            author=params.get("author"),
            status=params.get("status"),
            user_id=user_id,
        )

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
        search_result = await self._notion_search(title=title, user_id=user_id)
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
        new_page = await self._notion_create_note(
            title=title,
            author=author,
            status=status,
            source=source,
            user_id=user_id,
            # 日期
        )
        # await ctx.send(f"已在資料庫中新建{title}！\n連結: {new_page['url']}")

        page_id = new_page['id']

        if content:
            await self._append_content(page_id=page_id, content=content, user_id=user_id)
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
        response = await self._notion_search(title=title, user_id=user_id)
        results = response.get("results", [])
        print(results)

        if not results:
            print("no books found, trigger view")
            view = ConfirmAddView(self, title, content, status)
            return await ctx.send(f"沒有找到《{title}》這本書，要幫你改成『新增』嗎？", view=view)

        page_id = results[0]['id']

        # 2. 更新properties
        if status:
            await self._notion_update_properties(page_id=page_id, status=status, user_id=user_id)
    
        # 3. 有心得(content)的話也要更新
        if content:
            await self._append_content(page_id=page_id, content=content, user_id=user_id)

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
        # notion search 是使用 filter
        print("_notion_search() is called")
        if not user_id:
            return {"results": []}

        runtime = self._get_user_runtime(str(user_id))
        if not runtime:
            return {"results": []}

        filters = []
        if title:
            filters.append({"property": "題名", "title": {"contains": title}})
        if author:
            filters.append({"property": "作者", "multi_select": {"contains": author}})
        if status:
            filters.append({"property": "閱讀狀態", "status": {"equals": status}})
        
        # 有多個條件的時候要用and串起來
        # 「JSON 樹狀結構」
        query_filter = {"and": filters} if len(filters) > 1 else (filters[0] if filters else None)

        print(f"query_filter: {query_filter}")
        return runtime["notion"].data_sources.query(
            data_source_id=runtime["data_source_id"],
            filter=query_filter
        )

    # create new note
    async def _notion_create_note(self, title, author=None, status="待閱讀", source=None, readdate=None, remark=None, user_id=None):
        runtime = self._get_user_runtime(str(user_id)) if user_id else None
        if not runtime:
            raise ValueError("找不到此使用者的 Notion 設定，請先完成設定。")

        properties = {
            "題名": {"title": [{"text": {"content": title}}]},
            "來源": {"select": {"name": source}},
            "閱讀狀態": {"status": {"name": status}}
        }
        if author:
            properties["作者"] = {"multi_select": [{"name": author}]}

        if remark:
            properties['備註'] = {"rich_text": [{"text": {"content": remark}}]}

        # notion date property -> ISO 8601
        if status == "已閱讀":
            today_str = datetime.now().strftime("%Y-%m-%d")
            properties["閱讀日期"] = {"date": {"start": today_str}}
        
        return runtime["notion"].pages.create(
            parent={"data_source_id": runtime["data_source_id"]},
            properties=properties
        )

    # 新增notion children (心得等)
    async def _append_content(self, page_id, content, user_id=None):
        # content 理論上要是markdown，但是不確定
        if not content:
            return
        runtime = self._get_user_runtime(str(user_id)) if user_id else None
        if not runtime:
            raise ValueError("找不到此使用者的 Notion 設定，請先完成設定。")
        
        # 要把換行拆成不同的block (記得notion裡面不同block可以拖來拖去)
        lines = content.split('\n')
        blocks = [
            {
                "object": "block",
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [{"type": "text", "text": {"content": line}}] #單數的line
                }
            } for line in lines
        ]

        # blocks = [
        #     {
        #         "object": "block",
        #         "type": "paragraph",
        #         "paragraph": {
        #             "rich_text": [{"type": "text", "text": {"content": content}}] #單數的line
        #         }
        #     } 
        # ]

        return runtime["notion"].blocks.children.append(
            block_id=page_id,
            children=blocks
        )

    # 更新或修改 properties
    async def _notion_update_properties(self, page_id, status, user_id=None):
        if not status:
            return
        runtime = self._get_user_runtime(str(user_id)) if user_id else None
        if not runtime:
            raise ValueError("找不到此使用者的 Notion 設定，請先完成設定。")
        update_items = {}
        update_items['閱讀狀態'] = {"status": {"name": status}}
        
        # 如果看完了 也要把日期更新上去
        if status == "已閱讀":
            today_str = datetime.now().strftime("%Y-%m-%d")
            update_items['閱讀日期'] = {"date": {"start": today_str}}

        if update_items:
            runtime["notion"].pages.update(page_id=page_id, properties=update_items)

    # 獲取notion children
    async def _get_page_content(self, title, user_id=None):
        """
        抓notion頁面中的所有blocks作為 RAG Context
        因為notion return的格式非常非常多層，只要把真正的內容抓出來就好
        """
        try:
            if not user_id:
                return None

            runtime = self._get_user_runtime(str(user_id))
            if not runtime:
                return None

            search_results = await self._notion_search(title=title, user_id=str(user_id))
            if not search_results.get("results"):
                print("Notion沒有找到這本書，會切換成general recommend")
                return None

            first_page = search_results["results"][0]
            page_id = search_results["results"][0]["id"]
            # response = await self.notion.blocks.children.list(block_id=page_id)

            # full book title
            full_book_title = first_page['properties']['題名']['title'][0]['plain_text']

            response = runtime["notion"].blocks.children.list(block_id=page_id)


            paragraphs = []
            for block in response.get("results", []):
                # 因為只要抓文字的block
                block_type = block.get("type")
                if block_type == "paragraph":
                    rich_text = block["paragraph"].get("rich_text", [])
                    if rich_text:
                        paragraphs.append(rich_text[0].get("plain_text", ""))
                elif block_type == "bulleted_list_item":
                    rich_text = block["bulleted_list_item"].get("rich_text", [])
                    if rich_text:
                        paragraphs.append(f"- {rich_text[0].get('plain_text', '')}")
                
            # 組合起來
            # 不過也要確保有東西
            full_content = "\n".join(paragraphs)
            # print(f"full_content: {full_content}")
            if not full_content.strip():
                print(f"no full_content, will return None~~~~~~~~")
                return {
                    "book_title": full_book_title,
                    "content": None
                }
            else:
                return {
                    "book_title": full_book_title,
                    "content": full_content
                }
            
        except Exception as e:
            print(f"Error at _get_page_content: {e}")
            return ""


async def setup(bot):
    await bot.add_cog(Notion(bot))