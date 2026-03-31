
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import JsonOutputParser, StrOutputParser
from langchain_core.runnables import RunnableLambda, RunnableParallel, RunnablePassthrough, RunnableBranch


# 因為 notion的呼叫指令!note中包含了搜尋/新增兩種動作
# 所以用llm來辨別需要呼叫哪個function
def create_intent_chain(llm):
    parser = JsonOutputParser() # 方便提取對應位置的關鍵字
    prompt = ChatPromptTemplate.from_template("""
    你是一個圖書管理助手。請將使用者的話轉成JSON格式。
    intent只能是'ADD'、'UPDATE'或'SEARCH'。
    params包含
    - title(書名/題名/作品名)，一定會有
    - author(作者)，沒有提到的話就空著
    - status，包含「閱讀中」、「未讀」、「願望清單」、「已閱讀」、「棄書」共五種
    - content，詳見【心得處理規則】

    【心得處理規則】
    1. 識別關鍵字「心得：」或「感想：」
    2. 保持使用者換行結構，不要把文字擠成一團                                                                               

                                                
    【範例】
    - "找小王子" -> {{"intent": "SEARCH", "params": {{"title": "小王子"}}}}
    - "讀完了恆毅力" -> {{"intent": "ADD", "params": {{"title": "恆毅力", "status": "已閱讀", "content": "看完令人省思。"}}}}                                          

    使用者輸入：{input}
    """)
    return prompt | llm | parser


def create_query_extractor(llm):
    prompt = ChatPromptTemplate.from_template(
        """
        你是一個搜尋優化專家。請從使用者的輸入中提取最適合搜尋的「書名」或「關鍵字」
        只輸出文字，不要包和任何解釋或標點符號。
        使用者輸入：{input}
        搜尋關鍵字：
        """
    )
    return prompt | llm | StrOutputParser()

# router
def create_recommend_chain(llm, search_service, get_notion_func):

    # 先從user input中提取關鍵字（書名）
    query_extractor = create_query_extractor(llm)

    # 1. prompt
    # route A: 有心得
    personal_prompt = ChatPromptTemplate.from_template("""
    你是一位私人圖書顧問。使用者讀過這本書且有寫心得。
    書名：{book_title}
    使用者心得：{user_context}
    網路資料：{web_data}
    請結合使用者的口味與網路資料推薦書籍。    
    使用者輸入：{input}                                                                                                                                                                                                                                                                                
    """)
    # route B: 沒有心得
    general_prompt = ChatPromptTemplate.from_template("""
    你是一位圖書顧問。使用者沒有讀過這本書。
    書名：{book_title}
    網路資料：{web_data}
    請根據大眾資料推薦相似的書籍。  
    使用者輸入：{input}                                                                                                                                                                                                                                                                                  
    """)

    # 2. router
    # branch = RunnableBranch(
    #     (lambda x: x["user_context"] is not None and x["user_context"] != "", personal_prompt),
    #     general_prompt
    # )
    branch = RunnableBranch(
        (lambda x: x.get("user_context") is not None and x.get("user_context") != "", personal_prompt),
        general_prompt
    )

    # 3. async search package
    # 避免被說never await
    async def _async_get_notion(inputs):
        title = inputs.get("book_title")
        print(f" title: {title}; type = {type(title)}")
        # return await get_notion_func(title)
        if callable(get_notion_func):
            return await get_notion_func(title)
        return get_notion_func


    async def _async_web_Search(inputs):
        # print(f"now is in _async_web_search")
        title = inputs.get("book_title")
        context = inputs.get("user_context")

        # print(f"title: {title}; context: {context}")

        try:
            # 手動 await
            raw_results = await search_service.search_similar_books(
                book_title=title, 
                user_context=context or ""
            )
            # print(f"==========================\nresult: {result}")

            # raw_result is a list of dict
            # need to convert it to str -> llm can read
            search_docs = []
            for doc in raw_results:
                doc_content = doc.get("content", "")
                doc_title = doc.get("title", "")
                # 剩下的url, img之類的就不用了
                if doc_content:
                    search_docs.append(f"--- 來源: {doc_title} ---\n內容: {doc_content}")
            clean_results = "\n\n".join(search_docs)
            if not clean_results:
                clean_results = "未找到相關網路資料"

            print(clean_results)
            print(type(clean_results))
            return clean_results

        except Exception as e:
            print(f"in _async_web_Search: {e}")
            return {"results": []} # this allows llm to continue working

        # return await search_service.search_similar_books(book_title=title, user_context=context)

    # LCEL
    # 用RunnableParallel讓兩個動作同步執行
    chain = (
        RunnableParallel({
            "book_title": query_extractor,
            "original_input": RunnablePassthrough()
        })
        | RunnableParallel({
            # 會搜尋使用者心得
            "book_title": lambda x: x["book_title"],
            "user_context": RunnableLambda(_async_get_notion),
            "original_input":lambda x: x["original_input"]
        })
        | RunnableParallel({
            # book_title和user_context會從前一個RunnableParallel傳過來
            "book_title": lambda x: x["user_context"].get("book_title", x["book_title"]) if x["user_context"] else x["book_title"],
            "user_context": lambda x: x["user_context"].get("content") if x["user_context"] else None,
            "web_data": RunnableLambda(_async_web_Search),
            # lambda x: search_service.search_similar_books(x["book_title"], x["user_context"])
            "input": lambda x: x["original_input"]
        })
        | branch # 判斷要用哪一個prompt
        | llm
        | StrOutputParser()
    )
    return chain