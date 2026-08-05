import sys
import codecs
sys.stdout = codecs.getwriter("utf-8")(sys.stdout.detach())

from database import get_db_service
from datetime import datetime
import json

db = get_db_service()
client_id = 17
last_login_dt = datetime.strptime("03/08/2026", "%d/%m/%Y")
current_login_dt = datetime.strptime("04/08/2026", "%d/%m/%Y")
# current_login_dt will be set to end of day in the real route, but let's mimic parse_datetime(..., is_end_date=True)
current_login_dt = current_login_dt.replace(hour=23, minute=59, second=59)

survey_ids = db.get_survey_ids_by_client(client_id)
print(f"Client {client_id} Survey IDs: {survey_ids}")

if not survey_ids:
    print("No surveys!")
    sys.exit(0)

nps_data = db.get_nps_data_for_surveys(survey_ids, last_login_dt, current_login_dt)
print("\nNPS Data:")
print(json.dumps(nps_data, indent=2, ensure_ascii=False))

# Let's manually query voc_alerts for these surveys without date or priority filters to see what exists
# Let's manually query voc_alerts for these surveys without date or priority filters to see what exists
try:
    with db._cursor() as cursor:


            format_strings = ','.join(['%s'] * len(survey_ids))
            query = f"SELECT id, survey_res_id, sentiment, priority_level, is_critical, created_at, customer_verbatim FROM voc_alerts WHERE survey_id IN ({format_strings})"
            cursor.execute(query, tuple(survey_ids))
            all_vocs = cursor.fetchall()
            print(f"\nTotal VOCs found for Client {client_id} in voc_alerts table (no filters): {len(all_vocs)}")
            for voc in all_vocs:
                # Format datetime for json serialization
                if voc.get('created_at'):
                    voc['created_at'] = voc['created_at'].isoformat()
                print(json.dumps(voc, ensure_ascii=False))
except Exception as e:
    print("Error querying raw VOCs:", e)

print("\nDebugging database.py exact API query for survey_id=26:")
try:
    with db._cursor() as cursor:
        survey_id = 26
        nr_table = f"survey_responses_nr_{survey_id}"
        fh_table = f"filter_hierarchy_{survey_id}"
        query = f"""
            SELECT
                v.priority_level,
                v.created_at
            FROM voc_alerts v
            LEFT JOIN {nr_table} nr ON v.survey_res_id = nr.id
            LEFT JOIN {fh_table} fh1 ON nr.f1 = fh1.id AND fh1.level = 1
            LEFT JOIN {fh_table} fh2 ON nr.f2 = fh2.id AND fh2.level = 2
            LEFT JOIN {fh_table} fh3 ON nr.f3 = fh3.id AND fh3.level = 3
            LEFT JOIN {fh_table} fh4 ON nr.f4 = fh4.id AND fh4.level = 4
            WHERE v.survey_id = %s
              AND v.sentiment = 'Negative'
              AND v.created_at >= %s
              AND v.created_at  < %s
              AND (
                    LOWER(v.priority_level) IN ('high', 'critical', 'urgent', 'medium')
                    OR v.is_critical = 1
              )
            ORDER BY
                CASE LOWER(v.priority_level)
                    WHEN 'critical' THEN 1
                    WHEN 'urgent'   THEN 2
                    WHEN 'high'     THEN 3
                    WHEN 'medium'   THEN 4
                    ELSE 5
                END ASC,
                v.created_at DESC
        """
        cursor.execute(query, (survey_id, last_login_dt, current_login_dt))
        print("API Query Results from scratch:", cursor.fetchall())
except Exception as e:
    print("API Query Error:", e)

