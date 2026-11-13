import { esc, $, $$, makeApi, toast, modal, formData, money, money2, addDays, hora, hm, dataCurta, diaSem, dataLonga, quando, todayLocal, utcToLocal, statusBadge, STATUS, d as toDate } from '/assets/common.js';

const TK = 'atende_admin_token';
const api = makeApi(TK, () => (localStorage.getItem('atende_tenant') ? { 'X-Tenant': localStorage.getItem('atende_tenant') } : {}));
const app = $('#app');
let ME = null; let ES = null;
const T = (k) => ME?.terms?.[k] || k;
const cap = (s) => s.charAt(0).toUpperCase() + s.slice(1);
const isMgr = () => ['admin', 'superadmin'].includes(ME?.user?.role);
const isProf = () => ME?.user?.role === 'profissional';

// [rota, ícone, rótulo, perfis permitidos]
const NAV = [
  ['sec', 'Operação'],
  ['dashboard', '📊', 'Dashboard', 'all'], ['agenda', '📅', 'Agenda', 'all'], ['conversas', '💬', 'Conversas', 'staff'], ['clientes', '👥', () => cap(T('clientes')), 'staff'],
  ['espera', '⏳', 'Lista de espera', 'staff'], ['tratamentos', '📈', 'Tratamentos', 'all'], ['financeiro', '💰', 'Financeiro', 'mgr'],
  ['sec', 'Cadastros'],
  ['profissionais', '🩺', () => cap(T('profissionais')), 'all'], ['servicos', '🧾', 'Catálogo de serviços', 'all'],
  ['sec', 'Configuração', 'mgr'],
  ['empresa', '🏢', 'Clínica & regras', 'mgr'], ['automacao', '⚡', 'Agente & automações', 'mgr'], ['seguranca', '🛡', 'Segurança', 'mgr'], ['integracoes', '🔌', 'Integrações', 'mgr'], ['usuarios', '🔐', 'Usuários', 'mgr'],
  ['sec', 'Plataforma', 'superadmin'], ['empresas', '🌐', 'Empresas (SaaS)', 'superadmin'],
];
const allowed = (who) => !who || who === 'all' || (who === 'staff' && !isProf()) || (who === 'mgr' && isMgr()) || (who === 'superadmin' && ME.user.role === 'superadmin');

window.addEventListener('hashchange', route);
route();

