#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Importiert neue Bücher (als Minimal-Einträge) aus output/new_books_from_fotos.csv in die SQLite-DB.
- Legt pro Zeile einen books-Datensatz (title optional) an.
- Legt dazugehöriges Exemplar (copies) an mit cover_local = Segmentbild und photo_ref = Originalfoto.
- Kennzeichnet copies.status_digitalisierung = 'Foto-Segment'.

Sicherheitsfeatures:
- --limit N: importiert höchstens N Zeilen (Default 0 = nur Dry-Run anzeigen)
- --dry-run: zeigt nur an, was passieren würde (Default true, wenn --limit 0)

Nach Import wird export_to_csv.py aufgerufen, damit die CSV aktualisiert wird.
"""
from __future__ import annotations

import argparse
import csv
import os
import sqlite3
from datetime import date

DB_PATH = "output/lukas_bibliothek_v1.sqlite3"
NEW_BOOKS_CSV = "output/new_books_from_fotos.csv"


def norm(v):
    return (v or "").strip()


def main() -> int:
    ap = argparse.ArgumentParser(description="Importiert Foto-Segmente als neue Bücher/Exemplare")
    ap.add_argument("--csv", default=NEW_BOOKS_CSV, help="Pfad zur CSV der neuen Bücher aus Fotos")
    ap.add_argument("--limit", type=int, default=0, help="Max. Anzahl zu importierender Zeilen (0 = Dry-Run)")
    ap.add_argument("--collection-id", type=int, default=1, help="Standard-Collection-ID (1=Kirche)")
    args = ap.parse_args()

    if not os.path.exists(DB_PATH):
        raise FileNotFoundError(f"Datenbank nicht gefunden: {DB_PATH}")
    if not os.path.exists(args.csv):
        raise FileNotFoundError(f"CSV nicht gefunden: {args.csv}")

    with open(args.csv, "r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    print(f"Gefundene neue Kandidaten: {len(rows)}")
    if args.limit <= 0:
        print("Dry-Run: Keine Einträge werden geschrieben. Verwenden Sie --limit N zum Import.")

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("PRAGMA foreign_keys = ON;")

    imported = 0
    for i, row in enumerate(rows, start=1):
        if args.limit and imported >= args.limit:
            break

        title = norm(row.get("title")) or "Unbekannter Titel"
        cover_local = norm(row.get("cover_local"))
        photo_ref = norm(row.get("source_photo"))

        print(f"[{i}] + Buch '{title}' | cover_local={cover_local}")
        if args.limit <= 0:
            continue  # Dry-Run

        # Buch anlegen (minimal)
        c.execute(
            """
            INSERT INTO books(title, language, collection_id, created_at)
            VALUES(?,?,?,?)
            """,
            (title, "de", args.collection_id, str(date.today())),
        )
        book_id = c.lastrowid

        # Exemplar anlegen
        c.execute(
            """
            INSERT INTO copies(book_id, status_digitalisierung, cover_local, photo_ref, created_at)
            VALUES(?,?,?,?,?)
            """,
            (book_id, "Foto-Segment", cover_local, photo_ref, str(date.today())),
        )

        imported += 1

    if args.limit > 0:
        conn.commit()
        print(f"✅ Import abgeschlossen: {imported} Einträge angelegt")
        os.system('python export_to_csv.py')
    else:
        print("(Dry-Run beendet – keine Änderungen gespeichert)")

    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
