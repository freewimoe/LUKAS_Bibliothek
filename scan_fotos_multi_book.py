#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Erkennt mehrere Bücher (Buchrücken) in einem Foto.

Workflow:
 1) Lädt alle Bilder aus fotos/.
 2) Segmentiert vertikal (Spaltenprojektion) und findet Trennfugen zwischen Buchrücken.
 3) Schneidet Segmente aus und speichert sie unter output/fotos_segments/<datei>__segXX.jpg.
 4) (Optional) OCR mit pytesseract zur Titel/Autor-Andeutung.
 5) Abgleich mit Katalog (lukas_bibliothek_v1.csv) via Fuzzy-Match auf Titel.
 6) Schreibt:
    - output/fotos_segments.csv   (alle Segmente)
    - output/fotos_new_candidates.csv (Segment-Granular, inkl. Match-Infos)
    - output/new_books_from_fotos.csv (Vorschläge zum Import neuer Bücher)

Nutzung:
  python scan_fotos_multi_book.py --ocr --min-seg-width 80 --threshold 180

Hinweis:
 - Nur Standardbibliotheken + Pillow (PIL) werden benötigt. OCR via pytesseract ist optional.
 - Für Windows: Tesseract kann separat installiert werden (z.B. https://tesseract-ocr.github.io/tessdoc/Installation.html).
"""
from __future__ import annotations

import argparse
import csv
import os
import sys
from datetime import datetime
from difflib import SequenceMatcher
from typing import List, Tuple, Optional, Dict

from PIL import Image, ImageOps
import numpy as np

FOTOS_DIR = "fotos"
OUT_DIR = os.path.join("output", "fotos_segments")
SEGMENTS_CSV = os.path.join("output", "fotos_segments.csv")
CANDIDATES_CSV = os.path.join("output", "fotos_new_candidates.csv")
NEW_BOOKS_CSV = os.path.join("output", "new_books_from_fotos.csv")
CATALOG_CSV = os.path.join("output", "lukas_bibliothek_v1.csv")


def list_images(root: str) -> List[str]:
    exts = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
    out: List[str] = []
    for dp, _, fns in os.walk(root):
        for fn in fns:
            if os.path.splitext(fn)[1].lower() in exts:
                out.append(os.path.join(dp, fn))
    out.sort()
    return out


def ocr_text(img: Image.Image, langs: str = "deu+eng") -> Tuple[str, str]:
    try:
        import pytesseract
    except Exception:
        return "", ""
    try:
        # sanfte Vorverarbeitung
        g = ImageOps.grayscale(img)
        g = ImageOps.autocontrast(g)
        text = pytesseract.image_to_string(g, lang=langs)
        text = " ".join(text.split())
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


def vertical_segments(img: Image.Image, min_seg_width: int = 80, threshold: int = 180, margin: int = 6) -> List[Tuple[int, int]]:
    """Ermittelt vertikale Segmente durch Spaltenprojektion.
    - min_seg_width: minimale Breite eines Segments in Pixeln
    - threshold: Grauwert-Schwelle (0..255). Werte < threshold zählen als "dunkel".
    - margin: Ränder links/rechts (Pixel), die ignoriert werden.
    """
    g = ImageOps.grayscale(img)
    arr = np.asarray(g)
    _, W = arr.shape
    x0 = margin
    x1 = W - margin
    if x1 <= x0:
        x0, x1 = 0, W
    # Dunkelheits-Projektion: je Spalte Anzahl der Pixel unter threshold
    dark = (arr[:, x0:x1] < threshold).sum(axis=0)

    # Lücken (helle Fugen) sind dort, wo dark klein ist. Wir suchen lokale Minima unter einem Perzentil.
    # Heuristik: Trennschwelle = 20. Perzentil
    thr = np.percentile(dark, 20)
    gaps = (dark <= thr).astype(np.uint8)

    # Finde Abschnitte (Runs) zusammenhängender "nicht-gap" Bereiche (dark > thr) => potentielle Bücher
    segments: List[Tuple[int, int]] = []
    in_run = False
    run_start = 0
    for i, is_gap in enumerate(gaps):
        if is_gap:
            if in_run:
                # run endet vor i
                sx = x0 + run_start
                ex = x0 + i
                if ex - sx >= min_seg_width:
                    segments.append((sx, ex))
                in_run = False
        else:
            if not in_run:
                in_run = True
                run_start = i
    if in_run:
        sx = x0 + run_start
        ex = x0 + len(gaps)
        if ex - sx >= min_seg_width:
            segments.append((sx, ex))

    # Falls kein Segment erkannt wurde, nimm das gesamte Bild als 1 Segment
    if not segments:
        segments = [(0, W)]

    return segments


def load_catalog(csv_path: str) -> List[Dict[str, str]]:
    if not os.path.isfile(csv_path):
        return []
    out: List[Dict[str, str]] = []
    with open(csv_path, "r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            out.append(row)
    return out


def best_title_match(title_hint: str, catalog: List[Dict[str, str]]) -> Tuple[Optional[Dict[str, str]], float]:
    title_hint = (title_hint or "").strip()
    if not title_hint:
        return None, 0.0
    best = None
    best_score = 0.0
    for r in catalog:
        t = (r.get("title") or "").strip()
        if not t:
            continue
        score = SequenceMatcher(None, title_hint.lower(), t.lower()).ratio()
        if score > best_score:
            best_score = score
            best = r
    return best, best_score


def ensure_dir(p: str):
    os.makedirs(p, exist_ok=True)


def process_image(path: str, out_dir: str, args) -> Tuple[List[List[str]], List[List[str]], List[List[str]]]:
    """Verarbeitet 1 Bild, liefert Zeilen für (segments_csv, candidates_csv, new_books_csv)."""
    base = os.path.basename(path)
    try:
        img = Image.open(path)
    except Exception as e:
        print(f"WARN: Konnte Bild nicht öffnen: {path} ({e})", file=sys.stderr)
        return [], [], []

    # Orientierungs-Fix (EXIF)
    try:
        img = ImageOps.exif_transpose(img)
    except Exception:
        pass

    segs = vertical_segments(img, min_seg_width=args.min_seg_width, threshold=args.threshold, margin=args.margin)
    H = img.height

    seg_rows: List[List[str]] = []
    cand_rows: List[List[str]] = []
    new_rows: List[List[str]] = []

    for idx, (sx, ex) in enumerate(segs, start=1):
        crop = img.crop((sx, 0, ex, H))
        seg_name = f"{os.path.splitext(base)[0]}__seg{idx:02d}.jpg"
        seg_path = os.path.join(out_dir, seg_name)
        try:
            crop.save(seg_path, format="JPEG", quality=90)
        except Exception as e:
            print(f"WARN: Konnte Segment nicht speichern: {seg_path} ({e})", file=sys.stderr)
            continue

        ocr_text_val = ""
        ocr_hint_val = ""
        if args.ocr:
            ocr_text_val, ocr_hint_val = ocr_text(crop)

        seg_rows.append([
            path.replace("\\", "/"), base, str(idx), str(sx), str(ex), str(ex - sx), str(H), seg_path.replace("\\", "/"), ocr_hint_val, ocr_text_val
        ])

        match, score = (None, 0.0)
        if args.match and args.catalog:
            match, score = best_title_match(ocr_hint_val, args.catalog)
        match_id = (match or {}).get("id") if match else ""
        match_title = (match or {}).get("title") if match else ""
        status = "existing" if (match and score >= args.match_threshold) else "new"

        cand_rows.append([
            path.replace("\\", "/"), seg_path.replace("\\", "/"), str(idx), ocr_hint_val,
            match_id or "", match_title or "", f"{score:.3f}", status
        ])

        if status == "new":
            # Minimaler Vorschlag für neuen Buch-Eintrag
            new_rows.append([
                ocr_hint_val, "",  # title, author (leer)
                seg_path.replace("\\", "/"),  # cover_local (Segment)
                path.replace("\\", "/"),       # source_photo
                os.path.splitext(base)[0],         # photo_base
                str(idx)                           # segment_index
            ])

    return seg_rows, cand_rows, new_rows


def write_csv(path: str, header: List[str], rows: List[List[str]]):
    ensure_dir(os.path.dirname(path))
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


def main() -> int:
    ap = argparse.ArgumentParser(description="Mehrfach-Buchscanner für Fotos")
    ap.add_argument("--min-seg-width", type=int, default=80, help="Minimale Segmentbreite in px")
    ap.add_argument("--threshold", type=int, default=180, help="Schwelle für dunkle Pixel (0-255)")
    ap.add_argument("--margin", type=int, default=6, help="Linker/Rechter Rand in px, die ignoriert werden")
    ap.add_argument("--ocr", action="store_true", help="OCR (pytesseract) aktivieren, falls vorhanden")
    ap.add_argument("--match", action="store_true", help="Mit Katalog-Titeln abgleichen (Fuzzy)")
    ap.add_argument("--match-threshold", type=float, default=0.82, help="Match-Schwelle 0..1 für 'existing'")
    ap.add_argument("--catalog", default=CATALOG_CSV, help="Pfad zur Katalog-CSV")
    args = ap.parse_args()

    if not os.path.isdir(FOTOS_DIR):
        print(f"Ordner nicht gefunden: {FOTOS_DIR}", file=sys.stderr)
        return 2

    ensure_dir(OUT_DIR)

    catalog_rows: List[Dict[str, str]] = []
    if args.match and isinstance(args.catalog, str):
        catalog_rows = load_catalog(args.catalog)
    args.catalog = catalog_rows  # bind in args for downstream access

    imgs = list_images(FOTOS_DIR)

    seg_header = ["source_path", "source_file", "segment_index", "x0", "x1", "width", "height", "crop_path", "ocr_title_hint", "ocr_text"]
    cand_header = ["source_path", "crop_path", "segment_index", "ocr_title_hint", "matched_book_id", "matched_title", "match_score", "status"]
    new_header = ["title", "author", "cover_local", "source_photo", "photo_base", "segment_index"]

    seg_rows_all: List[List[str]] = []
    cand_rows_all: List[List[str]] = []
    new_rows_all: List[List[str]] = []

    for i, p in enumerate(imgs, start=1):
        seg_rows, cand_rows, new_rows = process_image(p, OUT_DIR, args)
        seg_rows_all.extend(seg_rows)
        cand_rows_all.extend(cand_rows)
        new_rows_all.extend(new_rows)
        print(f"[{i}/{len(imgs)}] {os.path.basename(p)} => {len(seg_rows)} Segmente")

    write_csv(SEGMENTS_CSV, seg_header, seg_rows_all)
    write_csv(CANDIDATES_CSV, cand_header, cand_rows_all)
    write_csv(NEW_BOOKS_CSV, new_header, new_rows_all)

    print(f"✓ Segment-CSV: {SEGMENTS_CSV} ({len(seg_rows_all)} Zeilen)")
    print(f"✓ Kandidaten-CSV: {CANDIDATES_CSV} ({len(cand_rows_all)} Zeilen)")
    print(f"✓ Neue-Bücher-Vorschläge: {NEW_BOOKS_CSV} ({len(new_rows_all)} Zeilen)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
