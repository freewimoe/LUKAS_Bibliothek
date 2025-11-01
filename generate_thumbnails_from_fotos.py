#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Erzeugt Web-Thumbnails ausschließlich aus lokalen Fotos/.

Vorgehen:
- Liest aus der SQLite-DB (copies.cover_local) die Foto-Pfade je Buch-ID.
- Wenn ein Pfad in fotos/ existiert, wird ein Thumbnail unter
  output/thumbnails/book_{id}.jpg erzeugt.

Hinweise:
- Die Originalfotos bleiben unverändert; es werden nur Thumbnails generiert.
- Die CSV-Ausgabe (export_to_csv.py) kann so angepasst werden, dass vorhandene
  Thumbnails bevorzugt werden.

Beispiel:
  python generate_thumbnails_from_fotos.py --limit 500 --max-width 380 --quality 85
"""

from __future__ import annotations

import argparse
import os
import sqlite3
from typing import Optional

DB_PATH = "output/lukas_bibliothek_v1.sqlite3"
THUMBS_DIR = os.path.join("output", "thumbnails")


def ensure_dir(path: str):
    if not os.path.isdir(path):
        os.makedirs(path, exist_ok=True)


def resolve_foto_path(p: str) -> Optional[str]:
    if not p:
        return None
    # normalisieren: akzeptiere 'fotos/...', '../fotos/...', 'output/fotos/...'
    p = p.strip().replace("\\", "/")
    candidates = []
    if p.startswith("fotos/"):
        candidates.append(p)
    if p.startswith("../fotos/"):
        candidates.append(p.replace("../", ""))
    if p.startswith("output/fotos/"):
        candidates.append(p.replace("output/", ""))
    # falls keiner der Fälle: evtl. absolut/anderer relativer Pfad
    candidates.append(p)
    for c in candidates:
        if os.path.isfile(c):
            return c
    return None


def open_image(path: str):
    try:
        from PIL import Image
    except Exception:  # pragma: no cover
        raise RuntimeError("Pillow (PIL) ist nicht installiert. Bitte 'pip install pillow'.")
    return Image.open(path)


def make_thumbnail(src_path: str, dst_path: str, max_width: int, quality: int):
    img = open_image(src_path)
    # orientierung beachten
    try:
        from PIL import ImageOps
        img = ImageOps.exif_transpose(img)
    except Exception:
        pass
    w, h = img.size
    if w > max_width:
        new_h = int(h * (max_width / float(w)))
        img = img.resize((max_width, new_h))
    ensure_dir(os.path.dirname(dst_path))
    # Immer als JPEG speichern
    img = img.convert("RGB")
    img.save(dst_path, format="JPEG", quality=quality, optimize=True)


def main():
    ap = argparse.ArgumentParser(description="Generate thumbnails from local fotos/")
    ap.add_argument("--limit", type=int, default=0, help="Max zu verarbeitende Bücher (0=alle)")
    ap.add_argument("--max-width", type=int, default=380, help="Maximale Breite der Thumbnails")
    ap.add_argument("--quality", type=int, default=85, help="JPEG-Qualität 1-95")
    ap.add_argument("--force", action="store_true", help="Existierende Thumbnails überschreiben")
    args = ap.parse_args()

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        """
        SELECT b.id, COALESCE(c.cover_local,'')
        FROM books b
        LEFT JOIN copies c ON c.book_id = b.id
        ORDER BY b.id
        """
    )
    rows = c.fetchall()
    conn.close()

    total = 0
    created = 0
    skipped = 0

    for (book_id, cover_local) in rows:
        total += 1
        if args.limit and created >= args.limit:
            break

        src = resolve_foto_path(cover_local)
        if not src:
            skipped += 1
            continue

        dst_rel = f"thumbnails/book_{book_id}.jpg"
        dst_abs = os.path.join("output", dst_rel)
        if os.path.isfile(dst_abs) and not args.force:
            skipped += 1
            continue

        try:
            make_thumbnail(src, dst_abs, args.max_width, args.quality)
            created += 1
        except Exception as e:
            skipped += 1
            # optional: print error for diagnostics
            print(f"⚠️  Übersprungen #{book_id} ({src}): {e}")

    print(f"✅ Thumbnails: erstellt={created}, übersprungen={skipped}, gesamt={total}")


if __name__ == "__main__":
    main()
