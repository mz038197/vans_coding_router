/* PROTOTYPE — throwaway. Not production.
   Question: how should the classroom settings list be laid out so the right
   side is not clipped, controls are not crushed, and the panel can get narrow?
   Three variants of the teacher session list, switchable via ?variant=A|B|C,
   mounted on the existing /portal course panel (and on
   /portal/prototype/session-layout with fixture data).
   Local clicks update the state readout only. Nothing is written to the server.
*/
(function () {
  const VARIANTS = [
    { key: 'A', name: '課堂卡' },
    { key: 'B', name: '清單與檢視窗' },
    { key: 'C', name: '摺疊列' },
    { key: 'D', name: '寬度切換' },
  ];

  const state = {
    selectedId: null,
    expandedId: null,
    seatsOpenId: null,
    choices: {},
    lastAction: '開啟原型',
    dWide: null,
  };

  const D_NARROW_BELOW = 720;
  const D_WIDE_AT = 800;

  let context = null;
  let chromeReady = false;

  function variantKey() {
    const raw = new URLSearchParams(location.search).get('variant') || '';
    const key = raw.trim().toUpperCase();
    return VARIANTS.some((item) => item.key === key) ? key : '';
  }

  function variantName(key) {
    return VARIANTS.find((item) => item.key === key)?.name || key;
  }

  function esc(value) {
    return String(value ?? '')
      .replaceAll('&', '&amp;')
      .replaceAll('<', '&lt;')
      .replaceAll('>', '&gt;')
      .replaceAll('"', '&quot;');
  }

  function when(iso) {
    if (!iso) return '—';
    const date = new Date(iso);
    if (Number.isNaN(date.getTime())) return String(iso);
    return date.toLocaleString(undefined, {
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
    });
  }

  function displayName(session) {
    const name = (session?.name || '').trim();
    return name || '（未命名）';
  }

  function isActive(session, courseStatus) {
    if (courseStatus === 'ended') return false;
    if (!session.expires_at) return true;
    const date = new Date(session.expires_at);
    return Number.isNaN(date.getTime()) || date > new Date();
  }

  function seatLimit(session) {
    const n = Number(session.seat_limit);
    return Number.isFinite(n) && n >= 1 ? n : 60;
  }

  function catalogHas(session) {
    return /^-\s+\S/m.test(String(session.course_catalog_yaml || ''));
  }

  function hasShelf(session, flag) {
    for (const provider of session.session_chat_language_models || []) {
      for (const model of (provider && provider.models) || []) {
        if (model && model[flag] === true && model.id) return true;
      }
    }
    return false;
  }

  function promptOn(session) {
    const value = session.prompt_logging_enabled;
    if (value === undefined || value === null) return true;
    return value === true || value === 1 || value === '1';
  }

  function syncSessionState(sessions) {
    const ids = sessions.map((session) => session.id);
    if (!ids.includes(state.selectedId)) state.selectedId = ids[0] ?? null;
    if (state.expandedId != null && !ids.includes(state.expandedId)) state.expandedId = ids[0] ?? null;
    if (state.expandedId == null && ids.length && state.lastAction === '開啟原型') {
      state.expandedId = ids[0];
    }
    for (const session of sessions) {
      if (!(session.id in state.choices)) {
        const choice = session.classroom_model_choice;
        state.choices[session.id] = choice === 'picked' || choice === 'automatic' ? choice : '';
      }
    }
  }

  function statusTag(session, courseStatus) {
    const active = isActive(session, courseStatus);
    const cls = active ? 'tag-active' : 'tag-ended';
    const label = active ? '進行中' : '已結束';
    return `<span class="tag ${cls}">${label}</span>`;
  }

  function chips(session) {
    const items = [
      ['生圖', hasShelf(session, 'imageShelf')],
      ['語音', hasShelf(session, 'speechShelf')],
      ['語音轉寫', hasShelf(session, 'speechTranscriptionShelf')],
      ['決策', hasShelf(session, 'decisionShelf')],
      ['Prompt', promptOn(session)],
    ];
    return items.map(([name, on]) => (
      `<span class="capability-chip ${on ? 'is-on' : 'is-off'}">${esc(name)} ${on ? '開' : '關'}</span>`
    )).join('');
  }

  function choiceSelect(session) {
    const choice = state.choices[session.id] || '';
    const options = [
      ['', '未設定'],
      ['picked', '學生自選'],
      ['automatic', '自動'],
    ].map(([value, label]) => {
      const selected = value === choice ? ' selected' : '';
      const disabled = value === '' ? ' disabled' : '';
      return `<option value="${value}"${selected}${disabled}>${esc(label)}</option>`;
    }).join('');
    return `<select class="slp-select" aria-label="學生怎麼選模型" data-slp-choice="${session.id}">${options}</select>`;
  }

  function iconButton(icon, label, action, sessionId) {
    return `<button type="button" class="icon-btn" title="${esc(label)}" aria-label="${esc(label)}" data-slp-edit="${esc(action)}" data-slp-id="${sessionId}"><i class="${icon}"></i></button>`;
  }

  function inviteBlock(session) {
    const code = esc(session.invite_code || '');
    return `<div class="slp-invite"><code>${code}</code>${iconButton('fas fa-copy', '複製邀請碼', 'copy', session.id)}</div>`;
  }

  function seatButton(session) {
    const occupied = Number(session.redemption_count || 0);
    const open = state.seatsOpenId === session.id ? ' is-open' : '';
    return `<button type="button" class="slp-seat${open}" data-slp-seats="${session.id}">座位 ${occupied} / ${seatLimit(session)}</button>`;
  }

  function seatNote(session) {
    if (state.seatsOpenId !== session.id) return '';
    return `<p class="slp-note">領取名單會在這裡展開。原型只標記已展開，不打 API。</p>`;
  }

  function expiryBlock(session) {
    return `<div class="slp-inline"><span>${esc(when(session.expires_at))}</span>${iconButton('fas fa-pen', '編輯到期時間', 'expires', session.id)}</div>`;
  }

  function catalogBlock(session) {
    const label = catalogHas(session) ? '已有項目' : '尚無項目';
    return `<div class="slp-inline">${iconButton('fas fa-file-code', '編輯安裝清單', 'catalog', session.id)}<span>${label}</span></div>`;
  }

  const SHELF_FLAGS = ['decisionShelf', 'imageShelf', 'speechShelf', 'speechTranscriptionShelf'];

  function checkedModels(session) {
    const rows = [];
    for (const provider of session.session_chat_language_models || []) {
      for (const model of (provider && provider.models) || []) {
        if (!model || !model.id) continue;
        const shelf = SHELF_FLAGS.find((flag) => model[flag] === true) || 'text';
        rows.push({
          id: String(model.id),
          name: String(model.name || model.id),
          shelf,
        });
      }
    }
    return rows;
  }

  function modelInspector(session) {
    const chat = checkedModels(session).filter((model) => model.shelf === 'text');
    const pills = chat.length
      ? chat.map((model) => `<span class="slp-model-pill" title="${esc(model.id)}">${esc(model.name)}</span>`).join('')
      : '<span class="slp-model-empty">尚未勾選對話模型</span>';
    return `<div class="slp-models-head">
      <span class="slp-models-title"><span class="slp-kicker">對話模型</span>${iconButton('fas fa-pen', '編輯本課對話模型', 'models', session.id)}</span>
      ${choiceSelect(session)}
    </div>
    <div class="slp-model-pills">${pills}</div>`;
  }

  function renderA(sessions, courseStatus) {
    return `<div class="slp-stack">${sessions.map((session) => `
      <article class="slp-card">
        <header class="slp-head">
          <div class="slp-identity">
            <div class="slp-title-row"><span class="slp-name">${esc(displayName(session))}</span>${statusTag(session, courseStatus)}</div>
            <span class="session-name-sub">${esc(when(session.session_at || session.created_at))}</span>
          </div>
          <div class="slp-head-actions">${inviteBlock(session)}${seatButton(session)}</div>
        </header>
        <div class="slp-grid">
          <section class="slp-tile"><span class="slp-kicker">Key 到期</span>${expiryBlock(session)}</section>
          <section class="slp-tile"><span class="slp-kicker">安裝清單</span>${catalogBlock(session)}</section>
          <section class="slp-tile slp-models-span">${modelInspector(session)}</section>
        </div>
        <div class="slp-caps">${chips(session)}</div>
        ${seatNote(session)}
      </article>
    `).join('')}</div>`;
  }

  function renderB(sessions, courseStatus) {
    const selected = sessions.find((session) => session.id === state.selectedId) || sessions[0];
    const list = sessions.map((session) => {
      const current = session.id === selected.id ? ' is-current' : '';
      return `<button type="button" class="slp-row${current}" data-slp-select="${session.id}">
        <span class="slp-name">${esc(displayName(session))}</span>
        ${statusTag(session, courseStatus)}
        <span class="session-name-sub">${esc(when(session.session_at || session.created_at))}</span>
        <span class="slp-seat-text">${Number(session.redemption_count || 0)} / ${seatLimit(session)}</span>
      </button>`;
    }).join('');
    const detail = selected ? `
      <div class="slp-inspector">
        <div class="slp-title-row"><span class="slp-name">${esc(displayName(selected))}</span>${statusTag(selected, courseStatus)}</div>
        <span class="session-name-sub">${esc(when(selected.session_at || selected.created_at))}</span>
        <div class="slp-form">
          <label class="slp-field"><span class="slp-kicker">邀請碼</span>${inviteBlock(selected)}</label>
          <label class="slp-field"><span class="slp-kicker">座位</span>${seatButton(selected)}</label>
          <label class="slp-field"><span class="slp-kicker">Key 到期</span>${expiryBlock(selected)}</label>
          <label class="slp-field"><span class="slp-kicker">安裝清單</span>${catalogBlock(selected)}</label>
          <div class="slp-field">${modelInspector(selected)}</div>
        </div>
        <div class="slp-caps">${chips(selected)}</div>
        ${seatNote(selected)}
      </div>` : '';
    return `<div class="slp-split"><div class="slp-list" role="listbox" aria-label="課堂">${list}</div>${detail}</div>`;
  }

  function renderC(sessions, courseStatus) {
    return `<div class="slp-bands">${sessions.map((session) => {
      const open = state.expandedId === session.id;
      return `<section class="slp-band${open ? ' is-open' : ''}">
        <button type="button" class="slp-summary" data-slp-expand="${session.id}" aria-expanded="${open ? 'true' : 'false'}">
          <span class="slp-name">${esc(displayName(session))}</span>
          ${statusTag(session, courseStatus)}
          <span class="session-name-sub">${esc(when(session.session_at || session.created_at))}</span>
          <span class="slp-seat-text">${Number(session.redemption_count || 0)} / ${seatLimit(session)}</span>
          <i class="fas fa-chevron-${open ? 'up' : 'down'}" aria-hidden="true"></i>
        </button>
        ${open ? `<div class="slp-rail">
          <div class="slp-prop"><span class="slp-kicker">邀請碼</span>${inviteBlock(session)}</div>
          <div class="slp-prop"><span class="slp-kicker">座位</span>${seatButton(session)}</div>
          <div class="slp-prop"><span class="slp-kicker">Key 到期</span>${expiryBlock(session)}</div>
          <div class="slp-prop"><span class="slp-kicker">安裝清單</span>${catalogBlock(session)}</div>
          <div class="slp-prop slp-prop-wide">${modelInspector(session)}</div>
          <div class="slp-prop slp-prop-wide"><span class="slp-kicker">能力</span><div class="slp-caps">${chips(session)}</div></div>
          ${seatNote(session)}
        </div>` : ''}
      </section>`;
    }).join('')}</div>`;
  }

  function dIsWide(width) {
    if (state.dWide === true) return width >= D_NARROW_BELOW;
    if (state.dWide === false) return width >= D_WIDE_AT;
    return width >= D_WIDE_AT;
  }

  function renderD(sessions, courseStatus) {
    const width = context && context.box ? context.box.clientWidth : 0;
    const wide = dIsWide(width);
    if (wide !== state.dWide) {
      if (wide && state.expandedId) state.selectedId = state.expandedId;
      if (!wide && state.selectedId) state.expandedId = state.selectedId;
      state.dWide = wide;
    }
    return wide ? renderB(sessions, courseStatus) : renderC(sessions, courseStatus);
  }

  function renderBody(sessions, courseStatus) {
    const key = variantKey();
    if (!sessions.length) return '<p class="hint">尚無課堂。</p>';
    if (key === 'B') return renderB(sessions, courseStatus);
    if (key === 'C') return renderC(sessions, courseStatus);
    if (key === 'D') return renderD(sessions, courseStatus);
    return renderA(sessions, courseStatus);
  }

  function stateText() {
    const key = variantKey();
    const width = context && context.box ? context.box.clientWidth : 0;
    const mode = key === 'D' ? (state.dWide ? ' · 目前清單與檢視窗' : ' · 目前摺疊列') : '';
    return `${key} — ${variantName(key)}${mode} · 面板 ${width}px · 選取 ${state.selectedId ?? '—'} · ${state.lastAction}`;
  }

  function paintState() {
    const node = document.getElementById('slp-state');
    const label = document.getElementById('slp-variant-label');
    const key = variantKey();
    if (label) label.textContent = `${key} — ${variantName(key)}`;
    if (node) node.textContent = stateText();
  }

  function setVariant(key) {
    const url = new URL(location.href);
    url.searchParams.set('variant', key);
    history.replaceState(null, '', url);
    state.lastAction = `切換到 ${key} — ${variantName(key)}`;
    paint();
  }

  function cycle(step) {
    const key = variantKey() || 'A';
    const index = VARIANTS.findIndex((item) => item.key === key);
    const next = VARIANTS[(index + step + VARIANTS.length) % VARIANTS.length];
    setVariant(next.key);
  }

  function onChromeClick(event) {
    const button = event.target.closest('[data-slp-cycle]');
    if (!button) return;
    cycle(Number(button.dataset.slpCycle));
  }

  function onKeyDown(event) {
    if (!variantKey()) return;
    const tag = event.target && event.target.tagName;
    if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || event.target.isContentEditable) return;
    if (event.key === 'ArrowLeft') {
      event.preventDefault();
      cycle(-1);
    } else if (event.key === 'ArrowRight') {
      event.preventDefault();
      cycle(1);
    }
  }

  function ensureChrome() {
    if (chromeReady) return;
    chromeReady = true;
    const style = document.createElement('style');
    style.id = 'slp-style';
    style.textContent = CSS;
    document.head.appendChild(style);
    const chrome = document.createElement('div');
    chrome.id = 'slp-chrome';
      chrome.innerHTML = `
      <div class="slp-switcher" role="toolbar" aria-label="原型版面切換">
        <button type="button" data-slp-cycle="-1" aria-label="上一個版面">←</button>
        <span class="slp-switcher-text">
          <span id="slp-variant-label"></span>
          <span id="slp-state"></span>
        </span>
        <button type="button" data-slp-cycle="1" aria-label="下一個版面">→</button>
      </div>`;
    document.body.appendChild(chrome);
    chrome.addEventListener('click', onChromeClick);
    document.addEventListener('keydown', onKeyDown);
    window.addEventListener('resize', paintState);
  }

  function onPanelClick(event) {
    const seat = event.target.closest('[data-slp-seats]');
    if (seat) {
      const id = Number(seat.dataset.slpSeats);
      state.seatsOpenId = state.seatsOpenId === id ? null : id;
      state.lastAction = state.seatsOpenId ? `展開座位 ${id}` : `收合座位 ${id}`;
      paint();
      return;
    }
    const selectRow = event.target.closest('[data-slp-select]');
    if (selectRow) {
      state.selectedId = Number(selectRow.dataset.slpSelect);
      state.expandedId = state.selectedId;
      state.lastAction = `選取課堂 ${state.selectedId}`;
      paint();
      return;
    }
    const expand = event.target.closest('[data-slp-expand]');
    if (expand) {
      const id = Number(expand.dataset.slpExpand);
      state.expandedId = state.expandedId === id ? null : id;
      if (state.expandedId) state.selectedId = state.expandedId;
      state.lastAction = state.expandedId ? `展開課堂 ${id}` : `收合課堂 ${id}`;
      paint();
      return;
    }
    const edit = event.target.closest('[data-slp-edit]');
    if (edit) {
      const id = Number(edit.dataset.slpId);
      if (edit.dataset.slpEdit === 'copy') {
        const session = (context.sessions || []).find((item) => item.id === id);
        const code = session?.invite_code || '';
        if (code && navigator.clipboard) navigator.clipboard.writeText(code).catch(() => {});
        state.lastAction = `複製邀請碼 ${code}`;
      } else {
        state.lastAction = `點了${edit.dataset.slpEdit}（課堂 ${id}，不寫入）`;
      }
      paintState();
    }
  }

  function onPanelChange(event) {
    const select = event.target.closest('[data-slp-choice]');
    if (!select) return;
    const id = Number(select.dataset.slpChoice);
    state.choices[id] = select.value;
    state.lastAction = `課堂 ${id} 模型選擇 = ${select.value}`;
    paintState();
  }

  function paint() {
    if (!context || !context.box) return;
    const { box, sessions, courseStatus } = context;
    syncSessionState(sessions);
    ensureChrome();
    box.innerHTML = `<div class="slp-root"><p class="slp-banner">PROTOTYPE　這三種排法只改畫面，不寫入伺服器。左右方向鍵可切換。</p>${renderBody(sessions, courseStatus)}</div>`;
    paintState();
  }

  function render(box, classId, sessions, options) {
    context = {
      box,
      classId,
      sessions: sessions || [],
      courseStatus: options?.courseStatus || 'active',
    };
    if (!box.dataset.slpBound) {
      box.dataset.slpBound = '1';
      box.addEventListener('click', onPanelClick);
      box.addEventListener('change', onPanelChange);
      const observer = new ResizeObserver(() => {
        if (variantKey() !== 'D' || !context || context.box !== box) return;
        const wide = dIsWide(box.clientWidth);
        if (wide === state.dWide) return;
        paint();
      });
      observer.observe(box);
    }
    paint();
  }

  window.SessionLayoutPrototype = {
    variant: variantKey,
    render,
  };

  const CSS = `
    .slp-root { container-type: inline-size; padding-bottom: 88px; }
    .slp-banner {
      margin: 0 0 10px;
      padding: 6px 10px;
      border-radius: 8px;
      background: #111827;
      color: #f9fafb;
      font-size: 0.78rem;
    }
    .slp-stack { display: flex; flex-direction: column; gap: 12px; }
    .slp-card, .slp-inspector, .slp-band {
      border: 1px solid var(--border-strong);
      border-radius: 12px;
      background: var(--surface-1);
    }
    .slp-card, .slp-inspector { padding: 12px 14px; }
    .slp-head, .slp-head-actions, .slp-inline, .slp-title-row, .slp-invite {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 8px;
    }
    .slp-head { justify-content: space-between; align-items: flex-start; gap: 10px 16px; }
    .slp-identity { min-width: 0; }
    .slp-name { font-weight: 700; }
    .slp-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 10px;
      margin-top: 12px;
    }
    .slp-tile, .slp-prop, .slp-field {
      min-width: 0;
      border: 1px solid var(--border-glass);
      border-radius: 8px;
      padding: 8px 10px;
      background: var(--surface-overlay);
    }
    .slp-kicker {
      display: block;
      margin: 6px 0 4px;
      color: var(--text-muted);
      font-size: 0.75rem;
      font-weight: 600;
    }
    .slp-tile .slp-kicker:first-child, .slp-prop .slp-kicker:first-child, .slp-field .slp-kicker:first-child { margin-top: 0; }
    .slp-select { display: block; width: 100%; margin: 0; box-sizing: border-box; }
    .slp-caps { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 10px; }
    button.slp-seat, button.slp-row, button.slp-summary {
      margin: 0;
      box-shadow: none;
      font-weight: 500;
      text-align: left;
    }
    button.slp-seat {
      background: var(--surface-2);
      color: var(--text-primary);
      border: 1px solid var(--border-strong);
    }
    button.slp-seat:hover { background: var(--surface-3); }
    .slp-seat.is-open { border-color: var(--accent-border); color: var(--accent-text); }
    .slp-note { margin: 8px 0 0; color: var(--text-muted); font-size: 0.82rem; }
    .slp-split {
      display: grid;
      grid-template-columns: minmax(200px, 34%) minmax(0, 1fr);
      gap: 12px;
      align-items: start;
    }
    .slp-list { display: flex; flex-direction: column; gap: 6px; }
    button.slp-row, button.slp-summary {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 8px;
      width: 100%;
      background: var(--surface-1);
      color: var(--text-primary);
      border: 1px solid var(--border-strong);
    }
    button.slp-row:hover, button.slp-summary:hover { background: var(--surface-2); }
    .slp-row .slp-name, .slp-summary .slp-name { flex: 1 1 140px; }
    .slp-row .session-name-sub, .slp-summary .session-name-sub { display: inline; margin: 0; }
    button.slp-row.is-current, button.slp-row.is-current:hover { border-color: var(--accent-border); background: var(--accent-soft); }
    .slp-seat-text { color: var(--text-muted); font-size: 0.85rem; }
    .slp-band { overflow: hidden; }
    .slp-band + .slp-band { margin-top: 8px; }
    button.slp-summary { border: 0; border-radius: 12px; background: transparent; }
    button.slp-summary:hover { background: var(--surface-overlay); }
    .slp-band.is-open button.slp-summary { border-radius: 12px 12px 0 0; }
    .slp-rail {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      padding: 0 12px 12px;
    }
    .slp-prop { flex: 1 1 200px; }
    .slp-prop-wide { flex-basis: 100%; }
    .slp-models-span { grid-column: 1 / -1; }
    .slp-models-head { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
    .slp-models-title { display: inline-flex; align-items: center; gap: 6px; min-width: 0; }
    .slp-models-title .slp-kicker { margin: 0; }
    .slp-models-head .slp-select {
      width: auto;
      min-width: 6.5rem;
      margin: 0;
      padding: 3px 8px;
      border-radius: 999px;
      font-size: 0.82rem;
      line-height: 1.4;
      flex-shrink: 0;
    }
    .slp-model-pills {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 6px;
      max-height: 60px;
      margin-top: 8px;
      overflow: auto;
    }
    .slp-model-pill {
      display: inline-flex;
      align-items: center;
      max-width: 100%;
      padding: 3px 8px;
      border-radius: 999px;
      border: 1px solid var(--border-strong);
      background: var(--surface-2);
      color: var(--text-primary);
      font-size: 0.82rem;
      line-height: 1.4;
    }
    .slp-model-empty { color: var(--text-muted); font-size: 0.85rem; }
    .slp-form { display: flex; flex-direction: column; gap: 8px; margin-top: 12px; }
    .slp-inspector .slp-caps { margin-top: 12px; }
    @container (max-width: 640px) {
      .slp-split { grid-template-columns: 1fr; }
    }
    #slp-chrome { position: fixed; z-index: 80; left: 50%; bottom: 16px; transform: translateX(-50%); width: min(720px, calc(100vw - 24px)); }
    #slp-state {
      margin: 0;
      padding: 0 8px;
      overflow: hidden;
      background: transparent;
      color: #a7f3d0;
      font: 11px/1.4 ui-monospace, monospace;
      white-space: nowrap;
      text-overflow: ellipsis;
    }
    .slp-switcher {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
      padding: 6px 8px 6px 14px;
      border-radius: 999px;
      background: #111827;
      color: #f9fafb;
      box-shadow: 0 10px 30px rgba(0, 0, 0, 0.35);
    }
    .slp-switcher button {
      margin: 0;
      width: 34px;
      height: 34px;
      padding: 0;
      border-radius: 999px;
      background: #f9fafb;
      color: #111827;
      box-shadow: none;
      font-weight: 700;
    }
    .slp-switcher-text { display: flex; flex-direction: column; min-width: 0; text-align: center; }
    #slp-variant-label { font-size: 0.92rem; font-weight: 700; }
  `;
})();
