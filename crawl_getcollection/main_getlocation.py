import tools_db, tools_bookinfo

from playwright.sync_api import sync_playwright
import time


def run_holdings():

    conn = tools_db.get_connection()
    processed_ids = []

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(storage_state="auth.json")
            page = context.new_page()


            # fetch books(id) that has no location yet
            pendings = tools_db.get_id_with_no_location(conn=conn)
            # pendings = [ (id,), (id,), (id,), ...]
            print(f"共有{len(pendings)}本書待處理")

            for item in pendings:
                book_id = item[0]
            # for book_id in ['102496']: #this si for testing
                # then get the location infos
                locations = tools_bookinfo.process_location(page, book_id)
                # print(locations)
                # save to bd (in case there are too many items)
                if locations:
                    tools_db.save_loc_to_supa(conn=conn, location_list=locations)
                    processed_ids.append(book_id)
                
                if len(processed_ids) >= 10:
                    tools_db.mark_has_location_true(conn, processed_ids)
                    processed_ids = [] # clear list
                    print("===============> 已更新10本書的標籤")
                
                time.sleep(2)
            
            # 最後當processed_ids沒有累積到10本，我們還是要更新標籤
            if processed_ids:
                tools_db.mark_has_location_true(conn, processed_ids)
                print(f"最後更新了{len(processed_ids)}本書的標籤")

                

    except Exception as e:
        print(e)
    
    finally:
        if conn:
            conn.close()
    

    return 0




if __name__ == "__main__":
    run_holdings()