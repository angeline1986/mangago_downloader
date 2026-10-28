"use strict";

function progressPercent(value){
  return Math.max(0,Math.min(100,Number(value)||0));
}

function progressTrack(value,label,variant){
  const percent=progressPercent(value);
  return `<div class="${variant}-progress-track"
    role="progressbar" aria-label="${escAttr(label)}" aria-valuemin="0"
    aria-valuemax="100" aria-valuenow="${percent}">
      <div class="${variant}-progress-fill" style="width:${percent}%"></div>
    </div>`;
}

function chapterProgressLabel(row){
  if(row.status==='failed'){
    return row.total_pages
      ? `${row.current_page||0}/${row.total_pages} páginas antes da falha`
      : 'Falhou antes de baixar páginas';
  }
  if(row.total_pages){
    return `${row.current_page||0}/${row.total_pages} páginas · ${progressPercent(row.progress)}%`;
  }
  if(row.status==='downloading' && !row.current_page){
    return 'Preparando primeira página…';
  }
  return `${progressPercent(row.progress)}%`;
}

function chapterRow(job,row){
  const label=`Capítulo ${fmt(row.number)}`;
  return `<div class="queue-row ${escAttr(row.status)}">
    <b>Ch. ${fmt(row.number)}</b>
    <div class="queue-chapter">
      <span>${esc(row.title||'')}</span>
      ${progressTrack(row.progress,label,'chapter')}
      <small>${esc(chapterProgressLabel(row))}</small>
    </div>
    <span class="queue-status ${escAttr(row.status)}">${esc(pdfText(row))}</span>
    ${pdfAction(job,row)}
  </div>`;
}

function renderDownloads(){
  const box=$('#downloadsContainer');
  if(!state.jobs.length){
    box.innerHTML='<div class="empty-card">Nenhum download iniciado nesta sessão.</div>';
    return;
  }
  box.innerHTML=state.jobs.map(job=>{
    return `<article class="download-card">
      <div class="download-top">
        <div><h3>${esc(job.manga.title)}</h3><p>${esc(job.message||'')}</p></div>
        <span class="download-state">${esc(stateLabel(job.state))}</span>
      </div>
      ${progressTrack(job.progress,'Progresso geral','job')}
      <div class="progress-meta">
        <span>${job.completed}/${job.total} capítulos</span>
        <span>${progressPercent(job.progress)}%</span>
      </div>
      <div class="queue">${(job.chapters||[]).map(row=>chapterRow(job,row)).join('')}</div>
    </article>`;
  }).join('');
  $$('.pdf-action').forEach(button=>button.addEventListener('click',()=>
    generatePdf(button.dataset.job,button.dataset.chapter,button.dataset.regenerate==='1')));
}

function pdfText(row){
  const base=row.message||row.status;
  if(row.status==='completed'&&row.pdf_status==='failed')return `${base} · Falha ao gerar PDF`;
  if(row.status==='completed'&&row.pdf_message)return `${base} · ${row.pdf_message}`;
  return base;
}

function pdfAction(job,row){
  if(row.status!=='completed'||!row.file_path||!(row.images_downloaded>0))return '';
  const done=row.pdf_status==='generated'||row.pdf_status==='existing';
  const failed=row.pdf_status==='failed';
  return `<button class="ghost pdf-action" data-job="${escAttr(job.id)}"
    data-chapter="${escAttr(row.url)}" data-regenerate="${done?'1':'0'}">
    ${done?'Gerar novamente':failed?'Tentar novamente':'Gerar PDF'}</button>`;
}

async function generatePdf(jobId,chapterUrl,regenerate=false){
  setBusy('Gerando PDF…');
  try{
    await api('/api/pdf',{method:'POST',body:JSON.stringify({job_id:jobId,chapter_url:chapterUrl,regenerate})});
    toast('PDF gerado');
  }catch(error){
    toast(error.message);
  }finally{
    await refreshDownloads();
    setBusy('Pronto');
  }
}

async function refreshDownloads(){
  try{
    state.jobs=await api('/api/downloads');
    renderDownloads();
    const active=state.jobs.filter(job=>['queued','running'].includes(job.state)).length;
    $('#downloadCount').textContent=state.jobs.length;
    $('#downloadBadge').textContent=active?active:'';
    if(active)startPolling();
  }catch(error){console.error(error);}
}

function startPolling(){
  if(state.poller)return;
  state.poller=setInterval(async()=>{
    await refreshDownloads();
    if(!state.jobs.some(job=>['queued','running'].includes(job.state))){
      clearInterval(state.poller);
      state.poller=null;
    }
  },1000);
}

function stateLabel(status){
  return ({queued:'Na fila',running:'Em andamento',completed:'Concluído',
    completed_with_errors:'Concluído com falhas',failed:'Falhou'})[status]||status;
}
