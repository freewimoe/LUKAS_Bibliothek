"""
OCR-Importer für die LUKAS-Bibliothek
Erstellt von Friedrich-Wilhelm Möller · Version 1.0 Beta (2025-11)
---------------------------------------------------------------
Liest alle Bilder im Ordner 'fotos/', extrahiert Titel, Autor und Signatur
und trägt sie automatisch in die SQLite-Datenbank ein.
"""

import os, re, sqlite3
from datetime import date
from PIL import Image
import pytesseract

# ========== KONFIGURATION ==========
DB_PATH = "output/lukas_bibliothek_v1.sqlite3"
PHOTO_PATH = "fotos/"
LANG = "deu"  # OCR-Sprache (Deutsch)

# Pfad zu tesseract.exe (Windows) - aktiviert für direkten Zugriff
pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

# ========== HILFSFUNKTIONEN ==========
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("PRAGMA foreign_keys = ON;")
    return conn, c

def extract_text(image_path):
    """OCR-Texterkennung auf einem Bild."""
    img = Image.open(image_path)
    text = pytesseract.image_to_string(img, lang=LANG)
    return text.strip()

def parse_fields(text):
    """Versucht Signatur, Autor, Titel zu erkennen."""
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    signatur = ""
    autor = ""
    titel = ""

    # einfache Heuristik: Signatur = kurze Kombination unten
    if lines:
        for l in reversed(lines):
            if re.match(r"^[A-ZÄÖÜ][a-z]{1,3}\s?[A-ZÄÖÜa-z]{0,3}$", l):
                signatur = l
                lines.remove(l)
                break

    # Restliche Zeilen zu einem String verbinden
    joined = " ".join(lines)
    # Trenne Autor und Titel (heuristisch am ersten Großbuchstabenblock)
    m = re.match(r"([A-ZÄÖÜ][A-Za-zÄÖÜäöüß\s\.\-']{2,40})\s+(.*)", joined)
    if m:
        autor, titel = m.groups()

    return signatur, autor, titel

def insert_book(c, autor, titel, signatur, photo_ref):
    """Schreibt Datensatz in DB (books + copies)."""
    if not titel:
        return
    # Autor einfügen oder holen
    c.execute("SELECT id FROM authors WHERE name=?", (autor,))
    row = c.fetchone()
    if row:
        autor_id = row[0]
    else:
        c.execute("INSERT INTO authors(name) VALUES(?)", (autor,))
        autor_id = c.lastrowid

    # Buch einfügen
    c.execute("INSERT INTO books(title, author_id, collection_id) VALUES(?,?,1)", (titel, autor_id))
    book_id = c.lastrowid

    # Exemplar einfügen
    c.execute("""
        INSERT INTO copies(book_id, signatur, regal, fach, zustand,
                           status_digitalisierung, cover_local, created_at)
        VALUES (?,?,?,?,?,?,?,?)
    """, (book_id, signatur, "", "", "unbekannt", "Foto erfasst", photo_ref, str(date.today())))

def process_all():
    conn, c = init_db()
    images = [f for f in os.listdir(PHOTO_PATH) if f.lower().endswith((".jpg", ".jpeg", ".png"))]
    print(f"📸 {len(images)} Bilder gefunden – Starte OCR...\n")

    for i, img_name in enumerate(images, 1):
        path = os.path.join(PHOTO_PATH, img_name)
        text = extract_text(path)
        signatur, autor, titel = parse_fields(text)
        insert_book(c, autor, titel, signatur, path)
        print(f"{i:03d}/{len(images)} | {signatur:6} | {autor:20} | {titel[:50]}")

    conn.commit()
    conn.close()
    print("\n✅ Fertig! Datenbank aktualisiert:", DB_PATH)

if __name__ == "__main__":
    process_all()
