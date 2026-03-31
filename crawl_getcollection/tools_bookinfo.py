import time
import random
from bs4 import BeautifulSoup
# from playwright.sync_api import sync_playwright

book_detail_url = "https://webpacx.ksml.edu.tw/bookDetail/"


#center > div > div > div.mainrightblock > div > div.book_detaildata > div.bookdata.columnsblock > div.columns_leftblock


def process_new_books(new_items):
    print(f"這個new_items共有{len(new_items)}項")
    list_book_info = []

    # new_items = page.locator(".bookdata:not(processed)").all() #list

    for item in new_items:

        book_info = {
            "book_id": None,
            "title": None,
            "author": None,
            "publisher": None,
            "year": None,
            "ISBN": None
        }

        item_html = item.evaluate("el => el.outerHTML")
        item_soup = BeautifulSoup(item_html, "html.parser")

        # book id要另外存，之後要抓館藏地點
        href = item_soup.select_one("h2 a").get("href")
        print(f"書名上的連結是{href}")
        book_id = href.split("/")[-1]
        print(f"book id是{book_id}")
        book_info['book_id'] = book_id


        # 書名、作者、出版社、出版年、ISBN
        title = item_soup.select_one("h2 a").text.replace(" /", "")
        
        book_info['title'] = title

        lilist = item_soup.select("li")
        for li in lilist:
            str = li.text
            if "作者" in str:
                book_info['author'] = str.replace("作者：", "").strip()
            elif "出版者" in str:
                book_info['publisher'] = str.replace("出版者：", "").strip()
            elif "出版年" in str:
                book_info['year'] = str.replace("出版年：", "").strip()
            elif "ISBN" in str:
                book_info['ISBN'] = str.replace("ISBN：", "").strip()

        list_book_info.append(book_info)
        item.evaluate("el => el.classList.add('processed')")
        print("處理完一項")
        # item.evaluate("el => el.dataset.processed = 'True'")
        
    return list_book_info


def process_one_book(item):
    # 一次處理一本而已

    book_info = {
        "book_id": None,
        "title": None,
        "author": None,
        "publisher": None,
        "year": None,
        "ISBN": None
    }

    item_html = item.evaluate("el => el.outerHTML")
    item_soup = BeautifulSoup(item_html, "html.parser")

    # book id要另外存，之後要抓館藏地點
    href = item_soup.select_one("h2 a").get("href")
    book_id = href.split("/")[-1]
    # print(f"book id是{book_id}")
    book_info['book_id'] = book_id


    # 書名、作者、出版社、出版年、ISBN
    title = item_soup.select_one("h2 a").text.replace(" /", "")
    
    book_info['title'] = title

    lilist = item_soup.select("li")
    for li in lilist:
        str = li.text
        if "作者" in str:
            book_info['author'] = str.replace("作者：", "").strip()
        elif "出版者" in str:
            book_info['publisher'] = str.replace("出版者：", "").strip()
        elif "出版年" in str:
            book_info['year'] = str.replace("出版年：", "").strip()
        elif "ISBN" in str:
            book_info['ISBN'] = str.replace("ISBN：", "").strip()

    item.evaluate("el => el.classList.add('processed')")
    # print(f"處理完{book_info}")
    # item.evaluate("el => el.dataset.processed = 'True'")
        
    return book_info


def get_new_books(page):
    # 1. 收集全部not processed的
    target_locator = page.locator(".bookdata:not(.processed)")
    temp_batch = []

    # 2. 一本一本處理
    while target_locator.count() > 0:

        # 用queue的概念每次都處理「第一本」
        item = target_locator.first

        try:
            item.wait_for(state="attached", timeout=2000)
            temp_batch.append(process_one_book(item))

        except Exception as e:
            print(e)

        if len(temp_batch) >= 10:
            break
    
    return temp_batch


# 取得館藏地點、索書號、狀態
def get_location(page):

    location_list = []

    # selector
    table_selector = "div.bookplace_list table"
    button_selector = "button:has-text('載入更多')"

    # 等table出現
    try:
        page.wait_for_selector(table_selector, timeout=10000)
    except:
        print("找不到館藏資訊表格")
        return []
    

    # 檢查是否顯示全部館藏地
    while True:
        load_more_button = page.query_selector(button_selector)

        # 如果有
        if load_more_button and load_more_button.is_visible():
            load_more_button.click()
            time.sleep(random(5, 7))
        # 沒有的話
        else: break

    # get whole table
    table_html = page.inner_html(table_selector)

    soup = BeautifulSoup(table_html, 'html.parser')
    rows = soup.find_all('tr')

    for row in rows:
        location = row.select_one('td[data-title="館藏地/室"]')
        call = row.select_one('td[data-title="索書號"]')
        status = row.select_one('td[data-title="狀態/到期日"]')

        location_list.append([location, call, status])

    return location_list


def process_location(page, book_id):

    location_list = []

    # pendings = list of "book_id"s
    # print(f"{book_detail_url}{book_id}")
    page.goto(f"{book_detail_url}{book_id}")

    # selector
    table_selector = "div.bookplace_list table"
    button_selector = "button:has-text('載入更多')"

    # 等table出現
    try:
        page.wait_for_selector(table_selector, timeout=100000)
        # print("有看到館藏表格了")
    except:
        print("找不到館藏資訊表格")
        return []


    # 檢查是否顯示全部館藏地
    while True:
        load_more_button = page.query_selector(button_selector)

        # 如果有
        if load_more_button and load_more_button.is_visible():
            load_more_button.click()
            time.sleep(random(5, 7))
        # 沒有的話
        else: break

    # get whole table
    table_html = page.inner_html(table_selector)

    soup = BeautifulSoup(table_html, 'html.parser')
    rows = soup.find_all('tr')

    for row in rows:
        location_info = {
            "book_id": book_id,
            "location": None,
            "call_number": None,
            "status": None
        }

        loc_td = row.select_one('td[data-title="館藏地/室"]')

        if loc_td is None:
            continue

        location_info['location'] = loc_td.get_text(strip=True)
        location_info['call_number'] = row.select_one('td[data-title="索書號"]').get_text(strip=True)
        location_info['status'] = row.select_one('td[data-title="狀態/到期日"]').get_text(strip=True)
        # print(location_info)
        location_list.append(location_info)
    return location_list