async function route() {
  const [page, id] = location.hash.replace(/^#\/?/, '').split('/');
  if (!localStorage.getItem(TK) || page === 'login') return renderLogin();
  if (!ME) {
    try { ME = await api('/me'); } catch { return renderLogin(); }
    connectEvents();
  }
  const pages = { dashboard, agenda, conversas, clientes, espera, tratamentos, financeiro, automacao, servicos, profissionais, integracoes, empresa, seguranca, usuarios, empresas };
  const nav = NAV.find((n) => n[0] === page);
  const target = pages[page] && (!nav || allowed(nav[3])) ? page : 'dashboard';
  renderShell(target);
  const main = $('.main');
  try { await pages[target](main, id); } catch (e) { main.innerHTML += `<div class="card">${esc(e.message)}</div>`; }
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
    <div><h2>Entrar no painel</h2><p class="muted small">Agenda, atendimento e agente de IA da sua clínica.</p></div>
    <label class="f">E-mail<input name="email" value="gestor@vidaintegrada.com" autocomplete="username" maxlength="190"></label>
    <label class="f">Senha<input name="password" type="password" value="gestor123" autocomplete="current-password" maxlength="200"></label>
    <button class="btn primary">Entrar</button>
    <div class="small muted">Acessos de teste:<br>• gestor@vidaintegrada.com / gestor123 (gestor)<br>• recepcao@vidaintegrada.com / recepcao123 (recepção)<br>• helena@vidaintegrada.com / helena123 (profissional)<br>• admin@atende.ai / admin123 (plataforma)</div>
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
  const items = NAV.filter((n) => (n[0] === 'sec' ? allowed(n[2]) : allowed(n[3])));
  app.innerHTML = `<div class="shell"><aside class="side">
    <div class="brand"><div class="logo">A</div>Atende.AI</div>
    <nav class="nav">${items.map((n) => n[0] === 'sec' ? `<div class="sec">${n[1]}</div>` :
      `<a href="#/${n[0]}" class="${page === n[0] ? 'on' : ''}"><span>${n[1]}</span>${typeof n[2] === 'function' ? n[2]() : n[2]}${n[0] === 'conversas' ? '<span class="n" id="unread" hidden></span>' : ''}</a>`).join('')}</nav>
    <div class="grow"></div>
    <div class="card tight small" style="margin-top:12px">
      <div class="row"><span class="dot" style="background:${ME.tenant?.automation_active ? 'var(--green)' : 'var(--dim)'}"></span>Agente ${ME.tenant?.automation_active ? 'ativo 24h' : 'desligado'}</div>
      <div class="muted">${ME.agent.mode === 'claude' ? 'IA: ' + esc(ME.agent.model) : 'Modo regras (sem chave de IA)'} · 🛡 protegido</div>
    </div>
    <div class="row small" style="padding:10px 6px"><div class="grow"><b>${esc(ME.user.name)}</b><div class="muted">${esc(ME.user.role)} · ${esc(ME.tenant?.name || '')}</div></div><button class="btn sm" id="logout">Sair</button></div>
  </aside><main class="main"></main></div>`;
  $('#logout').onclick = () => { localStorage.removeItem(TK); localStorage.removeItem('atende_tenant'); ME = null; location.hash = '#/login'; };
  if (!isProf()) updateUnread();
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
let dashDays = 30;
async function dashboard(main) {
  const c = await header(main, 'Dashboard', `${esc(ME.tenant.name)} · números calculados a partir da agenda`, `
    <div class="tabs">${[7, 30, 90].map((d) => `<button data-d="${d}" class="${dashDays === d ? 'on' : ''}">${d} dias</button>`).join('')}</div>
    ${isProf() ? '' : '<button class="btn sm" id="jobs">⏱ Rodar rotinas agora</button>'}`);
  $$('[data-d]').forEach((b) => (b.onclick = () => { dashDays = +b.dataset.d; dashboard(main); }));
  $('#jobs')?.addEventListener('click', async () => { const r = await api('/jobs/run', { method: 'POST' }); toast(`Rotinas: ${r.lembretes} lembretes · ${r.reposicoes} reposições · ${r.encaixes} encaixes · ${r.reativacoes} reativações`); });
  const draw = async () => {
    const k = await api('/dashboard?days=' + dashDays);
    const A = k.atendimentos; const G = k.agente;
    const fin = k.financeiro;
    const maxS = Math.max(1, ...k.serie.map((s) => s.realizado + s.previsto));
    c.innerHTML = `
    ${fin ? `<div class="grid g4">
      ${kpi('Faturamento realizado', money(k.realizado.receita), `${k.realizado.n} atendimentos · ticket médio ${money(k.ticket_medio)}`, 'green')}
      ${kpi('Lucro estimado', money(k.realizado.lucro), `margem ${k.margem.toFixed(0)}% · após custos ${money(k.realizado.custo)} e repasses ${money(k.realizado.repasse)}`)}
      ${kpi('Previsto na agenda (30 dias)', money(k.previsto.receita), `${k.previsto.n} agendados · lucro previsto ${money(k.previsto.lucro)}`, 'blue')}
      ${kpi('Perdido com faltas/cancelamentos', money(k.perdido.receita), `${A.faltas} faltas · ${A.cancelados} cancelamentos · ${money(k.recuperado.v)} recuperados`, 'red')}
    </div>` : ''}
    <div class="grid g4" style="margin-top:${fin ? 14 : 0}px">
      ${kpi('Comparecimento', A.comparecimento != null ? A.comparecimento + '%' : '—', `${A.realizados} realizados · ${A.faltas} faltas`)}
      ${kpi('Ocupação próximos 7 dias', k.ocupacao.geral + '%', `${A.futuros} horários marcados nos próximos 30 dias`)}
      ${kpi('Agendados pelo agente', G.agendamentos, `${G.pct}% dos agendamentos · ${G.fora_do_horario} fora do horário comercial`)}
      ${kpi('Recuperados pelo agente', G.recuperados, `${G.reposicoes} reofertas enviadas · ${G.espera} na lista de espera`)}
    </div>
    ${fin ? `<div class="grid g2" style="margin-top:14px">
      <div class="card"><div class="row between"><h3>Faturamento por dia</h3><span class="small muted"><span class="dot" style="background:var(--green)"></span> realizado &nbsp; <span class="dot" style="background:var(--blue)"></span> agendado</span></div>
        <div class="bars">${k.serie.map((s, i) => `<div class="b" title="${s.d}: ${money(s.realizado)} realizado, ${money(s.previsto)} agendado"><i style="height:${(s.realizado / maxS) * 130}px;background:var(--green)"></i><i style="height:${(s.previsto / maxS) * 130}px;background:var(--blue)"></i>${i % 3 === 0 ? `<small>${dataCurta(s.d)}</small>` : ''}</div>`).join('') || '<div class="empty">Sem dados</div>'}</div><div style="height:16px"></div></div>
      <div class="card"><h3>Por categoria</h3><table style="margin-top:6px"><tr><th>Categoria</th><th style="text-align:right">Faturamento</th><th style="text-align:right">Lucro</th><th style="text-align:right">Margem</th></tr>
        ${k.porCat.map((x) => `<tr><td>${esc(x.category)}</td><td style="text-align:right">${money(x.receita)}</td><td style="text-align:right">${money(x.lucro)}</td><td style="text-align:right">${x.receita ? ((100 * x.lucro) / x.receita).toFixed(0) : 0}%</td></tr>`).join('')}</table></div>
    </div>` : ''}
    <div class="card" style="padding:0;margin-top:14px"><div style="padding:12px 14px"><h3>Por ${T('profissional')}</h3></div><table><tr><th>${cap(T('profissional'))}</th><th>Atend.</th><th>Faltas</th>${fin ? '<th style="text-align:right">Faturamento</th><th style="text-align:right">Repasse</th><th style="text-align:right">Lucro clínica</th>' : ''}<th>Ocupação 7d</th></tr>
        ${k.porProf.map((p) => { const o = k.ocupacao.prof.find((x) => x.name === p.name) || { pct: 0 }; return `<tr><td><span class="dot" style="background:${p.color}"></span> ${esc(p.name)}</td><td>${p.n}</td><td>${p.faltas ? `<span class="badge red">${p.faltas}</span>` : 0}</td>
        ${fin ? `<td style="text-align:right">${money(p.receita)}</td><td style="text-align:right" class="muted">${money(p.repasse)}</td><td style="text-align:right">${money(p.lucro)}</td>` : ''}<td style="min-width:120px"><div class="small">${o.pct}%</div><div class="progress"><i style="width:${o.pct}%;background:${p.color}"></i></div></td></tr>`; }).join('')}</table></div>
    <div class="grid g2" style="margin-top:14px">
      ${fin ? `<div class="card" style="padding:0"><div style="padding:12px 14px"><h3>Procedimentos que mais faturam</h3></div><table><tr><th>Serviço</th><th>Qtd</th><th style="text-align:right">Faturamento</th><th style="text-align:right">Lucro</th></tr>
        ${k.porServ.map((s) => `<tr><td>${esc(s.name)} <span class="dim small">${esc(s.category)}</span></td><td>${s.n}</td><td style="text-align:right">${money(s.receita)}</td><td style="text-align:right">${money(s.lucro)}</td></tr>`).join('')}</table></div>` : ''}
      ${`<div class="card"><h3>Agente</h3><div class="col small" style="margin-top:8px"><span>${G.conversas} conversas no período</span><span>${G.humano} aguardando a equipe</span><span>${G.bloqueios} tentativas bloqueadas pela proteção</span></div></div>`}
    </div>
    ${fin ? `<div class="small dim" style="margin-top:10px">Lucro estimado = valor do atendimento − custo direto do procedimento − repasse do profissional (configure no Catálogo e em ${cap(T('profissionais'))}). Não inclui despesas fixas (aluguel, folha, impostos).</div>` : ''}`;
  };
  await draw(); onLive(draw);
}
const kpi = (l, v, s, color) => `<div class="card kpi"><div class="small muted">${l}</div><div class="v" style="${color ? 'color:var(--' + color + ')' : ''}">${v}</div><div class="s">${s}</div></div>`;

// ---------------- Agenda ----------------
let agendaDate = todayLocal(); let agendaView = 'dia'; let agendaProf = '';
async function agenda(main) {
  const profs = await api('/professionals');
  const c = await header(main, 'Agenda', 'Eventos marcados pelo agente têm o selo ✳️ · clique num horário livre para agendar', `
    <div class="tabs"><button data-v="dia" class="${agendaView === 'dia' ? 'on' : ''}">Dia</button><button data-v="mes" class="${agendaView === 'mes' ? 'on' : ''}">Mês</button></div>
    ${isProf() ? '' : `<select id="pf" style="width:190px"><option value="">Todos os ${T('profissionais')}</option>${profs.filter((p) => p.active).map((p) => `<option value="${p.id}" ${String(p.id) === agendaProf ? 'selected' : ''}>${esc(p.name)}</option>`).join('')}</select>`}
    <button class="btn sm" id="prev">‹</button><input type="date" id="date" value="${agendaDate}" style="width:150px"><button class="btn sm" id="next">›</button><button class="btn sm" id="hoje">Hoje</button>
    ${isMgr() ? '<button class="btn sm" id="bloq">⛔ Bloquear período</button>' : ''}${isProf() ? '' : '<button class="btn primary sm" id="novo">+ Agendamento</button>'}`);
  $$('[data-v]').forEach((b) => (b.onclick = () => { agendaView = b.dataset.v; agenda(main); }));
  $('#pf')?.addEventListener('change', (e) => { agendaProf = e.target.value; agenda(main); });
  $('#prev').onclick = () => { agendaDate = agendaView === 'dia' ? addDays(agendaDate, -1) : addDays(agendaDate.slice(0, 8) + '01', -1).slice(0, 8) + '01'; agenda(main); };
  $('#next').onclick = () => { agendaDate = agendaView === 'dia' ? addDays(agendaDate, 1) : addDays(agendaDate.slice(0, 8) + '28', 7).slice(0, 8) + '01'; agenda(main); };
  $('#hoje').onclick = () => { agendaDate = todayLocal(); agenda(main); };
  $('#date').onchange = (e) => { agendaDate = e.target.value; agenda(main); };
  $('#novo')?.addEventListener('click', () => newAppointment({ start: agendaDate + 'T09:00', professional_id: agendaProf ? +agendaProf : undefined }));
  $('#bloq')?.addEventListener('click', () => blockModal(profs));
  const draw = async () => (agendaView === 'dia' ? drawDay(c) : drawMonth(c));
  await draw(); onLive(draw);
}

async function drawDay(c) {
  const data = await api(`/agenda?from=${agendaDate}&days=1${agendaProf ? '&professional_id=' + agendaProf : ''}`);
  const START = 7 * 60, END = 21 * 60, STEP = 15, H = 16;
  const rows = (END - START) / STEP;
  const wd = toDate(agendaDate).getUTCDay();
  const profs = data.professionals.filter((p) => !agendaProf || String(p.id) === agendaProf);
  if (!profs.length) { c.innerHTML = '<div class="card empty">Nenhum profissional para exibir.</div>'; return; }
  const toMin = (s) => (+s.slice(11, 13)) * 60 + (+s.slice(14, 16));
  const tcol = Array.from({ length: rows }, (_, i) => { const m = START + i * STEP; return `<div class="tcell" style="height:${H}px;line-height:${H}px">${m % 60 === 0 ? String(m / 60).padStart(2, '0') + ':00' : ''}</div>`; }).join('');
  const cols = profs.map((p) => {
    const sched = JSON.parse(p.schedule_json || '{}')[wd] || [];
    const slots = Array.from({ length: rows }, (_, i) => {
      const m = START + i * STEP; const t = `${String(Math.floor(m / 60)).padStart(2, '0')}:${String(m % 60).padStart(2, '0')}`;
      const on = sched.some(([a, b]) => t >= a && t < b);
      return `<div class="slot ${on && !isProf() ? 'free' : on ? '' : 'off'}" style="height:${H}px;${m % 60 === 0 ? 'border-top:1px solid #2a2a31' : ''}" data-p="${p.id}" data-t="${agendaDate}T${t}"></div>`;
    }).join('');
    const blocks = data.blocks.filter((b) => !b.professional_id || b.professional_id === p.id).map((b) => {
      const s = Math.max(START, b.start.slice(0, 10) < agendaDate ? START : toMin(b.start)); const e = Math.min(END, b.end.slice(0, 10) > agendaDate ? END : toMin(b.end));
      return e > s ? `<div class="ev" style="top:${((s - START) / STEP) * H}px;height:${((e - s) / STEP) * H}px;background:repeating-linear-gradient(135deg,#2a1215 0 6px,#1f0d10 6px 12px);border-left-color:var(--red);cursor:default"><div class="t">⛔ ${esc(b.reason || 'Bloqueado')}</div></div>` : '';
    }).join('');
    const evs = data.appointments.filter((a) => a.professional_id === p.id).map((a) => {
      const s = toMin(a.start); const e = toMin(a.end);
      return `<div class="ev ${a.status} ${a.created_by}" data-a="${a.id}" style="top:${((s - START) / STEP) * H + 1}px;height:${((e - s) / STEP) * H - 2}px;border-left-color:${p.color}">
        <div class="t">${a.created_by === 'agente' ? '✳️ ' : ''}${esc(a.client_name || a.client_phone)} <span class="s">${hm(a.start)}–${hm(a.end)}</span></div>
        <div class="s">${esc(a.service_name)}${a.session_number ? ` · ${a.session_number}ª` : ''} · ${STATUS[a.status]?.[0] || a.status}</div></div>`;
    }).join('');
    return `<div style="position:relative">${slots}${blocks}${evs}</div>`;
  }).join('');
  c.innerHTML = `<div class="row" style="margin-bottom:10px"><h3>${cap(dataLonga(agendaDate))}</h3><span class="muted small right">${data.appointments.filter((a) => a.status !== 'cancelado').length} atendimentos</span></div>
   <div class="agenda" style="grid-template-columns:64px repeat(${profs.length}, minmax(170px,1fr))">
    <div class="hcell"></div>${profs.map((p) => `<div class="hcell"><span class="dot" style="background:${p.color}"></span><div>${esc(p.name)}<div class="muted small">${esc(p.specialty || '')}</div></div></div>`).join('')}
    <div>${tcol}</div>${cols}</div>`;
  $$('.slot.free', c).forEach((s) => (s.onclick = () => newAppointment({ start: s.dataset.t, professional_id: +s.dataset.p })));
  $$('.ev[data-a]', c).forEach((e) => (e.onclick = (ev) => { ev.stopPropagation(); openAppointment(+e.dataset.a, data.appointments.find((a) => a.id === +e.dataset.a)); }));
}

async function drawMonth(c) {
  const first = agendaDate.slice(0, 8) + '01';
  const startDow = (toDate(first).getUTCDay() + 6) % 7;
  const gridStart = addDays(first, -startDow);
  const data = await api(`/agenda?from=${gridStart}&days=42${agendaProf ? '&professional_id=' + agendaProf : ''}`);
  const today = todayLocal();
  const byDay = {};
  for (const a of data.appointments) if (a.status !== 'cancelado') (byDay[a.start.slice(0, 10)] ||= []).push(a);
  const agentN = data.appointments.filter((a) => a.created_by === 'agente' && a.start.slice(0, 7) === first.slice(0, 7)).length;
  c.innerHTML = `<div class="row" style="margin-bottom:10px"><h3>${first.slice(5, 7)}/${first.slice(0, 4)}</h3><span class="badge orange right">✳️ ${agentN} agendados pelo agente</span></div>
   <div class="month">${['seg', 'ter', 'qua', 'qui', 'sex', 'sáb', 'dom'].map((x) => `<div class="small muted" style="padding:0 4px">${x}</div>`).join('')}
   ${Array.from({ length: 42 }, (_, i) => { const day = addDays(gridStart, i); const list = byDay[day] || [];
      return `<div class="day ${day === today ? 'today' : ''}" style="${day.slice(0, 7) !== first.slice(0, 7) ? 'opacity:.4' : ''}"><div class="small muted row between"><span data-day="${day}" style="cursor:pointer">${+day.slice(8)}</span>${list.length ? `<span>${list.length}</span>` : ''}</div>
      ${list.slice(0, 4).map((a) => `<div class="chip ${a.created_by} ${a.status}" data-a="${a.id}" style="background:${a.color}33;color:#e5e7eb;border-left:3px solid ${a.color}" title="${esc(a.client_name)} ${hm(a.start)} · ${esc(a.professional_name)}">${hm(a.start)} ${esc((a.client_name || '').split(' ')[0])}</div>`).join('')}${list.length > 4 ? `<div class="small dim" data-day="${day}" style="cursor:pointer">+${list.length - 4}</div>` : ''}</div>`; }).join('')}</div>`;
  $$('.chip', c).forEach((e) => (e.onclick = () => openAppointment(+e.dataset.a, data.appointments.find((a) => a.id === +e.dataset.a))));
  $$('[data-day]', c).forEach((e) => (e.onclick = () => { agendaDate = e.dataset.day; agendaView = 'dia'; route(); }));
}

async function newAppointment({ start, professional_id, client_id } = {}) {
  const [svcs, profs] = await Promise.all([api('/services'), api('/professionals')]);
  const m = modal('Novo agendamento', `
    ${client_id ? `<input type="hidden" name="client_id" value="${client_id}">` : `<div class="grid g2"><label class="f">Nome do ${T('cliente')}<input name="client_name" required maxlength="80"></label><label class="f">WhatsApp (DDD+número)<input name="client_phone" placeholder="11999999999" maxlength="15"></label></div>`}
    <label class="f">${cap(T('profissional'))}<select name="professional_id" id="np">${profs.filter((p) => p.active).map((p) => `<option value="${p.id}" ${p.id === professional_id ? 'selected' : ''}>${esc(p.name)} — ${esc(p.specialty || '')}</option>`).join('')}</select></label>
    <label class="f">Serviço<select name="service_id" id="ns"></select></label>
    <div class="grid g2"><label class="f">Início<input type="datetime-local" name="start" id="nt" value="${start || ''}" step="300"></label><div class="f small muted" id="ninfo" style="justify-content:flex-end"></div></div>
    <div class="small muted">Horários livres neste dia: <span id="nfree"></span></div>
    <label class="row small"><input type="checkbox" name="package"> Reservar o pacote de ${T('sessoes')} (se o serviço tiver)</label>
    <label class="f">Observações<input name="notes" maxlength="500"></label>`, {
    onSave: async (el) => { const b = formData(el); await api('/appointments', { method: 'POST', body: b }); toast('Agendamento criado'); window.dispatchEvent(new Event('live')); },
  });
  const fillSvcs = () => {
    const pid = +$('#np', m.el).value;
    const list = svcs.filter((s) => s.active && s.professionals.some((x) => x.professional_id === pid));
    $('#ns', m.el).innerHTML = list.map((s) => `<option value="${s.id}">${esc(s.category)} › ${esc(s.name)}</option>`).join('') || '<option value="">Este profissional não tem serviços</option>';
    info();
  };
  const info = async () => {
    const sid = $('#ns', m.el).value; const pid = $('#np', m.el).value; if (!sid) return;
    const p = await api(`/price?service_id=${sid}&professional_id=${pid}`);
    $('#ninfo', m.el).textContent = `${p.duration} min${p.buffer ? ` + ${p.buffer} min de intervalo` : ''} · ${money2(p.price)}`;
    const day = ($('#nt', m.el).value || todayLocal()).slice(0, 10);
    const free = await api(`/availability?service_id=${sid}&professional_id=${pid}&date=${day}`);
    $('#nfree', m.el).innerHTML = free.slice(0, 16).map((o) => `<a href="#" data-t="${o.start}" style="margin-right:6px">${hm(o.start)}</a>`).join('') || 'nenhum';
    $$('[data-t]', m.el).forEach((a) => (a.onclick = (e) => { e.preventDefault(); $('#nt', m.el).value = a.dataset.t; }));
  };
  $('#np', m.el).onchange = fillSvcs; $('#ns', m.el).onchange = info; $('#nt', m.el).onchange = info;
  fillSvcs();
  return m;
}

function openAppointment(id, a) {
  if (!a) return;
  const m = modal(`${a.service_name}${a.session_number ? ` · ${a.session_number}ª ${T('sessao')}` : ''}`, `
    <div class="row wrap">${statusBadge(a.status)} ${a.created_by === 'agente' ? '<span class="badge orange">✳️ agendado pelo agente</span>' : `<span class="badge">via ${a.created_by}</span>`} ${a.cancelled_by ? `<span class="badge">cancelado por ${a.cancelled_by}</span>` : ''}</div>
    <div class="grid g2">
      <div><div class="small muted">${cap(T('cliente'))}</div>${isProf() ? esc(a.client_name || '—') : `<a href="#/clientes/${a.client_id}" data-x>${esc(a.client_name || '—')}</a>`}<div class="small muted">${esc(a.client_phone)}</div></div>
      <div><div class="small muted">Quando</div>${cap(dataLonga(a.start))} · ${hm(a.start)}–${hm(a.end)}<div class="small muted">${esc(a.professional_name)} · ${money2(a.price)}${isMgr() && a.cost != null ? ` · lucro ${money2(a.price - a.cost - a.commission)}` : ''}</div></div>
    </div>
    ${a.notes ? `<div class="small muted">Obs.: ${esc(a.notes)}</div>` : ''}
    <div class="row wrap">
      <button class="btn sm" data-s="confirmado">✓ Confirmar</button><button class="btn sm" data-s="realizado">✔ Realizado</button>
      <button class="btn sm danger" data-s="faltou">✗ Faltou</button>
    </div>
    ${isProf() ? '' : `<div class="row wrap"><button class="btn sm danger" data-c="cliente">Cancelar (pedido do ${T('cliente')})</button><button class="btn sm danger" data-c="clinica">Cancelar (pela clínica)</button></div>
    <div class="small dim">Ao marcar falta ou cancelar, o agente envia novas datas ao ${T('cliente')} automaticamente e oferece a vaga para a lista de espera.</div>
    <div class="row"><input type="datetime-local" id="rs" step="300" value="${a.start}"><button class="btn sm" id="rsb">Remarcar e avisar</button></div>`}`);
  const done = (msg) => { toast(msg); m.close(); window.dispatchEvent(new Event('live')); };
  $$('[data-s]', m.el).forEach((b) => (b.onclick = async () => {
    try { await api(`/appointments/${id}`, { method: 'PATCH', body: { status: b.dataset.s } }); done(b.dataset.s === 'faltou' ? 'Falta registrada — o agente já ofereceu novas datas' : 'Status atualizado'); } catch (e) { toast(e.message, true); }
  }));
  $$('[data-c]', m.el).forEach((b) => (b.onclick = async () => {
    const reason = prompt('Motivo do cancelamento (opcional):', '') ?? null; if (reason === null) return;
    try { await api(`/appointments/${id}`, { method: 'PATCH', body: { status: 'cancelado', by: b.dataset.c, reason } }); done('Cancelado — novas datas enviadas ao ' + T('cliente')); } catch (e) { toast(e.message, true); }
  }));
  $('#rsb', m.el)?.addEventListener('click', async () => { try { await api(`/appointments/${id}/reschedule`, { method: 'POST', body: { start: $('#rs', m.el).value } }); done('Remarcado e ' + T('cliente') + ' avisado'); } catch (e) { toast(e.message, true); } });
}

function blockModal(profs) {
  const d = agendaDate;
  modal('Bloquear período', `<div class="small muted">Use para férias, congresso, manutenção ou imprevistos. Quem já estava agendado no período recebe na hora novas opções de data.</div>
    <label class="f">${cap(T('profissional'))}<select name="professional_id"><option value="">Clínica inteira</option>${profs.map((p) => `<option value="${p.id}" ${String(p.id) === agendaProf ? 'selected' : ''}>${esc(p.name)}</option>`).join('')}</select></label>
    <div class="grid g2"><label class="f">Início<input type="datetime-local" name="start" value="${d}T08:00"></label><label class="f">Fim<input type="datetime-local" name="end" value="${d}T18:00"></label></div>
    <label class="f">Motivo<input name="reason" placeholder="Ex.: congresso" maxlength="200"></label>
    <label class="row small"><input type="checkbox" name="reoffer" checked> Remarcar automaticamente quem estiver no período</label>`, {
    saveLabel: 'Bloquear', onSave: async (el) => { const r = await api('/blocks', { method: 'POST', body: formData(el) }); toast(`Período bloqueado · ${r.afetados} ${T('clientes')} avisados com novas datas`); window.dispatchEvent(new Event('live')); },
  });
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
  const tag = m.meta?.blocked ? `<span class="tag" style="color:#fca5a5">🛡 bloqueado: ${esc(m.meta.blocked)}</span>` : m.sender === 'agente' ? '<span class="tag">✳ agente IA</span>' : m.sender === 'humano' ? `<span class="tag" style="color:#fde68a">🙋 ${esc(m.meta?.user || 'equipe')}</span>` : '';
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

// ---------------- Lista de espera ----------------
async function espera(main) {
  const c = await header(main, 'Lista de espera', `Quando um horário vaga (cancelamento/remarcação), o agente oferece automaticamente ao primeiro da fila compatível`);
  const draw = async () => {
    const list = await api('/waitlist');
    c.innerHTML = `<div class="card" style="padding:0"><table><tr><th>Desde</th><th>${cap(T('cliente'))}</th><th>Serviço</th><th>${cap(T('profissional'))}</th><th>Status</th><th></th></tr>
      ${list.map((w) => `<tr><td class="small muted">${utcToLocal(w.created_at)}</td><td><a href="#/clientes/${w.client_id}">${esc(w.client_name)}</a><div class="small dim">${esc(w.client_phone)}</div></td><td>${esc(w.service_name)}${w.notes ? `<div class="small dim">${esc(w.notes)}</div>` : ''}</td><td>${esc(w.professional_name || 'qualquer')}</td>
      <td><span class="badge ${w.status === 'aguardando' ? 'amber' : w.status === 'atendido' ? 'green' : ''}">${w.status}</span></td>
      <td>${w.status !== 'atendido' && w.status !== 'cancelado' ? `<button class="btn sm" data-w="${w.id}" data-s="cancelado">Remover</button>` : ''}</td></tr>`).join('') || '<tr><td colspan="6" class="empty">Ninguém na lista. O agente oferece a lista quando não há horário no período desejado.</td></tr>'}</table></div>`;
    $$('[data-w]', c).forEach((b) => (b.onclick = async () => { await api(`/waitlist/${b.dataset.w}`, { method: 'PATCH', body: { status: b.dataset.s } }); draw(); }));
  };
  await draw(); onLive(draw);
}

// ---------------- Catálogo de serviços ----------------
async function servicos(main) {
  const mgr = isMgr();
  const c = await header(main, 'Catálogo de serviços', 'Consultas, exames, procedimentos e terapias · duração, preço e repasse podem variar por profissional', mgr ? '<button class="btn primary sm" id="novo">+ Serviço</button>' : '');
  const [list, profs] = await Promise.all([api('/services'), api('/professionals')]);
  const cats = [...new Set(list.map((s) => s.category || 'Outros'))];
  const range = (s) => { const ps = [s.price, ...s.professionals.map((p) => p.price ?? s.price)]; const a = Math.min(...ps), b = Math.max(...ps); return a === b ? money(a) : `${money(a)}–${money(b)}`; };
  const durs = (s) => { const ds = [s.duration_min, ...s.professionals.map((p) => p.duration_min || s.duration_min)]; const a = Math.min(...ds), b = Math.max(...ds); return a === b ? `${a} min` : `${a}–${b} min`; };
  c.innerHTML = cats.map((cat) => `<div class="card" style="padding:0;margin-bottom:14px"><div style="padding:12px 14px" class="row"><h3>${esc(cat)}</h3><span class="small muted right">${list.filter((s) => (s.category || 'Outros') === cat).length} serviços</span></div><table>
    <tr><th>Serviço</th><th>Duração</th><th>Preço</th>${mgr ? '<th>Custo</th><th>Margem*</th>' : ''}<th>Agendamento</th><th>${cap(T('profissionais'))}</th></tr>
    ${list.filter((s) => (s.category || 'Outros') === cat).map((s) => `<tr class="click" data-id="${s.id}" style="${s.active ? '' : 'opacity:.45'}">
      <td><b>${esc(s.name)}</b> ${s.is_entry ? '<span class="badge green">entrada</span>' : ''} ${s.package_sessions ? `<span class="badge blue">pacote ${s.package_sessions}x</span>` : ''} ${s.modality !== 'presencial' ? `<span class="badge purple">${s.modality}</span>` : ''}
        ${s.preparation ? `<div class="small dim">Preparo: ${esc(s.preparation)}</div>` : ''}</td>
      <td>${durs(s)}${s.buffer_min ? `<div class="small dim">+${s.buffer_min} min intervalo</div>` : ''}</td><td>${s.price || s.professionals.some((p) => p.price) ? range(s) : 'sem custo'}</td>
      ${mgr ? `<td class="muted">${money(s.cost)}</td><td>${s.price ? Math.round((100 * (s.price - s.cost)) / s.price) + '%' : '—'}</td>` : ''}
      <td>${s.online_booking ? '<span class="badge green">agente + app</span>' : '<span class="badge amber">só equipe</span>'}</td>
      <td class="small">${s.professionals.map((p) => `${esc(p.name)}${p.duration_min || p.price != null ? ` <span class="dim">(${[p.duration_min ? p.duration_min + 'min' : '', p.price != null ? money(p.price) : ''].filter(Boolean).join(' · ')})</span>` : ''}`).join('<br>') || '<span class="badge red">sem profissional</span>'}</td></tr>`).join('')}</table></div>`).join('') +
    (mgr ? '<div class="small dim">* Margem antes do repasse ao profissional, sobre o preço base.</div>' : '');
  if (!mgr) return;
  const form = (s = { professionals: [], active: 1, online_booking: 1, modality: 'presencial', category: cats[0] || 'Consultas' }) => `
    <div class="grid g3"><label class="f">Nome<input name="name" value="${esc(s.name || '')}" maxlength="120"></label>
      <label class="f">Categoria<input name="category" list="cats" value="${esc(s.category || '')}" maxlength="60"><datalist id="cats">${cats.map((x) => `<option value="${esc(x)}">`).join('')}<option value="Consultas"><option value="Exames"><option value="Procedimentos"><option value="Terapias"></datalist></label>
      <label class="f">Modalidade<select name="modality">${['presencial', 'online', 'ambos'].map((x) => `<option ${s.modality === x ? 'selected' : ''}>${x}</option>`).join('')}</select></label></div>
    <div class="grid g4"><label class="f">Duração padrão (min)<input type="number" name="duration_min" value="${s.duration_min || 30}" min="5"></label><label class="f">Intervalo depois (min)<input type="number" name="buffer_min" value="${s.buffer_min || 0}" min="0" title="limpeza/preparo da sala"></label>
      <label class="f">Preço padrão (R$)<input type="number" step="0.01" name="price" value="${s.price ?? 0}"></label><label class="f">Custo direto (R$)<input type="number" step="0.01" name="cost" value="${s.cost ?? 0}" title="insumos, materiais"></label></div>
    <label class="f">Descrição (o agente usa para explicar)<input name="description" value="${esc(s.description || '')}" maxlength="500"></label>
    <label class="f">Preparo / orientações (enviado na confirmação e no lembrete)<input name="preparation" value="${esc(s.preparation || '')}" maxlength="500"></label>
    <label class="f">Palavras-chave (como os ${T('clientes')} pedem este serviço)<input name="keywords" value="${esc(s.keywords || '')}" maxlength="500"></label>
    <div class="grid g4"><label class="f">Retorno incluso (dias)<input type="number" name="return_days" value="${s.return_days || 0}"></label><label class="f">Idade mín.<input type="number" name="min_age" value="${s.min_age ?? ''}"></label><label class="f">Idade máx.<input type="number" name="max_age" value="${s.max_age ?? ''}"></label>
      <label class="f">Status<select name="active"><option value="1">Ativo</option><option value="0" ${s.active === 0 ? 'selected' : ''}>Inativo</option></select></label></div>
    <div class="row wrap"><label class="row small"><input type="checkbox" name="online_booking" ${s.online_booking ? 'checked' : ''}> Agente e app podem agendar sozinhos</label>
      <label class="row small"><input type="checkbox" name="is_entry" ${s.is_entry ? 'checked' : ''}> Porta de entrada (avaliação/1ª consulta)</label>
      <label class="row small"><input type="checkbox" name="requires_document" ${s.requires_document ? 'checked' : ''}> Pedir foto de documento</label><input name="document_label" value="${esc(s.document_label || '')}" placeholder="qual documento" style="width:180px"></div>
    <details ${s.package_sessions ? 'open' : ''}><summary class="small muted" style="cursor:pointer">Pacote de sessões (ex.: fisioterapia, psicoterapia, estética)</summary>
      <div class="grid g4" style="margin-top:8px"><label class="f">Nº de sessões<input type="number" name="package_sessions" value="${s.package_sessions || 0}"></label><label class="f">Preço por sessão<input type="number" step="0.01" name="package_session_price" value="${s.package_session_price || 0}"></label>
      <label class="f">Sessões/semana<input type="number" name="sessions_per_week" value="${s.sessions_per_week || 2}" min="1" max="5"></label>
      <label class="f">Serviço das sessões<select name="package_service_id"><option value="">o próprio</option>${list.filter((x) => x.id !== s.id).map((x) => `<option value="${x.id}" ${x.id === s.package_service_id ? 'selected' : ''}>${esc(x.name)}</option>`).join('')}</select></label></div></details>
    <h4>Quem realiza e personalização por ${T('profissional')}</h4>
    <div class="small dim">Deixe em branco para usar o padrão do serviço. Ex.: a Dra. X faz em 40 min e cobra R$ 280.</div>
    <table class="small"><tr><th></th><th>${cap(T('profissional'))}</th><th>Duração (min)</th><th>Preço (R$)</th><th>Repasse (%)</th></tr>
    ${profs.filter((p) => p.active).map((p) => { const ps = s.professionals.find((x) => x.professional_id === p.id); return `<tr data-pp="${p.id}"><td><input type="checkbox" class="pp-on" ${ps ? 'checked' : ''}></td><td>${esc(p.name)} <span class="dim">${esc(p.specialty || '')}</span></td>
      <td><input type="number" class="pp-d" value="${ps?.duration_min ?? ''}" placeholder="${s.duration_min || ''}" style="width:90px"></td><td><input type="number" step="0.01" class="pp-p" value="${ps?.price ?? ''}" placeholder="${s.price ?? ''}" style="width:110px"></td>
      <td><input type="number" class="pp-c" value="${ps?.commission_pct ?? ''}" placeholder="${p.commission_pct ?? ''}" style="width:80px"></td></tr>`; }).join('')}</table>`;
  const collect = (el) => {
    const b = formData(el);
    for (const k of ['is_entry', 'requires_document', 'online_booking']) b[k] = b[k] ? 1 : 0;
    b.active = +b.active;
    b.professionals = $$('[data-pp]', el).filter((r) => $('.pp-on', r).checked).map((r) => ({ professional_id: +r.dataset.pp, duration_min: $('.pp-d', r).value || null, price: $('.pp-p', r).value, commission_pct: $('.pp-c', r).value }));
    return b;
  };
  const save = (id) => async (el) => { await api(id ? `/services/${id}` : '/services', { method: id ? 'PUT' : 'POST', body: collect(el) }); toast('Serviço salvo'); servicos(main); };
  $('#novo').onclick = () => modal('Novo serviço', form(), { wide: true, onSave: save() });
  $$('tr.click', c).forEach((r) => (r.onclick = () => { const s = list.find((x) => x.id === +r.dataset.id); modal(s.name, form(s), { wide: true, onSave: save(s.id) }); }));
}

// ---------------- Profissionais ----------------
const WD = ['Dom', 'Seg', 'Ter', 'Qua', 'Qui', 'Sex', 'Sáb'];
async function profissionais(main) {
  const mgr = isMgr();
  const c = await header(main, cap(T('profissionais')), 'Cadastro, registro no conselho, jornada, intervalos e procedimentos de cada um', mgr ? '<button class="btn primary sm" id="novo">+ Adicionar</button>' : '');
  const [list, svcs] = await Promise.all([api('/professionals'), api('/services')]);
  c.innerHTML = `<div class="grid g3">${list.map((p) => `<div class="card col ${mgr ? 'click' : ''}" data-id="${p.id}" style="${mgr ? 'cursor:pointer;' : ''}${p.active ? '' : 'opacity:.5'}">
    <div class="row"><div class="avatar" style="background:${p.color}33;color:${p.color}">${esc(p.name.replace(/^(Dra?\.?\s*)/, '')[0])}</div><div><b>${esc(p.name)}</b><div class="small muted">${esc(p.specialty || '')}</div><div class="small dim">${esc([p.council, p.registry].filter(Boolean).join(' '))}</div></div></div>
    <div class="small">${[1, 2, 3, 4, 5, 6, 0].filter((d) => p.schedule[d]?.length).map((d) => `${WD[d]} ${p.schedule[d].map((w) => w.join('–')).join(', ')}`).join('<br>') || '<span class="dim">sem jornada</span>'}</div>
    <div class="col" style="gap:3px">${p.services.map((s) => `<div class="row small"><span class="grow">${esc(s.name)}</span><span class="dim">${s.duration_min || s.base_duration} min · ${money(s.price ?? s.base_price)}</span></div>`).join('') || '<span class="badge red">nenhum serviço</span>'}</div>
    ${mgr ? `<div class="small dim">Repasse padrão ${p.commission_pct || 0}%${p.buffer_min ? ` · intervalo ${p.buffer_min} min` : ''}</div>` : ''}</div>`).join('')}</div>`;
  if (!mgr) return;
  const blank = { schedule: { 1: [['08:00', '12:00'], ['13:00', '18:00']], 2: [['08:00', '12:00'], ['13:00', '18:00']], 3: [['08:00', '12:00'], ['13:00', '18:00']], 4: [['08:00', '12:00'], ['13:00', '18:00']], 5: [['08:00', '12:00'], ['13:00', '18:00']] }, services: [], active: 1, commission_pct: 40, buffer_min: 0 };
  const form = (p = blank) => `
    <div class="grid g3"><label class="f">Nome<input name="name" value="${esc(p.name || '')}" maxlength="120"></label><label class="f">Especialidade<input name="specialty" value="${esc(p.specialty || '')}" maxlength="120"></label><label class="f">Cor na agenda<input type="color" name="color" value="${p.color || '#3b82f6'}" style="height:38px"></label>
    <label class="f">Conselho (CRM, CRO, CRP, CREFITO, CRN…)<input name="council" value="${esc(p.council || '')}" maxlength="40"></label><label class="f">Nº de registro<input name="registry" value="${esc(p.registry || '')}" maxlength="40"></label><label class="f">Telefone<input name="phone" value="${esc(p.phone || '')}" maxlength="20"></label>
    <label class="f">E-mail<input name="email" value="${esc(p.email || '')}" maxlength="120"></label><label class="f">Repasse padrão (%)<input type="number" name="commission_pct" value="${p.commission_pct ?? 0}" min="0" max="100"></label><label class="f">Intervalo entre atendimentos (min)<input type="number" name="buffer_min" value="${p.buffer_min ?? 0}" min="0"></label></div>
    <label class="f">Apresentação (o agente pode usar)<input name="bio" value="${esc(p.bio || '')}" maxlength="500"></label>
    <h4>Jornada (até 2 turnos por dia — vazio = folga)</h4>
    <div class="sched-grid">${[1, 2, 3, 4, 5, 6, 0].map((d) => { const w = p.schedule[d] || []; return `<span>${WD[d]}</span>${[0, 1].map((i) => `<div class="row"><input type="time" data-d="${d}" data-i="${i}" data-k="0" value="${w[i]?.[0] || ''}"><input type="time" data-d="${d}" data-i="${i}" data-k="1" value="${w[i]?.[1] || ''}"></div>`).join('')}<span></span>`; }).join('')}</div>
    <h4>Procedimentos que realiza — tempo e preço deste ${T('profissional')}</h4>
    <div class="small dim">Em branco = usa o padrão do catálogo.</div>
    <table class="small"><tr><th></th><th>Serviço</th><th>Duração (min)</th><th>Preço (R$)</th><th>Repasse (%)</th></tr>
    ${svcs.filter((s) => s.active).map((s) => { const ps = p.services.find((x) => x.service_id === s.id); return `<tr data-ss="${s.id}"><td><input type="checkbox" class="ss-on" ${ps ? 'checked' : ''}></td><td>${esc(s.name)} <span class="dim">${esc(s.category)}</span></td>
      <td><input type="number" class="ss-d" value="${ps?.duration_min ?? ''}" placeholder="${s.duration_min}" style="width:90px"></td><td><input type="number" step="0.01" class="ss-p" value="${ps?.price ?? ''}" placeholder="${s.price}" style="width:110px"></td>
      <td><input type="number" class="ss-c" value="${ps?.commission_pct ?? ''}" placeholder="padrão" style="width:80px"></td></tr>`; }).join('')}</table>
    ${p.id ? `<label class="row small"><input type="checkbox" name="active" ${p.active ? 'checked' : ''}> Ativo</label>` : ''}`;
  const collect = (el) => {
    const b = formData(el); const sch = {};
    $$('[data-d]', el).forEach((i) => { if (!i.value) return; const d = i.dataset.d; sch[d] ||= [[], []]; sch[d][i.dataset.i][i.dataset.k] = i.value; });
    for (const d in sch) sch[d] = sch[d].filter((w) => w[0] && w[1]);
    b.schedule = sch; if ('active' in b) b.active = b.active ? 1 : 0;
    b.services = $$('[data-ss]', el).filter((r) => $('.ss-on', r).checked).map((r) => ({ service_id: +r.dataset.ss, duration_min: $('.ss-d', r).value || null, price: $('.ss-p', r).value, commission_pct: $('.ss-c', r).value }));
    return b;
  };
  $('#novo').onclick = () => modal('Novo ' + T('profissional'), form(), { wide: true, onSave: async (el) => { await api('/professionals', { method: 'POST', body: collect(el) }); profissionais(main); } });
  $$('[data-id]', c).forEach((x) => (x.onclick = () => { const p = list.find((y) => y.id === +x.dataset.id); modal(p.name, form(p), { wide: true, onSave: async (el) => { await api(`/professionals/${p.id}`, { method: 'PUT', body: collect(el) }); toast('Salvo'); profissionais(main); } }); }));
}

// ---------------- Clínica & regras ----------------
async function empresa(main) {
  const c = await header(main, 'Clínica & regras', 'Tudo o que o agente informa e as regras que ele segue ao agendar');
  const t = (await api('/me')).tenant; const hours = JSON.parse(t.hours_json || '{}'); const terms = JSON.parse(t.terms_json || '{}');
  const num = (n, l, v, help = '') => `<label class="f">${l}<input type="number" step="any" name="${n}" value="${v ?? ''}">${help ? `<span class="dim" style="font-size:11px">${help}</span>` : ''}</label>`;
  c.innerHTML = `<form id="f" class="col" style="max-width:980px">
    <div class="card col"><h3>Dados da clínica</h3>
      <div class="grid g3"><label class="f">Nome<input name="name" value="${esc(t.name)}"></label><label class="f">Tipo<select name="segment">${Object.entries(ME.segments).map(([k, v]) => `<option value="${k}" ${k === t.segment ? 'selected' : ''}>${v}</option>`).join('')}</select></label><label class="f">Telefone<input name="phone" value="${esc(t.phone || '')}"></label>
      <label class="f">Endereço<input name="address" value="${esc(t.address || '')}"></label><label class="f">Cidade<input name="city" value="${esc(t.city || '')}"></label><div class="grid g2"><label class="f">Latitude<input type="number" step="any" name="lat" value="${t.lat ?? ''}"></label><label class="f">Longitude<input type="number" step="any" name="lng" value="${t.lng ?? ''}"></label></div></div>
      <h4>Horário de funcionamento</h4>
      <div class="grid g4">${[1, 2, 3, 4, 5, 6, 0].map((d) => `<div class="row"><span style="width:34px">${WD[d]}</span><input type="time" data-h="${d}" data-k="0" value="${hours[d]?.[0] || ''}"><input type="time" data-h="${d}" data-k="1" value="${hours[d]?.[1] || ''}"></div>`).join('')}</div></div>
    <div class="card col"><h3>Regras de agenda</h3>
      <div class="grid g4">${num('min_advance_hours', 'Antecedência mínima (horas)', t.min_advance_hours, 'não agenda em cima da hora')}${num('max_advance_days', 'Agenda aberta até (dias)', t.max_advance_days)}${num('slot_step_min', 'Intervalo da grade (min)', t.slot_step_min, 'ex.: 15 → 08:00, 08:15…')}${num('options_count', 'Opções oferecidas', t.options_count, '1 a 4 horários por vez')}
      ${num('cancel_min_hours', 'Cancelar/remarcar sozinho até (h antes)', t.cancel_min_hours, 'depois disso vai para a equipe')}${num('reminder_hours_before', 'Lembrete (horas antes)', t.reminder_hours_before)}
      <label class="f">Não enviar mensagens de<input type="time" name="quiet_start" value="${t.quiet_start}"></label><label class="f">até<input type="time" name="quiet_end" value="${t.quiet_end}"></label></div></div>
    <div class="card col"><h3>Informações que o agente passa</h3>
      <div class="grid g2"><label class="f">Convênios aceitos (vazio = só particular; o agente transfere dúvidas)<textarea name="insurances" rows="3">${esc(t.insurances || '')}</textarea></label>
      <label class="f">Formas de pagamento<textarea name="payment_methods" rows="3">${esc(t.payment_methods || '')}</textarea></label></div>
      <label class="f">Políticas (chegada, atraso, documentos, acompanhante, menores…)<textarea name="policies" rows="3">${esc(t.policies || '')}</textarea></label>
      <label class="f">Mensagem de boas-vindas (opcional)<input name="welcome_message" value="${esc(t.welcome_message || '')}" maxlength="300"></label></div>
    <div class="card col"><h3>Terminologia</h3><div class="small dim">Vazio = padrão do tipo de clínica (ex.: paciente/consulta). Útil para estética (cliente/sessão) ou veterinária (tutor).</div>
      <div class="grid g4">${['cliente', 'clientes', 'profissional', 'profissionais', 'sessao', 'sessoes', 'documento'].map((k) => `<label class="f">${k}<input data-t="${k}" value="${esc(terms[k] || '')}" placeholder="${esc(ME.terms[k] || '')}"></label>`).join('')}</div></div>
    <div><button class="btn primary">Salvar alterações</button></div></form>`;
  $('#f').onsubmit = async (e) => {
    e.preventDefault(); const b = formData(e.target); const h = {}; const tm = {};
    $$('[data-h]').forEach((i) => { if (i.value) (h[i.dataset.h] ||= [])[i.dataset.k] = i.value; }); for (const d in h) if (!h[d][0] || !h[d][1]) delete h[d];
    $$('[data-t]').forEach((i) => { if (i.value.trim()) tm[i.dataset.t] = i.value.trim(); });
    b.hours = h; b.terms = tm;
    try { await api('/tenant', { method: 'PUT', body: b }); toast('Salvo'); ME = null; route(); } catch (err) { toast(err.message, true); }
  };
}

// ---------------- Agente & automações ----------------
async function automacao(main) {
  const c = await header(main, 'Agente & automações', 'Atendimento no WhatsApp 24h, lembretes e ações proativas');
  const r = await api('/automation'); const t = r.tenant;
  const st = (s) => r.stats.find((x) => x.step === s) || {};
  const tg = (n, l, d) => `<label class="row small" style="align-items:flex-start"><input type="checkbox" name="${n}" ${t[n] ? 'checked' : ''} style="margin-top:3px"><span><b>${l}</b><br><span class="muted">${d}</span></span></label>`;
  c.innerHTML = `<div class="grid g2">
    <div class="card"><div class="row"><span style="color:var(--green)">⌁</span><div class="grow"><b>Agente · ${esc(t.name)}</b><div class="small muted">atendimento no WhatsApp</div></div>
      <span class="small" style="color:${t.automation_active ? 'var(--green)' : ''}">${t.automation_active ? 'Ativo' : 'Desligado'}</span><button class="toggle ${t.automation_active ? 'on' : ''}" id="tg"></button></div>
      <div class="flow" style="margin-top:14px">
        ${[['🟢', '#14532d', 'WhatsApp', 'chega a mensagem', 'whatsapp'], ['🎙', '#1e3a8a', 'Transcreve', 'áudio → texto', 'transcreve'], ['🛡', '#3f3f46', 'Proteção', 'bloqueia manipulação', 'protecao'], ['✳️', '#7c2d12', 'Agente', 'entende e decide', 'agente_ia'], ['📅', '#3f3f46', 'Agenda', 'acha horário livre', 'agenda'], ['✅', '#14532d', 'Responde', 'confirma no WhatsApp', 'responde']]
          .map(([ic, bg, n, d, s], i) => `<div class="node ${t.automation_active ? 'on' : ''}"><span class="k">${i + 1}</span><div class="ic" style="background:${bg}">${ic}</div><div><b>${n}</b><div class="small muted">${d}</div><div class="small dim">${st(s).n || 0}× ${st(s).avg_ms ? '· ' + (st(s).avg_ms / 1000).toFixed(1) + 's' : ''}</div></div></div>`).join('')}
      </div>
      <div class="small muted" style="margin-top:10px">Motor: <b>${r.agent.mode === 'claude' ? 'Claude · ' + esc(r.agent.model) : 'regras determinísticas'}</b>${r.agent.mode !== 'claude' ? ' — defina <span class="mono">ANTHROPIC_API_KEY</span> no servidor para respostas com IA generativa.' : ''}</div>
    </div>
    <form class="card col" id="cfg"><h3>Personalidade do agente</h3>
      <div class="grid g2"><label class="f">Nome<input name="agent_name" value="${esc(t.agent_name)}" maxlength="40"></label><label class="f">Tom de voz<input name="agent_tone" value="${esc(t.agent_tone)}" maxlength="120"></label></div>
      <label class="f">Orientações do gestor (o agente segue, sem nunca violar as regras de segurança)<textarea name="agent_instructions" rows="4" placeholder="Ex.: Ofereça sempre a consulta de avaliação antes de procedimentos estéticos. Menores de 18 só com responsável.">${esc(t.agent_instructions || '')}</textarea></label>
      <h4>Ações proativas</h4>
      ${tg('noshow_recovery', 'Repor faltas', 'Quando alguém falta, o agente oferece novas datas na hora.')}
      ${tg('reoffer_cancel', 'Repor cancelamentos', 'Após um cancelamento (do paciente ou da clínica), já envia novas opções.')}
      ${tg('waitlist_enabled', 'Lista de espera e encaixe', 'Sem vaga? Entra na fila. Vagou horário? O primeiro da fila é avisado.')}
      ${tg('auto_book_package', 'Reservar pacotes', 'Ao agendar um serviço com pacote, reserva as próximas sessões.')}
      ${tg('return_reminder', 'Avisar retorno incluso', 'Lembra o paciente quando o retorno gratuito está perto de vencer.')}
      <div class="grid g2"><label class="f">Convidar a retomar tratamento parado há (dias)<input type="number" name="reactivation_days" value="${t.reactivation_days}"></label><label class="f">Lembrete (horas antes)<input type="number" name="reminder_hours_before" value="${t.reminder_hours_before}"></label></div>
      <div class="row"><button class="btn primary">Salvar</button><button type="button" class="btn" id="run">⏱ Rodar rotinas agora</button></div>
    </form></div>
    <div class="card" style="margin-top:14px;padding:0"><div style="padding:12px 14px"><h3>Log de execução</h3></div><table><tr><th>Quando</th><th>Etapa</th><th>${cap(T('cliente'))}</th><th>Tempo</th><th>Detalhe</th></tr>
    ${r.logs.map((l) => `<tr><td class="small muted">${utcToLocal(l.created_at)}</td><td><span class="badge ${/protecao/.test(l.step) ? 'red' : /proativo|encaixe|reativacao|retorno|lembrete/.test(l.step) ? 'blue' : ''}">${esc(l.step)}</span></td><td>${l.conversation_id ? `<a href="#/conversas/${l.conversation_id}">${esc(l.client_name || '')}</a>` : ''}</td><td class="small">${l.ms != null ? (l.ms / 1000).toFixed(2) + 's' : ''}</td><td class="small mono muted" style="max-width:420px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(l.detail || '')}</td></tr>`).join('')}</table></div>`;
  $('#tg').onclick = async () => { await api('/tenant', { method: 'PUT', body: { automation_active: !t.automation_active } }); ME = null; route(); };
  $('#run').onclick = async () => { const x = await api('/jobs/run', { method: 'POST' }); toast(`${x.lembretes} lembretes · ${x.reposicoes} reposições · ${x.encaixes} encaixes · ${x.reativacoes} reativações · ${x.retornos} retornos`); };
  $('#cfg').onsubmit = async (e) => { e.preventDefault(); const b = formData(e.target); for (const k of ['noshow_recovery', 'reoffer_cancel', 'waitlist_enabled', 'auto_book_package', 'return_reminder']) b[k] = !!b[k]; await api('/tenant', { method: 'PUT', body: b }); toast('Configurações salvas'); };
}

// ---------------- Segurança ----------------
const SEC = { injection: ['Tentativa de manipulação da IA', 'red'], data: ['Pedido de dados de terceiros/internos', 'red'], discount: ['Pedido de desconto', 'amber'], offtopic: ['Assunto fora do escopo', ''], flood: ['Excesso de mensagens', 'amber'], saida_bloqueada: ['Resposta da IA bloqueada', 'purple'], login_falhou: ['Login com senha errada', 'amber'], login_bloqueado: ['Login bloqueado (força bruta)', 'red'], rate_limit: ['Limite de requisições', 'amber'], webhook_assinatura_invalida: ['Webhook com assinatura inválida', 'red'] };
async function seguranca(main) {
  const c = await header(main, 'Segurança', 'Proteções ativas do agente e do sistema, e o registro de tentativas bloqueadas');
  const r = await api('/security');
  c.innerHTML = `<div class="grid g2">
    <div class="card col"><h3>🛡 Agente de IA</h3><ul class="small" style="margin:0;padding-left:18px;line-height:1.7">
      <li>Mensagens do paciente são tratadas como dados, nunca como instruções (anti prompt injection), antes e depois da IA.</li>
      <li>Responde só sobre a clínica; assuntos fora do escopo são recusados com gentileza.</li>
      <li>Não dá desconto nem inventa preço: valores vêm só do catálogo e respostas com valores fora da tabela são bloqueadas.</li>
      <li>As ferramentas só acessam os agendamentos do próprio paciente; custos, repasses e dados de outros pacientes nunca chegam à IA.</li>
      <li>Telefones, e-mails e CPFs de terceiros são ocultados; respostas que mencionam o funcionamento interno são bloqueadas.</li>
      <li>Três tentativas de manipulação em 30 min pausam o agente e passam a conversa para a equipe.</li>
      <li>Emergências são orientadas (SAMU 192 / CVV 188) e transferidas para humano.</li></ul></div>
    <div class="card col"><h3>🔐 Sistema</h3><ul class="small" style="margin:0;padding-left:18px;line-height:1.7">
      <li>Senhas com scrypt; sessões assinadas que expiram e caem se a senha mudar.</li>
      <li>Bloqueio de força bruta: 5 erros por e-mail ou 20 por IP → 15 min.</li>
      <li>Limite de requisições por IP e de mensagens por número de WhatsApp.</li>
      <li>Perfis com permissões (admin, recepção, profissional) e isolamento total entre clínicas.</li>
      <li>Validação de todos os campos, tipos e tamanhos de arquivo; erros internos não são expostos.</li>
      <li>Cabeçalhos de segurança (CSP, anti-clickjacking, no-sniff, HSTS em produção).</li>
      <li>Webhook do WhatsApp com verificação de assinatura (<span class="mono">WHATSAPP_APP_SECRET</span>).</li>
      <li>Auditoria de acessos e alterações; exclusão de dados a pedido (LGPD).</li></ul></div></div>
    <div class="grid g4" style="margin-top:14px">${r.resumo.map((x) => kpi(SEC[x.kind]?.[0] || x.kind, x.n, 'últimos 30 dias')).join('') || '<div class="card small muted">Nenhuma tentativa registrada nos últimos 30 dias.</div>'}</div>
    <div class="card" style="margin-top:14px;padding:0"><div style="padding:12px 14px"><h3>Eventos recentes</h3></div><table><tr><th>Quando</th><th>Tipo</th><th>Origem</th><th>Conteúdo</th></tr>
    ${r.events.map((e) => `<tr><td class="small muted">${utcToLocal(e.created_at)}</td><td><span class="badge ${SEC[e.kind]?.[1] || ''}">${esc(SEC[e.kind]?.[0] || e.kind)}</span></td><td class="small mono">${esc(e.source || '')}</td><td class="small muted" style="max-width:520px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(e.detail || '')}</td></tr>`).join('') || '<tr><td colspan="4" class="empty">Sem eventos</td></tr>'}</table></div>`;
}

// ---------------- Integrações ----------------
const INTEG = {
  whatsapp: ['🟢', 'WhatsApp Business (Cloud API · Meta)', 'Recebe e envia mensagens, áudios, imagens, botões e localização. Webhook: <span class="mono">/api/webhook/whatsapp</span>', ['phone_number_id', 'waba_id'], 'WHATSAPP_TOKEN, WHATSAPP_VERIFY_TOKEN, WHATSAPP_APP_SECRET'],
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

// ---------------- Usuários ----------------
async function usuarios(main) {
  const c = await header(main, 'Usuários e permissões', 'admin: tudo · recepção: agenda, conversas e clientes · profissional: a própria agenda', '<button class="btn primary sm" id="novo">+ Usuário</button>');
  const [list, profs, logs] = await Promise.all([api('/users'), api('/professionals'), api('/audit')]);
  c.innerHTML = `<div class="card" style="padding:0"><table><tr><th>Nome</th><th>E-mail</th><th>Perfil</th><th>Status</th><th></th></tr>${list.map((u) => `<tr><td>${esc(u.name)}</td><td class="muted">${esc(u.email)}</td><td><span class="badge">${u.role}</span></td><td>${u.active ? '<span class="badge green">ativo</span>' : '<span class="badge">inativo</span>'}</td><td><button class="btn sm" data-u="${u.id}">${u.active ? 'Desativar' : 'Ativar'}</button></td></tr>`).join('')}</table></div>
  <div class="card" style="margin-top:14px;padding:0"><div style="padding:12px 14px"><h3>Auditoria</h3></div><table>${logs.slice(0, 50).map((l) => `<tr><td class="small muted">${utcToLocal(l.created_at)}</td><td>${esc(l.user_name || '')}</td><td>${esc(l.action)} ${esc(l.entity)} #${l.entity_id ?? ''}</td><td class="small mono dim">${esc(l.detail || '')}</td></tr>`).join('') || '<tr><td class="empty">Sem registros</td></tr>'}</table></div>`;
  $$('[data-u]', c).forEach((b) => (b.onclick = async () => { const u = list.find((x) => x.id === +b.dataset.u); await api(`/users/${u.id}`, { method: 'PUT', body: { active: u.active ? 0 : 1 } }); usuarios(main); }));
  $('#novo').onclick = () => modal('Novo usuário', `<div class="grid g2"><label class="f">Nome<input name="name"></label><label class="f">E-mail<input name="email"></label><label class="f">Senha (8+ caracteres, letras e números)<input name="password" type="password" minlength="8"></label>
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
    <h4>Gestor da empresa</h4><div class="grid g3"><label class="f">Nome<input name="admin_name"></label><label class="f">E-mail<input name="admin_email"></label><label class="f">Senha (8+ letras e números)<input name="admin_password" type="password" minlength="8"></label></div>`,
  { onSave: async (el) => { const t = await api('/tenants', { method: 'POST', body: formData(el) }); toast('Empresa criada. Cadastre os profissionais.'); localStorage.setItem('atende_tenant', t.id); ME = null; location.hash = '#/profissionais'; } });
}
