const state = { page:'search', searchMode:'title', currentManga:null, chapters:[], selected:new Set(), jobs:[], poller:null, settings:null, chapterType:'all' };
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

async function shutdownApplication(){
  const button=$('#shutdownButton');
  if(button.disabled)return;

  button.disabled=true;
  button.textContent='Finalizando…';
  setBusy('Finalizando…');

  try{
    await api('/api/shutdown',{
      method:'POST',
      body:JSON.stringify({})
    });

    if(state.poller){
      clearInterval(state.poller);
      state.poller=null;
    }

    $('#globalStatus').textContent='Finalizado';
    $('#footerState').textContent='Aplicação finalizada';
    button.textContent='Finalizado';

    toast('Aplicação finalizada.');

    setTimeout(()=>{
      window.close();

      setTimeout(()=>{
        if(!window.closed){
          document.body.innerHTML=`
            <div style="min-height:100vh;display:grid;place-items:center;font-family:Inter,-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif">
              <div style="text-align:center">
                <h2>Aplicação finalizada</h2>
                <p>O servidor foi encerrado. Esta aba pode ser fechada.</p>
              </div>
            </div>
          `;
        }
      },300);
    },500);
  }catch(e){
    button.disabled=false;
    button.textContent='Finalizar aplicação';
    setBusy('Pronto');
    toast(e.message);
  }
}

$('#shutdownButton').addEventListener('click',shutdownApplication);

$$('.mode-switch button').forEach(btn=>btn.addEventListener('click',()=>{ $$('.mode-switch button').forEach(x=>x.classList.remove('selected')); btn.classList.add('selected'); state.searchMode=btn.dataset.mode; $('#searchInput').placeholder=state.searchMode==='title'?'Digite o nome do mangá…':'Cole a URL do mangá no Mangago…'; $('#searchButton').textContent=state.searchMode==='title'?'Buscar':'Abrir'; }));

$('#searchButton').addEventListener('click', runSearch); $('#searchInput').addEventListener('keydown',e=>{if(e.key==='Enter')runSearch();});
const comixState = {
  chapters: [],
  selected: new Set(),
  source: ''
};

$('#comixDownloadButton').addEventListener('click', startComixDownload);
$('#comixLoadButton').addEventListener('click', loadComixChapters);
$('#comixSelectAll').addEventListener('click', () => {
  visibleComixChapters().forEach(ch => comixState.selected.add(ch.url));
  renderComixChapters();
});
$('#comixSelectNone').addEventListener('click', () => {
  visibleComixChapters().forEach(ch => comixState.selected.delete(ch.url));
  renderComixChapters();
});

