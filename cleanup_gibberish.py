"""
Bereinigt die Datenbank von offensichtlich unleserlichen OCR-Einträgen ("Gibberish").

Sicherheitsnetz (niemals löschen):
- Hat ein Exemplar mit status_digitalisierung = 'Gemini-Import'
- Hat ein Exemplar mit Status, der 'online' und 'verifiz' enthält (z. B. "Online verifiziert")

Konservative aber strengere Lösch-Regel (Ziel: OCR-Müll entfernen, echte Bücher behalten):
- KEIN Gemini-Import und NICHT online verifiziert
- KEINE ISBN (weder 10 noch 13)
- KEIN Verlag und KEIN plausibles Erscheinungsjahr (1450 .. aktuelles Jahr + 1)
- UND Titel ist gibberish UND (Autor fehlt ODER Autor ist gibberish)

Löschen erfolgt über books (FK ON DELETE CASCADE löscht copies automatisch).
Am Ende wird die CSV neu exportiert.

Benutzung:
    python cleanup_gibberish.py --dry-run
    python cleanup_gibberish.py --apply
"""

import re
import sqlite3
import os
import argparse
from datetime import datetime
from typing import Optional, List, Tuple

DB_PATH = "output/lukas_bibliothek_v1.sqlite3"

# ---------- Heuristik für Gibberish ----------

def gibberish_score(text: Optional[str]) -> int:
    """Gibt einen Score >=0 zurück. Ab Score >= 2 gilt der Text als gibberish."""
    if text is None:
        return 3
    s = text.strip()
    if not s:
        return 3

    vowels = len(re.findall(r"[AEIOUYÄÖÜaeiouyäöü]", s))
    letters = len(re.findall(r"[A-Za-zÄÖÜäöüß]", s))
    specials = len(re.findall(r"[^A-Za-zÄÖÜäöüß0-9\s,.'\-()!?]", s))
    total = len(s)

    score = 0

    # 1) zu wenig Vokale im Verhältnis zur Länge
    if total >= 12 and vowels <= 1:
        score += 1

    # 2) hoher Anteil an Sonderzeichen oder Mischtext
    if total and (specials / total) > 0.20:
        score += 1

    # 3) lange Tokens ohne Vokale
    tokens = re.split(r"\s+", s)
    if any(len(t) >= 12 and not re.search(r"[AEIOUYÄÖÜaeiouyäöü]", t) for t in tokens):
        score += 1

    # 4) Zeichenmuster wie viele Backslashes/Unicode-Artefakte
    if s.count("\\") >= 3:
        score += 1

    # 5) Kaum Buchstaben insgesamt
    if total and letters / total < 0.35:
        score += 1

    return score


def looks_gibberish(text: Optional[str]) -> bool:
    return gibberish_score(text) >= 2


def cleanup(apply: bool = True, preview_limit: int = 25) -> Tuple[int, List[Tuple[int, str, str]]]:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # Hole alle Bücher samt Autor/Verlag/ISBN/Jahr sowie Flags zu Gemini/Online-verifiziert
    c.execute(
        """
        SELECT 
            b.id,
            COALESCE(b.title, '') AS title,
            COALESCE(a.name, '') AS author,
            COALESCE(p.name, '') AS publisher,
            COALESCE(b.isbn_10, '') AS isbn10,
            COALESCE(b.isbn_13, '') AS isbn13,
            b.publication_year,
            EXISTS (
                SELECT 1 FROM copies cp 
                WHERE cp.book_id = b.id 
                  AND cp.status_digitalisierung = 'Gemini-Import'
            ) AS has_gemini,
            EXISTS (
                SELECT 1 FROM copies cp 
                WHERE cp.book_id = b.id 
                  AND LOWER(COALESCE(cp.status_digitalisierung,'')) LIKE '%online%verifiz%'
            ) AS has_online_verified
        FROM books b
        LEFT JOIN authors a ON a.id = b.author_id
        LEFT JOIN publishers p ON p.id = b.publisher_id
        """
    )
    rows = c.fetchall()

    current_year = datetime.now().year
    to_delete: List[int] = []
    examples: List[Tuple[int, str, str]] = []
    for (
        book_id, title, author, publisher, isbn10, isbn13, pub_year, has_gemini, has_online_verified
    ) in rows:
        if has_gemini or has_online_verified:
            continue  # niemals löschen

        # Strukturierte Metadaten vorhanden? Dann eher behalten.
        has_isbn = bool(isbn10 or isbn13)
        has_publisher = bool(publisher)
        has_plausible_year = pub_year is not None and 1450 <= int(pub_year) <= (current_year + 1)

        title_is_gib = looks_gibberish(title)
        author_is_gib = (author.strip() == '') or looks_gibberish(author)

        if (not has_isbn) and (not has_publisher) and (not has_plausible_year) and title_is_gib and author_is_gib:
            to_delete.append(book_id)
            if len(examples) < preview_limit:
                examples.append((book_id, title[:120], author[:120]))

    print(f"Gefundene verdächtige Bücher (Kandidaten zum Löschen): {len(to_delete)}")
    if examples:
        print("\nBeispiele:")
        for bid, t, a_ in examples:
            print(f"  - #{bid}: '{t}' | {a_}")

    if apply and to_delete:
        # Lösche in Blöcken, damit SQLite Platz hat für IN-Klausel
        BATCH = 200
        for i in range(0, len(to_delete), BATCH):
            batch = to_delete[i:i+BATCH]
            q_marks = ",".join(["?"] * len(batch))
            c.execute(f"DELETE FROM books WHERE id IN ({q_marks})", batch)
        conn.commit()
        print(f"\n✅ Gelöscht: {len(to_delete)} Bücher (inkl. zugehöriger Exemplare)")
    else:
        print("\n(Trockenlauf) – Nichts gelöscht. Verwenden Sie --apply zum Ausführen.")

    # CSV neu exportieren
    conn.close()
    os.system('python export_to_csv.py')


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Bereinigt OCR-Gibberish aus der Datenbank.")
    parser.add_argument("--dry-run", action="store_true", help="Nur zählen und Beispiele zeigen, nichts löschen")
    parser.add_argument("--apply", action="store_true", help="Löschen wirklich ausführen")
    args = parser.parse_args()

    apply_flag = True if args.apply and not args.dry_run else False
    cleanup(apply=apply_flag)
