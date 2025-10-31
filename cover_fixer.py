#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
cover_fixer.py

Ziel:
- Lokale Cover-Thumbnails für Katalogeinträge anlegen/aktualisieren – sicher und nachvollziehbar.

Prinzipien:
- Nur Einträge mit verifizierbarer ISBN (10/13-stellig, mit gültiger Prüfziffer) werden standardmäßig verarbeitet.
- Download-Quellen in Reihenfolge: Open Library (ISBN) → vorhandenes cover_online (optional per Flag) → Google Books API (optional, nicht standardmäßig genutzt).
- Speichern unter: output/thumbnails/book_{id}.jpg
- CSV-Feld cover_local wird auf den lokalen Pfad gesetzt, CSV bleibt ansonsten unverändert.

Nutzung:
  python cover_fixer.py --csv output/lukas_bibliothek_v1.csv --limit 300 --timeout 6

Optionen:
  --force        Setzt cover_local in CSV auch dann neu, wenn Datei schon existiert.
  --refresh      Lädt Dateien neu, selbst wenn sie bereits lokal existieren.
  --allow-online Erlaubt Fallback auf vorhandenes cover_online-Feld, falls Open Library nichts liefert.
  --dry-run      Keine Dateien/CSV schreiben, nur Report ausgeben.

Ausgaben:
- Berichte in output/: cover_fixer_added.csv, cover_fixer_skipped.csv (für Transparenz).
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import re
import sys
import time
from dataclasses import dataclass
from typing import Optional, Tuple, List

try:
    # Python 3
    from urllib.request import Request, urlopen
    from urllib.error import URLError, HTTPError
except Exception:  # pragma: no cover
    print("Python urllib nicht verfügbar", file=sys.stderr)
    raise


CSV_PATH_DEFAULT = os.path.join('output', 'lukas_bibliothek_v1.csv')
THUMBS_DIR = os.path.join('output', 'thumbnails')


def norm_isbn(s: str) -> str:
    return re.sub(r"[^0-9Xx]", "", s or "").upper()


def isbn10_check(isbn10: str) -> bool:
    if not re.fullmatch(r"[0-9]{9}[0-9X]", isbn10):
        return False
    s = 0
    for i, ch in enumerate(isbn10[:9], start=1):
        s += i * int(ch)
    check = s % 11
    check_char = 'X' if check == 10 else str(check)
    return isbn10[-1] == check_char


def isbn13_check(isbn13: str) -> bool:
    if not re.fullmatch(r"[0-9]{13}", isbn13):
        return False
    s = 0
    for i, ch in enumerate(isbn13[:12]):
        w = 1 if i % 2 == 0 else 3
        s += int(ch) * w
    check = (10 - (s % 10)) % 10
    return int(isbn13[-1]) == check


def is_valid_isbn(isbn: str) -> bool:
    n = norm_isbn(isbn)
    if len(n) == 10:
        return isbn10_check(n)
    if len(n) == 13:
        return isbn13_check(n)
    return False


def http_get(url: str, timeout: int = 6) -> Tuple[int, bytes, str]:
    headers = {
        'User-Agent': 'LukasBibliothek/cover-fixer (https://github.com/freewimoe/LUKAS_Bibliothek)'
    }
    req = Request(url, headers=headers)
    try:
        with urlopen(req, timeout=timeout) as resp:
            code = resp.getcode() or 0
            data = resp.read() or b''
            ctype = resp.headers.get('Content-Type', '')
            return code, data, ctype
    except HTTPError as e:
        return e.code or 0, b'', ''
    except URLError:
        return 0, b'', ''


def openlibrary_cover_url(isbn: str, size: str = 'L') -> str:
    n = norm_isbn(isbn)
    return f"https://covers.openlibrary.org/b/isbn/{n}-{size}.jpg"


@dataclass
class Args:
    csv_path: str
    limit: int
    timeout: int
    force: bool
    refresh: bool
    allow_online: bool
    dry_run: bool


def parse_args() -> Args:
    p = argparse.ArgumentParser(description='Lokale Cover-Thumbnails sicher befüllen')
    p.add_argument('--csv', dest='csv_path', default=CSV_PATH_DEFAULT)
    p.add_argument('--limit', type=int, default=300)
    p.add_argument('--timeout', type=int, default=6)
    p.add_argument('--force', action='store_true')
    p.add_argument('--refresh', action='store_true')
    p.add_argument('--allow-online', action='store_true')
    p.add_argument('--dry-run', action='store_true')
    a = p.parse_args()
    return Args(
        csv_path=a.csv_path,
        limit=a.limit,
        timeout=a.timeout,
        force=a.force,
        refresh=a.refresh,
        allow_online=a.allow_online,
        dry_run=a.dry_run,
    )


