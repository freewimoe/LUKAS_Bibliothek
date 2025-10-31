#!/usr/bin/env python3
"""
Catalog validator for LUKAS-Bibliothek

Goals
- Find suspicious records (ISBN not found, title/author mismatch, missing/placeholder cover)
- Propose safer fixes (ISBN and cover URL) when a high-confidence match exists
- Produce a CSV report and optional JSON for further processing
- Optional safe apply that never overwrites title/author: fill only missing ISBN when
    title+author anchor matches at high confidence.

Usage (local):
    python verify_catalog.py --csv output/lukas_bibliothek_v1.csv --report output/validation_report.csv

Options:
    --apply-safe           Apply only safe fixes: fill missing ISBN if title+author similarity ≥ 0.80 for both.
                                                 Writes an updated CSV (see --fixed-out). Never overwrites title/author.
    --fixed-out PATH       Output path for updated CSV (default output/lukas_bibliothek_v1.fixed.csv)
    --max-requests N       Cap outbound API calls (to be friendly to public APIs)
    --timeout SEC          HTTP timeout per request (default 6)
    --cache FILE           JSON cache file for API responses (default output/metadata_cache.json)

This script purposefully has zero third‑party deps.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from difflib import SequenceMatcher
from typing import Any, Dict, Optional, Tuple, List

# ---------- Utils ----------

def norm_text(s: str) -> str:
    if not s:
        return ""
    s = s.strip().lower()
    # normalize german umlauts
    s = s.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
    # remove punctuation
    s = re.sub(r"[^a-z0-9\s]", " ", s)
    # collapse whitespace
    s = re.sub(r"\s+", " ", s).strip()
    return s

def token_key(s: str) -> str:
    toks = sorted(set(norm_text(s).split()))
    return " ".join(toks)

def similarity(a: str, b: str) -> float:
    ta, tb = token_key(a), token_key(b)
    if not ta or not tb:
        return 0.0
    return SequenceMatcher(None, ta, tb).ratio()

# ---------- HTTP / caching ----------

class Cache:
    def __init__(self, path: str):
        self.path = path
        self.data: Dict[str, Any] = {}
        if os.path.isfile(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    self.data = json.load(f)
            except Exception:
                self.data = {}

    def get(self, key: str) -> Optional[Any]:
        return self.data.get(key)

    def set(self, key: str, value: Any) -> None:
        self.data[key] = value

    def save(self) -> None:
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)


def http_get_json(url: str, timeout: float) -> Optional[Dict[str, Any]]:
    req = urllib.request.Request(url, headers={"User-Agent": "LUKAS-Bibliothek/validator"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        if r.status != 200:
            return None
        body = r.read()
    try:
        return json.loads(body.decode("utf-8"))
    except Exception:
        return None

# ---------- External metadata sources ----------

OPENLIB_BOOK_API = "https://openlibrary.org/isbn/{isbn}.json"
OPENLIB_COVER_URL = "https://covers.openlibrary.org/b/isbn/{isbn}-L.jpg"
OPENLIB_SEARCH = (
    "https://openlibrary.org/search.json?title={title}&author={author}&limit=5"
)
GOOGLE_VOLUMES_ISBN = (
    "https://www.googleapis.com/books/v1/volumes?q=isbn:{isbn}"
)
GOOGLE_VOLUMES_SEARCH = (
    "https://www.googleapis.com/books/v1/volumes?q=intitle:{title}+inauthor:{author}&maxResults=5"
)


def ol_by_isbn(isbn: str, timeout: float, cache: Cache) -> Optional[Dict[str, Any]]:
    key = f"ol:isbn:{isbn}"
    cached = cache.get(key)
    if cached is not None:
        return cached
    url = OPENLIB_BOOK_API.format(isbn=urllib.parse.quote(isbn))
    data = http_get_json(url, timeout)
    cache.set(key, data)
    return data


def ol_search(title: str, author: str, timeout: float, cache: Cache) -> Optional[Dict[str, Any]]:
    key = f"ol:search:{token_key(title)}::{token_key(author)}"
    cached = cache.get(key)
    if cached is not None:
        return cached
    url = OPENLIB_SEARCH.format(
        title=urllib.parse.quote(title), author=urllib.parse.quote(author)
    )
    data = http_get_json(url, timeout)
    cache.set(key, data)
    return data


def google_by_isbn(isbn: str, timeout: float, cache: Cache) -> Optional[Dict[str, Any]]:
    key = f"g:isbn:{isbn}"
    cached = cache.get(key)
    if cached is not None:
        return cached
    url = GOOGLE_VOLUMES_ISBN.format(isbn=urllib.parse.quote(isbn))
    data = http_get_json(url, timeout)
    cache.set(key, data)
    return data


def google_search(title: str, author: str, timeout: float, cache: Cache) -> Optional[Dict[str, Any]]:
    key = f"g:search:{token_key(title)}::{token_key(author)}"
    cached = cache.get(key)
    if cached is not None:
        return cached
    url = GOOGLE_VOLUMES_SEARCH.format(
        title=urllib.parse.quote(title), author=urllib.parse.quote(author)
    )
    data = http_get_json(url, timeout)
    cache.set(key, data)
    return data


# ---------- Suggestion logic ----------

def pick_google_volume(data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    try:
        items = data.get("items") or []
        if not items:
            return None
        # prefer first result
        vol = items[0]
        info = vol.get("volumeInfo") or {}
        isbn_13 = None
        for iden in info.get("industryIdentifiers", []) or []:
            if iden.get("type") == "ISBN_13":
                isbn_13 = iden.get("identifier")
                break
        return {
            "title": info.get("title"),
            "authors": info.get("authors") or [],
            "publisher": info.get("publisher"),
            "isbn": isbn_13,
            "cover": (info.get("imageLinks") or {}).get("thumbnail") or (info.get("imageLinks") or {}).get("smallThumbnail"),
        }
    except Exception:
        return None


def canonical_from_isbn(isbn: str, timeout: float, cache: Cache) -> Optional[Dict[str, Any]]:
    # Try OpenLibrary first
    ol = ol_by_isbn(isbn, timeout, cache)
    if ol:
        title = ol.get("title")
        authors = []
        if isinstance(ol.get("authors"), list):
            authors = [a.get("name") for a in ol.get("authors") if isinstance(a, dict) and a.get("name")]
        publishers = []
        if isinstance(ol.get("publishers"), list):
            publishers = [p for p in ol.get("publishers") if isinstance(p, str)]
        return {
            "title": title,
            "authors": authors,
            "publisher": publishers[0] if publishers else None,
            "isbn": isbn,
            "cover": OPENLIB_COVER_URL.format(isbn=isbn),
            "source": "openlibrary",
        }
    # Fall back: Google Books
    g = google_by_isbn(isbn, timeout, cache)
    if g:
        picked = pick_google_volume(g)
        if picked:
            picked["source"] = "google"
            if not picked.get("isbn"):
                picked["isbn"] = isbn
            return picked
    return None


def search_by_title_author(title: str, author: str, timeout: float, cache: Cache) -> Optional[Dict[str, Any]]:
    # Try OpenLibrary search
    ol = ol_search(title, author, timeout, cache)
    if ol and (ol.get("docs")):
        doc = ol["docs"][0]
        cand_isbn = None
        for key in ("isbn", "isbn13", "isbn_13"):
            v = doc.get(key)
            if isinstance(v, list) and v:
                cand_isbn = v[0]
                break
            if isinstance(v, str):
                cand_isbn = v
                break
        return {
            "title": doc.get("title"),
            "authors": doc.get("author_name") or [],
            "publisher": (doc.get("publisher") or [None])[0],
            "isbn": cand_isbn,
            "cover": (OPENLIB_COVER_URL.format(isbn=cand_isbn) if cand_isbn else None),
            "source": "openlibrary-search",
        }
    # Fall back: Google search
    g = google_search(title, author, timeout, cache)
    if g:
        picked = pick_google_volume(g)
        if picked:
            picked["source"] = "google-search"
            return picked
    return None


# ---------- Main check ----------

FIELDS = [
    "id", "title", "author", "publisher", "isbn", "cover_local", "cover_online",
]

STATUS_FIELDS = [
    "status",    # comma-separated flags
    "title_sim", "author_sim",
    "suggested_isbn", "suggested_title", "suggested_author", "suggested_publisher", "suggested_cover", "suggested_source",
]


def load_rows(csv_path: str) -> Tuple[List[dict], List[str]]:
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = [dict(r) for r in reader]
        fieldnames = reader.fieldnames or []
    return rows, fieldnames


def write_report(rows: list[dict], out_path: str) -> None:
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    fieldnames = FIELDS + STATUS_FIELDS
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in fieldnames})


def write_fixed_csv(out_path: str, fieldnames: List[str], rows: List[dict]) -> None:
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in fieldnames})


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default="output/lukas_bibliothek_v1.csv", help="Input catalog CSV")
    ap.add_argument("--report", default="output/validation_report.csv", help="Output report CSV")
    ap.add_argument("--timeout", type=float, default=6.0)
    ap.add_argument("--max-requests", type=int, default=1000)
    ap.add_argument("--cache", default="output/metadata_cache.json")
    ap.add_argument("--apply-safe", action="store_true", help="Apply very safe fixes (missing ISBN only)")
    ap.add_argument("--fixed-out", default="output/lukas_bibliothek_v1.fixed.csv", help="Updated CSV path when applying safe fixes")
    args = ap.parse_args(argv)

    rows, input_fields = load_rows(args.csv)

    # duplicate ISBNs
    isbn_counts = Counter([ (r.get("isbn") or "").strip() for r in rows if r.get("isbn") ])

    cache = Cache(args.cache)
    requests_left = args.max_requests

    report_rows = []
    changed = 0
    for r in rows:
        title = r.get("title") or ""
        author = r.get("author") or ""
        isbn = (r.get("isbn") or "").replace(" ", "").replace("-", "")
        r["isbn"] = isbn
        cover_local = r.get("cover_local") or ""
        cover_online = r.get("cover_online") or ""

        flags = []
        t_sim = None
        a_sim = None

        # Cover quality flags
        if not cover_local and not cover_online:
            flags.append("COVER_MISSING")
        elif os.path.basename(cover_local).lower().startswith("placeholder"):
            flags.append("COVER_PLACEHOLDER")

        # Duplicates
        if isbn and isbn_counts.get(isbn, 0) > 1:
            flags.append("DUPLICATE_ISBN")

        suggested = {
            "isbn": None,
            "title": None,
            "author": None,
            "publisher": None,
            "cover": None,
            "source": None,
        }

        # Validate or infer using online sources (respect request cap)
        if requests_left <= 0:
            flags.append("SKIP_REMOTE")
        else:
            if isbn:
                meta = canonical_from_isbn(isbn, args.timeout, cache)
                requests_left -= 1
                if not meta:
                    flags.append("ISBN_NOT_FOUND")
                else:
                    t_sim = similarity(title, meta.get("title") or "")
                    a_sim = similarity(author, ", ".join(meta.get("authors") or []))
                    if t_sim < 0.5:
                        flags.append("TITLE_MISMATCH")
                    if a_sim < 0.5:
                        flags.append("AUTHOR_MISMATCH")
                    # offer better cover if missing
                    if (not cover_local and not cover_online) and meta.get("cover"):
                        suggested.update({
                            "isbn": meta.get("isbn"),
                            "title": meta.get("title"),
                            "author": ", ".join(meta.get("authors") or []),
                            "publisher": meta.get("publisher"),
                            "cover": meta.get("cover"),
                            "source": meta.get("source")
                        })
            else:
                # No ISBN: try to find one by title+author
                meta = search_by_title_author(title, author, args.timeout, cache)
                requests_left -= 1
                if meta:
                    t_sim = similarity(title, meta.get("title") or "")
                    a_sim = similarity(author, ", ".join(meta.get("authors") or []))
                    if t_sim >= 0.65 and a_sim >= 0.65 and meta.get("isbn"):
                        suggested.update({
                            "isbn": meta.get("isbn"),
                            "title": meta.get("title"),
                            "author": ", ".join(meta.get("authors") or []),
                            "publisher": meta.get("publisher"),
                            "cover": meta.get("cover"),
                            "source": meta.get("source")
                        })
                        # optional safe apply (anchor: title+author)
                        if args.apply_safe and t_sim >= 0.80 and a_sim >= 0.80 and not r.get("isbn"):
                            r["isbn"] = meta.get("isbn")
                            changed += 1
                    else:
                        flags.append("NEED_REVIEW_NO_ISBN")
                else:
                    flags.append("NO_MATCH_BY_TITLE_AUTHOR")

        r_out = {k: r.get(k, "") for k in FIELDS}
        r_out.update({
            "status": ",".join(flags),
            "title_sim": f"{t_sim:.2f}" if t_sim is not None else "",
            "author_sim": f"{a_sim:.2f}" if a_sim is not None else "",
            "suggested_isbn": suggested["isbn"] or "",
            "suggested_title": suggested["title"] or "",
            "suggested_author": suggested["author"] or "",
            "suggested_publisher": suggested["publisher"] or "",
            "suggested_cover": suggested["cover"] or "",
            "suggested_source": suggested["source"] or "",
        })
        report_rows.append(r_out)

    # Save cache and report
    cache.save()
    write_report(report_rows, args.report)

    print(f"Checked {len(rows)} records. Report: {args.report}")
    suspicious = sum(1 for r in report_rows if r.get("status"))
    print(f"Suspicious/flagged rows: {suspicious}")

    if args.apply_safe and changed:
        # Preserve original input field order for the fixed CSV
        out_fields = input_fields or []
        if not out_fields:
            # fallback: reconstruct from first row
            out_fields = list(rows[0].keys()) if rows else []
        write_fixed_csv(args.fixed_out, out_fields, rows)
        print(f"Safe applied: {changed} ISBN(s) added. Updated CSV: {args.fixed_out}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
