"""
Smart OCR mit Online-Buchsuche
Erkennt Text auf Buchrücken und sucht online nach Metadaten
"""

import os
import re
import sqlite3
import time
from datetime import date
from PIL import Image
import pytesseract
import requests

# ========== KONFIGURATION ==========
DB_PATH = "output/lukas_bibliothek_v1.sqlite3"
PHOTO_PATH = "fotos/"
LANG = "deu"
pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

# ========== HILFSFUNKTIONEN ==========

def extract_text_from_image(image_path):
    """OCR auf Bild"""
    img = Image.open(image_path)
    text = pytesseract.image_to_string(img, lang=LANG)
    return text.strip()

def clean_text_for_search(text):
    """Extrahiert sinnvolle Wörter für die Suche"""
    # Entferne Sonderzeichen und kurze Fragmente
    words = re.findall(r'\b[A-ZÄÖÜa-zäöüß]{3,}\b', text)
    # Nehme die längsten/wichtigsten Wörter
    words = sorted(set(words), key=len, reverse=True)[:5]
    return ' '.join(words)

def search_openlibrary(search_query):
    """Sucht in der Open Library API"""
    if not search_query.strip():
        return []
    
    url = "https://openlibrary.org/search.json"
    params = {
        'q': search_query,
        'limit': 5,
        'language': 'ger'
    }
    
    try:
        response = requests.get(url, params=params, timeout=10)
        if response.status_code == 200:
            data = response.json()
            results = []
            
            for doc in data.get('docs', [])[:5]:
                result = {
                    'title': doc.get('title', ''),
                    'author': ', '.join(doc.get('author_name', [])),
                    'publisher': ', '.join(doc.get('publisher', []))[:100] if doc.get('publisher') else '',
                    'year': doc.get('first_publish_year', ''),
                    'isbn': doc.get('isbn', [''])[0] if doc.get('isbn') else '',
                    'cover_url': f"https://covers.openlibrary.org/b/id/{doc.get('cover_i', '')}-M.jpg" if doc.get('cover_i') else ''
                }
                results.append(result)
            
            return results
    except Exception as e:
        print(f"   ⚠️ API-Fehler: {e}")
    
    return []

def search_google_books(search_query):
    """Sucht in der Google Books API (kein API-Key nötig für Basis-Suche)"""
    if not search_query.strip():
        return []
    
    url = "https://www.googleapis.com/books/v1/volumes"
    params = {
        'q': search_query,
        'maxResults': 5,
        'langRestrict': 'de'
    }
    
    try:
        response = requests.get(url, params=params, timeout=10)
        if response.status_code == 200:
            data = response.json()
            results = []
            
            for item in data.get('items', [])[:5]:
                vol = item.get('volumeInfo', {})
                result = {
                    'title': vol.get('title', ''),
                    'author': ', '.join(vol.get('authors', [])),
                    'publisher': vol.get('publisher', ''),
                    'year': vol.get('publishedDate', '')[:4] if vol.get('publishedDate') else '',
                    'isbn': next((id['identifier'] for id in vol.get('industryIdentifiers', []) 
                                 if id['type'] in ['ISBN_13', 'ISBN_10']), ''),
                    'cover_url': vol.get('imageLinks', {}).get('thumbnail', '')
                }
                results.append(result)
            
            return results
    except Exception as e:
        print(f"   ⚠️ Google Books Fehler: {e}")
    
    return []

