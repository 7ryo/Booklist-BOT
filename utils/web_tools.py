from tavily import TavilyClient
import os

class SearchService:
    def __init__(self):
        print(os.getenv("TAVILY_DISCORD_BOT_API"))
        self.client = TavilyClient(api_key=os.getenv("TAVILY_DISCORD_BOT_API"))
    
    async def search_similar_books(self, book_title: str, user_context: str = ""):
        """
        根據書名與使用者心得搜尋相似書籍
        """
        query = f"和{book_title}相似的書"
        if user_context:
            query += f"以及{user_context}"
        
        # search_depth="advanced"的話會搜尋更深，但也會消耗更多quota
        # include_answer=True 的話Travily會做一個小總結
        response = self.client.search(
            query=query,
            search_depth="basic",
            max_results=5
        )
        return response["results"]
    
    