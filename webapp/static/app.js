const state = { page:'search', searchMode:'title', currentManga:null, chapters:[], selected:new Set(), jobs:[], poller:null, settings:null };
const $ = (s) => document.querySelector(s);
const $$ = (s) => [...document.querySelectorAll(s)];

function toast(message){ const el=$('#toast'); el.textContent=message; el.classList.add('show'); clearTimeout(el._t); el._t=setTimeout(()=>el.classList.remove('show'),2600); }
function setBusy(text){ $('#globalStatus').textContent=text; $('#footerState').textContent=text; }
async function api(url, options={}){ const response=await fetch(url,{headers:{'Content-Type':'application/json',...(options.headers||{})},...options}); const body=await response.json().catch(()=>({})); if(!response.ok) throw new Error(body.error||`Erro HTTP ${response.status}`); return body; }

function navigate(page){ state.page=page; $$('.page').forEach(x=>x.classList.toggle('active',x.id===`page-${page}`)); $$('.nav-item').forEach(x=>x.classList.toggle('active',x.dataset.page===page)); if(page==='downloads') refreshDownloads(); if(page==='settings') loadSettings(); }
$$('.nav-item').forEach(btn=>btn.addEventListener('click',()=>{ if(!btn.disabled) navigate(btn.dataset.page); }));

function applyTheme(theme){ document.documentElement.dataset.theme=theme; localStorage.setItem('mangago-theme',theme); $('#themeToggle').textContent=theme==='dark'?'☀':'☾'; }
applyTheme(localStorage.getItem('mangago-theme')||'dark');
$('#themeToggle').addEventListener('click',()=>applyTheme(document.documentElement.dataset.theme==='dark'?'light':'dark'));

$$('.mode-switch button').forEach(btn=>btn.addEventListener('click',()=>{ $$('.mode-switch button').forEach(x=>x.classList.remove('selected')); btn.classList.add('selected'); state.searchMode=btn.dataset.mode; $('#searchInput').placeholder=state.searchMode==='title'?'Digite o nome do mangá…':'Cole a URL do mangá no Mangago…'; $('#searchButton').textContent=state.searchMode==='title'?'Buscar':'Abrir'; }));