def save_book_to_db(book_data, photo_ref, signatur=""):
    """Speichert Buch in Datenbank"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    # Autor suchen/anlegen
    author_name = book_data['author']
    if author_name:
        c.execute("SELECT id FROM authors WHERE name=?", (author_name,))
        row = c.fetchone()
        if row:
            author_id = row[0]
        else:
            c.execute("INSERT INTO authors(name) VALUES(?)", (author_name,))
            author_id = c.lastrowid
    else:
        author_id = None
    
    # Verlag suchen/anlegen
    publisher_name = book_data['publisher']
    if publisher_name:
        c.execute("SELECT id FROM publishers WHERE name=?", (publisher_name,))
        row = c.fetchone()
        if row:
            publisher_id = row[0]
        else:
            c.execute("INSERT INTO publishers(name) VALUES(?)", (publisher_name,))
            publisher_id = c.lastrowid
    else:
        publisher_id = None
    
    # Buch anlegen
    c.execute("""
        INSERT INTO books(title, author_id, publisher_id, publication_year, isbn_13)
        VALUES(?,?,?,?,?)
    """, (book_data['title'], author_id, publisher_id, book_data['year'], book_data['isbn']))
    book_id = c.lastrowid
    
    # Exemplar anlegen
    c.execute("""
        INSERT INTO copies(book_id, signatur, zustand, status_digitalisierung, 
                          cover_local, cover_online, photo_ref, created_at)
        VALUES (?,?,?,?,?,?,?,?)
    """, (book_id, signatur, "gut", "Online verifiziert", "", book_data['cover_url'], 
          photo_ref, str(date.today())))
    
    conn.commit()
    conn.close()

def process_photo_interactive(image_path, image_name):
    """Verarbeitet ein Foto interaktiv mit Benutzer-Feedback"""
    print(f"\n{'='*70}")
    print(f"📸 Bild: {image_name}")
    print(f"{'='*70}")
    
    # 1. OCR
    print("🔍 Führe OCR durch...")
    ocr_text = extract_text_from_image(image_path)
    search_query = clean_text_for_search(ocr_text)
    
    print(f"   Erkannter Text: {ocr_text[:100]}...")
    print(f"   Suchbegriffe: {search_query}")
    
    if not search_query:
        print("   ⚠️ Kein Text erkannt - Überspringen")
        return False
    
    # 2. Online-Suche
    print("\n🌐 Suche online nach Buchdaten...")
    
    # Erst Google Books (oft besser für deutsche Bücher)
    results = search_google_books(search_query)
    if not results:
        # Fallback: Open Library
        results = search_openlibrary(search_query)
    
    if not results:
        print("   ❌ Keine Treffer gefunden")
        print("\n💡 Möchten Sie manuell suchen? (Titel eingeben oder Enter zum Überspringen)")
        manual = input("   → ").strip()
        if manual:
            results = search_google_books(manual)
            if not results:
                results = search_openlibrary(manual)
    
    if not results:
        print("   → Übersprungen\n")
        return False
    
    # 3. Ergebnisse anzeigen
    print(f"\n📚 {len(results)} Treffer gefunden:")
    print()
    for i, book in enumerate(results, 1):
        print(f"   [{i}] {book['title']}")
        print(f"       Autor: {book['author']}")
        print(f"       Verlag: {book['publisher']} ({book['year']})")
        print(f"       ISBN: {book['isbn']}")
        print()
    
    # 4. Benutzer-Auswahl
    print("Welches Buch ist es? (1-5, oder Enter zum Überspringen)")
    choice = input("→ ").strip()
    
    if choice.isdigit() and 1 <= int(choice) <= len(results):
        selected = results[int(choice) - 1]
        
        # Signatur erfragen
        print("\nSignatur (z.B. 'Mar', 'Fri') oder Enter wenn unbekannt:")
        signatur = input("→ ").strip()
        
        # Speichern
        save_book_to_db(selected, image_path, signatur)
        print(f"✅ Gespeichert: {selected['title']} von {selected['author']}")
        return True
    else:
        print("   → Übersprungen")
        return False

def main():
    """Hauptprogramm"""
    print("="*70)
    print("🔍 SMART OCR MIT ONLINE-BUCHSUCHE")
    print("="*70)
    print("\nDieses Tool:")
    print("• Scannt Buchrücken-Fotos mit OCR")
    print("• Sucht automatisch in Google Books & Open Library")
    print("• Zeigt Ihnen Vorschläge")
    print("• Sie wählen das richtige Buch aus")
    print("• Vollständige Metadaten werden gespeichert")
    print("\nDrücken Sie Strg+C zum Beenden")
    print("="*70)
    
    # Datenbank neu erstellen
    answer = input("\n⚠️ Datenbank neu erstellen? (j/n): ").strip().lower()
    if answer == 'j':
        os.system('python create_database.py')
    
    # Alle Bilder
    images = sorted([f for f in os.listdir(PHOTO_PATH) 
                    if f.lower().endswith(('.jpg', '.jpeg', '.png'))])
    
    print(f"\n📸 {len(images)} Bilder gefunden\n")
    
    processed = 0
    saved = 0
    
    for img_name in images:
        img_path = os.path.join(PHOTO_PATH, img_name)
        
        try:
            if process_photo_interactive(img_path, img_name):
                saved += 1
            processed += 1
            
            # Höfliche Pause zwischen API-Aufrufen
            time.sleep(1)
            
        except KeyboardInterrupt:
            print("\n\n⚠️ Abbruch durch Benutzer")
            break
        except Exception as e:
            print(f"   ❌ Fehler: {e}")
            continue
    
    print("\n" + "="*70)
    print(f"✅ Fertig!")
    print(f"   Verarbeitet: {processed}/{len(images)}")
    print(f"   Gespeichert: {saved}")
    print("="*70)
    
    # CSV exportieren
    print("\n📊 Exportiere zu CSV...")
    os.system('python export_to_csv.py')

if __name__ == "__main__":
    main()
