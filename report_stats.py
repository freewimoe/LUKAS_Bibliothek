import os
import csv
import sqlite3
import statistics
from collections import Counter, defaultdict

ROOT = os.path.dirname(__file__)
DB = os.path.join(ROOT, "output", "lukas_bibliothek_v1.sqlite3")
CSV_CATALOG = os.path.join(ROOT, "output", "lukas_bibliothek_v1.csv")
CSV_SEGMENTS = os.path.join(ROOT, "output", "fotos_segments.csv")
CSV_BASECAND = os.path.join(ROOT, "output", "fotos_new_candidates.csv")
CSV_ENHANCED = os.path.join(ROOT, "output", "fotos_candidates_matched.csv")

conn = sqlite3.connect(DB)
c = conn.cursor()

# total copies rows
c.execute("SELECT COUNT(*) FROM copies")
copies = c.fetchone()[0]

# local cover set
c.execute("SELECT COUNT(*) FROM copies WHERE COALESCE(cover_local,'') <> ''")
with_local = c.fetchone()[0]

# local cover file exists
c.execute("SELECT COALESCE(cover_local,'') FROM copies WHERE COALESCE(cover_local,'') <> ''")
paths = [r[0] for r in c.fetchall()]
exists = 0
for p in paths:
    check = os.path.join('output', p) if not p.startswith('output/') else p
    if os.path.exists(check):
        exists += 1

# online cover only
c.execute("SELECT COUNT(*) FROM copies WHERE COALESCE(cover_local,'') = '' AND COALESCE(cover_online,'') <> ''")
with_online_only = c.fetchone()[0]

# books with description / publisher
c.execute("SELECT COUNT(*) FROM books")
books = c.fetchone()[0]

c.execute("SELECT COUNT(*) FROM books WHERE COALESCE(description,'') <> ''")
with_desc = c.fetchone()[0]

c.execute("SELECT COUNT(*) FROM books WHERE publisher_id IS NOT NULL")
with_pub = c.fetchone()[0]

print(f"Copies total: {copies}")
print(f"Covers: local-set={with_local} (files-exist={exists}), online-only={with_online_only}")
print(f"Books total: {books}")
print(f"Descriptions: {with_desc}")
print(f"Publishers set: {with_pub}")

# --- Zusatz: Katalog/Autoren/Kategorien aus CSV (fallback und Details) -----------------------

def read_csv(path):
    if not os.path.isfile(path):
        return []
    with open(path, 'r', encoding='utf-8', newline='') as f:
        return list(csv.DictReader(f))

def safe_float(x, default=0.0):
    try:
        return float(x)
    except Exception:
        return default

def csv_catalog_stats(rows):
    total = len(rows)
    authors = [r.get('author','').strip() for r in rows if r.get('author')]
    uniq_authors = set(a for a in authors if a)
    by_author = defaultdict(int)
    for a in authors:
        if a:
            by_author[a] += 1
    regal_vals = [r.get('regal','').strip() for r in rows if r.get('regal')]
    fach_vals = [r.get('fach','').strip() for r in rows if r.get('fach')]
    return {
        'books_total_csv': total,
        'authors_total_csv': len(uniq_authors),
        'titles_per_author_mean_csv': round(statistics.mean(by_author.values()),2) if by_author else 0,
        'titles_per_author_median_csv': statistics.median(by_author.values()) if by_author else 0,
        'regal_distinct_csv': len(set([v for v in regal_vals if v])),
        'fach_distinct_csv': len(set([v for v in fach_vals if v])),
        'regal_top_csv': Counter([v for v in regal_vals if v]).most_common(10),
        'fach_top_csv': Counter([v for v in fach_vals if v]).most_common(10),
    }

def candidate_stats(base_rows, enh_rows, seg_rows):
    status_counts = Counter([(r.get('status') or '').lower() for r in base_rows])
    base_scores = [safe_float(r.get('match_score')) for r in base_rows if r.get('match_score')]
    enh_scores = [safe_float(r.get('match_score')) for r in enh_rows if r.get('match_score')]
    matched_title = sum(1 for r in enh_rows if (r.get('matched_title') or '').strip())
    matched_author = sum(1 for r in enh_rows if (r.get('matched_author') or '').strip())
    matched_publisher = sum(1 for r in enh_rows if (r.get('matched_publisher') or '').strip())
    with_hint = sum(1 for r in seg_rows if (r.get('ocr_title_hint') or '').strip())
    with_text = sum(1 for r in seg_rows if (r.get('ocr_text') or '').strip())
    return {
        'segments_total': len(seg_rows),
        'segments_with_title_hint': with_hint,
        'segments_with_text': with_text,
        'candidates_total': len(base_rows),
        'status_counts': dict(status_counts),
        'base_score_mean': round(statistics.mean(base_scores),3) if base_scores else 0.0,
        'base_score_p50': round(statistics.median(base_scores),3) if base_scores else 0.0,
        'base_score_p90': round(statistics.quantiles(base_scores, n=10)[-1],3) if len(base_scores) >= 10 else 0.0,
        'enh_score_mean': round(statistics.mean(enh_scores),3) if enh_scores else 0.0,
        'enh_matched_title': matched_title,
        'enh_matched_author': matched_author,
        'enh_matched_publisher': matched_publisher,
    }

# Try to fetch authors/categories from DB if such columns exist
try:
    c.execute("PRAGMA table_info(books)")
    cols = {row[1] for row in c.fetchall()}
    if 'author' in cols:
        c.execute("SELECT COUNT(DISTINCT author) FROM books WHERE COALESCE(author,'') <> ''")
        print(f"Authors (distinct, DB): {c.fetchone()[0]}")
        c.execute("SELECT author, COUNT(*) as n FROM books WHERE COALESCE(author,'') <> '' GROUP BY author ORDER BY n DESC LIMIT 10")
        print("Top authors by titles (DB):", c.fetchall())
    if 'regal' in cols:
        c.execute("SELECT COUNT(DISTINCT regal) FROM books WHERE COALESCE(regal,'') <> ''")
        print(f"Regal categories (distinct, DB): {c.fetchone()[0]}")
    if 'fach' in cols:
        c.execute("SELECT COUNT(DISTINCT fach) FROM books WHERE COALESCE(fach,'') <> ''")
        print(f"Fach categories (distinct, DB): {c.fetchone()[0]}")
except Exception as e:
    print("DB extra stats error:", e)

# CSV based stats (author/title/category) and candidate quality
cat_rows = read_csv(CSV_CATALOG)
seg_rows = read_csv(CSV_SEGMENTS)
base_rows = read_csv(CSV_BASECAND)
enh_rows = read_csv(CSV_ENHANCED)

if cat_rows:
    print("\n[CSV Catalog Stats]")
    for k,v in csv_catalog_stats(cat_rows).items():
        print(f"{k}: {v}")

if base_rows or enh_rows:
    print("\n[Photo Candidates / OCR Stats]")
    for k,v in candidate_stats(base_rows, enh_rows, seg_rows).items():
        print(f"{k}: {v}")