$('#searchButton').addEventListener('click', runSearch); $('#searchInput').addEventListener('keydown',e=>{if(e.key==='Enter')runSearch();});
async function runSearch(){ const q=$('#searchInput').value.trim(); if(!q) return toast('Informe um título ou URL.'); setBusy('Consultando…'); $('#searchButton').disabled=true;
  try{ if(state.searchMode==='url'){ await openManga(q); return; } const data=await api(`/api/search?q=${encodeURIComponent(q)}&page=1`); renderResults(data.results); $('#resultsMeta').textContent=`${data.results.length} resultado(s)`; $('#searchHint').textContent=`Busca por “${q}”`; }
  catch(e){toast(e.message);} finally{setBusy('Pronto');$('#searchButton').disabled=false;}
}
function renderResults(results){ const grid=$('#resultsGrid'); if(!results.length){grid.innerHTML='<div class="empty-state"><div class="empty-icon">⌕</div><strong>Nenhum resultado</strong><span>Tente outro título.</span></div>';return;} grid.innerHTML=''; results.forEach(m=>{ const card=document.createElement('article');card.className='result-card';card.innerHTML=`<img class="result-cover" src="${escAttr(m.cover_image_url)}" alt=""><div><h3>${esc(m.title)}</h3><p>${esc(m.author||'Autor não informado')}</p><p>${(m.genres||[]).map(esc).join(' · ')}</p><div class="open">Abrir mangá →</div></div>`;card.addEventListener('click',()=>openManga(m.url));grid.appendChild(card); }); }
async function openManga(url){ setBusy('Carregando mangá…'); try{ const data=await api('/api/manga',{method:'POST',body:JSON.stringify({url})}); state.currentManga=data.manga; state.chapters=data.chapters; state.selected.clear(); renderManga(); $('#mangaNav').disabled=false; navigate('manga'); }catch(e){toast(e.message);}finally{setBusy('Pronto');} }
function renderManga(){ const m=state.currentManga; $('#mangaTitle').textContent=m.title;$('#mangaAuthor').textContent=m.author||'';$('#mangaCover').src=m.cover_image_url||'';$('#mangaSummary').textContent=m.summary||'Sem resumo disponível.';$('#chapterCount').textContent=state.chapters.length;$('#mangaGenres').innerHTML=(m.genres||[]).map(g=>`<span class="chip">${esc(g)}</span>`).join('');$('#rangeEnd').value=state.chapters.length; renderChapterRows(); updateSelectionUI(); }
$('#summaryToggle').addEventListener('click',()=>{const x=$('#mangaSummary');x.classList.toggle('hidden');$('#summaryToggle').textContent=x.classList.contains('hidden')?'Ver resumo':'Ocultar resumo';});
function renderChapterRows(){ const filter=$('#chapterFilter').value.trim().toLowerCase(); const rows=$('#chapterRows');rows.innerHTML=''; state.chapters.forEach((ch,i)=>{ if(filter && !`${ch.number} ${ch.title}`.toLowerCase().includes(filter))return; const tr=document.createElement('tr');tr.innerHTML=`<td><input class="chapter-check" type="checkbox" data-index="${i}" ${state.selected.has(i)?'checked':''}></td><td><b>Ch. ${fmt(ch.number)}</b></td><td>${esc(ch.title||'')}</td>`;rows.appendChild(tr);}); $$('.chapter-check').forEach(c=>c.addEventListener('change',()=>{const i=Number(c.dataset.index);c.checked?state.selected.add(i):state.selected.delete(i);updateSelectionUI();})); }
$('#chapterFilter').addEventListener('input',renderChapterRows); $('#selectAll').addEventListener('click',()=>{state.chapters.forEach((_,i)=>state.selected.add(i));renderChapterRows();updateSelectionUI();}); $('#selectNone').addEventListener('click',()=>{state.selected.clear();renderChapterRows();updateSelectionUI();}); $('#selectRange').addEventListener('click',()=>{const a=Math.max(1,Number($('#rangeStart').value||1)),b=Math.min(state.chapters.length,Number($('#rangeEnd').value||state.chapters.length));for(let i=a-1;i<=b-1;i++)state.selected.add(i);renderChapterRows();updateSelectionUI();});
function updateSelectionUI(){const n=state.selected.size;$('#selectedCount').textContent=n;$('#downloadSelected').disabled=n===0;$('#downloadSummary').textContent=n?`${n} capítulo(s) selecionado(s).`:'Selecione capítulos para baixar.';}
$('#downloadSelected').addEventListener('click',()=>startDownload([...state.selected].map(i=>state.chapters[i]))); $('#downloadAll').addEventListener('click',()=>startDownload(state.chapters));
async function startDownload(chapters){ if(!state.currentManga||!chapters.length)return; setBusy('Iniciando download…'); try{const data=await api('/api/downloads',{method:'POST',body:JSON.stringify({manga:state.currentManga,chapters})});toast('Download iniciado.');navigate('downloads');await refreshDownloads();startPolling();}catch(e){toast(e.message);}finally{setBusy('Pronto');}}