def ensure_dir(path: str):
    if not os.path.isdir(path):
        os.makedirs(path, exist_ok=True)


def is_image_content(ctype: str, data: bytes) -> bool:
    if not ctype:
        # Fallback Heuristik
        return data[:2] == b"\xff\xd8" or data[:8].startswith(b"\x89PNG")
    return ctype.startswith('image/')


def load_csv(path: str) -> Tuple[List[str], List[dict]]:
    with open(path, 'r', encoding='utf-8', newline='') as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        return reader.fieldnames or [], rows


def write_csv(path: str, header: List[str], rows: List[dict]):
    with open(path, 'w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=header)
        w.writeheader()
        for r in rows:
            w.writerow(r)


def write_report(path: str, header: List[str], rows: List[List[str]]):
    with open(path, 'w', encoding='utf-8', newline='') as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


def pick_source(row: dict, timeout: int, allow_online: bool) -> Optional[Tuple[str, bytes]]:
    """Wähle eine Bildquelle. Reihenfolge: OpenLibrary by ISBN → cover_online (optional)."""
    isbn = (row.get('isbn') or '').strip()
    if is_valid_isbn(isbn):
        for size in ('L', 'M'):
            url = openlibrary_cover_url(isbn, size=size)
            code, data, ctype = http_get(url, timeout=timeout)
            if code == 200 and data and is_image_content(ctype, data):
                return url, data
    if allow_online:
        co = (row.get('cover_online') or '').strip()
        if co:
            code, data, ctype = http_get(co, timeout=timeout)
            if code == 200 and data and is_image_content(ctype, data):
                return co, data
    return None


def main() -> int:
    args = parse_args()

    if not os.path.isfile(args.csv_path):
        print(f"CSV nicht gefunden: {args.csv_path}", file=sys.stderr)
        return 2

    ensure_dir(THUMBS_DIR)
    header, rows = load_csv(args.csv_path)
    if not header:
        print("Leere CSV oder kein Header", file=sys.stderr)
        return 3

    required_cols = {'id', 'cover_local', 'cover_online', 'isbn'}
    missing = [c for c in required_cols if c not in header]
    if missing:
        print(f"CSV fehlt Spalten: {missing}", file=sys.stderr)
        return 4

    added_report: List[List[str]] = []
    skipped_report: List[List[str]] = []

    processed = 0
    changed = False

    for row in rows:
        if args.limit and processed >= args.limit:
            break

        rid = (row.get('id') or '').strip()
        try:
            rid_int = int(float(rid)) if rid else None
        except Exception:
            rid_int = None

        # Nur Datensätze mit validem ISBN standardmäßig
        isbn = (row.get('isbn') or '').strip()
        isbn_ok = is_valid_isbn(isbn)
        if not isbn_ok and not args.allow_online:
            skipped_report.append([rid, row.get('title', ''), 'kein gültiges ISBN, online-Fallback aus'])
            continue

        # Zielpfad anhand der ID
        if rid_int is None:
            skipped_report.append([rid, row.get('title', ''), 'keine numerische ID'])
            continue

        rel_path = f"thumbnails/book_{rid_int}.jpg"
        abs_path = os.path.join('output', rel_path)

        already_exists = os.path.isfile(abs_path)
        has_local = (row.get('cover_local') or '').strip() != ''

        if already_exists and not args.refresh and has_local and not args.force:
            skipped_report.append([rid, row.get('title', ''), 'lokal vorhanden'])
            continue

        src = pick_source(row, timeout=args.timeout, allow_online=args.allow_online)
        if not src:
            reason = 'keine Quelle (OpenLibrary/online)'
            skipped_report.append([rid, row.get('title', ''), reason])
            continue

        url, data = src

        processed += 1

        added_report.append([rid, row.get('title', ''), url, rel_path])

        if not args.dry_run:
            # Schreiben der Datei
            with open(abs_path, 'wb') as imgf:
                imgf.write(data)

            # CSV aktualisieren
            row['cover_local'] = rel_path
            changed = True

        # Kleines Delay, um Throttle zu vermeiden
        time.sleep(0.1)

    # Berichte schreiben
    ensure_dir('output')
    write_report(os.path.join('output', 'cover_fixer_added.csv'), ['id', 'title', 'source', 'local_path'], added_report)
    write_report(os.path.join('output', 'cover_fixer_skipped.csv'), ['id', 'title', 'reason'], skipped_report)

    if changed and not args.dry_run:
        write_csv(args.csv_path, header, rows)

    print(f"FERTIG: processed={processed}, added={len(added_report)}, skipped={len(skipped_report)}, changed_csv={changed}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
