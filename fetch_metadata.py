"""
Fetch short descriptions and publisher metadata for books.
Sources: Open Library (preferred), Google Books (fallback).
Writes results into books.description and books.publisher_id (creating publishers as needed).
Re-exports CSV afterwards.

Usage:
  python fetch_metadata.py --limit 200 --timeout 6
"""

import argparse
import os
import re
import sqlite3
from typing import Optional, Tuple
import xml.etree.ElementTree as ET

import requests
from requests.exceptions import RequestException

DB_PATH = "output/lukas_bibliothek_v1.sqlite3"
DNB_SRU_BASE = "https://services.dnb.de/sru/dnb"
GOOGLE_API = "https://www.googleapis.com/books/v1/volumes"
HEADERS = {"User-Agent": "LUKAS-Bibliothek/1.0 (+https://github.com/freewimoe/LUKAS_Bibliothek)"}
TIMEOUT_DEFAULT = 8

def clean_text(s: Optional[str]) -> Optional[str]:
    if not s:
        return s
    # Remove simple HTML tags
    s = re.sub(r"<[^>]+>", " ", s)
    # Collapse whitespace
    s = re.sub(r"\s+", " ", s).strip()
    return s


def ensure_schema(conn: sqlite3.Connection):
    c = conn.cursor()
    # add description column if not exists
    c.execute("PRAGMA table_info(books)")
    cols = [r[1] for r in c.fetchall()]
    if "description" not in cols:
        c.execute("ALTER TABLE books ADD COLUMN description TEXT")
        conn.commit()


def normalize_isbn(isbn: Optional[str]) -> Optional[str]:
    if not isbn:
        return None
    s = re.sub(r"[^0-9Xx]", "", isbn)
    return s or None


def pick_first_str(val) -> Optional[str]:
    if val is None:
        return None
    if isinstance(val, list):
        for x in val:
            if isinstance(x, str) and x.strip():
                return x.strip()
        return None
    if isinstance(val, dict) and "value" in val:
        v = val.get("value")
        if isinstance(v, str):
            return v.strip()
    if isinstance(val, str):
        return val.strip()
    return None


def ol_work_or_edition_description(key: str, timeout: float) -> Tuple[Optional[str], Optional[str]]:
    # key like "/works/OL...W" or "/books/OL...M"
    url = f"https://openlibrary.org{key}.json"
    try:
        r = requests.get(url, headers=HEADERS, timeout=timeout)
        if r.status_code == 200:
            js = r.json()
            desc = pick_first_str(js.get("description"))
            pub = pick_first_str(js.get("publishers"))
            return clean_text(desc), clean_text(pub)
    except Exception:
        pass
    return None, None


def from_openlibrary(title: str, author: str, isbn13: Optional[str], isbn10: Optional[str], timeout: float) -> Tuple[Optional[str], Optional[str]]:
    # try via ISBN detail first
    for isbn in (normalize_isbn(isbn13), normalize_isbn(isbn10)):
        if not isbn:
            continue
        try:
            r = requests.get(f"https://openlibrary.org/isbn/{isbn}.json", headers=HEADERS, timeout=timeout)
            if r.status_code == 200:
                js = r.json()
                desc = pick_first_str(js.get("description"))
                pub = pick_first_str(js.get("publishers"))
                if desc or pub:
                    return desc, pub
                # maybe follow works/ or key
                key = js.get("works", [{}])[0].get("key") if js.get("works") else js.get("key")
                if isinstance(key, str):
                    d2, p2 = ol_work_or_edition_description(key, timeout)
                    if d2 or p2:
                        return d2, p2
        except Exception:
            pass

    # fallback: search by title/author
    q = f"{title} {author}".strip()
    if not q:
        return None, None
    try:
        r = requests.get("https://openlibrary.org/search.json", params={"q": q, "limit": 3}, headers=HEADERS, timeout=timeout)
        if r.status_code == 200:
            js = r.json()
            for doc in js.get("docs", [])[:3]:
                key = doc.get("key")  # usually a work key like "/works/OL...W"
                if key:
                    d3, p3 = ol_work_or_edition_description(key, timeout)
                    if d3 or p3:
                        return clean_text(d3), clean_text(p3)
    except Exception:
        pass
    return None, None


