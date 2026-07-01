import pymysql
from sqlalchemy import create_engine
from pymysql.cursors import DictCursor
from config import settings

def test():
    db_url = f"mysql+pymysql://{settings.survey_db_user}:{settings.survey_db_password}@{settings.survey_db_host}:{settings.survey_db_port}/{settings.survey_db_name}?charset=utf8mb4"
    engine = create_engine(db_url, pool_size=5, pool_pre_ping=True)
    
    try:
        with engine.raw_connection() as conn:
            with conn.cursor(DictCursor) as cursor:
                cursor.execute("SELECT 1 AS test_col")
                res = cursor.fetchall()
                print("Result:", res)
    except Exception as e:
        print("Error:", e)

if __name__ == "__main__":
    test()
