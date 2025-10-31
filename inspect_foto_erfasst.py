import sqlite3

DB_PATH = "output/lukas_bibliothek_v1.sqlite3"

conn = sqlite3.connect(DB_PATH)
c = conn.cursor()

c.execute(
    """
    SELECT b.id, COALESCE(a.name,''), COALESCE(b.title,''), COALESCE(c.signatur,''), COALESCE(c.cover_local,''), COALESCE(c.status_digitalisierung,'')
    FROM books b
    LEFT JOIN authors a ON a.id = b.author_id
    LEFT JOIN copies c ON c.book_id = b.id
    WHERE c.status_digitalisierung = 'Foto erfasst'
    LIMIT 50
    """
)
rows = c.fetchall()
print(f"Foto-erfasst Einträge: {len(rows)} (zeige bis 50)")
for r in rows:
    print(r)
