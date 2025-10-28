/* =====================================================
   LUKAS-BIBLIOTHEK – FUNKTIONSLOGIK
   Autor: Friedrich-Wilhelm Möller · Version 1.0 Beta (2025-11)
   ===================================================== */

/**
 * Lädt die CSV-Datei, zeigt Banner und Tabelle,
 * ermöglicht Live-Suche und Fallback für Coverbilder.
 */

function hasManyNoiseChars(s){
  const noise = s.match(/[\\\/{}|<>+=_*^~`§°µ•·“”„›‹«»¤¢£¥©®™¶…–—]/g);
  return noise && noise.length >= 3;
}

function vowelCount(s){
  const m = (s.match(/[aeiouyäöüAEIOUYÄÖÜ]/g) || []).length;
  return m;
}

function punctRatio(s){
  if(!s) return 0;
  const puncts = s.replace(/[A-Za-zÄÖÜäöüß0-9\s,.'\-()!?]/g,'');
  return puncts.length / s.length;
}

function looksGibberish(s){
  if(!s) return true;
  s = String(s).trim();
  if(!s) return true;
  let score = 0;
  if(s.length >= 12 && vowelCount(s) <= 1) score++;
  if(punctRatio(s) > 0.22) score++;
  if(/\\x/.test(s) || (s.match(/\\/g)||[]).length >= 2) score++;
  if(hasManyNoiseChars(s)) score++;
  const tokens = s.split(/\s+/).filter(Boolean);
  if(tokens.length){
    const oneLetters = tokens.filter(t => t.length === 1).length;
    if(oneLetters / tokens.length >= 0.5) score++;
  }
  return score >= 2;
}

function keepRow(r){
  const status = (r.status_digitalisierung||'').toLowerCase();
  const verified = status.includes('gemini') || (status.includes('online') && status.includes('verifiz'));
  const hasIsbn = !!(r.isbn && String(r.isbn).trim());
  if(verified || hasIsbn) return true;
  const tlen = (r.title||'').trim().length;
  const alen = (r.author||'').trim().length;
  // sehr kurze Felder ohne Verifizierung oder ISBN aussortieren
  if(tlen < 4 && alen < 4) return false;
  const tG = looksGibberish(r.title);
  const aG = !r.author || looksGibberish(r.author);
  // Behalten, wenn nicht eindeutiger Müll
  return !(tG && aG);
}

async function init(){
  const isHttp = (location.protocol === 'http:' || location.protocol === 'https:');
  try {
    if (!isHttp){
      // Offline-Modus: Nutzer muss CSV per Dateiauswahl bereitstellen
      document.getElementById('offline-box').style.display = 'block';
      const tbody = document.querySelector('#books tbody');
      tbody.innerHTML = '<tr><td colspan="6">🔒 Offline-Modus aktiv. Bitte wählen Sie oben die CSV-Datei aus.</td></tr>';
      const fileInput = document.getElementById('csvFile');
      fileInput.addEventListener('change', e => {
        const file = e.target.files && e.target.files[0];
        if(!file) return;
        Papa.parse(file, {
          header: true,
          complete: (res) => {
            const all = (res.data || []).filter(r => r.title || r.author);
            const data = all.filter(keepRow);
            renderBanner(data);
            renderTable(data);
            bindSearch(data);
          },
          error: (err) => {
            console.error('CSV Parse Error', err);
          }
        });
      });
      return;
    }

    // Online (HTTP/S): CSV via fetch
    const text = await fetch('lukas_bibliothek_v1.csv').then(r=>r.text());
    const all = Papa.parse(text,{header:true}).data.filter(r => r.title || r.author);
    const data = all.filter(keepRow);
    renderBanner(data);
    renderTable(data);
    bindSearch(data);

  } catch (err) {
    console.error('Fehler beim Laden der CSV:', err);
    const tbody = document.querySelector('#books tbody');
    tbody.innerHTML = '<tr><td colspan="6">⚠️ Daten konnten nicht geladen werden.</td></tr>';
  }
}

function bindSearch(data){
  document.getElementById('search').addEventListener('input', e => {
    const term = e.target.value.toLowerCase();
    const filtered = data.filter(r =>
      (r.title || '').toLowerCase().includes(term) ||
      (r.author || '').toLowerCase().includes(term) ||
      (r.signatur || '').toLowerCase().includes(term)
    );
    renderTable(filtered);
  });
}

/**
 * Zeigt 8 zufällige Buchrücken als Banner oben.
 */
function renderBanner(data){
  const banner = document.getElementById('banner');
  banner.innerHTML = '';
  const sample = data.sort(()=>.5-Math.random()).slice(0,8);
  sample.forEach(r => {
    const img = document.createElement('img');
    img.src = r.cover_local || r.cover_online || 'placeholder.jpg';
    img.alt = r.title || 'Buchcover';
    banner.appendChild(img);
  });
}

/**
 * Baut die Tabelle aus den CSV-Daten auf.
 */
function renderTable(rows){
  const body = document.querySelector('#books tbody');
  body.innerHTML = '';

  rows.forEach(r => {
    const tr = document.createElement('tr');
    const cover = r.cover_local || r.cover_online || 'placeholder.jpg';
    tr.innerHTML = `
      <td data-label="Cover"><img class="thumb" src="${cover}" alt="Cover"></td>
      <td data-label="Autor">${r.author || ''}</td>
      <td data-label="Titel">${r.title || ''}</td>
      <td data-label="Signatur">${r.signatur || ''}</td>
      <td data-label="Regal">${r.regal || ''}</td>
      <td data-label="Status">${r.status_digitalisierung || ''}</td>
    `;
    body.appendChild(tr);
  });
}

// Initialisierung beim Laden der Seite
init();