async function refreshDownloads(){ try{state.jobs=await api('/api/downloads');renderDownloads();const active=state.jobs.filter(j=>['queued','running'].includes(j.state)).length;$('#downloadCount').textContent=state.jobs.length;$('#downloadBadge').textContent=active?active:'';if(active)startPolling();}catch(e){console.error(e);} }
function renderDownloads(){const box=$('#downloadsContainer');if(!state.jobs.length){box.innerHTML='<div class="empty-card">Nenhum download iniciado nesta sessão.</div>';return;}box.innerHTML=state.jobs.map(job=>`<article class="download-card"><div class="download-top"><div><h3>${esc(job.manga.title)}</h3><p>${esc(job.message||'')}</p></div><span class="download-state">${stateLabel(job.state)}</span></div><div class="progress-track"><div class="progress-fill" style="width:${job.progress||0}%"></div></div><div class="progress-meta"><span>${job.completed}/${job.total} capítulos</span><span>${job.current_page&&job.total_pages?`Página ${job.current_page}/${job.total_pages}`:`${job.progress||0}%`}</span></div><div class="queue">${(job.chapters||[]).map(r=>`<div class="queue-row"><b>Ch. ${fmt(r.number)}</b><span>${esc(r.title||'')}</span><span class="queue-status ${r.status}">${esc(r.message||r.status)}</span></div>`).join('')}</div></article>`).join('');}
function startPolling(){if(state.poller)return;state.poller=setInterval(async()=>{await refreshDownloads();if(!state.jobs.some(j=>['queued','running'].includes(j.state))){clearInterval(state.poller);state.poller=null;}},1000);}
function stateLabel(s){return ({queued:'Na fila',running:'Em andamento',completed:'Concluído',completed_with_errors:'Concluído com falhas',failed:'Falhou'})[s]||s;}

async function loadSettings(){try{state.settings=await api('/api/settings');$('#downloadLocation').value=state.settings.download_location||'';$('#maxWorkers').value=state.settings.max_workers??3;$('#pageDelay').value=state.settings.page_delay??2;$('#retryCount').value=state.settings.retry_count??3;$('#timeout').value=state.settings.timeout??30;$('#imageFormat').value=state.settings.image_format||'png';$('#keepOriginals').checked=!!state.settings.keep_originals;$$('#formatSegment button').forEach(b=>b.classList.toggle('selected',b.dataset.value===(state.settings.format||'images')));}catch(e){toast(e.message);}}
let saveTimer; function queueSave(){ $('#saveState').textContent='Salvando…';clearTimeout(saveTimer);saveTimer=setTimeout(saveSettings,350);} async function saveSettings(){const format=$('#formatSegment button.selected')?.dataset.value||'images';const payload={download_location:$('#downloadLocation').value.trim(),max_workers:Number($('#maxWorkers').value||3),page_delay:Number($('#pageDelay').value||2),retry_count:Number($('#retryCount').value||3),timeout:Number($('#timeout').value||30),image_format:$('#imageFormat').value,keep_originals:$('#keepOriginals').checked,format};try{state.settings=await api('/api/settings',{method:'PUT',body:JSON.stringify(payload)});$('#saveState').textContent='✓ Alterações salvas';}catch(e){$('#saveState').textContent='Falha ao salvar';toast(e.message);}}
['downloadLocation','maxWorkers','pageDelay','retryCount','timeout','imageFormat','keepOriginals'].forEach(id=>$('#'+id).addEventListener('change',queueSave));$('#downloadLocation').addEventListener('input',queueSave);$$('#formatSegment button').forEach(b=>b.addEventListener('click',()=>{$$('#formatSegment button').forEach(x=>x.classList.remove('selected'));b.classList.add('selected');queueSave();}));
function esc(v){return String(v??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));}function escAttr(v){return esc(v);}function fmt(v){const n=Number(v);return Number.isInteger(n)?n.toFixed(1):String(n);}
refreshDownloads();


