#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Liest output/fotos_segments.csv (mit OCR) und den Katalog output/lukas_bibliothek_v1.csv,
versucht robuste Matches (ISBN > Autor+Titel > Titel-only) und schreibt:
- output/fotos_candidates_matched.csv (mit matched_* Feldern und Status existing/new)
- output/new_books_from_fotos.csv (nur 'new' Zeilen, neu zusammengesetzt)

Heuristik:
- ISBN (10/13) extrahieren + prüfen => direkter Match (existing)
- Autor-Erkennung: suche Nachnamen/Autoren-Tokens aus Katalog in OCR-Text
- Titel-Similarity: Mischung aus SequenceMatcher und Token-Jaccard
- Publisher-Tokens erhöhen Score leicht

Akzeptanzkriterien:
- ISBN-Treffer => existing
- Autor vorhanden UND score >= 0.75 => existing
- score >= 0.84 => existing
sonst new
"""
from __future__ import annotations

import csv
import os
import re
from difflib import SequenceMatcher
from typing import Dict, List, Tuple, Optional

SEGMENTS_CSV   = os.path.join('output','fotos_segments.csv')
REFINED_CSV    = os.path.join('output','fotos_segments_refined.csv')
BASE_CAND_CSV  = os.path.join('output','fotos_new_candidates.csv')
CATALOG_CSV    = os.path.join('output','lukas_bibliothek_v1.csv')
CAND_OUT       = os.path.join('output','fotos_candidates_matched.csv')
NEW_OUT        = os.path.join('output','new_books_from_fotos.csv')


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

# --- Normalisierung & Tokenisierung -----------------------------------------------------------

def norm(s: str) -> str:
    return (s or '').strip()

def clean(s: str) -> str:
    s = (s or '').lower()
    # einfache Bereinigung, Umlaute bleiben
    s = re.sub(r"[^a-z0-9äöüß\s]"," ", s)
    s = re.sub(r"\s+"," ", s).strip()
    return s

def tokens(s: str) -> List[str]:
    return [t for t in clean(s).split(' ') if t]

# --- ISBN-Erkennung --------------------------------------------------------------------------

def is_isbn10(s: str) -> bool:
    s = re.sub(r"[^0-9xX]","", s)
    if len(s) != 10:
        return False
    total = 0
    for i,ch in enumerate(s[:9], start=1):
        if not ch.isdigit():
            return False
        total += i*int(ch)
    c = s[9]
    if c in 'xX':
        total += 10*10
    elif c.isdigit():
        total += 10*int(c)
    else:
        return False
    return total % 11 == 0

def is_isbn13(s: str) -> bool:
    s = re.sub(r"[^0-9]","", s)
    if len(s) != 13:
        return False
    sm = 0
    for i,ch in enumerate(s[:12]):
        d = ord(ch)-48
        sm += d * (1 if i%2==0 else 3)
    chk = (10 - (sm % 10)) % 10
    return chk == int(s[12])

def find_isbn(text: str) -> Optional[str]:
    if not text:
        return None
    # suche 10/13er Sequenzen mit oder ohne Bindestriche
    cands = re.findall(r"(?:97[89][- ]?(?:\d[- ]?){9}\d|\b\d{9}[\dXx]\b)", text)
    for raw in cands:
        flat = re.sub(r"[^0-9Xx]","", raw)
        if is_isbn13(flat) or is_isbn10(flat):
            return flat
    return None

# --- Katalog-Indizes -------------------------------------------------------------------------

def build_catalog_indexes(rows: List[Dict[str,str]]):
    by_isbn: Dict[str, Dict[str,str]] = {}
    authors: List[str] = []
    by_author: Dict[str, List[Dict[str,str]]] = {}
    publishers: List[str] = []

    for r in rows:
        isbn = norm(r.get('isbn'))
        if isbn:
            by_isbn[re.sub(r"[^0-9Xx]","", isbn)] = r
        a = norm(r.get('author'))
        if a:
            authors.append(a)
            key = clean(a)
            by_author.setdefault(key, []).append(r)
        p = norm(r.get('publisher'))
        if p:
            publishers.append(p)
    # einfache Token-Sets für Autor/Verlag
    author_tokens = set()
    for a in authors:
        author_tokens.update(tokens(a))
    publisher_tokens = set()
    for p in publishers:
        publisher_tokens.update(tokens(p))
    return by_isbn, by_author, author_tokens, publisher_tokens

# --- Scoring ----------------------------------------------------------------------------------

def jaccard(a: List[str], b: List[str]) -> float:
    sa, sb = set(a), set(b)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def score_title(o_txt: str, title: str) -> float:
    a = clean(o_txt)
    b = clean(title)
    if not a or not b:
        return 0.0
    s1 = SequenceMatcher(None, a, b).ratio()
    s2 = jaccard(tokens(a), tokens(b))
    return 0.6*s1 + 0.4*s2


def has_any_token(text: str, token_set: set) -> bool:
    for t in tokens(text):
        if t in token_set:
            return True
    return False

# --- Main -------------------------------------------------------------------------------------

def main():
    segs = read_csv(SEGMENTS_CSV)
    refined = read_csv(REFINED_CSV)
    base = read_csv(BASE_CAND_CSV)
    cat  = read_csv(CATALOG_CSV)
    if not segs or not base or not cat:
        print('Fehlende Eingaben. Prüfe, ob OCR-Segmente, Basiskandidaten und Katalog vorhanden sind.')
        return 2
    by_isbn, by_author_map, author_tokens, publisher_tokens = build_catalog_indexes(cat)
    # Indexe
    seg_index: Dict[Tuple[str,str], Dict[str,str]] = {}
    for r in segs:
        seg_index[(r.get('source_path',''), r.get('segment_index',''))] = r
    ref_index: Dict[Tuple[str,str], Dict[str,str]] = {}
    for r in refined:
        # prefer same key
        ref_index[(r.get('source_path','') or r.get('source_photo',''), r.get('segment_index',''))] = r
    by_id: Dict[str, Dict[str,str]] = { (row.get('id','') or ''): row for row in cat }

    cand_rows: List[List[str]] = []
    new_rows: List[List[str]]  = []

    cand_header = [
        'source_path','crop_path','segment_index','ocr_title_hint','ocr_text',
        'matched_book_id','matched_title','matched_author','matched_publisher','match_score','status','reason',
        'guess_title','guess_author','guess_publisher'
    ]
    new_header = ['title','author','publisher','cover_local','source_photo','photo_base','segment_index']

    for r in base:
        src = r.get('source_path') or ''
        crop = r.get('crop_path') or ''
        segi = r.get('segment_index') or ''
        hint = r.get('ocr_title_hint') or ''
        base_id = (r.get('matched_book_id') or '').strip()
        try:
            base_score = float(r.get('match_score') or '0')
        except ValueError:
            base_score = 0.0

        seg = seg_index.get((src, segi), {})
    otext = seg.get('ocr_text','')
    ref  = ref_index.get((src, segi), {})
    g_title = ref.get('title_guess','') or ''
    g_author = ref.get('author_guess','') or ''
    g_pub = ref.get('publisher_guess','') or ''
        text = ' '.join([hint, otext]).strip()

        status = 'new'
        reason = ''
        m_id = ''
        m_title = ''
        m_author = ''
        m_pub = ''
        final_score = base_score

        # 0) ISBN schlägt immer
        isbn = find_isbn(text)
        if isbn and isbn in by_isbn:
            bk = by_isbn[isbn]
            m_id = bk.get('id','')
            m_title = bk.get('title','')
            m_author = bk.get('author','')
            m_pub = bk.get('publisher','')
            final_score = 1.0
            status = 'existing'
            reason = 'isbn'
        else:
            # 1) Wenn Basiskandidat mit hohem Score existiert => übernehmen
            if base_id and base_id in by_id and base_score >= 0.84:
                bk = by_id[base_id]
                m_id = base_id
                m_title = bk.get('title','')
                m_author = bk.get('author','')
                m_pub = bk.get('publisher','')
                status = 'existing'
                reason = 'baseline>=0.84'
            else:
                # Wenn Basiskandidat existiert, Vorschlag übernehmen (auch bei niedrigerem Score)
                if base_id and base_id in by_id:
                    bk = by_id[base_id]
                    m_id = base_id
                    m_title = bk.get('title','')
                    m_author = bk.get('author','')
                    m_pub = bk.get('publisher','')
                    reason = 'baseline-suggestion'
                    final_score = base_score
                # 2) Autor+Titel-Heuristik
                has_author = has_any_token(text, author_tokens)
                has_pub    = has_any_token(text, publisher_tokens)
                best = None
                best_score = 0.0
                for bk in cat:
                    s = score_title(text, bk.get('title',''))
                    if has_author and bk.get('author') and has_any_token(text, set(tokens(bk.get('author','')))):
                        s += 0.05
                    if has_pub and bk.get('publisher') and has_any_token(text, set(tokens(bk.get('publisher','')))):
                        s += 0.03
                    if s > best_score:
                        best_score = s
                        best = bk
                if best is not None and ((has_author and best_score >= 0.75) or best_score >= 0.88):
                    m_id = best.get('id','')
                    m_title = best.get('title','')
                    m_author = best.get('author','')
                    m_pub = best.get('publisher','')
                    final_score = max(final_score, best_score)
                    status = 'existing'
                    reason = 'author+title' if has_author and best_score >= 0.75 else 'title-only>=0.88'

        # Ausgabezeilen
        cand_rows.append([
            src,crop,segi,hint,otext,
            m_id, m_title, m_author, m_pub, f"{final_score:.3f}", status, reason,
            g_title, g_author, g_pub
        ])

        if status == 'new':
            photo_base = os.path.splitext(os.path.basename(src))[0]
            new_rows.append([
                g_title or hint or '', g_author or '', g_pub or '',
                crop, src, photo_base, segi
            ])

    write_csv(CAND_OUT, cand_header, cand_rows)
    write_csv(NEW_OUT, new_header, new_rows)
    print(f"✓ Kandidaten (angereichert): {CAND_OUT} ({len(cand_rows)} Zeilen)")
    print(f"✓ Neue-Bücher (nur new): {NEW_OUT} ({len(new_rows)} Zeilen)")

if __name__ == '__main__':
    raise SystemExit(main())
