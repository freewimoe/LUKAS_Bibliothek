import os
import sqlite3

DB = "output/lukas_bibliothek_v1.sqlite3"

conn = sqlite3.connect(DB)
c = conn.cursor()

# total copies rows
c.execute("SELECT COUNT(*) FROM copies")
copies = c.fetchone()[0]

# local cover set
c.execute("SELECT COUNT(*) FROM copies WHERE COALESCE(cover_local,'') <> ''")
with_local = c.fetchone()[0]

# local cover file exists
c.execute("SELECT COALESCE(cover_local,'') FROM copies WHERE COALESCE(cover_local,'') <> ''")
paths = [r[0] for r in c.fetchall()]
exists = 0
for p in paths:
    check = os.path.join('output', p) if not p.startswith('output/') else p
    if os.path.exists(check):
        exists += 1

# online cover only
c.execute("SELECT COUNT(*) FROM copies WHERE COALESCE(cover_local,'') = '' AND COALESCE(cover_online,'') <> ''")
with_online_only = c.fetchone()[0]

# books with description / publisher
c.execute("SELECT COUNT(*) FROM books")
books = c.fetchone()[0]

c.execute("SELECT COUNT(*) FROM books WHERE COALESCE(description,'') <> ''")
with_desc = c.fetchone()[0]

c.execute("SELECT COUNT(*) FROM books WHERE publisher_id IS NOT NULL")
with_pub = c.fetchone()[0]

print(f"Copies total: {copies}")
print(f"Covers: local-set={with_local} (files-exist={exists}), online-only={with_online_only}")
print(f"Books total: {books}")
print(f"Descriptions: {with_desc}")
print(f"Publishers set: {with_pub}")