/* CHAPTER_TYPE_FILTER_V1
   Adds a chapter-version filter to Web V2.
   Classification:
     Official = title contains "official" (case-insensitive)
     Regular  = every other chapter entry.
   Selection helpers operate only on currently visible rows.
*/
(() => {
  "use strict";

  const normalize = value => (value || "").toString().trim().toLowerCase();

  function classifyRow(row) {
    const cells = row.querySelectorAll("td");
    const title = cells.length ? cells[cells.length - 1].textContent : row.textContent;
    return normalize(title).includes("official") ? "official" : "regular";
  }

  function chapterRows() {
    return [...document.querySelectorAll("table tbody tr")].filter(row => row.querySelector('input[type="checkbox"]'));
  }

  function currentFilter() {
    return document.querySelector(".chapter-version-filter [data-version].is-active")?.dataset.version || "all";
  }

  function applyFilter() {
    const mode = currentFilter();
    chapterRows().forEach(row => {
      const type = classifyRow(row);
      row.dataset.chapterVersion = type;
      row.hidden = mode !== "all" && type !== mode;
    });
    updateVisibleCount();
  }

  function updateVisibleCount() {
    const host = document.querySelector(".chapter-version-filter");
    if (!host) return;
    const visible = chapterRows().filter(row => !row.hidden);
    const official = visible.filter(row => classifyRow(row) === "official").length;
    const regular = visible.length - official;
    const info = host.querySelector(".chapter-version-count");
    if (info) info.textContent = `${visible.length} exibidos`;
    host.dataset.officialVisible = official;
    host.dataset.regularVisible = regular;
  }

  function setFilter(mode) {
    document.querySelectorAll(".chapter-version-filter [data-version]").forEach(btn => {
      const active = btn.dataset.version === mode;
      btn.classList.toggle("is-active", active);
      btn.setAttribute("aria-pressed", active ? "true" : "false");
    });
    applyFilter();
  }

  function addFilter() {
    if (document.querySelector(".chapter-version-filter")) return true;

    const rows = chapterRows();
    if (!rows.length) return false;

    const chapterHeading = [...document.querySelectorAll("h1,h2,h3")].find(
      el => normalize(el.textContent).includes("capítulos") || normalize(el.textContent).includes("chapters")
    );
    const table = rows[0].closest("table");
    const anchor = chapterHeading?.parentElement || table?.parentElement;
    if (!anchor) return false;

    const bar = document.createElement("div");
    bar.className = "chapter-version-filter";
    bar.innerHTML = `
      <div class="chapter-version-filter__label">
        <span>Versão</span>
        <small class="chapter-version-count"></small>
      </div>
      <div class="chapter-version-filter__segments" role="group" aria-label="Filtrar versão do capítulo">
        <button type="button" data-version="all" class="is-active" aria-pressed="true">Todos</button>
        <button type="button" data-version="official" aria-pressed="false">Official</button>
        <button type="button" data-version="regular" aria-pressed="false">Regular</button>
      </div>
    `;

    if (chapterHeading && chapterHeading.nextSibling) {
      chapterHeading.parentElement.insertBefore(bar, chapterHeading.nextSibling);
    } else if (table) {
      table.parentElement.insertBefore(bar, table);
    }

    bar.addEventListener("click", event => {
      const button = event.target.closest("[data-version]");
      if (button) setFilter(button.dataset.version);
    });

    // Make bulk-selection controls respect the active filter.
    document.addEventListener("click", event => {
      const button = event.target.closest("button");
      if (!button || !document.querySelector(".chapter-version-filter")) return;
      const label = normalize(button.textContent);

      if (["todos", "select all"].includes(label)) {
        setTimeout(() => {
          chapterRows().filter(row => row.hidden).forEach(row => {
            const cb = row.querySelector('input[type="checkbox"]');
            if (cb?.checked) {
              cb.checked = false;
              cb.dispatchEvent(new Event("change", {bubbles: true}));
            }
          });
        }, 0);
      }
    }, true);

    applyFilter();
    return true;
  }

  const observer = new MutationObserver(() => {
    if (!document.querySelector(".chapter-version-filter")) addFilter();
    else applyFilter();
  });

  function boot() {
    addFilter();
    observer.observe(document.body, {childList: true, subtree: true});
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot, {once: true});
  } else {
    boot();
  }

  window.MangagoChapterTypeFilter = { classifyRow, applyFilter, setFilter };
})();
