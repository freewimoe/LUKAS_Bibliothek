/* =====================================================
   LUKAS-BIBLIOTHEK – FUNKTIONSLOGIK
   Autor: Friedrich-Wilhelm Möller · Version 1.0 Beta (2025-11)
   ===================================================== */

/**
 * Lädt die CSV-Datei, zeigt Banner und Tabelle,
 * ermöglicht Live-Suche und Fallback für Coverbilder.
 */

function hasManyNoiseChars(s){
  const noise = s.match(/[\\/{}|<>+=_*^~`§°µ•·“”„›‹«»¤¢£¥©®™¶…–—]/g);
  return noise && noise.length >= 3;
}

function vowelCount(s){
  const m = (s.match(/[aeiouyäöüAEIOUYÄÖÜ]/g) || []).length;
  return m;
}

function punctRatio(s){
  if(!s) return 0;
  const punctsCount = (s.match(/[^A-Za-zÄÖÜäöüß0-9\s,.'\-()!?]/g) || []).length;
  return punctsCount / s.length;
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

function init(){
  const isHttp = (location.protocol === 'http:' || location.protocol === 'https:');
  loadCollapsedState();
  if (!isHttp){
    // Offline-Modus: Nutzer muss CSV per Dateiauswahl bereitstellen
  document.getElementById('offline-box').style.display = 'block';
  const tbody = document.querySelector('#books tbody');
  tbody.innerHTML = '<tr><td colspan="7">🔒 Offline-Modus aktiv. Bitte wählen Sie oben die CSV-Datei aus.</td></tr>';
    const fileInput = document.getElementById('csvFile');
    fileInput.addEventListener('change', e => {
  const file = e.target?.files?.[0];
      if(!file) return;
      Papa.parse(file, {
        header: true,
        complete: (res) => {
          const all = (res.data || []).filter(r => r.title || r.author);
          const data = all.filter(keepRow);
          setupControls(data);
          renderBanner(data);
          applyFiltersAndRender();
          applyDeepLink(data);
          globalThis.addEventListener('hashchange', ()=> applyDeepLink(data));
        },
        error: (err) => {
          console.error('CSV Parse Error', err);
        }
      });
    });
    return;
  }

  // Online (HTTP/S): CSV via fetch
  fetch('lukas_bibliothek_v1.csv')
    .then(r => r.text())
    .then(text => {
      const all = Papa.parse(text,{header:true}).data.filter(r => r.title || r.author);
      const data = all.filter(keepRow);
      renderBanner(data);
      setupControls(data);
      applyFiltersAndRender();
      applyDeepLink(data);
  globalThis.addEventListener('hashchange', ()=> applyDeepLink(data));
    })
    .catch(err => {
      console.error('Fehler beim Laden der CSV:', err);
      const tbody = document.querySelector('#books tbody');
      tbody.innerHTML = '<tr><td colspan="7">⚠️ Daten konnten nicht geladen werden.</td></tr>';
    });
}

let ORIG_DATA = [];
let CURRENT_GROUP = 'none';
let CURRENT_SORT = 'quality';
let ONLY_COVER = false;
let ONLY_DESC = false;
const COLLAPSED_GROUPS = new Set();
const STORAGE_KEY_COLLAPSE = 'lukas_bib_collapsed_groups_v1';
let LAST_GROUP = 'none';

function loadCollapsedState(){
  try {
    const raw = globalThis.localStorage?.getItem(STORAGE_KEY_COLLAPSE);
    if (!raw) return;
    const arr = JSON.parse(raw);
    if (Array.isArray(arr)){
      COLLAPSED_GROUPS.clear();
      for (const k of arr){ COLLAPSED_GROUPS.add(String(k)); }
    }
  } catch(e){ console.warn('loadCollapsedState failed', e); }
}
function saveCollapsedState(){
  try {
    const arr = Array.from(COLLAPSED_GROUPS);
    globalThis.localStorage?.setItem(STORAGE_KEY_COLLAPSE, JSON.stringify(arr));
  } catch(e){ console.warn('saveCollapsedState failed', e); }
}

function formatAuthorDisplay(raw){
  if(!raw) return '';
  let s = String(raw).trim();
  // unify separators for multiple authors
  s = s.replaceAll(/\s+und\s+/gi, ' | ')
    .replaceAll(/\s*&\s*/g, ' | ')
    .replaceAll(/\s*;\s*/g, ' | ')
    .replaceAll(/\s*\/\s*/g, ' | ');
  const parts = s.split('|').map(p => p.trim()).filter(Boolean);
  const fmt = parts.map(name => {
    if (!name) return '';
    if (/,/.test(name)) return name; // already "Nachname, Vorname"
    const tokens = name.split(/\s+/).filter(Boolean);
    if (tokens.length >= 2){
      const last = tokens.pop();
      const first = tokens.join(' ');
      return `${last}, ${first}`;
    }
    return name;
  });
  return fmt.join(' · ');
}
function authorSortKey(r){
  const d = r._author_display || r.author || '';
  const first = String(d).split(' · ')[0] || '';
  return first.toLowerCase();
}
function qualityScore(r){
  let s = 0;
  if ((r.description||'').toString().trim()) s += 3;
  if (r.cover_local || r.cover_online) s += 2;
  if ((r.isbn||'').toString().trim()) s += 2;
  if ((r.publisher||'').toString().trim()) s += 1;
  if ((r.year||'').toString().trim()) s += 1;
  if ((r.signatur||'').toString().trim()) s += 0.5;
  return s;
}

function deriveCategory(r){
  const fach = (r.fach||'').toLowerCase();
  const title = (r.title||'').toLowerCase();
  const pub = (r.publisher||'').toLowerCase();
  // 1) direkte Fach-Mappings
  if (/(kinder|jugend|bilderbuch|erstles|märchen)/i.test(fach)) return 'Kinder/Jugend';
  if (/(relig|theo|bibel|kirch)/i.test(fach)) return 'Religion';
  if (/(kunst|kultur|musik|architektur|design|fotografie)/i.test(fach)) return 'Kunst & Kultur';
  if (/(medizin|pflege|anatomie)/i.test(fach)) return 'Medizin';
  if (/(recht|jur|wirtschaft|finanz|bwl|management)/i.test(fach)) return 'Wirtschaft & Recht';
  if (/(schule|lernen|grammatik|deutsch|englisch|franz|mathematik|physik|biologie|chemie)/i.test(fach)) return 'Schule/Lernen';
  if (/(lexikon|sachbuch|geschichte|technik|informatik|ratgeber)/i.test(fach)) return 'Sachbuch';
  if (/(roman|erzählung|thriller|krimi|fantasy|novelle|drama|literatur)/i.test(fach)) return 'Belletristik';
  // 2) Verlags-Indizien Kinder/Jugend
  if (/(arena|ravensburger|carlsen|oetinger|thienemann|dressler|cbj|cbt|dtv junior|beltz|gelberg|usborne|fischer kjb)/i.test(pub)) return 'Kinder/Jugend';
  // 3) Titel-Schlüsselwörter
  if (/(hexe\s?lilli|olchis|conni|leselöwen|bibi|benjamin|wimmel|pony|abenteuer|erstles)/i.test(title)) return 'Kinder/Jugend';
  if (/(thriller|krimi|mord|detektiv)/i.test(title)) return 'Belletristik';
  if (/(fantasy|zauber|drachen|magie|science fiction|sci[- ]?fi)/i.test(title)) return 'Belletristik';
  if (/(lexikon|atlas|handbuch|ratgeber|geschichte|technik|informatik|biologie|physik|chemie)/i.test(title)) return 'Sachbuch';
  if (/(bibel|jesus|christ|kirche|theolog)/i.test(title)) return 'Religion';
  if (/(lernen|grammatik|arbeitsheft|übung|schul|abi)/i.test(title)) return 'Schule/Lernen';
  // 4) Fallback
  return 'Sonstiges';
}

function setupControls(data){
  // enrich data with author display/sort helpers
  ORIG_DATA = data.map(r => ({
    ...r,
    _author_display: formatAuthorDisplay(r.author),
    _category: deriveCategory(r)
  }));
  LAST_GROUP = CURRENT_GROUP;
  const search = document.getElementById('search');
  const gb = document.getElementById('groupBy');
  const sb = document.getElementById('sortBy');
  const oc = document.getElementById('onlyCover');
  const od = document.getElementById('onlyDesc');
  const gbtnWrap = document.getElementById('groupButtons');
  if (search) search.addEventListener('input', ()=> applyFiltersAndRender());
  if (gb) gb.addEventListener('change', ()=> { CURRENT_GROUP = gb.value; applyFiltersAndRender(); });
  if (sb){
    sb.value = CURRENT_SORT;
    sb.addEventListener('change', ()=> { CURRENT_SORT = sb.value; applyFiltersAndRender(); });
  }
  if (oc) oc.addEventListener('change', ()=> { ONLY_COVER = oc.checked; applyFiltersAndRender(); });
  if (od) od.addEventListener('change', ()=> { ONLY_DESC = od.checked; applyFiltersAndRender(); });
  if (gbtnWrap){
    const btns = gbtnWrap.querySelectorAll('button[data-group]');
    for (const btn of btns){
      btn.addEventListener('click', ()=> {
        CURRENT_GROUP = btn.dataset.group || 'none';
        if (gb) gb.value = CURRENT_GROUP;
        updateGroupButtons();
        applyFiltersAndRender();
      });
    }
    updateGroupButtons();
  }
}

function applyFiltersAndRender(){
  let rows = ORIG_DATA.slice();
  const term = (document.getElementById('search')?.value || '').toLowerCase();
  if (term){
    rows = rows.filter(r =>
      (r.title || '').toLowerCase().includes(term) ||
      (r.author || '').toLowerCase().includes(term) ||
      (r.signatur || '').toLowerCase().includes(term) ||
      (r.publisher || '').toLowerCase().includes(term) ||
      (r.description || '').toLowerCase().includes(term)
    );
  }
  if (ONLY_COVER){ rows = rows.filter(r => r.cover_local || r.cover_online); }
  if (ONLY_DESC){ rows = rows.filter(r => (r.description||'').toString().trim().length > 0); }
  const key = CURRENT_SORT || 'quality';
  if (key === 'author'){
    rows.sort((a,b)=> authorSortKey(a).localeCompare(authorSortKey(b), 'de', {numeric:true, sensitivity:'base'}));
  } else if (key === 'year'){
    rows.sort((a,b)=> String(a.year||'').localeCompare(String(b.year||''), 'de', {numeric:true, sensitivity:'base'}));
  } else if (key === 'title'){
    rows.sort((a,b)=> String(a.title||'').localeCompare(String(b.title||''), 'de', {numeric:true, sensitivity:'base'}));
  } else if (key === 'signatur'){
    rows.sort((a,b)=> String(a.signatur||'').localeCompare(String(b.signatur||''), 'de', {numeric:true, sensitivity:'base'}));
  } else if (key === 'quality'){
    rows.sort((a,b)=> {
      const dq = qualityScore(b) - qualityScore(a);
      if (dq) return dq;
      return String(a.title||'').localeCompare(String(b.title||''), 'de', {numeric:true, sensitivity:'base'});
    });
  } else {
    rows.sort((a,b)=> String(a[key]||'').localeCompare(String(b[key]||''), 'de', {numeric:true, sensitivity:'base'}));
  }
  const groupingChanged = (CURRENT_GROUP !== LAST_GROUP);
  renderTable(rows, CURRENT_GROUP, { initialCollapse: groupingChanged });
  LAST_GROUP = CURRENT_GROUP;
}

function updateGroupButtons(){
  const gbtnWrap = document.getElementById('groupButtons');
  if (!gbtnWrap) return;
  const btns = gbtnWrap.querySelectorAll('button[data-group]');
  for (const btn of btns){
    const val = btn.dataset.group || 'none';
    if (val === CURRENT_GROUP) btn.classList.add('active'); else btn.classList.remove('active');
  }
}

/**
 * Zeigt 8 zufällige Buchrücken als Banner oben.
 */
function renderBanner(data){
  const banner = document.getElementById('banner');
  banner.innerHTML = '';
  const sample = data.sort(()=>.5-Math.random()).slice(0,8);
  for (const r of sample){
    const img = document.createElement('img');
    img.src = r.cover_local || r.cover_online || 'placeholder.jpg';
    img.alt = r.title || 'Buchcover';
    img.style.cursor = 'pointer';
    img.addEventListener('click', ()=> openDetail(r));
    banner.appendChild(img);
  }
}

/**
 * Baut die Tabelle aus den CSV-Daten auf.
 */
function rowToDetailText(r){
  return `Titel: ${r.title||''}\nAutor: ${r.author||''}\nVerlag: ${r.publisher||''}\nSignatur: ${r.signatur||''}\nRegal: ${r.regal||''}\nStatus: ${r.status_digitalisierung||''}\nJahr: ${r.year||''}\nISBN: ${r.isbn||''}`.trim();
}

function openDetail(r){
  LAST_SCROLL_Y = window.scrollY || 0;
  const modal = document.getElementById('detail-modal');
  const cover = r.cover_local || r.cover_online || 'placeholder.jpg';
  document.getElementById('detail-cover').src = cover;
  document.getElementById('detail-title').textContent = r.title || '';
  document.getElementById('detail-author').textContent = r.author || '';
  document.getElementById('detail-publisher').textContent = r.publisher || '';
  document.getElementById('detail-signatur').textContent = r.signatur || '';
  document.getElementById('detail-regal').textContent = r.regal || '';
  document.getElementById('detail-status').textContent = r.status_digitalisierung || '';
  document.getElementById('detail-year').textContent = r.year || '';
  document.getElementById('detail-isbn').textContent = r.isbn || '';
  const rawDesc = (r.description||'').toString().trim();
  const descEl = document.getElementById('detail-description');
  if (rawDesc){
    descEl.style.display = 'block';
    const limit = 280;
    if (rawDesc.length <= limit){
      descEl.textContent = rawDesc;
    } else {
      const short = rawDesc.slice(0, limit).trim() + ' … ';
      descEl.innerHTML = '';
      const span = document.createElement('span');
      span.textContent = short;
      const btn = document.createElement('button');
      btn.className = 'linklike';
      btn.textContent = 'Mehr anzeigen';
      let expanded = false;
      btn.onclick = () => {
        expanded = !expanded;
        if (expanded){
          span.textContent = rawDesc + ' ';
          btn.textContent = 'Weniger anzeigen';
        } else {
          span.textContent = short;
          btn.textContent = 'Mehr anzeigen';
        }
      };
      descEl.appendChild(span);
      descEl.appendChild(btn);
    }
  } else {
    descEl.textContent = '';
    descEl.style.display = 'none';
  }

  // Reservierung per Mailto
  const TEAM_EMAIL = (globalThis?.LUKAS_TEAM_EMAIL) ?? '';
  const subject = encodeURIComponent(`[Reservierung] ${r.title || 'Buch'} (${r.signatur||'ohne Signatur'})`);
  const body = encodeURIComponent(rowToDetailText(r) + '\n\nMein Name: \nMeine E-Mail/Telefon: ');
  const mailto = `mailto:${TEAM_EMAIL}?subject=${subject}&body=${body}`;
  document.getElementById('reserve-btn').onclick = () => { location.href = mailto; };

  // Kopieren
  document.getElementById('copy-btn').onclick = async () => {
    try {
      await navigator.clipboard.writeText(rowToDetailText(r));
      const hint = document.getElementById('copy-hint');
      hint.style.display = 'block';
      setTimeout(()=> hint.style.display = 'none', 1200);
    } catch(e){
      console.error('Clipboard nicht verfügbar', e);
    }
  };

  // Close handlers
  const closers = modal.querySelectorAll('[data-close]');
  for (const el of closers){
    el.onclick = () => {
      modal.style.display='none';
      location.hash='';
      window.scrollTo({top: LAST_SCROLL_Y, behavior: 'auto'});
    };
  }
  modal.style.display = 'block';
  // Deep-Link setzen
  if (r.id){
    const y = LAST_SCROLL_Y;
    location.hash = `#b=${encodeURIComponent(r.id)}`;
    // Hash-Änderung kann Scrollposition beeinflussen: wiederherstellen
    setTimeout(()=> window.scrollTo({top: y, behavior: 'auto'}), 0);
  }
}

function applyDeepLink(data){
  if (location.hash.startsWith('#b=')){
    const id = decodeURIComponent(location.hash.slice(3));
    const found = data.find(r => String(r.id) === String(id));
    if(found) openDetail(found);
  }
}

function computeCollapsed(groupBy, groupName, size, initialCollapse){
  const key = `${groupBy}::${groupName}`;
  const has = COLLAPSED_GROUPS.has(key);
  if (initialCollapse){
    const shouldCollapse = size >= 4;
    if (shouldCollapse && !has){ COLLAPSED_GROUPS.add(key); return true; }
    if (!shouldCollapse && has){ COLLAPSED_GROUPS.delete(key); return false; }
    return shouldCollapse;
  }
  return has;
}

function renderGroupedRows(rows, groupBy, body, initialCollapse=false){
  const groups = new Map();
  for (const r of rows){
    const g = (groupBy === 'kategorie' ? (r._category || 'Sonstiges') : (r[groupBy] || '—')).toString();
    if(!groups.has(g)) groups.set(g, []);
    groups.get(g).push(r);
  }
  const groupNames = Array.from(groups.keys()).sort((a,b)=> a.localeCompare(b, 'de', {numeric:true, sensitivity:'base'}));
  for (const g of groupNames){
    const gr = document.createElement('tr');
    gr.className = 'group-row';
    const size = groups.get(g).length;
    const key = `${groupBy}::${g}`;
    const collapsed = computeCollapsed(groupBy, g, size, initialCollapse);
    const chev = collapsed ? '▸' : '▾';
  gr.innerHTML = `<td colspan="7"><span class="chev">${chev}</span>${g} – <span style="font-weight:400">${groups.get(g).length} Titel</span></td>`;
    gr.addEventListener('click', ()=>{
      if (COLLAPSED_GROUPS.has(key)) COLLAPSED_GROUPS.delete(key); else COLLAPSED_GROUPS.add(key);
      saveCollapsedState();
      renderTable(rows, groupBy);
    });
    body.appendChild(gr);
    if (!collapsed){
      for (const r of groups.get(g)) appendRow(body, r);
    }
  }
  if (initialCollapse){ saveCollapsedState(); }
}

function renderTable(rows, groupBy, opts){
  const body = document.querySelector('#books tbody');
  body.innerHTML = '';
  if (!groupBy) groupBy = 'none';
  const initialCollapse = !!(opts?.initialCollapse);
  if (groupBy && groupBy !== 'none'){
    renderGroupedRows(rows, groupBy, body, initialCollapse);
  } else {
    for (const r of rows) appendRow(body, r);
  }
}

function appendRow(body, r){
  const tr = document.createElement('tr');
  const cover = r.cover_local || r.cover_online || 'placeholder.jpg';
  tr.innerHTML = `
    <td data-label="Cover"><img class="thumb" src="${cover}" alt="Cover"></td>
    <td data-label="Autor">${r._author_display || r.author || ''}</td>
    <td data-label="Titel">${r.title || ''}</td>
    <td data-label="Verlag">${r.publisher || ''}</td>
    <td data-label="Signatur">${r.signatur || ''}</td>
    <td data-label="Regal">${r.regal || ''}</td>
    <td data-label="Status">${r.status_digitalisierung || ''}</td>
  `;
  tr.style.cursor = 'pointer';
  tr.addEventListener('click', ()=> openDetail(r));
  attachHover(tr, r);
  body.appendChild(tr);
}

// Hover-Karte
let HOVERCARD;
function ensureHoverCard(){
  if (!HOVERCARD){ HOVERCARD = document.getElementById('hover-card'); }
}
function attachHover(tr, r){
  ensureHoverCard();
  const show = (e)=>{
    const cover = r.cover_local || r.cover_online || 'placeholder.jpg';
    const snip = (r.description||'').toString().slice(0,140);
  HOVERCARD.innerHTML = `<div class="hc-body"><img src="${cover}" alt=""><div class="meta"><h4>${r.title||''}</h4><div>${r.author||''}</div><div>${r.publisher||''}</div><div style="color:#666;font-size:.85rem;">${snip}</div></div></div>`;
    HOVERCARD.style.display = 'block';
    positionHover(e);
  };
  const hide = ()=>{ if(HOVERCARD) HOVERCARD.style.display='none'; };
  const move = (e)=> positionHover(e);
  tr.addEventListener('mouseenter', show);
  tr.addEventListener('mousemove', move);
  tr.addEventListener('mouseleave', hide);
}
function positionHover(e){
  if(!HOVERCARD) return;
  const pad = 12;
  let x = e.clientX + pad;
  let y = e.clientY + pad;
  const rect = HOVERCARD.getBoundingClientRect();
  if (x + rect.width > window.innerWidth - 8) x = e.clientX - rect.width - pad;
  if (y + rect.height > window.innerHeight - 8) y = window.innerHeight - rect.height - 8;
  HOVERCARD.style.left = x + 'px';
  HOVERCARD.style.top = y + 'px';
}

// Scroll-Position beim Öffnen/Schließen beibehalten
let LAST_SCROLL_Y = 0;

// Initialisierung beim Laden der Seite
init();