function comixChapterNumber(url){
  const m=String(url||'').match(/chapter-([0-9]+(?:\.[0-9]+)?)(?:[/?#]|$)/i);
  return m?Number(m[1]):null;
}

function comixTitleFromUrl(url){
  try{
    const u=new URL(url);
    const slug=(u.pathname.match(/\/title\/([^/]+)/i)||[])[1]||'';
    const parts=slug.split('-').filter(Boolean);
    if(parts.length>1)parts.shift();
    const title=parts.join(' ').replace(/\b\w/g,c=>c.toUpperCase());
    return title||'Comix';
  }catch{
    return 'Comix';
  }
}

function validComixTitleUrl(url){
  try{
    const parsed=new URL(url);
    return ['comix.to','www.comix.to'].includes(parsed.hostname.toLowerCase())
      && /^\/title\/[^/]+\/?$/i.test(parsed.pathname);
  }catch{
    return false;
  }
}

function comixUrls(){
  return [...new Set(
    $('#comixUrl').value
      .split(/\r?\n/)
      .map(v=>v.trim())
      .filter(Boolean)
  )];
}

function validComixChapterUrl(url){
  try{
    const parsed=new URL(url);
    return ['comix.to','www.comix.to'].includes(parsed.hostname.toLowerCase())
      && parsed.pathname.includes('/title/')
      && parsed.pathname.toLowerCase().includes('chapter-')
      && comixChapterNumber(url)!==null;
  }catch{
    return false;
  }
}

function updateComixUrlCount(){
  const urls=comixUrls();
  const valid=urls.filter(validComixChapterUrl);
  const invalid=urls.length-valid.length;

  $('#comixUrlCount').textContent=invalid
    ? `${valid.length} capítulo(s) reconhecido(s) · ${invalid} URL(s) inválida(s)`
    : `${valid.length} capítulo(s) reconhecido(s)`;
}

$('#comixUrl').addEventListener('input',updateComixUrlCount);

function visibleComixChapters(){
  if(!comixState.source)return [];
  return comixState.chapters.filter(ch=>ch.source===comixState.source);
}

function updateComixSelectionUI(){
  const visible=visibleComixChapters();
  const selected=visible.filter(ch=>comixState.selected.has(ch.url)).length;

  $('#comixCurrentSource').textContent=comixState.source||'Fonte';
  $('#comixChapterCount').textContent=
    `${visible.length} capítulo(s) · ${selected} selecionado(s)`;

  $('#comixSelectedCount').textContent=selected
    ? `${selected} capítulo(s) selecionado(s).`
    : 'Nenhum capítulo selecionado.';
}

function renderComixSources(){
  const box=$('#comixSourceList');
  const counts=new Map();

  comixState.chapters.forEach(ch=>{
    counts.set(ch.source,(counts.get(ch.source)||0)+1);
  });

  box.innerHTML=[...counts.entries()]
    .map(([source,count])=>`
      <button
        type="button"
        class="comix-source-item ${source===comixState.source?'active':''}"
        data-source="${escAttr(source)}"
      >
        <span>${esc(source)}</span>
        <b>${count}</b>
      </button>
    `)
    .join('');

  $$('.comix-source-item').forEach(button=>{
    button.addEventListener('click',()=>{
      const source=button.dataset.source;

      if(source===comixState.source)return;

      comixState.source=source;
      $('#comixSource').value=source;

      comixState.selected.clear();
      visibleComixChapters().forEach(ch=>{
        comixState.selected.add(ch.url);
      });

      renderComixSources();
      renderComixChapters();
    });
  });
}

function renderComixChapters(){
  const chapters=visibleComixChapters();
  const grid=$('#comixChapterTable');

  grid.innerHTML='';

  chapters.forEach(ch=>{
    const item=document.createElement('label');
    const checked=comixState.selected.has(ch.url);

    item.className='comix-chapter-item';

    item.innerHTML=`
      <input
        class="comix-chapter-check"
        type="checkbox"
        data-url="${escAttr(ch.url)}"
        ${checked?'checked':''}
      >
      <b>Ch. ${fmt(ch.number)}</b>
    `;

    grid.appendChild(item);
  });

  $$('.comix-chapter-check').forEach(check=>{
    check.addEventListener('change',()=>{
      const url=check.dataset.url;

      if(check.checked){
        comixState.selected.add(url);
      }else{
        comixState.selected.delete(url);
      }

      updateComixSelectionUI();
    });
  });

  updateComixSelectionUI();
}

async function loadComixChapters(){
  const url=$('#comixTitleUrl').value.trim();

  if(!url){
    return toast('Informe a URL da obra no Comix.');
  }

  if(!validComixTitleUrl(url)){
    return toast('Informe uma URL válida de obra do Comix.');
  }

  $('#comixLoadButton').disabled=true;
  setBusy('Listando capítulos do Comix…');

  try{
    const data=await api('/api/comix/chapters',{
      method:'POST',
      body:JSON.stringify({url})
    });

    comixState.chapters=data.chapters||[];
    comixState.selected.clear();

    const sources=data.sources||[];

    if(!comixState.chapters.length || !sources.length){
      throw new Error('Nenhum capítulo foi encontrado para esta obra.');
    }

    $('#comixSource').innerHTML=sources
      .map(source=>`<option value="${escAttr(source)}">${esc(source)}</option>`)
      .join('');

    comixState.source=sources.includes('TappyToon')
      ? 'TappyToon'
      : sources[0];

    $('#comixSource').value=comixState.source;

    visibleComixChapters().forEach(ch=>{
      comixState.selected.add(ch.url);
    });

    if(!$('#comixTitle').value.trim()){
      $('#comixTitle').value=comixTitleFromUrl(url);
    }

    $('#comixDiscovery').classList.remove('hidden');
    $('#comixConfigArrow').classList.remove('hidden');

    renderComixSources();
    renderComixChapters();

    toast(`${visibleComixChapters().length} capítulo(s) encontrados em ${comixState.source}.`);
  }catch(e){
    comixState.chapters=[];
    comixState.selected.clear();
    comixState.source='';

    $('#comixDiscovery').classList.add('hidden');
    $('#comixConfigArrow').classList.add('hidden');
    $('#comixSourceList').innerHTML='';

    toast(e.message);
  }finally{
    setBusy('Pronto');
    $('#comixLoadButton').disabled=false;
  }
}

async function startComixDownload(){
  const folderPattern=$('#comixFolderPattern').value.trim()||'Ch. 01';

  let chapters=[];
  let mangaUrl=$('#comixTitleUrl').value.trim();

  const discovered=visibleComixChapters()
    .filter(ch=>comixState.selected.has(ch.url));

  if(discovered.length){
    chapters=discovered.map(ch=>({
      number:ch.number,
      url:ch.url,
      title:ch.title||`Capítulo ${ch.number}`,
      folder_pattern:folderPattern
    }));
  }else{
    const urls=comixUrls();

    if(!urls.length){
      return toast('Selecione capítulos ou informe URLs diretas.');
    }

    const invalid=urls.filter(url=>!validComixChapterUrl(url));

    if(invalid.length){
      return toast(`${invalid.length} URL(s) inválida(s). Revise a lista antes de continuar.`);
    }

    chapters=urls.map(url=>{
      const number=comixChapterNumber(url);

      return {
        number,
        url,
        title:`Capítulo ${number}`,
        folder_pattern:folderPattern
      };
    });

    mangaUrl=urls[0];
  }

  const title=$('#comixTitle').value.trim()
    || comixTitleFromUrl(mangaUrl);

  const manga={
    title,
    url:mangaUrl,
    author:'',
    genres:[],
    cover_image_url:'',
    summary:''
  };

  setBusy(`Iniciando ${chapters.length} capítulo(s) Comix…`);
  $('#comixDownloadButton').disabled=true;

  try{
    await api('/api/downloads',{
      method:'POST',
      body:JSON.stringify({manga,chapters})
    });

    toast(`${chapters.length} capítulo(s) adicionado(s) à fila.`);
    navigate('downloads');
    await refreshDownloads();
    startPolling();
  }catch(e){
    toast(e.message);
  }finally{
    setBusy('Pronto');
    $('#comixDownloadButton').disabled=false;
  }
}

updateComixUrlCount();

async function runSearch(){ const q=$('#searchInput').value.trim(); if(!q) return toast('Informe um título ou URL.'); setBusy('Consultando…'); $('#searchButton').disabled=true;
  try{ if(state.searchMode==='url'){ await openManga(q); return; } const data=await api(`/api/search?q=${encodeURIComponent(q)}&page=1`); renderResults(data.results); $('#resultsMeta').textContent=`${data.results.length} resultado(s)`; $('#searchHint').textContent=`Busca por “${q}”`; }
  catch(e){toast(e.message);} finally{setBusy('Pronto');$('#searchButton').disabled=false;}
}
function renderResults(results){ const grid=$('#resultsGrid'); if(!results.length){grid.innerHTML='<div class="empty-state"><div class="empty-icon">⌕</div><strong>Nenhum resultado</strong><span>Tente outro título.</span></div>';return;} grid.innerHTML=''; results.forEach(m=>{ const card=document.createElement('article');card.className='result-card';card.innerHTML=`<img class="result-cover" src="${escAttr(m.cover_image_url)}" alt=""><div><h3>${esc(m.title)}</h3><p>${esc(m.author||'Autor não informado')}</p><p>${(m.genres||[]).map(esc).join(' · ')}</p><div class="open">Abrir mangá →</div></div>`;card.addEventListener('click',()=>openManga(m.url));grid.appendChild(card); }); }
async function openManga(url){ setBusy('Carregando mangá…'); try{ const data=await api('/api/manga',{method:'POST',body:JSON.stringify({url})}); state.currentManga=data.manga; state.chapters=data.chapters; state.selected.clear(); state.chapterType='all'; syncChapterTypeButtons(); renderManga(); $('#mangaNav').disabled=false; navigate('manga'); }catch(e){toast(e.message);}finally{setBusy('Pronto');} }
function renderManga(){ const m=state.currentManga; $('#mangaTitle').textContent=m.title;$('#mangaAuthor').textContent=m.author||'';$('#mangaCover').src=m.cover_image_url||'';$('#mangaSummary').textContent=m.summary||'Sem resumo disponível.';$('#chapterCount').textContent=state.chapters.length;$('#mangaGenres').innerHTML=(m.genres||[]).map(g=>`<span class="chip">${esc(g)}</span>`).join('');$('#rangeEnd').value=state.chapters.length; renderChapterRows(); updateSelectionUI(); }
$('#summaryToggle').addEventListener('click',()=>{const x=$('#mangaSummary');x.classList.toggle('hidden');$('#summaryToggle').textContent=x.classList.contains('hidden')?'Ver resumo':'Ocultar resumo';});
function chapterType(ch){return String(ch.title||'').toLowerCase().includes('official')?'official':'regular';}
function visibleChapterIndexes(){const filter=$('#chapterFilter').value.trim().toLowerCase();const out=[];state.chapters.forEach((ch,i)=>{if(state.chapterType!=='all'&&chapterType(ch)!==state.chapterType)return;if(filter&&!`${ch.number} ${ch.title}`.toLowerCase().includes(filter))return;out.push(i);});return out;}
function syncChapterTypeButtons(){$$('#chapterTypeSegment button').forEach(b=>b.classList.toggle('selected',b.dataset.value===state.chapterType));}
function renderChapterRows(){const visible=visibleChapterIndexes();const rows=$('#chapterRows');rows.innerHTML='';visible.forEach(i=>{const ch=state.chapters[i];const tr=document.createElement('tr');tr.innerHTML=`<td><input class="chapter-check" type="checkbox" data-index="${i}" ${state.selected.has(i)?'checked':''}></td><td><b>Ch. ${fmt(ch.number)}</b></td><td>${esc(ch.title||'')}</td>`;rows.appendChild(tr);});$('#visibleChapterCount').textContent=`${visible.length} exibidos`;$$('.chapter-check').forEach(c=>c.addEventListener('change',()=>{const i=Number(c.dataset.index);c.checked?state.selected.add(i):state.selected.delete(i);updateSelectionUI();}));}
$('#chapterFilter').addEventListener('input',renderChapterRows);
$$('#chapterTypeSegment button').forEach(btn=>btn.addEventListener('click',()=>{state.chapterType=btn.dataset.value;syncChapterTypeButtons();renderChapterRows();}));
$('#selectAll').addEventListener('click',()=>{visibleChapterIndexes().forEach(i=>state.selected.add(i));renderChapterRows();updateSelectionUI();});
$('#selectNone').addEventListener('click',()=>{visibleChapterIndexes().forEach(i=>state.selected.delete(i));renderChapterRows();updateSelectionUI();});
$('#selectRange').addEventListener('click',()=>{const visible=new Set(visibleChapterIndexes());const a=Math.max(1,Number($('#rangeStart').value||1)),b=Math.min(state.chapters.length,Number($('#rangeEnd').value||state.chapters.length));for(let i=a-1;i<=b-1;i++)if(visible.has(i))state.selected.add(i);renderChapterRows();updateSelectionUI();});
function updateSelectionUI(){const n=state.selected.size;$('#selectedCount').textContent=n;$('#downloadSelected').disabled=n===0;$('#downloadSummary').textContent=n?`${n} capítulo(s) selecionado(s).`:'Selecione capítulos para baixar.';}
$('#downloadSelected').addEventListener('click',()=>startDownload([...state.selected].sort((a,b)=>a-b).map(i=>state.chapters[i]))); $('#downloadAll').addEventListener('click',()=>startDownload(visibleChapterIndexes().map(i=>state.chapters[i])));
async function startDownload(chapters){ if(!state.currentManga||!chapters.length)return; setBusy('Iniciando download…'); try{const data=await api('/api/downloads',{method:'POST',body:JSON.stringify({manga:state.currentManga,chapters})});toast('Download iniciado.');navigate('downloads');await refreshDownloads();startPolling();}catch(e){toast(e.message);}finally{setBusy('Pronto');}}

async function refreshDownloads(){ try{state.jobs=await api('/api/downloads');renderDownloads();const active=state.jobs.filter(j=>['queued','running'].includes(j.state)).length;$('#downloadCount').textContent=state.jobs.length;$('#downloadBadge').textContent=active?active:'';if(active)startPolling();}catch(e){console.error(e);} }
function renderDownloads(){const box=$('#downloadsContainer');if(!state.jobs.length){box.innerHTML='<div class="empty-card">Nenhum download iniciado nesta sessão.</div>';return;}box.innerHTML=state.jobs.map(job=>`<article class="download-card"><div class="download-top"><div><h3>${esc(job.manga.title)}</h3><p>${esc(job.message||'')}</p></div><span class="download-state">${stateLabel(job.state)}</span></div><div class="progress-track"><div class="progress-fill" style="width:${job.progress||0}%"></div></div><div class="progress-meta"><span>${job.completed}/${job.total} capítulos</span><span>${job.progress||0}%</span></div><div class="queue">${(job.chapters||[]).map(r=>`<div class="queue-row ${r.status==='downloading'?'downloading':''}"><b>Ch. ${fmt(r.number)}</b><span>${esc(r.title||'')}</span><span class="queue-status ${r.status}">${esc(pdfText(r))}</span>${pdfAction(job,r)}</div>`).join('')}</div></article>`).join('');$$('.pdf-action').forEach(btn=>btn.addEventListener('click',()=>generatePdf(btn.dataset.job,btn.dataset.chapter,btn.dataset.regenerate==='1')));}
function pdfText(row){const base=row.message||row.status;if(row.status==='completed'&&row.pdf_status==='failed')return `${base} · Falha ao gerar PDF`;if(row.status==='completed'&&row.pdf_message)return `${base} · ${row.pdf_message}`;return base;}
function pdfAction(job,row){if(row.status!=='completed'||!row.file_path||!(row.images_downloaded>0))return '';const done=row.pdf_status==='generated'||row.pdf_status==='existing';const failed=row.pdf_status==='failed';return `<button class="ghost pdf-action" data-job="${escAttr(job.id)}" data-chapter="${escAttr(row.url)}" data-regenerate="${done?'1':'0'}">${done?'Gerar novamente':failed?'Tentar novamente':'Gerar PDF'}</button>`;}
async function generatePdf(jobId,chapterUrl,regenerate=false){setBusy('Gerando PDF…');try{await api('/api/pdf',{method:'POST',body:JSON.stringify({job_id:jobId,chapter_url:chapterUrl,regenerate})});toast('PDF gerado');await refreshDownloads();}catch(e){toast(e.message);await refreshDownloads();}finally{setBusy('Pronto');}}
function startPolling(){if(state.poller)return;state.poller=setInterval(async()=>{await refreshDownloads();if(!state.jobs.some(j=>['queued','running'].includes(j.state))){clearInterval(state.poller);state.poller=null;}},1000);}
function stateLabel(s){return ({queued:'Na fila',running:'Em andamento',completed:'Concluído',completed_with_errors:'Concluído com falhas',failed:'Falhou'})[s]||s;}

function syncImageFormatUi(){const original=$('#imageFormat').value==='original';const row=$('#keepOriginalsRow');const checkbox=$('#keepOriginals');if(original){checkbox.checked=false;checkbox.disabled=true;row?.classList.add('setting-disabled');}else{checkbox.disabled=false;row?.classList.remove('setting-disabled');}}
async function loadSettings(){try{state.settings=await api('/api/settings');$('#downloadLocation').value=state.settings.download_location||'';$('#maxWorkers').value=state.settings.max_workers??3;$('#pageDelay').value=state.settings.page_delay??2;$('#retryCount').value=state.settings.retry_count??3;$('#timeout').value=state.settings.timeout??30;$('#imageFormat').value=state.settings.image_format||'original';$('#keepOriginals').checked=!!state.settings.keep_originals;$('#autoGeneratePdf').checked=!!state.settings.auto_generate_pdf;syncImageFormatUi();$$('#formatSegment button').forEach(b=>b.classList.toggle('selected',b.dataset.value===(state.settings.format||'images')));}catch(e){toast(e.message);}}
let saveTimer; function queueSave(){ $('#saveState').textContent='Salvando…';clearTimeout(saveTimer);saveTimer=setTimeout(saveSettings,350);} async function saveSettings(){const format=$('#formatSegment button.selected')?.dataset.value||'images';const payload={download_location:$('#downloadLocation').value.trim(),max_workers:Number($('#maxWorkers').value||3),page_delay:Number($('#pageDelay').value||2),retry_count:Number($('#retryCount').value||3),timeout:Number($('#timeout').value||30),image_format:$('#imageFormat').value,keep_originals:$('#imageFormat').value==='png'&&$('#keepOriginals').checked,auto_generate_pdf:$('#autoGeneratePdf').checked,format};try{state.settings=await api('/api/settings',{method:'PUT',body:JSON.stringify(payload)});$('#saveState').textContent='✓ Alterações salvas';}catch(e){$('#saveState').textContent='Falha ao salvar';toast(e.message);}}
['downloadLocation','maxWorkers','pageDelay','retryCount','timeout','keepOriginals','autoGeneratePdf'].forEach(id=>$('#'+id).addEventListener('change',queueSave));$('#imageFormat').addEventListener('change',()=>{syncImageFormatUi();queueSave();});$('#downloadLocation').addEventListener('input',queueSave);$$('#formatSegment button').forEach(b=>b.addEventListener('click',()=>{$$('#formatSegment button').forEach(x=>x.classList.remove('selected'));b.classList.add('selected');queueSave();}));
function esc(v){return String(v??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));}function escAttr(v){return esc(v);}function fmt(v){const n=Number(v);return Number.isInteger(n)?n.toFixed(1):String(n);}
refreshDownloads();
