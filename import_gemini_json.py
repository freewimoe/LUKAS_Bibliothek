"""
Importiert Gemini-JSON-Buchdaten in die SQLite-Datenbank
Verarbeitet LUKAS_books_*.json Dateien
"""

import json
import sqlite3
import os
from datetime import date
import glob

DB_PATH = "output/lukas_bibliothek_v1.sqlite3"

def import_json_to_db(json_file):
    """Importiert eine JSON-Datei in die Datenbank"""
    
    print(f"\n📖 Verarbeite: {json_file}")
    
    # JSON laden
    with open(json_file, 'r', encoding='utf-8') as f:
        books = json.load(f)
    
    print(f"   {len(books)} Bücher gefunden")
    
    # Datenbank öffnen
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    imported = 0
    skipped = 0
    
    for book in books:
        try:
            # Autor verarbeiten
            autor_name = book.get('Autor', '').strip()
            if autor_name:
                c.execute("SELECT id FROM authors WHERE name=?", (autor_name,))
                row = c.fetchone()
                if row:
                    autor_id = row[0]
                else:
                    c.execute("INSERT INTO authors(name) VALUES(?)", (autor_name,))
                    autor_id = c.lastrowid
            else:
                autor_id = None
            
            # Verlag verarbeiten
            verlag_name = book.get('Verlag', '').strip()
            if verlag_name:
                c.execute("SELECT id FROM publishers WHERE name=?", (verlag_name,))
                row = c.fetchone()
                if row:
                    verlag_id = row[0]
                else:
                    c.execute("INSERT INTO publishers(name) VALUES(?)", (verlag_name,))
                    verlag_id = c.lastrowid
            else:
                verlag_id = None
            
            # Sammlung basierend auf Kategorie
            kategorie = book.get('Kategorie', '')
            collection_id = 1  # Default: Kirche
            if 'Musik' in kategorie or 'Noten' in kategorie:
                collection_id = 2
            elif 'Quartier' in kategorie or 'Sozial' in kategorie:
                collection_id = 3
            elif 'Archiv' in kategorie or 'Geschichte' in kategorie:
                collection_id = 4
            
            # Buch einfügen oder prüfen ob schon vorhanden
            titel = book.get('Titel', '').strip()
            if not titel:
                skipped += 1
                continue
            
            # Prüfe ob Buch bereits existiert (gleicher Titel und Autor)
            if autor_id:
                c.execute("""
                    SELECT id FROM books 
                    WHERE title=? AND author_id=?
                """, (titel, autor_id))
            else:
                c.execute("SELECT id FROM books WHERE title=?", (titel,))
            
            existing = c.fetchone()
            
            if existing:
                book_id = existing[0]
                # Aktualisiere ggf. fehlende Daten
                c.execute("""
                    UPDATE books 
                    SET publisher_id=?, publication_year=?, isbn_13=?, collection_id=?
                    WHERE id=?
                """, (verlag_id, book.get('Erscheinungsjahr'), 
                      book.get('ISBN'), collection_id, book_id))
            else:
                # Neues Buch einfügen
                c.execute("""
                    INSERT INTO books(title, author_id, publisher_id, publication_year, 
                                     isbn_13, collection_id, created_at)
                    VALUES(?,?,?,?,?,?,?)
                """, (titel, autor_id, verlag_id, book.get('Erscheinungsjahr'), 
                      book.get('ISBN'), collection_id, str(date.today())))
                book_id = c.lastrowid
            
            # Exemplar einfügen/aktualisieren
            signatur = book.get('Signatur', '').strip()
            standort = book.get('Standort', '').strip()
            status = book.get('Status', 'Vorhanden')
            notizen = book.get('Notizen', '')
            
            # Prüfe ob Exemplar mit dieser Signatur schon existiert
            if signatur:
                c.execute("SELECT id FROM copies WHERE signatur=?", (signatur,))
                existing_copy = c.fetchone()
                
                if existing_copy:
                    # Aktualisiere bestehendes Exemplar
                    c.execute("""
                        UPDATE copies 
                        SET book_id=?, regal=?, zustand=?, status_digitalisierung=?
                        WHERE id=?
                    """, (book_id, standort, status, 'Gemini-Import', existing_copy[0]))
                else:
                    # Neues Exemplar
                    c.execute("""
                        INSERT INTO copies(book_id, signatur, regal, zustand, 
                                         status_digitalisierung, created_at)
                        VALUES(?,?,?,?,?,?)
                    """, (book_id, signatur, standort, status, 
                          'Gemini-Import', str(date.today())))
            else:
                # Kein Signatur, erstelle trotzdem Exemplar
                c.execute("""
                    INSERT INTO copies(book_id, regal, zustand, 
                                     status_digitalisierung, created_at)
                    VALUES(?,?,?,?,?)
                """, (book_id, standort, status, 'Gemini-Import', str(date.today())))
            
            imported += 1
            
        except Exception as e:
            print(f"   ⚠️ Fehler bei Buch '{book.get('Titel', 'UNBEKANNT')}': {e}")
            skipped += 1
            continue
    
    conn.commit()
    conn.close()
    
    print(f"   ✅ Importiert: {imported}")
    print(f"   ⚠️ Übersprungen: {skipped}")
    
    return imported, skipped

def main():
    """Importiert alle JSON-Dateien"""
    
    print("="*70)
    print("📚 GEMINI JSON-IMPORT IN LUKAS-BIBLIOTHEK")
    print("="*70)
    
    # Finde alle JSON-Dateien
    json_files = sorted(glob.glob("LUKAS_books_*.json"))
    
    if not json_files:
        print("\n❌ Keine LUKAS_books_*.json Dateien gefunden!")
        print("   Bitte JSON-Dateien von Gemini speichern als:")
        print("   - LUKAS_books_01.json")
        print("   - LUKAS_books_02.json")
        print("   - usw.")
        return
    
    print(f"\n📁 {len(json_files)} JSON-Datei(en) gefunden:")
    for f in json_files:
        print(f"   - {f}")
    
    # Datenbank neu erstellen?
    answer = input("\n⚠️ Datenbank neu erstellen? (j/n): ").strip().lower()
    if answer == 'j':
        print("\n🔧 Erstelle neue Datenbank...")
        os.system('python create_database.py')
    
    # Alle JSON-Dateien importieren
    total_imported = 0
    total_skipped = 0
    
    for json_file in json_files:
        imported, skipped = import_json_to_db(json_file)
        total_imported += imported
        total_skipped += skipped
    
    print("\n" + "="*70)
    print("✅ IMPORT ABGESCHLOSSEN")
    print("="*70)
    print(f"📚 Gesamt importiert: {total_imported}")
    print(f"⚠️ Gesamt übersprungen: {total_skipped}")
    print("="*70)
    
    # CSV exportieren
    print("\n📊 Exportiere zu CSV...")
    os.system('python export_to_csv.py')
    
    print("\n🌐 Webseite testen:")
    print("   cd output")
    print("   python -m http.server 8000")
    print("   http://localhost:8000/LukasBibliothek.html")

if __name__ == "__main__":
    main()
