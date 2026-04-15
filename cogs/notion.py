import os
import discord
import json
from datetime import datetime
from discord.ext import commands
from notion_client import Client

import importlib
import utils.ui, utils.chains

importlib.reload(utils.ui)
importlib.reload(utils.chains)

from utils.ui import ConfirmAddView, ConfirmUpdateView, AddInfoModal
from utils.chains import create_intent_chain, create_recommend_chain

class Notion(commands.Cog):

    def __init__(self, bot):
        self.bot = bot

        self.notion = Client(auth=os.getenv("NOTION_TOKEN"))
        self.database_id = os.getenv("NOTION_DATABASE_ID")
        self.recommend_chain = create_recommend_chain(
            llm=bot.llm,
            search_service=bot.search_service,
            get_notion_func=self._get_page_content
        )

        try:
            # 2025-09 後 Notion API有改動
            # 1. get database id from copied url
            # 2. get datasource id from retreiving the database
            self.db = self.notion.databases.retrieve(database_id=self.database_id)
            self.datasource_id = self.db["data_sources"][0]["id"]
        except Exception as e:
            print(f"Notion database init失敗: {e}")

    @commands.command(name="test_notion")
    async def test_notion(self, ctx): # 因為沒有要輸入什麼所以不需要後面的 ＊question
        async with ctx.typing():
            try:
                

                # 3. query the "data source"

                response = self.notion.data_sources.query(
                    data_source_id=self.datasource_id,
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
            await self.handle_notion_search(ctx, result['params'])
        elif result['intent'] == 'ADD':
            await self.handle_notion_add(ctx, result['params'])
        elif result['intent'] == 'UPDATE':
            await self.handle_update(ctx, result['params'])

    # in smart_note
    async def handle_notion_search(self, ctx, params):
        response = await self._notion_search(
            title=params.get("title"),
            author=params.get("author"),
            status=params.get("status")
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
    async def handle_notion_add(self, ctx, params):
        title = params.get("title")
        content = params.get("content")
        status = params.get("status")
        author = params.get("author")
        source = params.get("source")

        # 首先要確定有沒有書名
        if not title:
            return await ctx.send("你沒有給我書名QAQ")
        
        # 先search看有沒有已經建立過了，如果建立過了就變成修改欄位內容
        search_result = await self._notion_search(title=title)
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
            source=source
            # 日期
        )
        # await ctx.send(f"已在資料庫中新建{title}！\n連結: {new_page['url']}")

        page_id = new_page['id']

        if content:
            await self._append_content(page_id=page_id, content=content)
            await ctx.send(f"已新增{title}和心得。")
        else:
            await ctx.sned(f"已新增《{title}》。")
    
    # in smart_note
    # 讀完後 更新閱讀狀態、日期、可能還有心得
    # 也有可能看到一半棄了
    async def handle_update(self, ctx, params):
        title=params.get("title")
        status=params.get("status")
        content=params.get("content")

        # 1. 先搜尋有沒有這本書，有的話才能update
        response = await self._notion_search(title=title)
        results = response.get("results", [])
        print(results)

        if not results:
            print("no books found, trigger view")
            view = ConfirmAddView(self, title, content, status)
            return await ctx.send(f"沒有找到《{title}》這本書，要幫你改成『新增』嗎？", view=view)

        page_id = results[0]['id']

        # 2. 更新properties
        if status:
            await self._notion_update_properties(page_id=page_id, status=status)
    
        # 3. 有心得(content)的話也要更新
        if content:
            await self._append_content(page_id=page_id, content=content)

        #
        await ctx.send(f"已更新《{title}》")

    #
    @commands.command(name="recommend")
    async def recommend_books(self, ctx, *, title: str):
        await ctx.typing()


        response = await self.recommend_chain.ainvoke(
            title,
            config=self.bot.get_langchain_config(
                trace_name="discord.!recommend",
                user_id=ctx.author.id
            )
        )
        await ctx.send(response)



    # ------------------------------------------------
    # search
    async def _notion_search(self, title=None, author=None, status=None):
        # notion search 是使用 filter
        print("_notion_search() is called")
        filters = []
        if title:
            filters.append({"property": "題名", "title": {"contains": title}})
        if author:
            filters.append({"property": "作者", "multi_select": {"contains": author}})
        if status:
            filters.append({"property": "閱讀狀態", "status": {"equals": status}})
        
        # 有多個條件的時候要用and串起來
        # 「JSON 樹狀結構」
        query_filter = {"and": filter} if len(filters) > 1 else (filters[0] if filters else None)

        print(f"query_filter: {query_filter}")
        return self.notion.data_sources.query(
            data_source_id=self.datasource_id,
            filter=query_filter
        )

    # create new note
    async def _notion_create_note(self, title, author=None, status="待閱讀", source=None, readdate=None, remark=None):
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
        
        return self.notion.pages.create(
            parent={"data_source_id": self.datasource_id},
            properties=properties
        )

    # 新增notion children (心得等)
    async def _append_content(self, page_id, content):
        # content 理論上要是markdown，但是不確定
        if not content:
            return
        
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

        return self.notion.blocks.children.append(
            block_id=page_id,
            children=blocks
        )

    # 更新或修改 properties
    async def _notion_update_properties(self, page_id, status):
        if not status:
            return
        update_items = {}
        update_items['閱讀狀態'] = {"status": {"name": status}}
        
        # 如果看完了 也要把日期更新上去
        if status == "已閱讀":
            today_str = datetime.now().strftime("%Y-%m-%d")
            update_items['閱讀日期'] = {"date": {"start": today_str}}

        if update_items:
            self.notion.pages.update(page_id=page_id, properties=update_items)

    # 獲取notion children
    async def _get_page_content(self, title):
        """
        抓notion頁面中的所有blocks作為 RAG Context
        因為notion return的格式非常非常多層，只要把真正的內容抓出來就好
        """
        try:
            search_results = await self._notion_search(title=title)
            if not search_results.get("results"):
                print("Notion沒有找到這本書，會切換成general recommend")
                return None

            first_page = search_results["results"][0]
            page_id = search_results["results"][0]["id"]
            # response = await self.notion.blocks.children.list(block_id=page_id)

            # full book title
            full_book_title = first_page['properties']['題名']['title'][0]['plain_text']

            response = self.notion.blocks.children.list(block_id=page_id)


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