import ast
import os
from datetime import datetime, timedelta


from langfuse import get_client, observe
from langchain_community.utilities import SQLDatabase
from notion_client import Client


class NotionServiceError(Exception):
    """Raised when NotionService cannot complete a Notion API operation."""


class NotionService:
    def __init__(self, db_url: str | None = None, cache_minutes: int = 10):
        self.db_url = db_url or os.getenv("USER_DB_CONNECT_URI")
        self.sql_db = SQLDatabase.from_uri(self.db_url) if self.db_url else None
        self.cache_ttl = timedelta(minutes=cache_minutes)
        self.notion_config_cache = {}
        self.langfuse = get_client()

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
            return None

        safe_user_id = str(user_id).replace("'", "''")
        sql = (
            "SELECT notion_token, database_id "
            "FROM user_notion_config "
            f"WHERE discord_user_id = '{safe_user_id}' "
            "LIMIT 1"
        )
        raw_row = self.sql_db.run(sql, fetch="one")
        if not raw_row:
            return None

        try:
            row = ast.literal_eval(raw_row)[0]
        except (SyntaxError, ValueError, IndexError, TypeError):
            return None

        if not isinstance(row, (tuple, list)) or len(row) < 2:
            return None

        notion_api_key = row[0]
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

    def get_user_runtime(self, user_id: str):
        user_id = str(user_id)
        cached = self._get_cached_runtime(user_id)
        if cached:
            return cached

        config = self._load_user_config_from_db(user_id)
        if not config:
            return None

        try:
            return self._build_runtime(
                user_id=user_id,
                notion_api_key=config["notion_api_key"],
                notion_database_id=config["notion_database_id"],
            )
        except Exception as e:
            raise NotionServiceError(
                "Notion 連線初始化失敗（可能是 Token 失效、Database ID 錯誤或 Notion 暫時無法連線）。"
            ) from e


    async def save_user_notion_config(self, user_id: str, notion_api_key: str, notion_database_id: str):
        if not self.sql_db:
            raise ValueError("資料庫連線未設定，請確認 USER_DB_CONNECT_URI")

        with self.langfuse.start_as_current_observation(as_type="span", name="Notion_ACTION") as span:
            safe_user_id = str(user_id).replace("'", "''")
            safe_api_key = notion_api_key.replace("'", "''")
            safe_database_id = notion_database_id.replace("'", "''")
            upsert_sql = f"""
            INSERT INTO user_notion_config (discord_user_id, notion_token, database_id)
            VALUES ('{safe_user_id}', '{safe_api_key}', '{safe_database_id}')
            ON CONFLICT (discord_user_id)
            DO UPDATE SET
                notion_token = EXCLUDED.notion_token,
                database_id = EXCLUDED.database_id
            """
            self.sql_db.run(upsert_sql)

            self.notion_config_cache.pop(str(user_id), None)
            self._build_runtime(
                user_id=str(user_id),
                notion_api_key=notion_api_key,
                notion_database_id=notion_database_id,
            )
            span.update(
                tags=["ERP_LOG"],
                metadata={
                    "user_id": str(user_id),
                    "display_text": "已更新 Notion 帳號連線設定。",
                },
            )

    async def query_database(self, user_id: str, title=None, author=None, status=None):
        runtime = self.get_user_runtime(user_id)
        if not runtime:
            raise NotionServiceError("尚未設定 Notion 連線資訊。")

        filters = []
        if title:
            filters.append({"property": "題名", "title": {"contains": title}})
        if author:
            filters.append({"property": "作者", "multi_select": {"contains": author}})
        if status:
            filters.append({"property": "閱讀狀態", "status": {"equals": status}})

        query_filter = {"and": filters} if len(filters) > 1 else (filters[0] if filters else None)
        return runtime["notion"].data_sources.query(
            data_source_id=runtime["data_source_id"],
            filter=query_filter,
        )


    async def create_page(
        self,
        user_id: str,
        title: str,
        author=None,
        status="待閱讀",
        source="圖書館實體書",
        remark=None,
    ):
        with self.langfuse.start_as_current_observation(as_type="span", name="Notion_ACTION") as span:
            runtime = self.get_user_runtime(user_id)
            if not runtime:
                raise NotionServiceError("尚未設定 Notion 連線資訊。")

            properties = {
                "題名": {"title": [{"text": {"content": title}}]},
            }
            if source:
                properties["來源"] = {"select": {"name": source}}
            if status:
                properties["閱讀狀態"] = {"status": {"name": status}}
            if author:
                properties["作者"] = {"multi_select": [{"name": author}]}
            if remark:
                properties["備註"] = {"rich_text": [{"text": {"content": remark}}]}
            if status == "已閱讀":
                today_str = datetime.now().strftime("%Y-%m-%d")
                properties["閱讀日期"] = {"date": {"start": today_str}}

            print(properties)

            result = runtime["notion"].pages.create(
                parent={"data_source_id": runtime["data_source_id"]},
                properties=properties,
            )
            span.update(
                tags=["ERP_LOG"],
                metadata={
                    "user_id": str(user_id),
                    "display_text": f"已在 Notion 新增書籍《{title}》。",
                },
            )
            return result

    async def append_content(self, user_id: str, page_id: str, content: str):
        if not content:
            return

        with self.langfuse.start_as_current_observation(as_type="span", name="Notion_ACTION") as span:
            runtime = self.get_user_runtime(user_id)
            if not runtime:
                raise NotionServiceError("尚未設定 Notion 連線資訊。")

            blocks = [
                {
                    "object": "block",
                    "type": "paragraph",
                    "paragraph": {
                        "rich_text": [{"type": "text", "text": {"content": line}}],
                    },
                }
                for line in content.split("\n")
            ]
            result = runtime["notion"].blocks.children.append(block_id=page_id, children=blocks)
            span.update(
                tags=["ERP_LOG"],
                metadata={
                    "user_id": str(user_id),
                    "display_text": f"新增心得：{content[:20]}...",
                },
            )
            return result

    async def update_page_properties(self, user_id: str, page_id: str, status: str):
        if not status:
            return

        with self.langfuse.start_as_current_observation(as_type="span", name="Notion_ACTION") as span:
            runtime = self.get_user_runtime(user_id)
            if not runtime:
                raise NotionServiceError("尚未設定 Notion 連線資訊。")

            update_items = {"閱讀狀態": {"status": {"name": status}}}
            if status == "已閱讀":
                today_str = datetime.now().strftime("%Y-%m-%d")
                update_items["閱讀日期"] = {"date": {"start": today_str}}

            result = runtime["notion"].pages.update(page_id=page_id, properties=update_items)
            span.update(
                tags=["ERP_LOG"],
                metadata={
                    "user_id": str(user_id),
                    "display_text": f"已更新 Notion 書籍狀態為「{status}」。",
                },
            )
            return result

    async def get_page_content(self, user_id: str, title: str):
        search_results = await self.query_database(user_id=user_id, title=title)
        if not search_results.get("results"):
            return None

        runtime = self.get_user_runtime(user_id)
        if not runtime:
            return None

        first_page = search_results["results"][0]
        page_id = first_page["id"]
        full_book_title = first_page["properties"]["題名"]["title"][0]["plain_text"]
        response = runtime["notion"].blocks.children.list(block_id=page_id)

        paragraphs = []
        for block in response.get("results", []):
            block_type = block.get("type")
            if block_type == "paragraph":
                rich_text = block["paragraph"].get("rich_text", [])
                if rich_text:
                    paragraphs.append(rich_text[0].get("plain_text", ""))
            elif block_type == "bulleted_list_item":
                rich_text = block["bulleted_list_item"].get("rich_text", [])
                if rich_text:
                    paragraphs.append(f"- {rich_text[0].get('plain_text', '')}")

        full_content = "\n".join(paragraphs)
        if not full_content.strip():
            return {"book_title": full_book_title, "content": None}
        return {"book_title": full_book_title, "content": full_content}

    async def test_connection(self, user_id: str, page_size: int = 1):
        runtime = self.get_user_runtime(user_id)
        if not runtime:
            raise NotionServiceError("尚未設定 Notion 連線資訊。")
        return runtime["notion"].data_sources.query(
            data_source_id=runtime["data_source_id"],
            page_size=page_size,
        )