def from_google(title: str, author: str, isbn13: Optional[str], isbn10: Optional[str], timeout: float) -> Tuple[Optional[str], Optional[str]]:
    # prefer ISBN query
    for isbn in (normalize_isbn(isbn13), normalize_isbn(isbn10)):
        if not isbn:
            continue
        params = {"q": f"isbn:{isbn}", "maxResults": 3, "langRestrict": "de"}
        try:
            r = requests.get(GOOGLE_API, params=params, headers=HEADERS, timeout=timeout)
            if r.status_code == 200:
                js = r.json()
                for item in js.get("items", [])[:3]:
                    vi = item.get("volumeInfo", {})
                    desc = pick_first_str(vi.get("description"))
                    pub = pick_first_str(vi.get("publisher"))
                    if desc or pub:
                        return clean_text(desc), clean_text(pub)
        except Exception:
            pass
        # Fallback: without langRestrict
        params = {"q": f"isbn:{isbn}", "maxResults": 3}
        try:
            r = requests.get(GOOGLE_API, params=params, headers=HEADERS, timeout=timeout)
            if r.status_code == 200:
                js = r.json()
                for item in js.get("items", [])[:3]:
                    vi = item.get("volumeInfo", {})
                    desc = pick_first_str(vi.get("description"))
                    pub = pick_first_str(vi.get("publisher"))
                    if desc or pub:
                        return clean_text(desc), clean_text(pub)
        except Exception:
            pass
    # fallback title+author
    q = f"{title} {author}".strip()
    if not q:
        return None, None
    params = {"q": q, "maxResults": 3, "langRestrict": "de"}
    try:
        r = requests.get(GOOGLE_API, params=params, headers=HEADERS, timeout=timeout)
        if r.status_code == 200:
            js = r.json()
            for item in js.get("items", [])[:3]:
                vi = item.get("volumeInfo", {})
                desc = pick_first_str(vi.get("description"))
                pub = pick_first_str(vi.get("publisher"))
                if desc or pub:
                    return clean_text(desc), clean_text(pub)
    except Exception:
        pass
    # Fallback without langRestrict
    params = {"q": q, "maxResults": 3}
    try:
        r = requests.get(GOOGLE_API, params=params, headers=HEADERS, timeout=timeout)
        if r.status_code == 200:
            js = r.json()
            for item in js.get("items", [])[:3]:
                vi = item.get("volumeInfo", {})
                desc = pick_first_str(vi.get("description"))
                pub = pick_first_str(vi.get("publisher"))
                if desc or pub:
                    return clean_text(desc), clean_text(pub)
    except Exception:
        pass
    return None, None


def from_dnb(title: str, author: str, isbn13: Optional[str], isbn10: Optional[str], timeout: float) -> Tuple[Optional[str], Optional[str]]:
    """Try Deutsche Nationalbibliothek SRU for German descriptions/publisher.
    Strategy: query by ISBN first (dc schema), then fallback to title+author.
    """
    # (namespaces are inlined in tag names)

    def extract_desc_pub(xml_text: str) -> Tuple[Optional[str], Optional[str]]:
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError:
            return None, None
        # Find first record's DC fields
        # Try multiple possible paths for description/abstract and publisher
        desc = None
        pub = None
        # search all dc:description and dcterms:abstract
        for tag in ["{http://purl.org/dc/elements/1.1/}description", "{http://purl.org/dc/terms/}abstract"]:
            e = root.find(f".//{tag}")
            if e is not None and (e.text or "").strip():
                desc = (e.text or "").strip()
                break
        pe = root.find(".//{http://purl.org/dc/elements/1.1/}publisher")
        if pe is not None and (pe.text or "").strip():
            pub = (pe.text or "").strip()
        return clean_text(desc), clean_text(pub)

    # 1) ISBN query
    for isbn in (normalize_isbn(isbn13), normalize_isbn(isbn10)):
        if not isbn:
            continue
        params = {
            "version": "1.1",
            "operation": "searchRetrieve",
            "recordSchema": "dc",
            "maximumRecords": "3",
            "query": f"isbn={isbn}",
        }
        try:
            r = requests.get(DNB_SRU_BASE, params=params, headers=HEADERS, timeout=timeout)
            if r.status_code == 200 and "<searchRetrieveResponse" in r.text:
                d, p = extract_desc_pub(r.text)
                if d or p:
                    return d, p
        except RequestException:
            pass

    # 2) Title + Author fallback
    query_parts = []
    t = (title or "").strip()
    a = (author or "").strip()
    if t:
        # quote value; SRU supports field tit
        query_parts.append(f'tit="{t}"')
    if a:
        # field per = person (author)
        query_parts.append(f'per="{a}"')
    if not query_parts:
        return None, None
    params = {
        "version": "1.1",
        "operation": "searchRetrieve",
        "recordSchema": "dc",
        "maximumRecords": "3",
        "query": " and ".join(query_parts),
    }
    try:
        r = requests.get(DNB_SRU_BASE, params=params, headers=HEADERS, timeout=timeout)
        if r.status_code == 200 and "<searchRetrieveResponse" in r.text:
            d, p = extract_desc_pub(r.text)
            if d or p:
                return d, p
    except RequestException:
        pass
    return None, None


