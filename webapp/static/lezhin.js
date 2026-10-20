(() => {
  const state = { works: [], chapters: [], selected: new Set(), workUrl: '', title: '' };
  const $ = (id) => document.getElementById(id);
  const api = async (url, options = {}) => {
    const response = await fetch(url, { headers: { 'Content-Type': 'application/json' }, ...options });
    const body = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(body.error || `Erro HTTP ${response.status}`);
    return body;
  };
  const toast = (message) => {
    const el = $('toast'); if (!el) return;
    el.textContent = message; el.classList.add('show'); clearTimeout(el._lezhinTimer);
    el._lezhinTimer = setTimeout(() => el.classList.remove('show'), 3200);
  };
  const labelFor = (status) => ({ listed_unverified: 'Acesso pendente', free: 'Free · não verificado',
    paid_access_unverified: 'Pago · não verificado', unlocked: 'Desbloqueado',
    accessible_verified: 'Acessível', unavailable: 'Indisponível',
    authentication_required: 'Login necessário' })[status] || 'Acesso pendente';
  function session(status) {
    const el = $('lezhinSessionStatus'), dot = document.querySelector('.lezhin-session-dot');
    if (!el) return;
    const state = status.session_state === 'authenticated' ? 'connected' :
      status.session_state === 'unauthenticated' ? 'unauthenticated' :
      status.chrome_state === 'error' ? 'error' : status.chrome_state === 'unavailable' ? 'offline' : 'unknown';
    el.dataset.state = state; if (dot) dot.dataset.state = state;
    el.textContent = status.message || 'Estado da sessão não confirmado.';
  }
  async function refreshSession() {
    try { session(await api('/api/lezhinus/session')); }
    catch (_) { session({ chrome_state: 'unavailable', message: 'Chrome Lezhin indisponível.' }); }
  }
  async function savedWorks() {
    try {
      const data = await api('/api/saved-works?provider=lezhinus'); state.works = data.works || [];
      for (const [id, key] of [['lezhinSavedWorkOptions', 'name'], ['lezhinSavedUrlOptions', 'url']]) {
        const list = $(id); list.replaceChildren();
        state.works.forEach(work => { const option = document.createElement('option'); option.value = work[key] || ''; list.append(option); });
      }
    } catch (error) { toast(error.message); }
  }
  function updateCount() {
    const count = state.chapters.filter(ch => state.selected.has(ch.url) && ch.number !== null).length;
    $('lezhinSelectedCount').textContent = count ? `${count} episódio(s) selecionado(s).` : 'Nenhum episódio selecionado.';
    $('lezhinDownloadButton').disabled = !state.chapters.some(ch => state.selected.has(ch.url) && ch.availability === 'accessible_verified' && ch.number !== null);
  }
  function render() {
    const root = $('lezhinEpisodes'); root.replaceChildren();
    state.chapters.forEach(ch => {
      const row = document.createElement('div'); row.className = 'lezhin-episode';
      const label = document.createElement('label'), check = document.createElement('input');
      check.type = 'checkbox'; check.checked = state.selected.has(ch.url); check.dataset.url = ch.url;
      check.disabled = ch.number === null;
      check.addEventListener('change', () => { check.checked ? state.selected.add(ch.url) : state.selected.delete(ch.url); updateCount(); });
      const title = document.createElement('span'); title.className = 'lezhin-episode-title';
      title.textContent = `${ch.number == null ? 'Especial · sem número' : `Ep. ${ch.number}`} · ${ch.title}`;
      label.append(check, title);
      const access = document.createElement('span'); access.className = 'lezhin-access';
      access.dataset.state = ch.availability;
      access.textContent = ch.number === null ? 'Sem número · não enfileirável' : labelFor(ch.availability);
      row.append(label, access); root.append(row);
    });
    updateCount();
  }
  async function discover() {
    const url = $('lezhinWorkUrl').value.trim(); $('lezhinDiscoverButton').disabled = true;
    try {
      const data = await api('/api/lezhinus/chapters', { method: 'POST', body: JSON.stringify({ url }) });
      state.workUrl = data.url; state.title = data.title; state.chapters = data.chapters || [];
      state.selected.clear(); $('lezhinTitle').value = state.title;
      $('lezhinWorkTitle').textContent = state.title; $('lezhinEpisodeMeta').textContent = `${state.chapters.length} episódios listados`;
      $('lezhinEpisodeStep').classList.remove('hidden'); render();
      toast(`${state.chapters.length} episódios listados. Acesso ainda não confirmado.`);
    } catch (error) { toast(error.message); }
    finally { $('lezhinDiscoverButton').disabled = false; }
  }
  async function verifySelected() {
    const selected = state.chapters.filter(ch => state.selected.has(ch.url));
    if (!selected.length) return toast('Selecione episódios para verificar.');
    $('lezhinVerifyButton').disabled = true;
    try {
      for (const ch of selected) {
        try { const result = await api('/api/lezhinus/verify', { method: 'POST', body: JSON.stringify({ url: ch.url }) }); ch.availability = result.availability; }
        catch (error) { ch.availability = error.message.includes('AUTH_REQUIRED') ? 'authentication_required' : 'listed_unverified'; }
        render();
        if (ch.availability === 'authentication_required') break;
      }
    } finally { $('lezhinVerifyButton').disabled = false; }
  }
  async function queue() {
    const folder = $('lezhinFolderPattern').value.trim() || 'Ch. 01';
    const chapters = state.chapters.filter(ch => state.selected.has(ch.url) && ch.availability === 'accessible_verified' && ch.number !== null)
      .map(ch => ({ number: ch.number, title: ch.title, url: ch.url, folder_pattern: folder }));
    if (!chapters.length) return toast('Verifique o acesso antes de enfileirar.');
    $('lezhinDownloadButton').disabled = true;
    try {
      await api('/api/lezhinus/downloads', { method: 'POST', body: JSON.stringify({ manga: { title: $('lezhinTitle').value.trim() || state.title, url: state.workUrl }, chapters }) });
      toast(`${chapters.length} episódio(s) adicionado(s) à fila compartilhada.`);
      document.querySelector('[data-page="downloads"]')?.click();
      window.refreshDownloads?.(); window.startPolling?.();
    } catch (error) { toast(error.message); }
    finally { updateCount(); }
  }
  async function startChrome() {
    const button = $('lezhinStartButton'); button.disabled = true;
    try {
      session(await api('/api/lezhinus/session/start', { method: 'POST', body: '{}' }));
      for (let i = 0; i < 12; i++) { await new Promise(resolve => setTimeout(resolve, 1500)); await refreshSession(); }
    } catch (error) { toast(error.message); }
    finally { button.disabled = false; }
  }
  async function init() {
    try { $('lezhinPanel').innerHTML = await (await fetch('/static/lezhin_panel.html')).text(); }
    catch (_) { return; }
    await Promise.all([savedWorks(), refreshSession()]);
    $('lezhinStartButton').addEventListener('click', startChrome);
    $('lezhinDiscoverButton').addEventListener('click', discover);
    $('lezhinVerifyButton').addEventListener('click', verifySelected);
    $('lezhinDownloadButton').addEventListener('click', queue);
    $('lezhinSelectAll').addEventListener('click', () => { state.chapters.filter(ch => ch.number !== null).forEach(ch => state.selected.add(ch.url)); render(); });
    $('lezhinSelectNone').addEventListener('click', () => { state.selected.clear(); render(); });
    $('lezhinSavedWork').addEventListener('change', event => {
      const work = state.works.find(item => item.name === event.target.value); if (!work) return;
      $('lezhinWorkUrl').value = work.url; $('lezhinTitle').value = work.name;
    });
    $('lezhinWorkUrl').addEventListener('change', event => {
      const work = state.works.find(item => item.url === event.target.value); if (work) $('lezhinSavedWork').value = work.name;
    });
    setInterval(refreshSession, 15000);
  }
  init();
})();
