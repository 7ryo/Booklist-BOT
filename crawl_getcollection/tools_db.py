import psycopg2
from dotenv import load_dotenv
import os

load_dotenv()

uri = os.getenv("DB_CONNECT_URI")


def get_connection():
    
    conn = psycopg2.connect(uri)

    return conn


def save_info_to_supa(conn, book_list):
    if not book_list:
        return
    
    try:
        cur = conn.cursor()

        sql = """
            INSERT INTO book (book_id, title, author, publisher, year, isbn)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (book_id) DO NOTHING;
        """

        data_tuples = [
            (b['book_id'], b['title'], b['author'], b['publisher'], b['year'], b['ISBN'])
            for b in book_list
        ]

        # executemany()
        cur.executemany(sql, data_tuples)

        conn.commit()
        cur.close()
        print(f"成功存入{len(data_tuples)}筆資料")

    except Exception as e:
        conn.rollback()
        print(f"存入失敗: {e}")

def get_id_with_no_location(conn):
    query = """
    SELECT book_id FROM book
    WHERE has_location = FALSE
    """

    try: 
        cur = conn.cursor()
        cur.execute(query)

        pendings = cur.fetchall() #list of tuples

        return pendings

    except Exception as e:
        print(f"get_id_with_no_location: {e}")


def save_loc_to_supa(conn, location_list):
    if not location_list:
        return

    try:
        cur = conn.cursor()

        sql = """
            INSERT INTO inventory (book_id, location, call_number, status)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (book_id, location) 
            DO UPDATE SET
                "call_number" = EXCLUDED.call_number,
                "status" = EXCLUDED.status,
                "update_time" = NOW();
        """

        data_tuples = [
            (l['book_id'], l['location'], l['call_number'], l['status'])
            for l in location_list
        ]
        # print(f"data_tuples => {data_tuples}")

        cur.executemany(sql, data_tuples)

        conn.commit()
        cur.close()
        print("save location to db")


    except Exception as e:
        print(f"save_loc_to_supa: {e}")


# 應該還要有update的function
def mark_has_location_true(conn, list_bookid):
    if not list_bookid:
        return    
    
    # after saving the location info, we have to change "has_location" to TRUE
    try:
        cur = conn.cursor()

        update_sql = """
            UPDATE book
            SET has_location = TRUE
            WHERE book_id = %s
        """

        data_tuples = [
            (bid,) for bid in list_bookid
        ]

        cur.executemany(update_sql, data_tuples)
        
        conn.commit()
        cur.close()


    except Exception as e:
        print(f"mark_has_location_true: {e}")