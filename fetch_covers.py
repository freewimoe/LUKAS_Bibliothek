"""
Fetch and generate book cover thumbnails for LUKAS-Bibliothek
- Tries Open Library Covers API and Google Books
- Saves thumbnails under output/thumbnails/
- Updates copies.cover_local and copies.cover_online
- Creates output/placeholder.jpg if missing
- Re-exports CSV at the end
"""

import os
import re
import io
import sqlite3
from typing import Optional, Tuple

import requests
from requests.exceptions import RequestException
from PIL import Image, ImageDraw, ImageFont

DB_PATH = "output/lukas_bibliothek_v1.sqlite3"
THUMBS_DIR = "output/thumbnails"
PLACEHOLDER_PATH = "output/placeholder.jpg"
THUMB_SIZE = (240, 360)  # WxH
TIMEOUT = 12
HEADERS = {"User-Agent": "LUKAS-Bibliothek/1.0 (+https://github.com/freewimoe/LUKAS_Bibliothek)"}
PLACEHOLDER_REL = "placeholder.jpg"
SQL_UPD_BOTH = "UPDATE copies SET cover_local=?, cover_online=? WHERE id=?"


def ensure_dirs():
    os.makedirs(THUMBS_DIR, exist_ok=True)


def make_placeholder():
    if os.path.exists(PLACEHOLDER_PATH):
        return
    os.makedirs(os.path.dirname(PLACEHOLDER_PATH), exist_ok=True)
    img = Image.new("RGB", THUMB_SIZE, (230, 232, 236))
    d = ImageDraw.Draw(img)
    title = "LUKAS\nBIBLIOTHEK"
    # Use a basic font (system-dependent). Pillow will fallback if truetype not found
    try:
        font = ImageFont.truetype("arial.ttf", 28)
    except Exception:
        font = ImageFont.load_default()
    try:
        # Pillow >= 8 provides multiline_textbbox
        bbox = d.multiline_textbbox((0, 0), title, font=font, spacing=4, align="center")
        w = bbox[2] - bbox[0]
        h = bbox[3] - bbox[1]
    except Exception:
        # Fallback: approximate using single-line bbox repeated
        lines = title.split("\n")
        bboxes = [d.textbbox((0, 0), ln, font=font) for ln in lines]
        w = max(b[2]-b[0] for b in bboxes)
        h = sum(b[3]-b[1] for b in bboxes) + (len(lines)-1)*4
    d.multiline_text(((THUMB_SIZE[0]-w)//2, (THUMB_SIZE[1]-h)//2), title, fill=(60, 65, 80), font=font, align="center", spacing=4)
    d.rectangle([(10, 10), (THUMB_SIZE[0]-10, THUMB_SIZE[1]-10)], outline=(160, 165, 180), width=2)
    img.save(PLACEHOLDER_PATH, format="JPEG", quality=85)


def check_connectivity() -> bool:
    """Quick connectivity/DNS check against cover providers.
    Returns True if at least one provider is reachable, else False.
    """
    endpoints = [
        ("https://openlibrary.org", {}),
        ("https://covers.openlibrary.org", {}),
        ("https://www.googleapis.com", {}),
    ]
    for url, params in endpoints:
        try:
            r = requests.get(url, params=params, timeout=5, headers=HEADERS)
            if r.status_code < 500:
                return True
        except RequestException:
            continue
    return False


def normalize_isbn(isbn: Optional[str]) -> Optional[str]:
    if not isbn:
        return None
    s = re.sub(r"[^0-9Xx]", "", isbn)
    return s or None


def try_openlibrary_by_isbn(isbn: str) -> Optional[str]:
    # Default=false -> 404 if missing
    url = f"https://covers.openlibrary.org/b/isbn/{isbn}-L.jpg?default=false"
    r = requests.get(url, timeout=TIMEOUT, headers=HEADERS)
    if r.status_code == 200 and r.headers.get("content-type", "").startswith("image"):
        return url
    return None


def search_openlibrary(title: str, author: str) -> Optional[str]:
    q = f"{title} {author}".strip()
    if not q:
        return None
    try:
        resp = requests.get("https://openlibrary.org/search.json", params={"q": q, "limit": 5}, timeout=TIMEOUT, headers=HEADERS)
        if resp.status_code == 200:
            js = resp.json()
            for doc in js.get("docs", [])[:5]:
                cover_i = doc.get("cover_i")
                if cover_i:
                    return f"https://covers.openlibrary.org/b/id/{cover_i}-L.jpg"
    except Exception:
        pass
    return None


def search_google_books(title: str, author: str, isbn: Optional[str]) -> Optional[str]:
    params = {"maxResults": 5, "langRestrict": "de"}
    if isbn:
        q = f"isbn:{isbn}"
    else:
        q = f"{title} {author}".strip()
    params["q"] = q
    try:
        resp = requests.get("https://www.googleapis.com/books/v1/volumes", params=params, timeout=TIMEOUT, headers=HEADERS)
        if resp.status_code == 200:
            js = resp.json()
            for item in js.get("items", [])[:5]:
                links = item.get("volumeInfo", {}).get("imageLinks", {})
                url = links.get("thumbnail") or links.get("smallThumbnail")
                if url:
                    # Force https and larger if available
                    url = url.replace("http://", "https://")
                    return url
    except Exception:
        pass
    return None


def download_image(url: str) -> Optional[bytes]:
    try:
        r = requests.get(url, timeout=TIMEOUT, headers=HEADERS)
        if r.status_code == 200 and r.headers.get("content-type", "").startswith("image"):
            return r.content
    except Exception:
        return None
    return None


def to_thumbnail(img_bytes: bytes) -> Image.Image:
    img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
    img.thumbnail(THUMB_SIZE, Image.LANCZOS)
    # pad to exact size with light background
    canvas = Image.new("RGB", THUMB_SIZE, (245, 246, 248))
    x = (THUMB_SIZE[0] - img.width) // 2
    y = (THUMB_SIZE[1] - img.height) // 2
    canvas.paste(img, (x, y))
    return canvas


def save_thumb(img: Image.Image, path: str):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    img.save(path, format="JPEG", quality=85)


def pick_cover_url(title: str, author: str, isbn13: Optional[str], isbn10: Optional[str]) -> Optional[str]:
    for isbn in (normalize_isbn(isbn13), normalize_isbn(isbn10)):
        if isbn:
            url = try_openlibrary_by_isbn(isbn)
            if url:
                return url
            url = search_google_books("", "", isbn)
            if url:
                return url
    # Title/author search
    url = search_openlibrary(title, author)
    if url:
        return url
    return search_google_books(title, author, None)


def main():
    ensure_dirs()
    make_placeholder()

    online = check_connectivity()
    if not online:
        print("🌐 Kein Internet/DNS nicht erreichbar – setze Platzhalter-Cover lokal.")

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # Pull books and copies
    c.execute(
        """
        SELECT b.id, b.title, COALESCE(a.name,''), COALESCE(b.isbn_13,''), COALESCE(b.isbn_10,''),
               c.id, COALESCE(c.cover_local,''), COALESCE(c.cover_online,'')
        FROM books b
        LEFT JOIN authors a ON a.id = b.author_id
        LEFT JOIN copies c ON c.book_id = b.id
        ORDER BY b.id
        """
    )

    rows = c.fetchall()
    total = len(rows)
    downloaded = 0
    updated = 0

    for (book_id, title, author, isbn13, isbn10, copy_id, cover_local, cover_online) in rows:
        # Skip if we already have a valid local cover file
        if cover_local:
            check_path = os.path.join("output", cover_local) if not cover_local.startswith("output/") else cover_local
            if os.path.exists(check_path):
                continue

        if not online:
            # Offline: set placeholder and skip network
            c.execute("UPDATE copies SET cover_local=? WHERE id=?", (PLACEHOLDER_REL, copy_id))
            updated += 1
            continue

        # Online: try providers
        url = pick_cover_url(title or "", author or "", isbn13 or None, isbn10 or None)
        if not url:
            c.execute(SQL_UPD_BOTH, (PLACEHOLDER_REL, cover_online or "", copy_id))
            updated += 1
            continue

        img_bytes = download_image(url)
        if not img_bytes:
            c.execute(SQL_UPD_BOTH, (PLACEHOLDER_REL, cover_online or url, copy_id))
            updated += 1
            continue

        thumb = to_thumbnail(img_bytes)
        local_rel = f"thumbnails/book_{book_id}.jpg"
        local_abs = os.path.join("output", local_rel)
        save_thumb(thumb, local_abs)

        c.execute("UPDATE copies SET cover_local=?, cover_online=? WHERE id=?", (local_rel, url, copy_id))
        downloaded += 1
        updated += 1

    conn.commit()
    conn.close()

    print(f"✅ Cover-Update: {updated} Einträge aktualisiert, {downloaded} Bilder heruntergeladen (von {total}).")
    # Re-export CSV for the website
    os.system('python export_to_csv.py')


if __name__ == "__main__":
    main()
