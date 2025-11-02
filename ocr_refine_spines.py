#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Refined OCR for book spine/cover segments without OpenCV.
- Reads output/fotos_segments.csv and images under output/fotos_segments/
- Preprocesses with PIL (resize, autocontrast, sharpen, threshold variants)
- Tries rotations (0/90/180/270) and multiple PSMs (5,6,7,11)
- Picks best text by a quality score (alpha_ratio + vowel_ratio + length)
- Guesses author / publisher by token overlap with catalog lists
- Guesses title as longest remaining line after removing author/publisher tokens
- Writes output/fotos_segments_refined.csv with: source_path, crop_path, segment_index,
  ocr_text_refined, author_guess, author_conf, publisher_guess, publisher_conf,
  title_guess
Requires: Pillow, pytesseract; uses deu+eng traineddata.
"""
from __future__ import annotations

import csv
import os
import re
from typing import Dict, List, Tuple

from PIL import Image, ImageFilter, ImageOps, ImageEnhance
import pytesseract

SEGMENTS_CSV = os.path.join('output','fotos_segments.csv')
CATALOG_CSV  = os.path.join('output','lukas_bibliothek_v1.csv')
REF_OUT      = os.path.join('output','fotos_segments_refined.csv')

# --- IO helpers ------------------------------------------------------------------------------

def read_csv(path: str) -> List[Dict[str,str]]:
    if not os.path.isfile(path):
        return []
    with open(path, 'r', encoding='utf-8', newline='') as f:
        return list(csv.DictReader(f))

def write_csv(path: str, header: List[str], rows: List[List[str]]):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8', newline='') as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)

# --- Text utils ------------------------------------------------------------------------------

def clean(s: str) -> str:
    s = (s or '').replace('\r','\n')
    s = re.sub(r"\t+"," ", s)
    s = re.sub(r"\n{2,}", "\n", s)
    return s.strip()

def tokens(s: str) -> List[str]:
    s = s.lower()
    s = re.sub(r"[^a-z0-9äöüß\s]"," ", s)
    return [t for t in s.split() if t]

VOWELS = set(list('aeiouäöü'))

def text_quality_score(text: str) -> float:
    if not text:
        return 0.0
    t = re.sub(r"\s+","", text)
    if not t:
        return 0.0
    alpha = sum(ch.isalpha() for ch in t)
    vowels = sum(ch in VOWELS for ch in t.lower())
    ratio_alpha = alpha/len(t)
    ratio_vowel = vowels/max(1, alpha)
    # penalize very short
    length_score = min(len(t)/80.0, 1.0)
    return 0.55*ratio_alpha + 0.25*ratio_vowel + 0.20*length_score

STOPLINES = set(['band','reihe','bd','auflage'])

# --- Catalog token sets ----------------------------------------------------------------------

def build_catalog_sets(cat: List[Dict[str,str]]):
    author_counts: Dict[str,int] = {}
    publisher_counts: Dict[str,int] = {}
    for r in cat:
        for t in tokens(r.get('author','') or ''):
            author_counts[t] = author_counts.get(t,0)+1
        for t in tokens(r.get('publisher','') or ''):
            publisher_counts[t] = publisher_counts.get(t,0)+1
    # keep medium-frequency tokens (avoid stopwords)
    def filter_counts(d: Dict[str,int], minc=2, maxc=500):
        return {k for k,v in d.items() if minc <= v <= maxc and len(k) > 1}
    return filter_counts(author_counts), filter_counts(publisher_counts)

# --- OCR -------------------------------------------------------------------------------------

def preprocess_variants(img: Image.Image) -> List[Image.Image]:
    out: List[Image.Image] = []
    g = img.convert('L')
    # upscale
    w,h = g.size
    scale = 2 if max(w,h) < 1600 else 1
    if scale != 1:
        g = g.resize((w*scale,h*scale), Image.LANCZOS)
    # variants
    v1 = ImageOps.autocontrast(g)
    v2 = ImageEnhance.Contrast(v1).enhance(1.8)
    v3 = v2.filter(ImageFilter.UnsharpMask(radius=2, percent=150, threshold=3))
    # hard threshold
    v4 = v3.point(lambda p: 255 if p > 170 else 0)
    # mild threshold
    v5 = v3.point(lambda p: 255 if p > 140 else 0)
    # small closing via MaxFilter then MinFilter
    v6 = v3.filter(ImageFilter.MaxFilter(3)).filter(ImageFilter.MinFilter(3))
    out.extend([v1,v2,v3,v4,v5,v6])
    return out

PSMS = [5,6,7,11]
ROTS = [0,90,270,180]

TES_BASE_CONFIG = "--oem 1 -l deu+eng"


def best_ocr_text(img: Image.Image) -> Tuple[str,float,int,int]:
    best_txt = ''
    best_score = 0.0
    best_rot = 0
    best_psm = 6
    for rot in ROTS:
        rimg = img.rotate(rot, expand=True) if rot else img
        for pv in preprocess_variants(rimg):
            for psm in PSMS:
                # Build two config variants without braces to avoid format issues
                cfgs = [
                    f"{TES_BASE_CONFIG} --psm {psm}",
                    f"{TES_BASE_CONFIG} --psm {psm} -c tessedit_char_blacklist=~`^*_|<>[]\\/"
                ]
                for cfg in cfgs:
                    try:
                        txt = pytesseract.image_to_string(pv, config=cfg)
                    except Exception:
                        continue
                    txt = clean(txt)
                    sc = text_quality_score(txt)
                    if sc > best_score:
                        best_txt, best_score, best_rot, best_psm = txt, sc, rot, psm
    return best_txt, best_score, best_rot, best_psm

# --- Guessers --------------------------------------------------------------------------------

def guess_author(text: str, author_token_set: set) -> Tuple[str,float]:
    toks = tokens(text)
    if not toks:
        return '', 0.0
    inter = [t for t in toks if t in author_token_set]
    if not inter:
        return '', 0.0
    # heuristic: choose top 3 contiguous words around the densest area
    conf = min(len(inter)/max(3,len(set(toks))), 1.0)
    # return joined unique tokens in order
    seen, seq = set(), []
    for t in toks:
        if t in author_token_set and t not in seen:
            seq.append(t); seen.add(t)
        if len(seq) >= 4:
            break
    return ' '.join(seq), conf


def guess_publisher(text: str, publisher_token_set: set) -> Tuple[str,float]:
    toks = tokens(text)
    inter = [t for t in toks if t in publisher_token_set]
    if not inter:
        return '', 0.0
    conf = min(len(inter)/max(3,len(set(toks))), 1.0)
    seen, seq = set(), []
    for t in toks:
        if t in publisher_token_set and t not in seen:
            seq.append(t); seen.add(t)
        if len(seq) >= 3:
            break
    return ' '.join(seq), conf


def guess_title(text: str, author_guess: str, publisher_guess: str) -> str:
    # remove lines that look like noise or known fields
    lines = [ln.strip() for ln in text.split('\n') if ln.strip()]
    ag = set(tokens(author_guess)) if author_guess else set()
    pg = set(tokens(publisher_guess)) if publisher_guess else set()
    candidates: List[str] = []
    for ln in lines:
        lk = tokens(ln)
        if not lk:
            continue
        if any(t in STOPLINES for t in lk):
            continue
        if ag and any(t in ag for t in lk):
            continue
        if pg and any(t in pg for t in lk):
            continue
        # strong candidate if contains at least 2 letters and not all uppercase gibberish
        letters = sum(ch.isalpha() for ch in ln)
        if letters < 4:
            continue
        candidates.append(ln)
    if not candidates:
        # fallback: longest line
        candidates = lines
    if not candidates:
        return ''
    # choose the visually longest line
    candidates.sort(key=lambda s: len(s), reverse=True)
    return candidates[0]

# --- Main ------------------------------------------------------------------------------------

def main():
    segs = read_csv(SEGMENTS_CSV)
    cat  = read_csv(CATALOG_CSV)
    if not segs:
        print('Keine Segmente gefunden. Bitte zuerst die Segmente erzeugen.')
        return 2
    author_set, publisher_set = build_catalog_sets(cat)

    rows_out: List[List[str]] = []
    header = [
        'source_path','crop_path','segment_index',
        'ocr_text_refined','author_guess','author_conf','publisher_guess','publisher_conf','title_guess'
    ]

    for r in segs:
        crop = r.get('crop_path') or ''
        src  = r.get('source_path') or ''
        segi = r.get('segment_index') or ''
        if not crop or not os.path.isfile(crop):
            continue
        try:
            img = Image.open(crop)
        except Exception:
            continue
        txt, score, rot, psm = best_ocr_text(img)
        a_guess, a_conf = guess_author(txt, author_set)
        p_guess, p_conf = guess_publisher(txt, publisher_set)
        t_guess = guess_title(txt, a_guess, p_guess)
        rows_out.append([
            src, crop, segi,
            txt, a_guess, f"{a_conf:.3f}", p_guess, f"{p_conf:.3f}", t_guess
        ])

    write_csv(REF_OUT, header, rows_out)
    print(f"✓ Verfeinerte OCR: {REF_OUT} ({len(rows_out)} Zeilen)")

if __name__ == '__main__':
    raise SystemExit(main())
