# 📚 LUKAS-Bibliothek

Eine digitale Bibliotheksverwaltung für das LUKAS-Forum Karlsruhe, entwickelt von Friedrich-Wilhelm Möller.

## 🎯 Projektziel

Digitalisierung und Verwaltung der Bibliotheksbestände des LUKAS-Forums mit:
- **OCR-basierter Erfassung** von Buchrücken-Fotos
- **Online-Buchsuche** (Google Books & Open Library API)
- **Responsive Weboberfläche** zur Buchsuche und -verwaltung
- **SQLite-Datenbank** für strukturierte Datenspeicherung

## 🚀 Features

### 1. Smart OCR mit Online-Suche
- Automatische Texterkennung auf Buchrücken-Fotos
- Intelligente Suche in Google Books und Open Library
- Interaktive Buchauswahl mit vollständigen Metadaten
- Automatischer Download von Cover-Bildern

### 2. Weboberfläche
- Moderne, responsive Bibliotheksansicht
- Live-Suche nach Autor, Titel oder Signatur
- Buchrücken-Banner-Animation
- Mobile-optimiert

### 3. Datenbank
- Relationale SQLite-Struktur
- Tabellen für Bücher, Autoren, Verlage, Exemplare
- Export nach CSV für Web-Integration

## 📁 Projektstruktur

```
LUKAS_Bibliothek/
├── fotos/                          # Buchrücken-Fotos (209 Bilder)
├── output/                         # Web-Ausgabe
│   ├── LukasBibliothek.html       # Hauptseite
│   ├── index.html                 # Startseite
│   ├── bibliothek.js              # JavaScript-Logik
│   ├── style.css                  # Styling
│   ├── papaparse.min.js           # CSV-Parser
│   ├── lukas_bibliothek_v1.csv    # Exportierte Daten
│   ├── lukas_bibliothek_v1.sqlite3 # Datenbank
│   └── thumbnails/                # Cover-Thumbnails
├── create_database.py             # DB-Schema erstellen
├── ocr_lukas_import.py            # Einfaches OCR-Import
├── smart_ocr_with_search.py       # Smart OCR + Online-Suche
├── export_to_csv.py               # DB → CSV Export
└── read_word_doc.py               # Word-Dokumenten-Reader

```

## 🛠️ Installation & Setup

### Voraussetzungen
- Python 3.10+
- Tesseract-OCR (https://github.com/UB-Mannheim/tesseract/wiki)
- Deutsche Tesseract-Sprachdaten (`deu.traineddata`)

### Python-Pakete installieren
```bash
pip install pytesseract pillow opencv-python requests python-docx
```

### Tesseract-Pfad konfigurieren
In den Python-Skripten (falls nötig):
```python
pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
```

## 📖 Verwendung

### 1. Datenbank erstellen
```bash
python create_database.py
```

### 2. Bücher erfassen (Smart OCR)
```bash
python smart_ocr_with_search.py
```
- Geht durch alle Fotos
- Zeigt Online-Suchergebnisse
- Sie wählen das richtige Buch aus
- Vollständige Metadaten werden gespeichert

### 3. Nach CSV exportieren
```bash
python export_to_csv.py
```

### 4. Webseite öffnen
```bash
cd output
python -m http.server 8000
```
Dann öffnen: http://localhost:8000/LukasBibliothek.html

## 🌐 Online-APIs

- **Google Books API**: Buchsuche mit deutschen Metadaten
- **Open Library API**: Alternative/Ergänzung für Buchdaten
- Keine API-Keys erforderlich (Basis-Nutzung)

## 📊 Datenbankstruktur

### Haupttabellen
- `books` - Buchtitel, Metadaten
- `authors` - Autorendaten
- `publishers` - Verlagsinformationen
- `copies` - Physische Exemplare mit Signatur
- `collections` - Sammlungen (Kirche, Musik, Quartier, Archiv)
- `media` - Scans, Fotos, OCR-Texte

### CSV-Export-Format
```csv
id,author,title,signatur,regal,fach,zustand,status,cover,year,language
```

## 🎨 Weboberfläche

- **Responsive Design** (Desktop/Tablet/Mobile)
- **Live-Suche** in allen Feldern
- **Buchrücken-Banner** mit Scroll-Animation
- **Cover-Fallback** für fehlende Bilder

## 📝 Lizenz & Projekt

**Projekt:** Wir für Lukas e. V. · LUKAS-Forum Karlsruhe  
**Version:** 1.0 Beta (November 2025)  
**Entwickler:** Friedrich-Wilhelm Möller  

## 🤝 Beitragen

Dieses Projekt ist für das LUKAS-Forum entwickelt. Verbesserungsvorschläge und Erweiterungen sind willkommen!

## 📧 Kontakt

LUKAS-Forum Karlsruhe  
Wir für Lukas e. V.

---

*Ein digitales Bibliotheksprojekt für das Gemeinwohl* 📚✨
