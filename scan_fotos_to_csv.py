#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Scannt den Ordner fotos/ nach Bildern und erstellt:
 - output/fotos_manifest.csv: alle Bilddateien mit Größe, Datum, Hash (optional), Referenzstatus
 - output/fotos_new_candidates.csv: Bilder, die in der Katalog-CSV (cover_local) nicht referenziert sind

Abgleich mit Katalog-CSV (Standard: output/lukas_bibliothek_v1.csv).

Optional: einfacher OCR-Versuch, wenn pytesseract verfügbar ist (nur bei --ocr),
um grobe Hinweise zu Titel/Autor zu notieren (nicht invasiv, nur in Manifest-Spalten ocr_text/ocr_title_hint).

Nutzung:
  python scan_fotos_to_csv.py --csv output/lukas_bibliothek_v1.csv --ocr
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import os
import sys
from datetime import datetime
from typing import Dict, List, Optional, Tuple

FOTOS_DIR = "fotos"
DEFAULT_CSV = os.path.join("output", "lukas_bibliothek_v1.csv")
MANIFEST_OUT = os.path.join("output", "fotos_manifest.csv")
NEW_OUT = os.path.join("output", "fotos_new_candidates.csv")


def list_images(root: str) -> List[str]:
    exts = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
    out: List[str] = []
    for dirpath, _dirnames, filenames in os.walk(root):
        for fn in filenames:
            ext = os.path.splitext(fn)[1].lower()
            if ext in exts:
                out.append(os.path.join(dirpath, fn))
    out.sort()
    return out


def sha1sum(path: str, blocksize: int = 65536) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(blocksize), b""):
            h.update(chunk)
    return h.hexdigest()


def load_catalog_refs(csv_path: str) -> Tuple[Dict[str, List[str]], Dict[str, List[str]]]:
    """Lädt CSV und baut zwei Maps (basename->ids, relpath->ids)."""
    base_to_ids: Dict[str, List[str]] = {}
    path_to_ids: Dict[str, List[str]] = {}
    if not os.path.isfile(csv_path):
        return base_to_ids, path_to_ids
    with open(csv_path, "r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            bid = (row.get("id") or "").strip()
            p = (row.get("cover_local") or "").replace("\\", "/").strip()
            if not bid or not p:
                continue
            # Normalisiere ../fotos/... oder fotos/... auf basename
            base = os.path.basename(p)
            if base:
                base_to_ids.setdefault(base, []).append(bid)
            path_to_ids.setdefault(p, []).append(bid)
    return base_to_ids, path_to_ids


def try_ocr(path: str) -> Tuple[str, str]:
    """Grobe OCR. Gibt (raw_text, title_hint) zurück. Fällt still zurück, wenn pytesseract fehlt."""
    try:
        import pytesseract
        from PIL import Image
    except Exception:
        return "", ""
    try:
        img = Image.open(path)
        # Schnellmodus
        text = pytesseract.image_to_string(img, lang="deu+eng")
        text = " ".join(text.split())
        # Einfacher Heuristik-Versuch für Titel-Hinweis: nimm die längste Wortsequenz 2-6 Wörter
        words = text.split()
        best = ""
        for span in range(6, 1, -1):
            for i in range(0, max(0, len(words) - span + 1)):
                cand = " ".join(words[i:i+span])
                if len(cand) > len(best):
                    best = cand
            if best:
                break
        return text, best
    except Exception:
        return "", ""


def write_csv(path: str, header: List[str], rows: List[List[str]]):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


def main() -> int:
    ap = argparse.ArgumentParser(description="Scan fotos/ and produce manifest + new candidates CSV")
    ap.add_argument("--csv", default=DEFAULT_CSV, help="Katalog-CSV zum Abgleich")
    ap.add_argument("--hash", action="store_true", help="SHA1 berechnen (langsamer)")
    ap.add_argument("--ocr", action="store_true", help="Einfaches OCR probieren (falls pytesseract vorhanden)")
    args = ap.parse_args()

    if not os.path.isdir(FOTOS_DIR):
        print(f"Ordner nicht gefunden: {FOTOS_DIR}", file=sys.stderr)
        return 2

    imgs = list_images(FOTOS_DIR)
    base_to_ids, _ = load_catalog_refs(args.csv)

    manifest_rows: List[List[str]] = []
    new_rows: List[List[str]] = []

    for p in imgs:
        st = os.stat(p)
        size = st.st_size
        mtime = datetime.fromtimestamp(st.st_mtime).isoformat(timespec="seconds")
        base = os.path.basename(p)
        ids = base_to_ids.get(base, [])
        referenced = "yes" if ids else "no"
        sha = sha1sum(p) if args.hash else ""
        ocr_text = ""
        ocr_hint = ""
        if args.ocr:
            ocr_text, ocr_hint = try_ocr(p)
        manifest_rows.append([
            p.replace("\\", "/"), base, size, mtime, referenced, ",".join(ids), sha, ocr_hint, ocr_text
        ])
        if referenced == "no":
            new_rows.append([p.replace("\\", "/"), base, size, mtime, sha])

    write_csv(MANIFEST_OUT, [
        "path", "file", "size_bytes", "modified", "referenced", "book_ids", "sha1", "ocr_title_hint", "ocr_text"
    ], manifest_rows)

    write_csv(NEW_OUT, [
        "path", "file", "size_bytes", "modified", "sha1"
    ], new_rows)

    print(f"📸 Fotos gescannt: {len(imgs)} Dateien. Referenziert: {sum(1 for r in manifest_rows if r[4]=='yes')}, neu: {len(new_rows)}")
    print(f"→ Manifest: {MANIFEST_OUT}")
    print(f"→ Neue Kandidaten: {NEW_OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
