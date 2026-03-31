# from tools_db import *
# from tools_bookinfo import *
import os
import tools_db, tools_bookinfo

from playwright.sync_api import sync_playwright
import time


def main():

    conn = tools_db.get_connection()
    user_acc = os.getenv("LIBRARY_USER_ACC")
    user_passwd = os.getenv("LIBRARY_USER_PASSWORD")

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(storage_state="auth.json")
            page = context.new_page()
            page.goto("https://webpacx.ksml.edu.tw/personal/list?action=getPacCollection&form=QueryForm")

            # 檢查是否需要先登入
            print("檢查登入中")
            login_widget = page.locator("text=會員登入")
            if login_widget.is_visible(timeout=5000):
                print("正在登入......")
            
                # page.wait_for_selector('button:has-text("登入個人書房")')
                # page.get_by_role("button", name="登入個人書房").click()
                page.get_by_role("textbox", name="請輸入借閱證號或身分證字號").fill(user_acc)
                page.get_by_role("textbox", name="請輸入密碼").fill(user_passwd)
                page.get_by_role("button", name="登入", exact=True).click()
                print("登入！")
                page.context.storage_state(path="auth.json")
                print("更新auth.json")
            else: print("不用登入")

            time.sleep(5)
            

            ## 看看
            ttt = page.locator("text=批次加入標籤")
            if ttt.is_visible(timeout=5000):
                print("清單似乎顯示出來了！")

            while True:
                books_batch = tools_bookinfo.get_new_books(page)
                tools_db.save_info_to_supa(conn=conn, book_list=books_batch)

                if books_batch:
                    print("執行完一次book batch")
                else:
                    # break
                    page.keyboard.press("End")
                    page.wait_for_timeout(10000)
                    

                    # 確認真的沒有剩下的
                    if page.locator(".bookdata:not(.processed)").count() == 0:
                        print("全部抓完了")
                        break

            browser.close()
            

    except Exception as e:
        print(e)


    finally:

        if conn:
            conn.close()
            print("關閉db連線")





if __name__ == "__main__":
    main()