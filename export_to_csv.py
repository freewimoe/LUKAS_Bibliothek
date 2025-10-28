"""
Exportiert die SQLite-Datenbank in eine CSV-Datei für die Webseite
"""

import sqlite3
import csv

DB_PATH = "output/lukas_bibliothek_v1.sqlite3"
CSV_PATH = "output/lukas_bibliothek_v1.csv"

print("📊 Exportiere Datenbank zu CSV...")

# Verbinde zur Datenbank
conn = sqlite3.connect(DB_PATH)
c = conn.cursor()

# Hole alle Bücher mit Autoren und Signaturen
query = """
SELECT 
    b.id,
    a.name as author,
    b.title,
    c.signatur,
    c.regal,
    c.fach,
    c.zustand,
    c.status_digitalisierung,
    c.cover_local,
    c.cover_online,
    b.publication_year,
    b.language,
    COALESCE(b.isbn_13, b.isbn_10) AS isbn
FROM books b
LEFT JOIN authors a ON b.author_id = a.id
LEFT JOIN copies c ON b.id = c.book_id
ORDER BY COALESCE(c.signatur, ''), a.name, b.title
"""

c.execute(query)
rows = c.fetchall()

# Schreibe CSV
with open(CSV_PATH, 'w', newline='', encoding='utf-8') as f:
    writer = csv.writer(f)
    
    # Header
    writer.writerow([
        'id', 'author', 'title', 'signatur', 'regal', 'fach', 
        'zustand', 'status_digitalisierung', 'cover_local', 'cover_online', 'year', 'language', 'isbn'
    ])
    
    # Daten
    for row in rows:
        writer.writerow(row)

conn.close()

print(f"✅ CSV-Export abgeschlossen: {CSV_PATH}")
print(f"📚 {len(rows)} Einträge exportiert")
print("\n🌐 Sie können jetzt die Webseite öffnen:")
print("   Öffnen Sie: output/LukasBibliothek.html")
