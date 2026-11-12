import { esc, $, $$, makeApi, toast, modal, formData, money, money2, addDays, hora, hm, dataCurta, diaSem, dataLonga, quando, todayLocal, utcToLocal, statusBadge, STATUS, d as toDate } from '/assets/common.js';

const TK = 'atende_admin_token';
const api = makeApi(TK, () => (localStorage.getItem('atende_tenant') ? { 'X-Tenant': localStorage.getItem('atende_tenant') } : {}));
const app = $('#app');
let ME = null; let ES = null;
const T = (k) => ME?.terms?.[k] || k;
const cap = (s) => s.charAt(0).toUpperCase() + s.slice(1);

const NAV = [
  ['sec', 'Operação'],
  ['dashboard', '📊', 'Dashboard'], ['agenda', '📅', 'Agenda'], ['conversas', '💬', 'Conversas'], ['clientes', '👥', () => cap(T('clientes'))], ['tratamentos', '📈', 'Tratamentos'], ['financeiro', '💰', 'Financeiro'],
  ['sec', 'Configuração'],
  ['automacao', '⚡', 'Automação & IA'], ['servicos', '🧾', 'Serviços'], ['profissionais', '🩺', () => cap(T('profissionais'))], ['integracoes', '🔌', 'Integrações'], ['empresa', '🏢', 'Empresa'], ['usuarios', '🔐', 'Usuários'],
  ['sec', 'Plataforma', 'superadmin'], ['empresas', '🌐', 'Empresas (SaaS)', 'superadmin'],
];

window.addEventListener('hashchange', route);
route();

