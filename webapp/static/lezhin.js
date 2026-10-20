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
  // LEZHIN_RIDI_LIST_V2: status de conexão, não de autorização de leitura.
  function session(status) {
    const el = $('lezhinSessionStatus'), dot = document.querySelector('.lezhin-session-dot');
    if (!el) return;
    const chrome = status?.chrome_state;
    const visual = chrome === 'connected' ? 'connected' :
      chrome === 'error' ? 'error' : 'offline';
    const label = { connected: 'Online', offline: 'Offline', error: 'Erro' }[visual];
    el.dataset.state = visual;
    if (dot) dot.dataset.state = visual;
    el.textContent = label;
    el.title = status?.message || (visual === 'connected'
      ? 'Chrome conectado. Acesso aos episódios não confirmado.' : label);
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
    const selected = state.chapters.filter(ch => state.selected.has(ch.url) && ch.number !== null).length;
    $('lezhinEpisodeMeta').textContent = `${state.chapters.length} episódio(s) · ${selected} selecionado(s)`;
    // O backend sempre revalida cada episódio; não confundir seleção com acesso.
    $('lezhinDownloadButton').disabled = selected === 0;
  }
  function render() {
    const root = $('lezhinEpisodes'); root.replaceChildren();
    state.chapters.forEach(ch => {
      const row = document.createElement('label');
      row.className = 'comix-chapter-item';
      const check = document.createElement('input');
      check.type = 'checkbox';
      check.className = 'lezhin-episode-check';
      check.checked = state.selected.has(ch.url);
      check.disabled = ch.number === null;
      check.dataset.url = ch.url;
      check.addEventListener('change', () => {
        if (check.checked) state.selected.add(ch.url);
        else state.selected.delete(ch.url);
        updateCount();
      });
      const title = document.createElement('b');
      title.textContent = ch.number === null ? 'Especial · sem número' : `Ep. ${ch.number}`;
      title.title = ch.title || title.textContent;
      row.append(check, title);
      root.append(row);
    });
    updateCount();
  }
  async function discover() {
    const current = await api('/api/lezhinus/session').catch(() => null);
    if (!current || current.chrome_state !== 'connected') {
      session(current || { chrome_state: 'unavailable' });
      return toast('Clique em Iniciar Lezhin antes de Desvendar.');
    }
    const url = $('lezhinWorkUrl').value.trim(); $('lezhinDiscoverButton').disabled = true;
    try {
      const data = await api('/api/lezhinus/chapters', { method: 'POST', body: JSON.stringify({ url }) });
      state.workUrl = data.url; state.title = data.title; state.chapters = data.chapters || [];
      state.selected.clear();
      state.chapters.filter(ch => ch.number !== null).forEach(ch => state.selected.add(ch.url));
      $('lezhinTitle').value = state.title;
      $('lezhinWorkTitle').textContent = state.title; $('lezhinEpisodeMeta').textContent = `${state.chapters.length} episódios listados`;
      $('lezhinEpisodeStep').classList.remove('hidden'); render();
      toast(`${state.chapters.length} episódios listados. Acesso ainda não confirmado.`);
    } catch (error) { toast(error.message); }
    finally { $('lezhinDiscoverButton').disabled = false; }
  }

  async function queue() {
    const folder = $('lezhinFolderPattern').value.trim() || 'Ch. 01';
    const chapters = state.chapters.filter(ch => state.selected.has(ch.url) && ch.number !== null)
      .map(ch => ({ number: ch.number, title: ch.title, url: ch.url, folder_pattern: folder }));
    if (!chapters.length) return toast('Selecione ao menos um episódio.');
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
      const started = await api('/api/lezhinus/session/start', { method: 'POST', body: '{}' });
      if (started.chrome_state === 'error') throw new Error(started.message || 'Falha no Chrome Lezhin.');
      session(started);
      if (started.chrome_state !== 'connected') {
        for (let i = 0; i < 12; i++) {
          await new Promise(resolve => setTimeout(resolve, 1500));
          const current = await api('/api/lezhinus/session');
          session(current);
          if (current.chrome_state === 'connected') break;
          if (current.chrome_state === 'error') throw new Error(current.message || 'Falha na sessão Lezhin.');
        }
      }
      const current = await api('/api/lezhinus/session');
      session(current);
      if (current.chrome_state !== 'connected')
        throw new Error(current.message || 'Chrome Lezhin não ficou disponível.');
    } catch (error) {
      toast(error.message);
      session({ chrome_state: 'unavailable', message: error.message });
    } finally { button.disabled = false; }
  }
  async function init() {
    try { $('lezhinPanel').innerHTML = await (await fetch('/static/lezhin_panel.html')).text(); }
    catch (_) { return; }
    session({ chrome_state: 'unavailable' });
    await savedWorks();
    $('lezhinStartButton').addEventListener('click', startChrome);
    $('lezhinDiscoverButton').addEventListener('click', discover);
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
  }
  init();
})();
