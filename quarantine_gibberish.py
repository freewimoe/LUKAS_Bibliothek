"""
Quarantäne-Script für verdächtige OCR-/Gibberish-Einträge.

- Identifiziert verdächtige Bücher (ähnliche Heuristik wie cleanup_gibberish.py)
- Exportiert diese in eine Quarantäne-CSV unter output/quarantine/quarantine_YYYYMMDD_HHMM.csv
- Kopiert zugehörige Bilder (cover_local) nach output/quarantine/images/
- Entfernt die Bücher optional aus der Haupt-DB (--apply); im Dry-Run nur Bericht + CSV/Images
- Exportiert am Ende die reguläre CSV neu

Nutzung:
  python quarantine_gibberish.py --dry-run
  python quarantine_gibberish.py --apply

Hinweise:
- Geschützte Einträge (Gemini-Import oder "Online verifiziert") werden nie quarantänisiert.
- ISBN/Verlag/Jahr gelten als strukturierte Metadaten und schützen i. d. R. vor Quarantäne.
"""

import os
import re
import csv
import shutil
import sqlite3
import argparse
from datetime import datetime
from typing import Optional, List, Tuple

DB_PATH = "output/lukas_bibliothek_v1.sqlite3"
QUAR_DIR = "output/quarantine"
QUAR_IMG_DIR = os.path.join(QUAR_DIR, "images")

# ------------- Heuristik -------------

def gibberish_score(text: Optional[str]) -> int:
    if text is None:
        return 3
    s = str(text).strip()
    if not s:
        return 3
    vowels = len(re.findall(r"[AEIOUYÄÖÜaeiouyäöü]", s))
    letters = len(re.findall(r"[A-Za-zÄÖÜäöüß]", s))
    specials = len(re.findall(r"[^A-Za-zÄÖÜäöüß0-9\s,.'\-()!?]", s))
    total = len(s)
    score = 0
    if total >= 12 and vowels <= 1:
        score += 1
    if total and (specials / total) > 0.22:
        score += 1
    tokens = re.split(r"\s+", s)
    if any(len(t) >= 12 and not re.search(r"[AEIOUYÄÖÜaeiouyäöü]", t) for t in tokens):
        score += 1
    if s.count("\\") >= 3:
        score += 1
    if total and letters / total < 0.35:
        score += 1
    # 6) hoher Anteil 1-Zeichen-Tokens
    if tokens:
        one_letters = sum(1 for t in tokens if len(t) == 1)
        if one_letters / len(tokens) >= 0.5:
            score += 1
    return score

def looks_gibberish(text: Optional[str]) -> bool:
    return gibberish_score(text) >= 2

# ------------- Pfadauflösung für Bilder -------------

def resolve_image_path(cover_local: Optional[str]) -> Optional[str]:
    if not cover_local:
        return None
    p = cover_local.replace("\\", "/")
    # häufige Varianten
    candidates: List[str] = []
    if p.startswith("output/"):
        candidates.append(p)
    if p.startswith("thumbnails/"):
        candidates.append(os.path.join("output", p))
    if p.startswith("../fotos/"):
        candidates.append(os.path.normpath(p.replace("../", "")))  # -> fotos/...
    if p.startswith("fotos/"):
        candidates.append(p)
    # Fallback: probiere unter output/
    candidates.append(os.path.join("output", p))
    for c in candidates:
        if os.path.exists(c):
            return c
    return None

# ------------- Quarantäne -------------