async function route() {
  const [page, id] = location.hash.replace(/^#\/?/, '').split('/');
  if (!localStorage.getItem(TK) || page === 'login') return renderLogin();
  if (!ME) {
    try { ME = await api('/me'); } catch { return renderLogin(); }
    connectEvents();
  }
  renderShell(page || 'dashboard');
  const main = $('.main');
  const pages = { dashboard, agenda, conversas, clientes, tratamentos, financeiro, automacao, servicos, profissionais, integracoes, empresa, usuarios, empresas };
  try { await (pages[page || 'dashboard'] || dashboard)(main, id); } catch (e) { main.innerHTML += `<div class="card">${esc(e.message)}</div>`; }
}

function connectEvents() {
  ES?.close();
  const tenant = localStorage.getItem('atende_tenant') || '';
  ES = new EventSource(`/api/events?token=${localStorage.getItem(TK)}&tenant=${tenant}`);
  const refresh = debounce(() => window.dispatchEvent(new CustomEvent('live')), 250);
  ES.addEventListener('message', (e) => { const p = JSON.parse(e.data); window.dispatchEvent(new CustomEvent('live-msg', { detail: p })); refresh(); });
  ES.addEventListener('agenda', refresh);
  ES.addEventListener('conversation', (e) => { const p = JSON.parse(e.data); if (p.type === 'handoff') toast('🙋 Conversa transferida para a equipe: ' + (p.motivo || '')); refresh(); });
  ES.addEventListener('typing', (e) => window.dispatchEvent(new CustomEvent('live-typing', { detail: JSON.parse(e.data) })));
}
function debounce(fn, ms) { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; }
function onLive(fn) { const h = () => { if (document.body.contains(app)) fn(); }; window.addEventListener('live', h); window.addEventListener('hashchange', () => window.removeEventListener('live', h), { once: true }); }

// ---------------- Login ----------------
function renderLogin() {
  ME = null; ES?.close();
  app.innerHTML = `<div class="login"><form class="card col" id="f">
    <div class="brand"><div class="logo">A</div>Atende.AI</div>
    <div><h2>Entrar no painel</h2><p class="muted small">Gestão de atendimento, agenda e agente de IA.</p></div>
    <label class="f">E-mail<input name="email" value="admin@atende.ai" autocomplete="username"></label>
    <label class="f">Senha<input name="password" type="password" value="admin123" autocomplete="current-password"></label>
    <button class="btn primary">Entrar</button>
    <div class="small muted">Acessos de teste:<br>• admin@atende.ai / admin123 (plataforma)<br>• gestor@movimento.com / 123456 (clínica)<br>• recepcao@movimento.com / 123456 (recepção)</div>
  </form></div>`;
  $('#f').onsubmit = async (e) => {
    e.preventDefault();
    try {
      const r = await api('/auth/login', { method: 'POST', body: formData(e.target) });
      localStorage.setItem(TK, r.token);
      if (r.user.role !== 'superadmin') localStorage.removeItem('atende_tenant');
      location.hash = '#/dashboard'; route();
    } catch (err) { toast(err.message, true); }
  };
}

// ---------------- Shell ----------------
function renderShell(page) {
  const sup = ME.user.role === 'superadmin';
  app.innerHTML = `<div class="shell"><aside class="side">
    <div class="brand"><div class="logo">A</div>Atende.AI</div>
    <nav class="nav">${NAV.filter((n) => (n[0] === 'sec' ? !n[2] || sup : !n[3] || sup)).map((n) => n[0] === 'sec' ? `<div class="sec">${n[1]}</div>` :
      `<a href="#/${n[0]}" class="${page === n[0] ? 'on' : ''}"><span>${n[1]}</span>${typeof n[2] === 'function' ? n[2]() : n[2]}${n[0] === 'conversas' ? '<span class="n" id="unread" hidden></span>' : ''}</a>`).join('')}</nav>
    <div class="grow"></div>
    <div class="card tight small" style="margin-top:12px">
      <div class="row"><span class="dot" style="background:${ME.tenant?.automation_active ? 'var(--green)' : 'var(--dim)'}"></span>Agente ${ME.tenant?.automation_active ? 'ativo' : 'desligado'}</div>
      <div class="muted">${ME.agent.mode === 'claude' ? 'IA: ' + esc(ME.agent.model) : 'Modo regras (sem chave de IA)'}</div>
    </div>
    <div class="row small" style="padding:10px 6px"><div class="grow"><b>${esc(ME.user.name)}</b><div class="muted">${esc(ME.user.role)}</div></div><button class="btn sm" id="logout">Sair</button></div>
  </aside><main class="main"></main></div>`;
  $('#logout').onclick = () => { localStorage.removeItem(TK); localStorage.removeItem('atende_tenant'); ME = null; location.hash = '#/login'; };
  updateUnread();
}
async function updateUnread() {
  try { const c = await api('/conversations'); const n = c.reduce((a, v) => a + (v.unread || 0), 0) + c.filter((v) => v.mode === 'humano').length; const el = $('#unread'); if (el) { el.hidden = !n; el.textContent = n; } } catch {}
}
async function header(main, title, sub = '', actions = '') {
  let sel = '';
  if (ME.user.role === 'superadmin') {
    const ts = await api('/tenants');
    sel = `<select class="tenant-sel" id="tsel">${ts.map((t) => `<option value="${t.id}" ${t.id === ME.tenant?.id ? 'selected' : ''}>${esc(t.name)}</option>`).join('')}</select>`;
  }
  main.innerHTML = `<div class="top"><div><h1>${title}</h1>${sub ? `<div class="muted small">${sub}</div>` : ''}</div><div class="right row wrap">${actions}${sel}</div></div><div id="content"></div>`;
  const ts = $('#tsel'); if (ts) ts.onchange = () => { localStorage.setItem('atende_tenant', ts.value); ME = null; route(); };
  return $('#content');
}

// ---------------- Dashboard ----------------
async function dashboard(main) {
  const c = await header(main, 'Dashboard', `${esc(ME.tenant.name)} · últimos 30 dias`, `<button class="btn sm" id="jobs">⏱ Rodar lembretes/rotinas</button>`);
  $('#jobs').onclick = async () => { const r = await api('/jobs/run', { method: 'POST' }); toast(`Rotinas: ${r.lembretes} lembretes, ${r.recuperacoes} recuperações de falta`); };
  const draw = async () => {
    const k = await api('/dashboard?days=30');
    const max = Math.max(1, ...k.series.map((s) => s.agente + s.equipe));
    const roiMax = Math.max(k.receita_agente, k.custo_automacao, 1);
    const step = (s) => k.pipeline.find((p) => p.step === s) || {};
    c.innerHTML = `
    <div class="grid g4">
      ${kpi('Receita gerada pelo agente', money(k.receita_agente), `${k.agendamentos_agente} agendamentos feitos pela IA`, 'green')}
      ${kpi('Retorno sobre a automação', k.roi ? k.roi.toFixed(1) + 'x' : '—', `custo ${money(k.custo_automacao)} no período`)}
      ${kpi('Fora do horário comercial', k.fora_do_horario, `${T('clientes')} que iriam para outra clínica`)}
      ${kpi('Tempo médio de atendimento', k.tempo_medio_resposta_ms ? (k.tempo_medio_resposta_ms / 1000).toFixed(1) + ' s' : '—', 'do áudio à confirmação')}
      ${kpi('Conversas', k.conversas, `${k.mensagens_agente} mensagens do agente`)}
      ${kpi('Comparecimento', k.comparecimento != null ? k.comparecimento + '%' : '—', `${k.realizados} realizados · ${k.faltas} faltas`)}
      ${kpi('Faltas recuperadas', k.recuperados, 'remarcadas automaticamente')}
      ${kpi('Tratamentos ativos', k.tratamentos.ativos || 0, `${k.tratamentos.concluidos || 0} concluídos · ${k.transferidos_humano} com humano`)}
    </div>
    <div class="grid g2" style="margin-top:14px">
      <div class="card"><div class="row between"><h3>${cap(T('clientes'))} recuperados × automação</h3><span class="badge ${k.roi >= 1 ? 'green' : ''}">${k.roi >= 1 ? 'JÁ SE PAGOU ✓' : 'em andamento'}</span></div>
        <div class="roi">
          <div class="c"><b>${money(k.receita_agente)}</b><i style="height:${(k.receita_agente / roiMax) * 120}px;background:var(--green)"></i><span class="small muted">receita via agente</span></div>
          <div class="c"><b>${money(k.custo_automacao)}</b><i style="height:${(k.custo_automacao / roiMax) * 120}px;background:#3f3f46"></i><span class="small muted">automação</span></div>
        </div></div>
      <div class="card"><div class="row between"><h3>Novos agendamentos (14 dias)</h3><span class="small muted"><span class="dot" style="background:var(--green)"></span> agente &nbsp; <span class="dot" style="background:#3f3f46"></span> equipe</span></div>
        <div class="bars">${k.series.map((s) => `<div class="b" title="${s.d}: ${s.agente} agente, ${s.equipe} equipe"><i style="height:${(s.equipe / max) * 130}px;background:#3f3f46"></i><i style="height:${(s.agente / max) * 130}px;background:var(--green)"></i><small>${dataCurta(s.d)}</small></div>`).join('') || '<div class="empty">Sem dados</div>'}</div><div style="height:16px"></div></div>
    </div>
    <div class="grid g3" style="margin-top:14px">
      <div class="card"><h3>Pipeline do agente</h3><div class="col" style="margin-top:10px">
        ${[['whatsapp', '🟢 WhatsApp', 'chega a mensagem'], ['transcreve', '🎙 Transcreve', 'áudio → texto'], ['agente_ia', '✳️ Agente de IA', 'entende e decide'], ['agenda', '📅 Agenda', 'acha horário livre'], ['responde', '✅ Responde', 'confirma no WhatsApp']]
          .map(([s, l, d]) => `<div class="row between"><span>${l} <span class="dim small">${d}</span></span><span class="small muted">${step(s).n || 0}× ${step(s).avg_ms ? '· ' + (step(s).avg_ms / 1000).toFixed(1) + 's' : ''}</span></div>`).join('')}</div></div>
      <div class="card"><h3>Ocupação próximos 7 dias</h3><div class="col" style="margin-top:10px">${k.occupancy.map((o) => `<div><div class="row between small"><span><span class="dot" style="background:${o.color}"></span> ${esc(o.name)}</span><span class="muted">${o.n} horários</span></div><div class="progress"><i style="width:${Math.min(100, (o.n / 90) * 100)}%;background:${o.color}"></i></div></div>`).join('')}</div></div>
      <div class="card"><h3>Serviços que mais faturam</h3><table style="margin-top:6px">${k.topServices.map((s) => `<tr><td>${esc(s.name)}</td><td class="muted">${s.n}</td><td style="text-align:right">${money(s.v)}</td></tr>`).join('')}</table></div>
    </div>`;
  };
  await draw(); onLive(draw);
}
const kpi = (l, v, s, color) => `<div class="card kpi"><div class="small muted">${l}</div><div class="v" style="${color ? 'color:var(--' + color + ')' : ''}">${v}</div><div class="s">${s}</div></div>`;

// ---------------- Agenda ----------------
let agendaDate = todayLocal(); let agendaView = 'dia';
async function agenda(main) {
  const c = await header(main, 'Agenda', 'Visão da recepção · eventos marcados pelo agente têm o selo ✳️', `
    <div class="tabs"><button data-v="dia" class="${agendaView === 'dia' ? 'on' : ''}">Dia</button><button data-v="mes" class="${agendaView === 'mes' ? 'on' : ''}">Mês</button></div>
    <button class="btn sm" id="prev">‹</button><input type="date" id="date" value="${agendaDate}" style="width:150px"><button class="btn sm" id="next">›</button><button class="btn sm" id="hoje">Hoje</button>
    <button class="btn primary sm" id="novo">+ Agendamento</button>`);
  $$('[data-v]').forEach((b) => (b.onclick = () => { agendaView = b.dataset.v; agenda(main); }));
  $('#prev').onclick = () => { agendaDate = agendaView === 'dia' ? addDays(agendaDate, -1) : addDays(agendaDate.slice(0, 8) + '01', -1).slice(0, 8) + '01'; agenda(main); };
  $('#next').onclick = () => { agendaDate = agendaView === 'dia' ? addDays(agendaDate, 1) : addDays(agendaDate.slice(0, 8) + '28', 7).slice(0, 8) + '01'; agenda(main); };
  $('#hoje').onclick = () => { agendaDate = todayLocal(); agenda(main); };
  $('#date').onchange = (e) => { agendaDate = e.target.value; agenda(main); };
  $('#novo').onclick = () => newAppointment({ start: agendaDate + 'T09:00' });
  const draw = async () => (agendaView === 'dia' ? drawDay(c) : drawMonth(c));
  await draw(); onLive(draw);
}

async function drawDay(c) {
  const data = await api(`/agenda?from=${agendaDate}&days=1`);
  const START = 7 * 60, END = 21 * 60, STEP = 30, H = 28;
  const rows = (END - START) / STEP;
  const wd = toDate(agendaDate).getUTCDay();
  const profs = data.professionals;
  if (!profs.length) { c.innerHTML = '<div class="card empty">Cadastre profissionais para ver a agenda.</div>'; return; }
  const tcol = Array.from({ length: rows }, (_, i) => { const m = START + i * STEP; return `<div class="tcell" style="height:${H}px">${m % 60 === 0 ? String(m / 60).padStart(2, '0') + ':00' : ''}</div>`; }).join('');
  const cols = profs.map((p) => {
    const sched = JSON.parse(p.schedule_json || '{}')[wd] || [];
    const slots = Array.from({ length: rows }, (_, i) => {
      const m = START + i * STEP; const t = `${String(Math.floor(m / 60)).padStart(2, '0')}:${String(m % 60).padStart(2, '0')}`;
      const on = sched.some(([a, b]) => t >= a && t < b);
      return `<div class="slot ${on ? 'free' : 'off'}" style="height:${H}px" data-p="${p.id}" data-t="${agendaDate}T${t}"></div>`;
    }).join('');
    const evs = data.appointments.filter((a) => a.professional_id === p.id).map((a) => {
      const s = (+a.start.slice(11, 13)) * 60 + (+a.start.slice(14, 16)); const e = (+a.end.slice(11, 13)) * 60 + (+a.end.slice(14, 16));
      return `<div class="ev ${a.status} ${a.created_by}" data-a="${a.id}" style="top:${((s - START) / STEP) * H + 2}px;height:${((e - s) / STEP) * H - 4}px;border-left-color:${p.color}">
        <div class="t">${a.created_by === 'agente' ? '✳️ ' : ''}${esc(a.client_name || a.client_phone)} <span class="s">${hm(a.start)}</span></div>
        <div class="s">${esc(a.service_name)}${a.session_number ? ` · ${T('sessao')} ${a.session_number}` : ''} · ${STATUS[a.status]?.[0] || a.status}</div></div>`;
    }).join('');
    return `<div style="position:relative">${slots}${evs}</div>`;
  }).join('');
  c.innerHTML = `<div class="row" style="margin-bottom:10px"><h3>${cap(dataLonga(agendaDate))}</h3><span class="muted small right">${data.appointments.filter((a) => !['cancelado'].includes(a.status)).length} atendimentos</span></div>
   <div class="agenda" style="grid-template-columns:64px repeat(${profs.length}, minmax(180px,1fr))">
    <div class="hcell"></div>${profs.map((p) => `<div class="hcell"><span class="dot" style="background:${p.color}"></span>${esc(p.name)} <span class="muted small">${esc(p.specialty || '')}</span></div>`).join('')}
    <div>${tcol}</div>${cols}</div>`;
  $$('.slot.free', c).forEach((s) => (s.onclick = () => newAppointment({ start: s.dataset.t, professional_id: +s.dataset.p })));
  $$('.ev', c).forEach((e) => (e.onclick = (ev) => { ev.stopPropagation(); openAppointment(+e.dataset.a, data.appointments.find((a) => a.id === +e.dataset.a)); }));
}

async function drawMonth(c) {
  const first = agendaDate.slice(0, 8) + '01';
  const startDow = (toDate(first).getUTCDay() + 6) % 7; // segunda=0
  const gridStart = addDays(first, -startDow);
  const data = await api(`/agenda?from=${gridStart}&days=42`);
  const today = todayLocal();
  const byDay = {};
  for (const a of data.appointments) if (a.status !== 'cancelado') (byDay[a.start.slice(0, 10)] ||= []).push(a);
  const agentN = data.appointments.filter((a) => a.created_by === 'agente' && a.start.slice(0, 7) === first.slice(0, 7)).length;
  c.innerHTML = `<div class="row" style="margin-bottom:10px"><h3>Recepção · agenda — ${first.slice(5, 7)}/${first.slice(0, 4)}</h3><span class="badge orange right">✳️ ${agentN} agendados pelo agente</span></div>
   <div class="month">${['seg', 'ter', 'qua', 'qui', 'sex', 'sáb', 'dom'].map((x) => `<div class="small muted" style="padding:0 4px">${x}</div>`).join('')}
   ${Array.from({ length: 42 }, (_, i) => { const day = addDays(gridStart, i); const list = byDay[day] || [];
      return `<div class="day ${day === today ? 'today' : ''}" style="${day.slice(0, 7) !== first.slice(0, 7) ? 'opacity:.4' : ''}"><div class="small muted row between"><span>${+day.slice(8)}</span>${list.length ? `<span>${list.length}</span>` : ''}</div>
      ${list.slice(0, 4).map((a) => `<div class="chip ${a.created_by} ${a.status}" data-a="${a.id}" title="${esc(a.client_name)} ${hm(a.start)}">${hm(a.start)} ${esc((a.client_name || '').split(' ')[0])}</div>`).join('')}${list.length > 4 ? `<div class="small dim" data-day="${day}" style="cursor:pointer">+${list.length - 4}</div>` : ''}</div>`; }).join('')}</div>`;
  $$('.chip', c).forEach((e) => (e.onclick = () => openAppointment(+e.dataset.a, data.appointments.find((a) => a.id === +e.dataset.a))));
  $$('[data-day]', c).forEach((e) => (e.onclick = () => { agendaDate = e.dataset.day; agendaView = 'dia'; route(); }));
}

async function newAppointment({ start, professional_id, client_id } = {}) {
  const [svcs, profs] = await Promise.all([api('/services'), api('/professionals')]);
  const m = modal('Novo agendamento', `
    ${client_id ? `<input type="hidden" name="client_id" value="${client_id}">` : `<div class="grid g2"><label class="f">Nome do ${T('cliente')}<input name="client_name" required></label><label class="f">WhatsApp (DDD+número)<input name="client_phone" placeholder="11999999999"></label></div>`}
    <label class="f">Serviço<select name="service_id">${svcs.filter((s) => s.active).map((s) => `<option value="${s.id}">${esc(s.name)} · ${s.duration_min}min · ${money(s.price)}</option>`).join('')}</select></label>
    <label class="f">${cap(T('profissional'))}<select name="professional_id">${profs.filter((p) => p.active).map((p) => `<option value="${p.id}" ${p.id === professional_id ? 'selected' : ''}>${esc(p.name)}</option>`).join('')}</select></label>
    <label class="f">Início<input type="datetime-local" name="start" value="${start || ''}" step="1800"></label>
    <label class="row small"><input type="checkbox" name="package"> Reservar pacote de ${T('sessoes')} (se o serviço tiver)</label>
    <label class="f">Observações<input name="notes"></label>`, {
    onSave: async (el) => { const b = formData(el); await api('/appointments', { method: 'POST', body: b }); toast('Agendamento criado'); window.dispatchEvent(new Event('live')); },
  });
  return m;
}

function openAppointment(id, a) {
  if (!a) return;
  const m = modal(`${a.service_name}${a.session_number ? ` · ${T('sessao')} ${a.session_number}` : ''}`, `
    <div class="row wrap">${statusBadge(a.status)} ${a.created_by === 'agente' ? '<span class="badge orange">✳️ agendado pelo agente</span>' : `<span class="badge">via ${a.created_by}</span>`}</div>
    <div class="grid g2">
      <div><div class="small muted">${cap(T('cliente'))}</div><a href="#/clientes/${a.client_id}" data-x>${esc(a.client_name || '—')}</a><div class="small muted">${esc(a.client_phone)}</div></div>
      <div><div class="small muted">Quando</div>${cap(dataLonga(a.start))} · ${hm(a.start)}–${hm(a.end)}<div class="small muted">${esc(a.professional_name)}</div></div>
    </div>
    ${a.notes ? `<div class="small muted">Obs.: ${esc(a.notes)}</div>` : ''}
    <div class="row wrap">
      <button class="btn sm" data-s="confirmado">✓ Confirmar</button><button class="btn sm" data-s="realizado">✔ Realizado</button>
      <button class="btn sm danger" data-s="faltou">✗ Faltou (IA remarca)</button><button class="btn sm danger" data-s="cancelado">Cancelar</button>
    </div>
    <div class="row"><input type="datetime-local" id="rs" step="1800" value="${a.start}"><button class="btn sm" id="rsb">Remarcar</button></div>`);
  $$('[data-s]', m.el).forEach((b) => (b.onclick = async () => {
    try { await api(`/appointments/${id}`, { method: 'PATCH', body: { status: b.dataset.s } }); toast(b.dataset.s === 'faltou' ? 'Falta registrada — o agente enviou mensagem para remarcar' : 'Status atualizado'); m.close(); window.dispatchEvent(new Event('live')); } catch (e) { toast(e.message, true); }
  }));
  $('#rsb', m.el).onclick = async () => { try { await api(`/appointments/${id}/reschedule`, { method: 'POST', body: { start: $('#rs', m.el).value } }); toast('Remarcado'); m.close(); window.dispatchEvent(new Event('live')); } catch (e) { toast(e.message, true); } };
}

// ---------------- Conversas ----------------
let convFilter = 'todas';
async function conversas(main, id) {
  const c = await header(main, 'Conversas', 'WhatsApp · o agente atende 24h; assuma quando quiser',
    `<div class="tabs">${['todas', 'humano', 'bot'].map((f) => `<button data-f="${f}" class="${convFilter === f ? 'on' : ''}">${{ todas: 'Todas', humano: 'Precisa de humano', bot: 'Com o agente' }[f]}</button>`).join('')}</div>`);
  $$('[data-f]').forEach((b) => (b.onclick = () => { convFilter = b.dataset.f; conversas(main, id); }));
  c.innerHTML = `<div class="inbox"><div class="list" id="clist"></div><div class="chat" id="chat"><div class="empty" style="margin:auto">Selecione uma conversa</div></div><div class="info" id="cinfo"></div></div>`;
  const drawList = async () => {
    const list = (await api('/conversations')).filter((v) => convFilter === 'todas' || v.mode === convFilter);
    $('#clist').innerHTML = list.map((v) => `<div class="item ${+id === v.id ? 'on' : ''}" data-id="${v.id}"><div class="avatar">${esc((v.client_name || '?')[0])}</div>
      <div class="grow" style="min-width:0"><div class="row"><b class="grow" style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(v.client_name || v.client_phone)}</b><span class="small dim">${utcToLocal(v.last_message_at).slice(6)}</span></div>
      <div class="row"><span class="small muted grow" style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${v.last_type === 'audio' ? '🎙 ' : v.last_type === 'image' ? '📷 ' : ''}${esc(v.last_text || '')}</span>
      ${v.mode === 'humano' ? '<span class="badge amber">humano</span>' : ''}${v.unread ? `<span class="n" style="background:var(--green);color:#000;border-radius:99px;font-size:10px;padding:1px 6px">${v.unread}</span>` : ''}</div></div></div>`).join('') || '<div class="empty">Nenhuma conversa ainda. Teste pelo app do cliente: <a href="/cliente" target="_blank">/cliente</a></div>';
    $$('.item', $('#clist')).forEach((el) => (el.onclick = () => (location.hash = `#/conversas/${el.dataset.id}`)));
  };
  await drawList();
  if (id) await openConv(+id);
  onLive(async () => { await drawList(); updateUnread(); if (id) await openConv(+id, true); });
}

async function openConv(id, keepScroll) {
  const r = await api(`/conversations/${id}`);
  const chat = $('#chat'); if (!chat) return;
  const prevScroll = $('.msgs', chat)?.scrollTop;
  chat.innerHTML = `<div class="head"><div class="avatar">${esc((r.client.name || '?')[0])}</div><div class="grow"><b>${esc(r.client.name || r.client.phone)}</b><div class="small muted">${esc(r.client.phone)} · ${r.conversation.channel}</div></div>
    ${r.conversation.mode === 'humano' ? '<button class="btn sm" id="tobot">↩ Devolver ao agente</button>' : '<button class="btn sm" id="tohuman">🙋 Assumir conversa</button>'}</div>
    <div class="msgs">${r.messages.map(bubble).join('')}<div id="typing"></div></div>
    <form class="composer"><input name="text" placeholder="Responder como equipe (assume a conversa)…" autocomplete="off"><button class="btn primary">Enviar</button></form>`;
  const msgs = $('.msgs', chat); msgs.scrollTop = keepScroll && prevScroll != null ? msgs.scrollHeight : msgs.scrollHeight;
  $('form', chat).onsubmit = async (e) => { e.preventDefault(); const t = e.target.text.value.trim(); if (!t) return; e.target.text.value = ''; await api(`/conversations/${id}/reply`, { method: 'POST', body: { text: t } }); };
  $('#tohuman')?.addEventListener('click', () => api(`/conversations/${id}/mode`, { method: 'POST', body: { mode: 'humano' } }));
  $('#tobot')?.addEventListener('click', () => api(`/conversations/${id}/mode`, { method: 'POST', body: { mode: 'bot' } }));
  const tr = r.conversation.triage;
  const det = await api(`/clients/${r.client.id}`);
  const up = det.appointments.filter((a) => ['confirmado', 'pendente'].includes(a.status) && a.start >= todayLocal()).reverse();
  $('#cinfo').innerHTML = `
    ${tr ? `<div class="triage"><b class="row"><span style="color:var(--orange)">✳</span> O agente entendeu</b><ul>${(tr.pontos?.length ? tr.pontos : [tr.queixa]).map((p, i) => `<li><span class="dot" style="background:${i === 0 ? 'var(--red)' : 'var(--green)'}"></span>${esc(p)}</li>`).join('')}</ul>
      ${tr.urgencia ? `<div class="small muted" style="margin-top:6px">Urgência: ${esc(tr.urgencia)}</div>` : ''}</div>` : ''}
    <div><h4>${cap(T('cliente'))}</h4><div style="margin-top:6px"><a href="#/clientes/${r.client.id}">${esc(r.client.name || '—')}</a><div class="small muted">${esc(r.client.phone)}${r.client.email ? ' · ' + esc(r.client.email) : ''}</div></div></div>
    <div><h4>Próximos horários</h4>${up.slice(0, 5).map((a) => `<div class="small row between" style="margin-top:5px"><span>${quando(a.start)}</span><span class="muted">${esc(a.professional_name)}</span></div>`).join('') || '<div class="small dim">nenhum</div>'}
      <button class="btn sm" style="margin-top:8px" id="agendarAqui">+ Agendar</button></div>
    ${det.treatments.map((t) => `<div><h4>${esc(t.service_name)} · ${t.done}/${t.total_sessions}</h4><div class="progress" style="margin-top:6px"><i style="width:${(t.done / t.total_sessions) * 100}%"></i></div></div>`).join('')}
    ${det.documents.length ? `<div><h4>Documentos</h4><div class="row wrap" style="margin-top:6px">${det.documents.map((d) => `<a href="/api/documents/${d.id}?token=${localStorage.getItem(TK)}&tenant=${localStorage.getItem('atende_tenant') || ''}" target="_blank"><img src="/api/documents/${d.id}?token=${localStorage.getItem(TK)}&tenant=${localStorage.getItem('atende_tenant') || ''}" style="width:72px;height:72px;object-fit:cover;border-radius:8px;border:1px solid var(--line2)"></a>`).join('')}</div></div>` : ''}
    <div><h4>Linha do tempo da automação</h4><div class="col small" style="margin-top:6px;gap:4px">${r.logs.slice(0, 12).map((l) => `<div class="row between"><span>${esc(l.step)}</span><span class="dim">${l.ms != null ? (l.ms / 1000).toFixed(1) + 's' : ''} ${utcToLocal(l.created_at).slice(6)}</span></div>`).join('')}</div></div>`;
  $('#agendarAqui').onclick = () => newAppointment({ client_id: r.client.id, start: todayLocal() + 'T09:00' });
}
window.addEventListener('live-typing', (e) => { const t = $('#typing'); if (t && location.hash.endsWith('/' + e.detail.conversationId)) t.innerHTML = e.detail.typing ? '<div class="bubble out" style="opacity:.7">digitando…</div>' : ''; });

function bubble(m) {
  const time = `<div class="time">${utcToLocal(m.created_at).slice(6)}</div>`;
  if (m.sender === 'sistema' || m.type === 'note') return `<div class="sysnote">${esc(m.content)}</div>`;
  const out = m.sender !== 'cliente';
  const cls = `bubble ${out ? 'out' : 'in'} ${m.sender === 'humano' ? 'human' : ''}`;
  const tag = m.sender === 'agente' ? '<span class="tag">✳ agente IA</span>' : m.sender === 'humano' ? `<span class="tag" style="color:#fde68a">🙋 ${esc(m.meta?.user || 'equipe')}</span>` : '';
  let body = esc(m.content);
  if (m.type === 'audio') body = `🎙 <i>Áudio</i>${m.meta?.has_audio ? ` <audio controls src="/api/messages/${m.id}/audio?token=${localStorage.getItem(TK)}&tenant=${localStorage.getItem('atende_tenant') || ''}" style="height:28px;vertical-align:middle;max-width:200px"></audio>` : ''}<div class="small" style="color:#a7f3d0;margin-top:4px">✎ Transcrição</div>${esc(m.content)}`;
  if (m.type === 'image') body = `📷 Imagem${m.meta?.document_id ? `<br><img src="/api/documents/${m.meta.document_id}?token=${localStorage.getItem(TK)}&tenant=${localStorage.getItem('atende_tenant') || ''}" style="max-width:200px;border-radius:6px;margin-top:4px">` : ''}${m.content ? '<br>' + esc(m.content) : ''}`;
  if (m.type === 'options') body += `<div class="opts">${(m.meta?.options || []).map((o) => `<span>${esc(o.label)}</span>`).join('')}</div>`;
  if (m.type === 'appointment') body = `<b>✅ ${esc(m.meta?.service_name)}</b><br>📅 ${quando(m.meta?.start || '')}<br>👤 ${esc(m.meta?.professional_name)}`;
  if (m.type === 'package') body = `<b>📅 ${m.meta?.sessions?.length} ${T('sessoes')} reservadas</b><br><span class="small">${(m.meta?.sessions || []).map((s) => `${s.n}ª ${quando(s.start)}`).join('<br>')}</span>`;
  if (m.type === 'location') body = `📍 <b>${esc(m.meta?.name)}</b><br>${esc(m.meta?.address)}`;
  return `<div class="${cls}">${tag}${body}${time}</div>`;
}

// ---------------- Clientes ----------------
async function clientes(main, id) {
  if (id) return clienteDetalhe(main, +id);
  const c = await header(main, cap(T('clientes')), 'CRM com histórico, documentos e tratamentos', `<input id="q" placeholder="Buscar nome ou telefone" style="width:220px"><button class="btn primary sm" id="novo">+ Novo</button>`);
  const draw = async () => {
    const list = await api('/clients?q=' + encodeURIComponent($('#q')?.value || ''));
    c.innerHTML = `<div class="card" style="padding:0"><table><tr><th>Nome</th><th>WhatsApp</th><th>Origem</th><th>Última visita</th><th>Próximo horário</th><th>Atend.</th></tr>
      ${list.map((x) => `<tr class="click" data-id="${x.id}"><td><b>${esc(x.name || '—')}</b></td><td class="muted">${esc(x.phone)}</td><td><span class="badge">${esc(x.source)}</span></td><td class="muted">${x.last_visit ? quando(x.last_visit) : '—'}</td><td>${x.next_visit ? quando(x.next_visit) : '<span class="dim">—</span>'}</td><td>${x.total}</td></tr>`).join('')}</table></div>`;
    $$('tr.click', c).forEach((r) => (r.onclick = () => (location.hash = `#/clientes/${r.dataset.id}`)));
  };
  $('#q').oninput = debounce(draw, 250);
  $('#novo').onclick = () => modal(`Novo ${T('cliente')}`, clientForm({}), { onSave: async (el) => { await api('/clients', { method: 'POST', body: formData(el) }); draw(); } });
  await draw();
}
const clientForm = (x) => `<div class="grid g2"><label class="f">Nome<input name="name" value="${esc(x.name || '')}"></label><label class="f">WhatsApp<input name="phone" value="${esc(x.phone || '')}"></label>
  <label class="f">E-mail<input name="email" value="${esc(x.email || '')}"></label><label class="f">Nascimento<input type="date" name="birthdate" value="${esc(x.birthdate || '')}"></label>
  <label class="f">CPF/Documento<input name="document" value="${esc(x.document || '')}"></label><label class="f">Tags<input name="tags" value="${esc(x.tags || '')}"></label></div>
  <label class="f">Anotações<textarea name="notes">${esc(x.notes || '')}</textarea></label>`;

async function clienteDetalhe(main, id) {
  const r = await api(`/clients/${id}`); const x = r.client;
  const c = await header(main, esc(x.name || x.phone), `${esc(x.phone)} · ${T('cliente')} desde ${utcToLocal(x.created_at).slice(0, 5)} · LGPD ${x.consent_lgpd ? '✓ consentimento' : 'pendente'}`,
    `<a class="btn sm" href="#/clientes">← Voltar</a><button class="btn sm" id="ed">Editar</button><button class="btn sm" id="ag">+ Agendar</button><button class="btn sm" id="pg">+ Pagamento</button>${r.conversation ? `<a class="btn sm" href="#/conversas/${r.conversation.id}">💬 Conversa</a>` : ''}<button class="btn sm danger" id="del">Excluir (LGPD)</button>`);
  $('#ed').onclick = () => modal('Editar', clientForm(x), { onSave: async (el) => { await api(`/clients/${id}`, { method: 'PUT', body: formData(el) }); clienteDetalhe(main, id); } });
  $('#ag').onclick = () => newAppointment({ client_id: id, start: todayLocal() + 'T09:00' });
  $('#pg').onclick = () => modal('Registrar pagamento', `<label class="f">Valor<input type="number" name="amount" step="0.01"></label><label class="f">Forma<select name="method"><option value="pix">Pix</option><option value="cartao">Cartão</option><option value="dinheiro">Dinheiro</option><option value="convenio">Convênio</option></select></label>
    <label class="f">Tratamento<select name="treatment_id"><option value="">—</option>${r.treatments.map((t) => `<option value="${t.id}">${esc(t.service_name)} (${t.total_sessions}x)</option>`).join('')}</select></label>`,
    { onSave: async (el) => { const b = formData(el); b.client_id = id; b.treatment_id = b.treatment_id || null; await api('/payments', { method: 'POST', body: b }); toast('Pagamento registrado'); clienteDetalhe(main, id); } });
  $('#del').onclick = async () => { if (confirm('Excluir definitivamente este cadastro e todo o histórico (direito de exclusão LGPD)?')) { await api(`/clients/${id}`, { method: 'DELETE' }); location.hash = '#/clientes'; } };
  const tr = r.conversation?.triage;
  c.innerHTML = `<div class="grid g3">
    <div class="card col"><h3>Dados</h3><div class="small">${x.email ? '✉️ ' + esc(x.email) + '<br>' : ''}${x.birthdate ? '🎂 ' + esc(x.birthdate) + '<br>' : ''}${x.document ? '🪪 ' + esc(x.document) + '<br>' : ''}${x.tags ? '🏷 ' + esc(x.tags) : ''}</div>${x.notes ? `<div class="small muted">${esc(x.notes)}</div>` : ''}
      ${tr ? `<div class="triage"><b>✳ O agente entendeu</b><ul>${(tr.pontos?.length ? tr.pontos : [tr.queixa]).map((p) => `<li>• ${esc(p)}</li>`).join('')}</ul></div>` : ''}</div>
    <div class="card col"><h3>Tratamentos</h3>${r.treatments.map((t) => `<div><div class="row between"><b>${esc(t.service_name)}</b><span class="badge ${t.status === 'ativo' ? 'green' : ''}">${t.status}</span></div><div class="small muted">${t.done}/${t.total_sessions} ${T('sessoes')} · ${money(t.total_sessions * t.session_price)}</div><div class="progress" style="margin-top:5px"><i style="width:${(t.done / t.total_sessions) * 100}%"></i></div></div>`).join('') || '<div class="dim small">Nenhum</div>'}</div>
    <div class="card col"><h3>Documentos & pagamentos</h3><div class="row wrap">${r.documents.map((d) => `<a target="_blank" href="/api/documents/${d.id}?token=${localStorage.getItem(TK)}&tenant=${localStorage.getItem('atende_tenant') || ''}" class="badge blue">📎 ${esc(d.kind || 'doc')} ${utcToLocal(d.created_at).slice(0, 5)}</a>`).join('') || '<span class="dim small">Sem documentos</span>'}</div>
      ${r.payments.map((p) => `<div class="row between small"><span>${utcToLocal(p.created_at).slice(0, 5)} · ${esc(p.method)}</span><b>${money2(p.amount)}</b></div>`).join('')}</div>
  </div>
  <div class="card" style="margin-top:14px;padding:0"><table><tr><th>Quando</th><th>Serviço</th><th>${cap(T('profissional'))}</th><th>Origem</th><th>Status</th><th>Valor</th></tr>
    ${r.appointments.map((a) => `<tr><td>${quando(a.start)}</td><td>${esc(a.service_name)}${a.session_number ? ` <span class="dim">#${a.session_number}</span>` : ''}</td><td>${esc(a.professional_name)}</td><td>${a.created_by === 'agente' ? '✳️ agente' : a.created_by}</td><td>${statusBadge(a.status)}</td><td>${money(a.price)}</td></tr>`).join('')}</table></div>`;
}

// ---------------- Tratamentos ----------------
async function tratamentos(main) {
  const c = await header(main, 'Tratamentos & pacotes', `Acompanhe o progresso e evite abandono de tratamento`);
  const list = await api('/treatments');
  c.innerHTML = `<div class="card" style="padding:0"><table><tr><th>${cap(T('cliente'))}</th><th>Serviço</th><th>${cap(T('profissional'))}</th><th>Progresso</th><th>Faltas</th><th>Próxima</th><th>Valor</th><th>Status</th><th></th></tr>
    ${list.map((t) => `<tr><td><a href="#/clientes/${t.client_id}">${esc(t.client_name)}</a></td><td>${esc(t.service_name)}</td><td>${esc(t.professional_name || '')}</td>
      <td style="min-width:140px"><div class="small">${t.done}/${t.total_sessions}</div><div class="progress"><i style="width:${(t.done / t.total_sessions) * 100}%"></i></div></td>
      <td>${t.missed ? `<span class="badge red">${t.missed}</span>` : '0'}</td><td>${t.next_session ? quando(t.next_session) : '<span class="badge amber">sem próxima</span>'}</td>
      <td>${money(t.total_sessions * t.session_price)}</td><td><span class="badge ${t.status === 'ativo' ? 'green' : ''}">${t.status}</span></td>
      <td>${t.status === 'ativo' ? `<button class="btn sm" data-c="${t.id}">Concluir</button>` : ''}</td></tr>`).join('') || '<tr><td colspan="9" class="empty">Nenhum tratamento ainda</td></tr>'}</table></div>`;
  $$('[data-c]', c).forEach((b) => (b.onclick = async () => { await api(`/treatments/${b.dataset.c}`, { method: 'PATCH', body: { status: 'concluido' } }); tratamentos(main); }));
}

// ---------------- Financeiro ----------------
async function financeiro(main) {
  const c = await header(main, 'Financeiro', 'Receita contratada (agenda) e pagamentos recebidos');
  const [pays, trs] = await Promise.all([api('/payments'), api('/treatments')]);
  const contratado = trs.filter((t) => t.status !== 'cancelado').reduce((a, t) => a + t.total_sessions * t.session_price, 0);
  const recebido = pays.filter((p) => p.status === 'pago').reduce((a, p) => a + p.amount, 0);
  c.innerHTML = `<div class="grid g3">${kpi('Contratado em pacotes', money(contratado), `${trs.length} tratamentos`)}${kpi('Recebido', money(recebido), `${pays.length} pagamentos`, 'green')}${kpi('A receber', money(Math.max(0, contratado - recebido)), 'Pix/cartão via integração de pagamentos')}</div>
   <div class="card" style="margin-top:14px;padding:0"><table><tr><th>Data</th><th>${cap(T('cliente'))}</th><th>Forma</th><th>Status</th><th>Valor</th></tr>
   ${pays.map((p) => `<tr><td>${utcToLocal(p.created_at)}</td><td><a href="#/clientes/${p.client_id}">${esc(p.client_name)}</a></td><td>${esc(p.method)}</td><td><span class="badge green">${esc(p.status)}</span></td><td>${money2(p.amount)}</td></tr>`).join('') || '<tr><td colspan="5" class="empty">Registre pagamentos pela ficha do cliente.</td></tr>'}</table></div>`;
}

// ---------------- Automação ----------------
async function automacao(main) {
  const c = await header(main, 'Automação & Agente de IA', 'Atendimento no WhatsApp · todos os dias · 24 horas');
  const draw = async () => {
    const r = await api('/automation'); const t = r.tenant;
    const st = (s) => r.stats.find((x) => x.step === s) || {};
    const total = st('responde').n || 0;
    c.innerHTML = `<div class="grid g2">
      <div class="card"><div class="row"><span style="color:var(--green)">⌁</span><div class="grow"><b>Automação · ${esc(t.name)}</b><div class="small muted">atendimento no WhatsApp</div></div>
        <span class="small ${t.automation_active ? '' : 'muted'}" style="color:${t.automation_active ? 'var(--green)' : ''}">${t.automation_active ? 'Ativo' : 'Desligado'}</span><button class="toggle ${t.automation_active ? 'on' : ''}" id="tg"></button></div>
        <div class="flow" style="margin-top:14px">
          ${[['🟢', '#14532d', 'WhatsApp', 'chega a mensagem', 'whatsapp'], ['🎙', '#1e3a8a', 'Transcreve', 'áudio → texto', 'transcreve'], ['✳️', '#7c2d12', 'Agente de IA', 'entende e decide', 'agente_ia'], ['📅', '#3f3f46', 'Agenda', 'acha horário livre', 'agenda'], ['✅', '#14532d', 'Responde', 'confirma no WhatsApp', 'responde']]
            .map(([ic, bg, n, d, s], i) => `<div class="node ${t.automation_active ? 'on' : ''}"><span class="k">${i + 1}</span><div class="ic" style="background:${bg}">${ic}</div><div><b>${n}</b><div class="small muted">${d}</div><div class="small dim">${st(s).n || 0}× ${st(s).avg_ms ? '· ' + (st(s).avg_ms / 1000).toFixed(1) + 's' : ''}</div></div></div>`).join('')}
          <div class="counter" style="grid-column:2"><span style="width:18px;height:18px;border:2px solid #111;border-radius:50%"></span><div><b>24 horas</b><div class="small">todos os dias · ${total} atendimentos</div></div></div>
        </div>
        <div class="small muted" style="margin-top:10px">Motor: <b>${r.agent.mode === 'claude' ? 'Claude · ' + esc(r.agent.model) : 'regras determinísticas'}</b>${r.agent.mode !== 'claude' ? ' — defina <span class="mono">ANTHROPIC_API_KEY</span> no servidor para usar IA generativa.' : ''}</div>
      </div>
      <form class="card col" id="cfg"><h3>Comportamento do agente</h3>
        <div class="grid g2"><label class="f">Nome do agente<input name="agent_name" value="${esc(t.agent_name)}"></label><label class="f">Tom de voz<input name="agent_tone" value="${esc(t.agent_tone)}"></label></div>
        <label class="f">Instruções específicas da empresa (políticas, convênios, preparo, regras)<textarea name="agent_instructions" rows="5" placeholder="Ex.: Aceitamos Unimed e Bradesco. Avaliação deve ser feita antes do pacote. Não atendemos menores de 12 anos.">${esc(t.agent_instructions || '')}</textarea></label>
        <div class="grid g2"><label class="f">Lembrete antes (horas)<input type="number" name="reminder_hours_before" value="${t.reminder_hours_before}"></label><label class="f">Custo mensal da automação (R$)<input type="number" name="automation_cost_monthly" value="${t.automation_cost_monthly}"></label></div>
        <label class="row small"><input type="checkbox" name="auto_book_package" ${t.auto_book_package ? 'checked' : ''}> Reservar automaticamente as próximas ${T('sessoes')} do pacote</label>
        <label class="row small"><input type="checkbox" name="noshow_recovery" ${t.noshow_recovery ? 'checked' : ''}> Recuperar faltas: oferecer remarcação na hora</label>
        <div class="row"><button class="btn primary">Salvar</button><button type="button" class="btn" id="run">⏱ Rodar lembretes agora</button></div>
      </form></div>
      <div class="card" style="margin-top:14px;padding:0"><div style="padding:12px 14px"><h3>Log de execução</h3></div><table><tr><th>Quando</th><th>Etapa</th><th>${cap(T('cliente'))}</th><th>Tempo</th><th>Detalhe</th></tr>
      ${r.logs.map((l) => `<tr><td class="small muted">${utcToLocal(l.created_at)}</td><td><span class="badge">${esc(l.step)}</span></td><td>${l.conversation_id ? `<a href="#/conversas/${l.conversation_id}">${esc(l.client_name || '')}</a>` : ''}</td><td class="small">${l.ms != null ? (l.ms / 1000).toFixed(2) + 's' : ''}</td><td class="small mono muted" style="max-width:420px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(l.detail || '')}</td></tr>`).join('')}</table></div>`;
    $('#tg').onclick = async () => { await api('/tenant', { method: 'PUT', body: { automation_active: !t.automation_active } }); ME = null; route(); };
    $('#run').onclick = async () => { const x = await api('/jobs/run', { method: 'POST' }); toast(`${x.lembretes} lembretes · ${x.recuperacoes} recuperações`); };
    $('#cfg').onsubmit = async (e) => { e.preventDefault(); await api('/tenant', { method: 'PUT', body: formData(e.target) }); toast('Configurações salvas'); };
  };
  await draw();
}

// ---------------- Serviços ----------------
async function servicos(main) {
  const c = await header(main, 'Serviços', 'O que o agente pode oferecer e agendar', '<button class="btn primary sm" id="novo">+ Serviço</button>');
  const [list, profs] = await Promise.all([api('/services'), api('/professionals')]);
  c.innerHTML = `<div class="card" style="padding:0"><table><tr><th>Serviço</th><th>Duração</th><th>Preço</th><th>Pacote</th><th>Documento</th><th>${cap(T('profissionais'))}</th><th></th></tr>
    ${list.map((s) => `<tr class="click" data-id="${s.id}" style="${s.active ? '' : 'opacity:.5'}"><td><b>${esc(s.name)}</b> ${s.is_entry ? '<span class="badge green">entrada</span>' : ''}<div class="small dim">${esc(s.keywords || '')}</div></td><td>${s.duration_min} min</td><td>${money(s.price)}</td>
    <td>${s.package_sessions ? `${s.package_sessions}x ${money(s.package_session_price)} · ${s.sessions_per_week}/sem` : '—'}</td><td>${s.requires_document ? esc(s.document_label) : '—'}</td><td class="small">${s.professional_ids.map((id) => esc(profs.find((p) => p.id === id)?.name || '')).join(', ')}</td><td>›</td></tr>`).join('')}</table></div>`;
  const form = (s = {}) => `<div class="grid g2"><label class="f">Nome<input name="name" value="${esc(s.name || '')}"></label><label class="f">Duração (min)<input type="number" name="duration_min" value="${s.duration_min || 60}"></label>
    <label class="f">Preço (R$)<input type="number" step="0.01" name="price" value="${s.price ?? 0}"></label><label class="f">Ativo<select name="active"><option value="1">Sim</option><option value="0" ${s.active === 0 ? 'selected' : ''}>Não</option></select></label></div>
    <label class="f">Descrição<input name="description" value="${esc(s.description || '')}"></label>
    <label class="f">Palavras-chave (o agente usa para reconhecer o pedido)<input name="keywords" value="${esc(s.keywords || '')}"></label>
    <label class="row small"><input type="checkbox" name="is_entry" ${s.is_entry ? 'checked' : ''}> Porta de entrada (ex.: avaliação/primeira consulta)</label>
    <div class="grid g3"><label class="f">Nº sessões do pacote<input type="number" name="package_sessions" value="${s.package_sessions || 0}"></label><label class="f">Preço por sessão<input type="number" step="0.01" name="package_session_price" value="${s.package_session_price || 0}"></label><label class="f">Sessões/semana<input type="number" name="sessions_per_week" value="${s.sessions_per_week || 2}"></label></div>
    <label class="f">Serviço usado nas sessões do pacote<select name="package_service_id"><option value="">o próprio serviço</option>${list.filter((x) => x.id !== s.id).map((x) => `<option value="${x.id}" ${x.id === s.package_service_id ? 'selected' : ''}>${esc(x.name)}</option>`).join('')}</select></label>
    <div class="grid g2"><label class="row small"><input type="checkbox" name="requires_document" ${s.requires_document ? 'checked' : ''}> Pedir foto de documento</label><label class="f">Qual documento<input name="document_label" value="${esc(s.document_label || '')}" placeholder="pedido médico"></label></div>
    <label class="f">${cap(T('profissionais'))} habilitados<select name="professional_ids" multiple size="4">${profs.map((p) => `<option value="${p.id}" ${(s.professional_ids || []).includes(p.id) ? 'selected' : ''}>${esc(p.name)}</option>`).join('')}</select></label>`;
  const save = (id) => async (el) => { const b = formData(el); for (const k of ['is_entry', 'requires_document']) b[k] = b[k] ? 1 : 0; b.active = +b.active; b.package_service_id = b.package_service_id ? +b.package_service_id : null; await api(id ? `/services/${id}` : '/services', { method: id ? 'PUT' : 'POST', body: b }); servicos(main); };
  $('#novo').onclick = () => modal('Novo serviço', form(), { onSave: save() });
  $$('tr.click', c).forEach((r) => (r.onclick = () => { const s = list.find((x) => x.id === +r.dataset.id); modal(s.name, form(s), { onSave: save(s.id) }); }));
}

// ---------------- Profissionais ----------------
const WD = ['Dom', 'Seg', 'Ter', 'Qua', 'Qui', 'Sex', 'Sáb'];
async function profissionais(main) {
  const c = await header(main, cap(T('profissionais')), 'Jornada de trabalho e serviços de cada um', '<button class="btn primary sm" id="novo">+ Adicionar</button>');
  const [list, svcs] = await Promise.all([api('/professionals'), api('/services')]);
  c.innerHTML = `<div class="grid g3">${list.map((p) => `<div class="card col click" data-id="${p.id}" style="cursor:pointer;${p.active ? '' : 'opacity:.5'}"><div class="row"><div class="avatar" style="background:${p.color}33;color:${p.color}">${esc(p.name.replace(/^(Dra?\.?\s*)/, '')[0])}</div><div><b>${esc(p.name)}</b><div class="small muted">${esc(p.specialty || '')} ${p.registry ? '· ' + esc(p.registry) : ''}</div></div></div>
    <div class="small">${[1, 2, 3, 4, 5, 6, 0].filter((d) => p.schedule[d]?.length).map((d) => `${WD[d]} ${p.schedule[d].map((w) => w.join('–')).join(', ')}`).join('<br>') || '<span class="dim">sem jornada</span>'}</div>
    <div class="row wrap">${p.service_ids.map((id) => `<span class="badge">${esc(svcs.find((s) => s.id === id)?.name || '')}</span>`).join('')}</div></div>`).join('')}</div>`;
  const form = (p = { schedule: { 1: [['08:00', '12:00'], ['13:00', '18:00']], 2: [['08:00', '12:00'], ['13:00', '18:00']], 3: [['08:00', '12:00'], ['13:00', '18:00']], 4: [['08:00', '12:00'], ['13:00', '18:00']], 5: [['08:00', '12:00'], ['13:00', '18:00']] }, service_ids: [] }) => `
    <div class="grid g2"><label class="f">Nome<input name="name" value="${esc(p.name || '')}"></label><label class="f">Especialidade<input name="specialty" value="${esc(p.specialty || '')}"></label>
    <label class="f">Registro (CREFITO, CRO, CRP…)<input name="registry" value="${esc(p.registry || '')}"></label><label class="f">Cor<input type="color" name="color" value="${p.color || '#3b82f6'}" style="height:38px"></label></div>
    <label class="f">Serviços<select name="service_ids" multiple size="4">${svcs.map((s) => `<option value="${s.id}" ${p.service_ids.includes(s.id) ? 'selected' : ''}>${esc(s.name)}</option>`).join('')}</select></label>
    <h4>Jornada (até 2 turnos por dia — deixe vazio para folga)</h4>
    <div class="sched-grid">${[1, 2, 3, 4, 5, 6, 0].map((d) => { const w = p.schedule[d] || []; return `<span>${WD[d]}</span>${[0, 1].map((i) => `<div class="row"><input type="time" data-d="${d}" data-i="${i}" data-k="0" value="${w[i]?.[0] || ''}"><input type="time" data-d="${d}" data-i="${i}" data-k="1" value="${w[i]?.[1] || ''}"></div>`).join('')}<span></span>`; }).join('')}</div>
    ${p.id ? `<label class="row small"><input type="checkbox" name="active" ${p.active ? 'checked' : ''}> Ativo</label>` : ''}`;
  const collect = (el) => { const b = formData(el); const sch = {}; $$('[data-d]', el).forEach((i) => { if (!i.value) return; const d = i.dataset.d; sch[d] ||= [[], []]; sch[d][i.dataset.i][i.dataset.k] = i.value; });
    for (const d in sch) sch[d] = sch[d].filter((w) => w[0] && w[1]); b.schedule = sch; b.service_ids = (b.service_ids || []).map(Number); if ('active' in b) b.active = b.active ? 1 : 0; return b; };
  $('#novo').onclick = () => modal('Novo ' + T('profissional'), form(), { wide: true, onSave: async (el) => { await api('/professionals', { method: 'POST', body: collect(el) }); profissionais(main); } });
  $$('[data-id]', c).forEach((x) => (x.onclick = () => { const p = list.find((y) => y.id === +x.dataset.id); modal(p.name, form(p), { wide: true, onSave: async (el) => { await api(`/professionals/${p.id}`, { method: 'PUT', body: collect(el) }); profissionais(main); } }); }));
}

// ---------------- Integrações ----------------
const INTEG = {
  whatsapp: ['🟢', 'WhatsApp Business (Cloud API · Meta)', 'Recebe e envia mensagens, áudios, imagens, botões e localização. Webhook: <span class="mono">/api/webhook/whatsapp</span>', ['phone_number_id', 'waba_id'], 'WHATSAPP_TOKEN, WHATSAPP_VERIFY_TOKEN'],
  ia: ['✳️', 'Agente de IA (Claude · Anthropic)', 'Entende linguagem natural, lê fotos de pedidos médicos e decide a próxima ação com ferramentas (agenda, pacote, localização).', ['observacao'], 'ANTHROPIC_API_KEY (opcional: ANTHROPIC_MODEL)'],
  transcricao: ['🎙', 'Transcrição de áudio', 'Converte áudios do WhatsApp em texto (OpenAI Whisper/gpt-4o-transcribe). No simulador, o navegador transcreve.', ['idioma'], 'OPENAI_API_KEY'],
  google_calendar: ['📆', 'Google Agenda', 'Sincroniza a agenda de cada profissional (bidirecional) e bloqueia horários pessoais.', ['calendar_id'], 'GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET'],
  pagamentos: ['💳', 'Pagamentos (Pix / cartão)', 'Cobrança do pacote por link Pix (Mercado Pago, Asaas, Stripe) com baixa automática via webhook.', ['provedor', 'chave_pix'], 'PAYMENT_PROVIDER_TOKEN'],
  mapas: ['📍', 'Mapas e localização', 'Envia o pin da clínica após o agendamento (link Google Maps / Waze).', ['link_maps'], '—'],
};
async function integracoes(main) {
  const c = await header(main, 'Integrações', 'Credenciais ficam em variáveis de ambiente (nunca no banco). Aqui você ativa e configura.');
  const list = await api('/integrations');
  c.innerHTML = `<div class="grid g2">${list.map((i) => { const [ic, name, desc, fields, env] = INTEG[i.key] || ['🔌', i.key, '', [], '']; return `
    <form class="card col" data-k="${i.key}"><div class="row"><div class="ic" style="font-size:22px">${ic}</div><div class="grow"><b>${name}</b><div class="small ${i.env_ready ? '' : 'muted'}" style="color:${i.env_ready ? 'var(--green)' : ''}">${i.env_ready ? '● credenciais detectadas' : '○ aguardando credenciais'}</div></div>
      <label class="row small"><input type="checkbox" name="enabled" ${i.enabled ? 'checked' : ''}> Ativa</label></div>
    <div class="small muted">${desc}</div>
    ${fields.map((f) => `<label class="f">${f}<input name="${f}" value="${esc(i.config?.[f] || '')}"></label>`).join('')}
    <div class="small dim">Variáveis: <span class="mono">${env}</span></div><div><button class="btn sm">Salvar</button></div></form>`; }).join('')}</div>`;
  $$('form[data-k]', c).forEach((f) => (f.onsubmit = async (e) => { e.preventDefault(); const b = formData(f); const enabled = b.enabled; delete b.enabled; await api(`/integrations/${f.dataset.k}`, { method: 'PUT', body: { enabled, config: b } }); toast('Integração salva'); }));
}

// ---------------- Empresa ----------------
async function empresa(main) {
  const c = await header(main, 'Empresa', 'Dados usados pelo agente: endereço, horários, terminologia do segmento');
  const t = (await api('/me')).tenant; const hours = JSON.parse(t.hours_json || '{}'); const terms = JSON.parse(t.terms_json || '{}');
  c.innerHTML = `<form class="card col" id="f" style="max-width:820px">
    <div class="grid g2"><label class="f">Nome<input name="name" value="${esc(t.name)}"></label><label class="f">Segmento<select name="segment">${Object.entries(ME.segments).map(([k, v]) => `<option value="${k}" ${k === t.segment ? 'selected' : ''}>${v}</option>`).join('')}</select></label>
    <label class="f">Endereço<input name="address" value="${esc(t.address || '')}"></label><label class="f">Cidade<input name="city" value="${esc(t.city || '')}"></label>
    <label class="f">Latitude<input type="number" step="any" name="lat" value="${t.lat ?? ''}"></label><label class="f">Longitude<input type="number" step="any" name="lng" value="${t.lng ?? ''}"></label>
    <label class="f">Telefone<input name="phone" value="${esc(t.phone || '')}"></label><label class="f">WhatsApp phone_number_id (Meta)<input name="whatsapp_phone_number_id" value="${esc(t.whatsapp_phone_number_id || '')}"></label></div>
    <h4>Horário de funcionamento</h4>
    <div class="grid g4">${[1, 2, 3, 4, 5, 6, 0].map((d) => `<div class="row"><span style="width:34px">${WD[d]}</span><input type="time" data-h="${d}" data-k="0" value="${hours[d]?.[0] || ''}"><input type="time" data-h="${d}" data-k="1" value="${hours[d]?.[1] || ''}"></div>`).join('')}</div>
    <h4>Terminologia (deixe vazio para usar o padrão do segmento)</h4>
    <div class="grid g4">${['cliente', 'clientes', 'profissional', 'profissionais', 'sessao', 'sessoes', 'documento'].map((k) => `<label class="f">${k}<input data-t="${k}" value="${esc(terms[k] || '')}" placeholder="${esc(ME.terms[k] || '')}"></label>`).join('')}</div>
    <div><button class="btn primary">Salvar</button></div></form>`;
  $('#f').onsubmit = async (e) => {
    e.preventDefault(); const b = formData(e.target); const h = {}; const tm = {};
    $$('[data-h]').forEach((i) => { if (i.value) (h[i.dataset.h] ||= [])[i.dataset.k] = i.value; }); for (const d in h) if (!h[d][0] || !h[d][1]) delete h[d];
    $$('[data-t]').forEach((i) => { if (i.value.trim()) tm[i.dataset.t] = i.value.trim(); });
    b.hours = h; b.terms = tm; await api('/tenant', { method: 'PUT', body: b }); toast('Salvo'); ME = null; route();
  };
}

// ---------------- Usuários ----------------
async function usuarios(main) {
  const c = await header(main, 'Usuários e permissões', 'admin: tudo · recepção: agenda, conversas e clientes · profissional: a própria agenda', '<button class="btn primary sm" id="novo">+ Usuário</button>');
  const [list, profs, logs] = await Promise.all([api('/users'), api('/professionals'), api('/audit')]);
  c.innerHTML = `<div class="card" style="padding:0"><table><tr><th>Nome</th><th>E-mail</th><th>Perfil</th><th>Status</th><th></th></tr>${list.map((u) => `<tr><td>${esc(u.name)}</td><td class="muted">${esc(u.email)}</td><td><span class="badge">${u.role}</span></td><td>${u.active ? '<span class="badge green">ativo</span>' : '<span class="badge">inativo</span>'}</td><td><button class="btn sm" data-u="${u.id}">${u.active ? 'Desativar' : 'Ativar'}</button></td></tr>`).join('')}</table></div>
  <div class="card" style="margin-top:14px;padding:0"><div style="padding:12px 14px"><h3>Auditoria</h3></div><table>${logs.slice(0, 50).map((l) => `<tr><td class="small muted">${utcToLocal(l.created_at)}</td><td>${esc(l.user_name || '')}</td><td>${esc(l.action)} ${esc(l.entity)} #${l.entity_id ?? ''}</td><td class="small mono dim">${esc(l.detail || '')}</td></tr>`).join('') || '<tr><td class="empty">Sem registros</td></tr>'}</table></div>`;
  $$('[data-u]', c).forEach((b) => (b.onclick = async () => { const u = list.find((x) => x.id === +b.dataset.u); await api(`/users/${u.id}`, { method: 'PUT', body: { active: u.active ? 0 : 1 } }); usuarios(main); }));
  $('#novo').onclick = () => modal('Novo usuário', `<div class="grid g2"><label class="f">Nome<input name="name"></label><label class="f">E-mail<input name="email"></label><label class="f">Senha<input name="password" type="password"></label>
    <label class="f">Perfil<select name="role"><option value="recepcao">Recepção</option><option value="admin">Administrador</option><option value="profissional">Profissional</option></select></label></div>
    <label class="f">Vincular a profissional (perfil profissional)<select name="professional_id"><option value="">—</option>${profs.map((p) => `<option value="${p.id}">${esc(p.name)}</option>`).join('')}</select></label>`,
  { onSave: async (el) => { const b = formData(el); b.professional_id = b.professional_id ? +b.professional_id : null; await api('/users', { method: 'POST', body: b }); usuarios(main); } });
}

// ---------------- Empresas (superadmin) ----------------
async function empresas(main) {
  const c = await header(main, 'Empresas (multiempresa)', 'Cada empresa tem agenda, agente, WhatsApp e equipe próprios', '<button class="btn primary sm" id="novo">+ Nova empresa</button>');
  const list = await api('/tenants');
  c.innerHTML = `<div class="grid g3">${list.map((t) => `<div class="card col"><div class="row"><b class="grow">${esc(t.name)}</b><span class="badge">${esc(ME.segments[t.segment] || t.segment)}</span></div><div class="small muted">${esc(t.city || '')}</div>
    <div class="row"><span class="small">${t.automation_active ? '🟢 agente ativo' : '⚪ agente desligado'}</span><button class="btn sm right" data-t="${t.id}">Gerenciar</button></div></div>`).join('')}</div>`;
  $$('[data-t]', c).forEach((b) => (b.onclick = () => { localStorage.setItem('atende_tenant', b.dataset.t); ME = null; location.hash = '#/dashboard'; }));
  $('#novo').onclick = () => modal('Nova empresa', `<div class="grid g2"><label class="f">Nome<input name="name"></label><label class="f">Segmento (cria serviços e terminologia)<select name="segment">${Object.entries(ME.segments).map(([k, v]) => `<option value="${k}">${v}</option>`).join('')}</select></label>
    <label class="f">Endereço<input name="address"></label><label class="f">Cidade<input name="city"></label><label class="f">Nome do agente<input name="agent_name" value="Assistente"></label><label class="f">Telefone<input name="phone"></label></div>
    <h4>Gestor da empresa</h4><div class="grid g3"><label class="f">Nome<input name="admin_name"></label><label class="f">E-mail<input name="admin_email"></label><label class="f">Senha<input name="admin_password" value="123456"></label></div>`,
  { onSave: async (el) => { const t = await api('/tenants', { method: 'POST', body: formData(el) }); toast('Empresa criada. Cadastre os profissionais.'); localStorage.setItem('atende_tenant', t.id); ME = null; location.hash = '#/profissionais'; } });
}
