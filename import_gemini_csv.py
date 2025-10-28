"""
Importiert Bücher aus LUKAS_books.csv (Komma-separiert) in die SQLite-Datenbank.
- Erwartete Spalten (Header):
  Signatur,Titel,Autor,Verlag,ISBN,Erscheinungsjahr,Kategorie,Standort,Status,Notizen
- Mapping auf DB:
  authors.name <- Autor
  publishers.name <- Verlag
  books.title <- Titel
  books.author_id, books.publisher_id, books.publication_year, books.isbn_13 (unsaniert ok), books.collection_id (aus Kategorie), books.language='de'
  copies.signatur <- Signatur
  copies.regal <- Standort
  copies.zustand <- Status
  copies.status_digitalisierung <- 'Gemini-Import'

Dublettenregel (wie JSON-Importer):
- Buch = (Titel + Autor) identisch -> update fehlende Felder, sonst insert
- Exemplar = gleiche Signatur -> update Felder, sonst insert

Nach Import: export_to_csv.py ausführen
"""

import csv
import os
import sqlite3
from datetime import date

DB_PATH = "output/lukas_bibliothek_v1.sqlite3"
CSV_SOURCE = "LUKAS_books.csv"


def norm(value):
    if value is None:
        return ""
    return str(value).strip()


def to_int_or_none(v):
    v = norm(v)
    if not v:
        return None
    try:
        return int(v)
    except Exception:
        return None


def category_to_collection_id(cat: str) -> int:
    cat = (cat or "").lower()
    if "musik" in cat or "noten" in cat:
        return 2
    if "quartier" in cat or "sozial" in cat:
        return 3
    if "archiv" in cat or "geschichte" in cat:
        return 4
    return 1  # Kirche (Default)


def import_csv(path: str = CSV_SOURCE):
    if not os.path.exists(DB_PATH):
        raise FileNotFoundError(f"Datenbank nicht gefunden: {DB_PATH}. Bitte zuerst create_database.py laufen lassen.")
    if not os.path.exists(path):
        raise FileNotFoundError(f"CSV-Datei nicht gefunden: {path}")

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    imported = 0
    skipped = 0

    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f, delimiter=",")
        required = ["Signatur", "Titel", "Autor", "Verlag", "ISBN", "Erscheinungsjahr", "Kategorie", "Standort", "Status", "Notizen"]
        missing = [h for h in required if h not in reader.fieldnames]
        if missing:
            raise ValueError(f"Fehlende Spalten in {path}: {missing}")

        for row in reader:
            try:
                titel = norm(row.get("Titel"))
                if not titel:
                    skipped += 1
                    continue

                autor_name = norm(row.get("Autor"))
                verlag_name = norm(row.get("Verlag"))
                isbn = norm(row.get("ISBN"))
                jahr = to_int_or_none(row.get("Erscheinungsjahr"))
                kategorie = norm(row.get("Kategorie"))
                standort = norm(row.get("Standort"))
                status = norm(row.get("Status"))
                signatur = norm(row.get("Signatur"))

                # Autor
                autor_id = None
                if autor_name:
                    c.execute("SELECT id FROM authors WHERE name=?", (autor_name,))
                    r = c.fetchone()
                    if r:
                        autor_id = r[0]
                    else:
                        c.execute("INSERT INTO authors(name) VALUES(?)", (autor_name,))
                        autor_id = c.lastrowid

                # Verlag
                verlag_id = None
                if verlag_name:
                    c.execute("SELECT id FROM publishers WHERE name=?", (verlag_name,))
                    r = c.fetchone()
                    if r:
                        verlag_id = r[0]
                    else:
                        c.execute("INSERT INTO publishers(name) VALUES(?)", (verlag_name,))
                        verlag_id = c.lastrowid

                # Buch vorhanden?
                if autor_id:
                    c.execute("SELECT id FROM books WHERE title=? AND author_id=?", (titel, autor_id))
                else:
                    c.execute("SELECT id FROM books WHERE title=? AND author_id IS NULL", (titel,))
                r = c.fetchone()

                collection_id = category_to_collection_id(kategorie)
                if r:
                    book_id = r[0]
                    c.execute(
                        """
                        UPDATE books
                        SET publisher_id=COALESCE(publisher_id, ?),
                            publication_year=COALESCE(publication_year, ?),
                            isbn_13=COALESCE(isbn_13, ?),
                            collection_id=COALESCE(collection_id, ?)
                        WHERE id=?
                        """,
                        (verlag_id, jahr, isbn, collection_id, book_id),
                    )
                else:
                    c.execute(
                        """
                        INSERT INTO books(title, author_id, publisher_id, publication_year, isbn_13, collection_id, language, created_at)
                        VALUES(?,?,?,?,?,?,?,?)
                        """,
                        (titel, autor_id, verlag_id, jahr, isbn, collection_id, "de", str(date.today())),
                    )
                    book_id = c.lastrowid

                # Exemplar
                if signatur:
                    c.execute("SELECT id FROM copies WHERE signatur=?", (signatur,))
                    r = c.fetchone()
                    if r:
                        c.execute(
                            """
                            UPDATE copies
                            SET book_id=?, regal=?, zustand=?, status_digitalisierung='Gemini-Import'
                            WHERE id=?
                            """,
                            (book_id, standort, status, r[0]),
                        )
                    else:
                        c.execute(
                            """
                            INSERT INTO copies(book_id, signatur, regal, zustand, status_digitalisierung, created_at)
                            VALUES(?,?,?,?,?,?)
                            """,
                            (book_id, signatur, standort, status, 'Gemini-Import', str(date.today())),
                        )
                else:
                    c.execute(
                        """
                        INSERT INTO copies(book_id, regal, zustand, status_digitalisierung, created_at)
                        VALUES(?,?,?,?,?)
                        """,
                        (book_id, standort, status, 'Gemini-Import', str(date.today())),
                    )

                imported += 1
            except Exception as e:
                print(f"⚠️  Fehler bei Zeile mit Signatur '{row.get('Signatur','')}' und Titel '{row.get('Titel','')}' :: {e}")
                skipped += 1
                continue

    conn.commit()
    conn.close()

    print(f"✅ CSV-Import abgeschlossen: importiert={imported}, übersprungen={skipped}")
    os.system('python export_to_csv.py')


if __name__ == "__main__":
    import_csv(CSV_SOURCE)
