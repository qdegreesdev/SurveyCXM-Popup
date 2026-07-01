import pymysql
import os
from dotenv import load_dotenv

load_dotenv()

conn = pymysql.connect(
    host=os.getenv('SURVEY_DB_HOST'),
    port=int(os.getenv('SURVEY_DB_PORT', 3306)),
    user=os.getenv('SURVEY_DB_USER'),
    password=os.getenv('SURVEY_DB_PASSWORD'),
    database=os.getenv('SURVEY_DB_NAME'),
    cursorclass=pymysql.cursors.DictCursor
)

with conn.cursor() as cursor:
    cursor.execute("SELECT slug, type FROM questions WHERE survey_id = 6")
    print("Survey 6 Questions:", cursor.fetchall())
    
    cursor.execute("DESCRIBE survey_responses_6")
    print("Survey 6 Columns:", [row['Field'] for row in cursor.fetchall()])
    
    cursor.execute("SELECT * FROM survey_responses_6 LIMIT 5")
    print("Survey 6 Data:", cursor.fetchall())
