"""
Verknüpft bereits vorhandene Thumbnails (output/thumbnails/book_*.jpg) mit den Büchern in der Datenbank.
- Für jedes Thumbnail wird die book_id aus dem Dateinamen extrahiert.
- Für alle Exemplare (copies) dieses Buches wird cover_local gesetzt, falls leer.
- Pfad wird relativ zur Webseite gespeichert: 'thumbnails/book_{id}.jpg'.
- Am Ende wird die CSV für die Webseite neu exportiert.
"""

import os
import re
import sqlite3

DB_PATH = "output/lukas_bibliothek_v1.sqlite3"
THUMBS_DIR = "output/thumbnails"

THUMB_RE = re.compile(r"^book_(\d+)\.jpg$")


def link_thumbs():
    if not os.path.exists(THUMBS_DIR):
        print(f"❌ Ordner nicht gefunden: {THUMBS_DIR}")
        return 0

    files = os.listdir(THUMBS_DIR)
    ids = []
    for fn in files:
        m = THUMB_RE.match(fn)
        if m:
            ids.append(int(m.group(1)))

    if not ids:
        print("ℹ️ Keine Thumbnails im erwarteten Format gefunden (book_123.jpg)")
        return 0

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    updated = 0
    for bid in ids:
        rel = f"thumbnails/book_{bid}.jpg"
        # Setze cover_local für alle Exemplare dieses Buches, sofern leer oder NULL
        c.execute(
            """
            UPDATE copies
               SET cover_local = ?
             WHERE book_id = ?
               AND (cover_local IS NULL OR TRIM(cover_local) = '')
            """,
            (rel, bid),
        )
        updated += c.rowcount

    conn.commit()
    conn.close()

    print(f"✅ Verknüpft: {updated} Exemplare mit vorhandenen Thumbnails")

    # CSV neu exportieren
    os.system('python export_to_csv.py')

    return updated


if __name__ == "__main__":
    link_thumbs()
