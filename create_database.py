"""
Erstellt die SQLite-Datenbank für die LUKAS-Bibliothek
Version 1.0 Beta (2025-11)
"""

import sqlite3
import os

DB_PATH = "output/lukas_bibliothek_v1.sqlite3"

# Stelle sicher, dass der output-Ordner existiert
os.makedirs("output", exist_ok=True)

# Lösche alte Datenbank falls vorhanden
if os.path.exists(DB_PATH):
    os.remove(DB_PATH)
    print(f"🗑️  Alte Datenbank gelöscht: {DB_PATH}")

# Erstelle neue Datenbank
conn = sqlite3.connect(DB_PATH)
c = conn.cursor()

print("🔧 Erstelle Datenbankstruktur...")

# Foreign Keys aktivieren
c.execute("PRAGMA foreign_keys = ON;")

# 1. Autoren
c.execute("""
CREATE TABLE IF NOT EXISTS authors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    birth_year INTEGER,
    death_year INTEGER,
    notes TEXT
);
""")

# 2. Verlage
c.execute("""
CREATE TABLE IF NOT EXISTS publishers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL
);
""")

# 3. Themen / Kategorien
c.execute("""
CREATE TABLE IF NOT EXISTS subjects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    parent_id INTEGER,
    FOREIGN KEY (parent_id) REFERENCES subjects(id) ON DELETE SET NULL
);
""")

# 4. Sammlungen
c.execute("""
CREATE TABLE IF NOT EXISTS collections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    description TEXT
);
""")

# 5. Bücher (Haupttabelle)
c.execute("""
CREATE TABLE IF NOT EXISTS books (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    subtitle TEXT,
    author_id INTEGER,
    publisher_id INTEGER,
    publication_year INTEGER,
    language TEXT DEFAULT 'de',
    isbn_10 TEXT,
    isbn_13 TEXT,
    edition TEXT,
    description TEXT,
    collection_id INTEGER,
    created_at TEXT DEFAULT (DATE('now')),
    updated_at TEXT DEFAULT (DATE('now')),
    FOREIGN KEY (author_id) REFERENCES authors(id) ON DELETE SET NULL,
    FOREIGN KEY (publisher_id) REFERENCES publishers(id) ON DELETE SET NULL,
    FOREIGN KEY (collection_id) REFERENCES collections(id) ON DELETE SET NULL
);
""")

c.execute("CREATE INDEX IF NOT EXISTS idx_books_title ON books(title);")
c.execute("CREATE INDEX IF NOT EXISTS idx_books_author ON books(author_id);")

# 6. Exemplare (physische Bücher)
c.execute("""
CREATE TABLE IF NOT EXISTS copies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    book_id INTEGER NOT NULL,
    signatur TEXT,
    regal TEXT,
    fach TEXT,
    zustand TEXT,
    status_digitalisierung TEXT,
    cover_local TEXT,
    cover_online TEXT,
    photo_ref TEXT,
    created_at TEXT DEFAULT (DATE('now')),
    FOREIGN KEY (book_id) REFERENCES books(id) ON DELETE CASCADE
);
""")

c.execute("CREATE INDEX IF NOT EXISTS idx_copies_signatur ON copies(signatur);")

# 7. Medien (Bilder, Scans, OCR)
c.execute("""
CREATE TABLE IF NOT EXISTS media (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    book_id INTEGER NOT NULL,
    media_type TEXT,
    file_ref TEXT,
    caption TEXT,
    ocr_text TEXT,
    created_at TEXT DEFAULT (DATE('now')),
    FOREIGN KEY (book_id) REFERENCES books(id) ON DELETE CASCADE
);
""")

# 8. Personen
c.execute("""
CREATE TABLE IF NOT EXISTS people (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    email TEXT,
    phone TEXT,
    notes TEXT
);
""")

# 9. Ausleihen
c.execute("""
CREATE TABLE IF NOT EXISTS loans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    copy_id INTEGER NOT NULL,
    borrower_id INTEGER NOT NULL,
    loan_date TEXT NOT NULL,
    due_date TEXT,
    return_date TEXT,
    status TEXT DEFAULT 'ausgeliehen',
    notes TEXT,
    FOREIGN KEY (copy_id) REFERENCES copies(id) ON DELETE CASCADE,
    FOREIGN KEY (borrower_id) REFERENCES people(id) ON DELETE SET NULL
);
""")

# 10. Schlagworte
c.execute("""
CREATE TABLE IF NOT EXISTS tags (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL
);
""")

c.execute("""
CREATE TABLE IF NOT EXISTS book_tags (
    book_id INTEGER NOT NULL,
    tag_id INTEGER NOT NULL,
    PRIMARY KEY (book_id, tag_id),
    FOREIGN KEY (book_id) REFERENCES books(id) ON DELETE CASCADE,
    FOREIGN KEY (tag_id) REFERENCES tags(id) ON DELETE CASCADE
);
""")

# 11. Initiale Sammlungen
c.execute("""
INSERT OR IGNORE INTO collections (name, description) VALUES
('Kirche', 'Theologische Literatur, Gemeindearbeit, Liturgie'),
('Musik/Noten', 'Partituren, Chor- & Orchesterstimmen'),
('Quartier/Soziales', 'Sozialraum, Stadtteilgeschichte, Engagement'),
('Archiv', 'Chroniken, Programme, historische Dokumente');
""")

conn.commit()
conn.close()

print(f"✅ Datenbank erfolgreich erstellt: {DB_PATH}")
print("📊 Folgende Tabellen wurden angelegt:")
print("   - authors, publishers, subjects, collections")
print("   - books, copies, media")
print("   - people, loans, tags, book_tags")
print("\n🚀 Sie können jetzt das OCR-Import-Skript starten:")
print("   python ocr_lukas_import.py")
