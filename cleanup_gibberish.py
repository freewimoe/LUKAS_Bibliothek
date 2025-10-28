"""
Bereinigt die Datenbank von offensichtlich unleserlichen OCR-Einträgen ("Gibberish").
Regeln:
- Bücher, die mindestens ein Exemplar mit status_digitalisierung = 'Gemini-Import' haben, werden NIE gelöscht.
- Ein Buch wird gelöscht, wenn Titel UND Autor als "gibberish" bewertet werden UND kein Gemini-Import-Exemplar existiert.
- Löschen erfolgt über books (FK ON DELETE CASCADE löscht copies automatisch).

Am Ende wird die CSV neu exportiert.
"""

import re
import sqlite3
import os
from typing import Optional

DB_PATH = "output/lukas_bibliothek_v1.sqlite3"

# ---------- Heuristik für Gibberish ----------

def looks_gibberish(text: Optional[str]) -> bool:
    if text is None:
        return True
    s = text.strip()
    if not s:
        return True

    # Normale Buchtexte enthalten in der Regel Vokale und wenig Sonderzeichen
    vowels = len(re.findall(r"[AEIOUYÄÖÜaeiouyäöü]", s))
    letters = len(re.findall(r"[A-Za-zÄÖÜäöüß]", s))
    digits = len(re.findall(r"\d", s))
    specials = len(re.findall(r"[^A-Za-zÄÖÜäöüß0-9\s,.'\-()!?]", s))
    total = len(s)

    rules_triggered = 0

    # 1) zu wenig Vokale im Verhältnis zur Länge
    if total >= 10 and vowels <= 1:
        rules_triggered += 1

    # 2) Anteil Sonderzeichen zu hoch
    if total and (specials / total) > 0.25:
        rules_triggered += 1

    # 3) Enthält sehr lange Token ohne Vokale
    tokens = re.split(r"\s+", s)
    if any(len(t) >= 12 and not re.search(r"[AEIOUYÄÖÜaeiouyäöü]", t) for t in tokens):
        rules_triggered += 1

    # 4) Mehrere Fragmente in ALL CAPS mit Ziffern/Sonderzeichen gemischt
    if re.search(r"[A-ZÄÖÜ]{3,}[^a-z\s]{3,}", s):
        rules_triggered += 1

    # 5) Kaum Buchstaben insgesamt
    if letters and (letters / max(1, total)) < 0.4:
        rules_triggered += 1

    return rules_triggered >= 2


def cleanup(apply: bool = True):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # Hole alle Bücher samt Autor, sowie Info ob Gemini-Import-Exemplar existiert
    c.execute(
        """
        SELECT b.id,
               COALESCE(b.title, ''),
               COALESCE(a.name, ''),
               EXISTS (SELECT 1 FROM copies cp WHERE cp.book_id = b.id AND cp.status_digitalisierung = 'Gemini-Import') AS has_gemini
        FROM books b
        LEFT JOIN authors a ON a.id = b.author_id
        """
    )
    rows = c.fetchall()

    to_delete = []
    for book_id, title, author, has_gemini in rows:
        if has_gemini:
            continue  # niemals löschen
        if looks_gibberish(title) and looks_gibberish(author):
            to_delete.append(book_id)

    print(f"Gefundene verdächtige Bücher: {len(to_delete)}")

    if apply and to_delete:
        # Lösche in Blöcken, damit SQLite Platz hat für IN-Klausel
        BATCH = 200
        for i in range(0, len(to_delete), BATCH):
            batch = to_delete[i:i+BATCH]
            q_marks = ",".join(["?"] * len(batch))
            c.execute(f"DELETE FROM books WHERE id IN ({q_marks})", batch)
        conn.commit()
        print(f"✅ Gelöscht: {len(to_delete)} Bücher (inkl. zugehöriger Exemplare)")
    else:
        print("(Trockenlauf) – Nichts gelöscht.")

    # CSV neu exportieren
    conn.close()
    os.system('python export_to_csv.py')


if __name__ == "__main__":
    cleanup(apply=True)
