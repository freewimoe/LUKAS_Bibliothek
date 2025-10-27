/* =====================================================
   LUKAS-BIBLIOTHEK – FUNKTIONSLOGIK
   Autor: Friedrich-Wilhelm Möller · Version 1.0 Beta (2025-11)
   ===================================================== */

/**
 * Lädt die CSV-Datei, zeigt Banner und Tabelle,
 * ermöglicht Live-Suche und Fallback für Coverbilder.
 */

async function init(){
  try {
    const text = await fetch('lukas_bibliothek_v1.csv').then(r=>r.text());
    const data = Papa.parse(text,{header:true}).data.filter(r => r.title || r.author);
    renderBanner(data);
    renderTable(data);

    // Live-Suche
    document.getElementById('search').addEventListener('input', e => {
      const term = e.target.value.toLowerCase();
      const filtered = data.filter(r =>
        (r.title || '').toLowerCase().includes(term) ||
        (r.author || '').toLowerCase().includes(term) ||
        (r.signatur || '').toLowerCase().includes(term)
      );
      renderTable(filtered);
    });

  } catch (err) {
    console.error('Fehler beim Laden der CSV:', err);
    const tbody = document.querySelector('#books tbody');
    tbody.innerHTML = '<tr><td colspan="6">⚠️ Daten konnten nicht geladen werden.</td></tr>';
  }
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