def quarantine(apply: bool = False,
               include_foto_erfasst_all: bool = False,
               aggressive_titles: bool = False,
               ignore_isbn_safety: bool = False) -> Tuple[int, int]:
    os.makedirs(QUAR_DIR, exist_ok=True)
    os.makedirs(QUAR_IMG_DIR, exist_ok=True)

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

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
            -- hat ein Exemplar mit Status exakt 'Foto erfasst'
            EXISTS (
                SELECT 1 FROM copies cp
                WHERE cp.book_id = b.id AND cp.status_digitalisierung = 'Foto erfasst'
            ) AS has_foto_erfasst,
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

    now = datetime.now().strftime("%Y%m%d_%H%M")
    csv_path = os.path.join(QUAR_DIR, f"quarantine_{now}.csv")

    candidates: List[int] = []
    examples: List[Tuple[int, str, str]] = []
    # Vorbereiten CSV mit Header
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow([
            "book_id", "author", "title", "publisher", "isbn10", "isbn13", "year",
            "copy_id", "signatur", "status", "cover_local_src", "cover_online"
        ])

        current_year = datetime.now().year
        # Identifiziere Kandidaten
        for (book_id, title, author, publisher, isbn10, isbn13, pub_year, has_foto_erfasst, has_gemini, has_online_verified) in rows:
            if has_gemini or has_online_verified:
                continue
            has_isbn = bool(isbn10 or isbn13)
            has_publisher = bool(publisher)
            has_plausible_year = pub_year is not None and 1450 <= int(pub_year) <= (current_year + 1)
            title_is_gib = looks_gibberish(title)
            author_is_gib = (not author.strip()) or looks_gibberish(author)
            # 1) Aggressive: ALLE "Foto erfasst"-Bücher in Quarantäne, unabhängig von Titel/Autor
            rule_foto_all = include_foto_erfasst_all and has_foto_erfasst
            # 2) Aggressive: Komische Titel/Autoren unabhängig von Verlag/Jahr, optional ISBN-Schutz ignorieren
            rule_aggr_titles = aggressive_titles and (title_is_gib or author_is_gib) and (ignore_isbn_safety or (not has_isbn))
            # 3) Standard: konservative Heuristik
            rule_conservative = (not has_isbn) and (not has_publisher) and (not has_plausible_year) and title_is_gib and author_is_gib
            # 4) Mild: Foto-OCR plus mind. ein Feld gibberish (mit ISBN-Schutz)
            rule_foto_ocr = (not include_foto_erfasst_all) and has_foto_erfasst and (title_is_gib or author_is_gib) and (not has_isbn)

            if rule_foto_all or rule_aggr_titles or rule_conservative or rule_foto_ocr:
                candidates.append(book_id)
                if len(examples) < 20:
                    examples.append((book_id, title[:100], author[:100]))

        # Für jede Kandidaten-ID: Exemplare sammeln und CSV schreiben
        if candidates:
            q_marks = ",".join(["?"] * len(candidates))
            c.execute(
                f"""
                SELECT b.id, COALESCE(a.name,''), COALESCE(b.title,''), COALESCE(p.name,''),
                       COALESCE(b.isbn_10,''), COALESCE(b.isbn_13,''), b.publication_year,
                       cp.id, COALESCE(cp.signatur,''), COALESCE(cp.status_digitalisierung,''),
                       COALESCE(cp.cover_local,''), COALESCE(cp.cover_online,'')
                FROM books b
                LEFT JOIN authors a ON a.id = b.author_id
                LEFT JOIN publishers p ON p.id = b.publisher_id
                LEFT JOIN copies cp ON cp.book_id = b.id
                WHERE b.id IN ({q_marks})
                ORDER BY b.id, cp.id
                """,
                candidates,
            )
            copy_rows = c.fetchall()
            for (bid, a, t, pub, is10, is13, y, copy_id, sign, stat, cov_local, cov_online) in copy_rows:
                src_path = resolve_image_path(cov_local)
                w.writerow([bid, a, t, pub, is10, is13, y, copy_id, sign, stat, src_path or '', cov_online])
                # Bilder kopieren (wenn vorhanden)
                if src_path and os.path.exists(src_path):
                    ext = os.path.splitext(src_path)[1].lower() or ".jpg"
                    dst = os.path.join(QUAR_IMG_DIR, f"book_{bid}__copy_{copy_id}{ext}")
                    try:
                        shutil.copy2(src_path, dst)
                    except Exception:
                        pass

    print(f"🧪 Quarantäne-Kandidaten: {len(candidates)} | CSV: {csv_path}")
    if examples:
        print("Beispiele:")
        for bid, t, a in examples:
            print(f"  - #{bid}: '{t}' | {a}")

    removed = 0
    if apply and candidates:
        BATCH = 200
        for i in range(0, len(candidates), BATCH):
            batch = candidates[i:i+BATCH]
            q_marks = ",".join(["?"] * len(batch))
            c.execute(f"DELETE FROM books WHERE id IN ({q_marks})", batch)
        conn.commit()
        removed = len(candidates)
        print(f"✅ In Quarantäne verschoben (aus DB entfernt): {removed} Bücher")
    else:
        print("(Trockenlauf) – DB bleibt unverändert. CSV und Bilder wurden erstellt.")

    conn.close()
    # CSV für Webseite neu exportieren
    os.system('python export_to_csv.py')

    return len(candidates), removed


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Quarantänisiert verdächtige OCR-Einträge und sichert Bilder/CSV")
    parser.add_argument("--dry-run", action="store_true", help="Nur CSV/Bilder erzeugen, DB nicht verändern")
    parser.add_argument("--apply", action="store_true", help="Kandidaten aus DB entfernen (Quarantäne)")
    parser.add_argument("--include-foto-erfasst-all", action="store_true", help="ALLE Einträge mit Status 'Foto erfasst' quarantänisieren")
    parser.add_argument("--aggressive-titles", action="store_true", help="Auch Einträge mit gibberish Titel/Autor quarantänisieren (mit ISBN-Schutz)")
    parser.add_argument("--ignore-isbn", action="store_true", help="Bei aggressiven Titeln den ISBN-Schutz ignorieren")
    args = parser.parse_args()

    do_apply = True if args.apply and not args.dry_run else False
    quarantine(
        apply=do_apply,
        include_foto_erfasst_all=args.include_foto_erfasst_all,
        aggressive_titles=args.aggressive_titles,
        ignore_isbn_safety=args.ignore_isbn,
    )
