import sqlite3

conn = sqlite3.connect('complaints.db')
conn.row_factory = sqlite3.Row
cursor = conn.cursor()
cursor.execute("SELECT complaint_id, name, address, description, parent_id, duplicate_count, priority FROM complaints")
rows = cursor.fetchall()

print(f"Total Complaints: {len(rows)}")
for r in rows:
    print(dict(r))