def upsert_publisher(conn: sqlite3.Connection, name: str) -> int:
    c = conn.cursor()
    c.execute("SELECT id FROM publishers WHERE name = ?", (name,))
    row = c.fetchone()
    if row:
        return row[0]
    c.execute("INSERT INTO publishers(name) VALUES (?)", (name,))
    conn.commit()
    return c.lastrowid


def main():
    parser = argparse.ArgumentParser(description="Fetch descriptions and publisher info")
    parser.add_argument("--limit", type=int, default=200, help="Max number of books to enrich (0 = all)")
    parser.add_argument("--timeout", type=float, default=TIMEOUT_DEFAULT, help="HTTP timeout per request")
    args = parser.parse_args()

    timeout = args.timeout if args.timeout and args.timeout > 0 else TIMEOUT_DEFAULT

    conn = sqlite3.connect(DB_PATH)
    ensure_schema(conn)
    c = conn.cursor()

    # Candidates: missing description OR missing publisher
    c.execute(
        """
        SELECT b.id, COALESCE(b.title,''), COALESCE(a.name,''), COALESCE(b.isbn_13,''), COALESCE(b.isbn_10,''),
               COALESCE(b.description,''), COALESCE(p.name,''), COALESCE(b.publication_year,'')
        FROM books b
        LEFT JOIN authors a ON a.id = b.author_id
        LEFT JOIN publishers p ON p.id = b.publisher_id
        ORDER BY b.id
        """
    )
    rows = c.fetchall()

    updated = 0
    processed = 0
    for (book_id, title, author, isbn13, isbn10, description, publisher_name, year) in rows:
        need_desc = not description.strip()
        need_pub = not publisher_name.strip()
        if not need_desc and not need_pub:
            continue

        processed += 1
        if args.limit and processed > args.limit:
            break

        # Try Open Library first, then DNB (German), then Google
        d, p = from_openlibrary(title, author, isbn13, isbn10, timeout)
        if not d and not p:
            d, p = from_dnb(title, author, isbn13, isbn10, timeout)
        if not d and not p:
            d, p = from_google(title, author, isbn13, isbn10, timeout)

        set_desc = description
        set_pub_id = None

        if need_desc and d:
            set_desc = d
        if need_pub and p:
            set_pub_id = upsert_publisher(conn, p)

        if set_desc != description or set_pub_id is not None:
            if set_pub_id is not None:
                c.execute("UPDATE books SET description=?, publisher_id=? WHERE id=?", (set_desc, set_pub_id, book_id))
            else:
                c.execute("UPDATE books SET description=? WHERE id=?", (set_desc, book_id))
            updated += 1

    conn.commit()
    conn.close()

    print(f"✅ Metadaten-Update: {updated} Bücher aktualisiert (bearbeitet: {processed}).")
    os.system('python export_to_csv.py')


if __name__ == "__main__":
    main()
