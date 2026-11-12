import { esc, $, $$, makeApi, toast, formData, money, quando, hora, dataLonga, utcToLocal, statusBadge } from '/assets/common.js';

const TK = 'atende_client_token';
const api = makeApi(TK);
const app = $('#app');
let ME = null; let tab = 'chat'; let ES = null; let MSGS = [];

window.addEventListener('hashchange', () => { if (location.hash === '#/login') { localStorage.removeItem(TK); start(); } });
start();

async function start() {
  renderTips();
  if (!localStorage.getItem(TK)) return renderLogin();
  try { ME = await api('/client/me'); } catch { return renderLogin(); }
  connect(); render();
}

// ---------- Login ----------
async function renderLogin() {
  ES?.close();
  const tenants = await api('/public/tenants');
  const rnd = '119' + String(Math.floor(10000000 + Math.random() * 89999999));
  app.innerHTML = `<form class="login" id="f">
    <div style="font-size:40px">💬</div><h2>Fale com a clínica</h2>
    <p class="muted small">Simulador do WhatsApp da empresa. Em produção o ${'cliente'} conversa pelo próprio WhatsApp; aqui você testa o mesmo agente.</p>
    <label class="f">Empresa<select name="tenant_id">${tenants.map((t) => `<option value="${t.id}">${esc(t.name)} — ${esc(t.segment)}</option>`).join('')}</select></label>
    <label class="f">Seu nome<input name="name" value="Carlos Martins" required></label>
    <label class="f">WhatsApp (DDD + número)<input name="phone" value="${rnd}" inputmode="tel" required></label>
    <label class="row small"><input type="checkbox" name="consent" checked> Aceito o uso dos meus dados para atendimento e agendamento (LGPD).</label>
    <button class="btn primary">Entrar</button>
    <p class="small dim">Login simplificado para testes. Em produção: código de verificação enviado por WhatsApp/SMS.</p>
  </form>`;
  $('#f').onsubmit = async (e) => {
    e.preventDefault();
    try { const r = await api('/client/login', { method: 'POST', body: formData(e.target) }); localStorage.setItem(TK, r.token); location.hash = ''; start(); } catch (err) { toast(err.message, true); }
  };
}

function connect() {
  ES?.close();
  ES = new EventSource(`/api/client/events?token=${localStorage.getItem(TK)}`);
  ES.addEventListener('message', (e) => {
    const p = JSON.parse(e.data);
    if (!MSGS.find((m) => m.id === p.message.id)) { MSGS.push(p.message); if (tab === 'chat') drawMsgs(); }
    if (tab !== 'chat' && p.message.sender !== 'cliente') { $('[data-t=chat]')?.setAttribute('style', 'color:#fbbf24'); }
  });
  ES.addEventListener('typing', (e) => { const t = $('.typing'); if (t) { t.classList.toggle('on', JSON.parse(e.data).typing); scrollDown(); } });
}

// ---------- Layout ----------
function render() {
  const t = ME.tenant;
  const tabs = [['chat', '💬', 'Conversa'], ['agenda', '📅', 'Agenda'], ['trat', '📈', 'Tratamento'], ['agendar', '➕', 'Agendar'], ['perfil', '👤', 'Perfil']];
  app.innerHTML = `<div id="view" style="flex:1;display:flex;flex-direction:column;min-height:0"></div>
    <div class="tabbar">${tabs.map(([k, i, l]) => `<button data-t="${k}" class="${tab === k ? 'on' : ''}"><b>${i}</b>${l}</button>`).join('')}</div>`;
  $$('[data-t]').forEach((b) => (b.onclick = () => { tab = b.dataset.t; render(); }));
  ({ chat, agenda, trat, agendar, perfil })[tab]($('#view'), t);
}

// ---------- Conversa (WhatsApp) ----------
async function chat(v, t) {
  v.innerHTML = `<div class="wa-head"><div class="avatar">${esc(t.name[0])}</div><div class="grow"><b>${esc(t.name)}</b><div class="st">conta comercial · ${esc(t.agent_name)} responde 24h</div></div><span style="color:#8696a0">📹 📞</span></div>
    <div class="msgs" id="msgs"></div>
    <div style="position:relative"><div class="rec-bar" id="recbar">● Gravando… solte/clique para enviar</div>
    <form class="composer" id="comp"><div class="in"><input name="text" placeholder="Mensagem" autocomplete="off"><button type="button" class="ic" id="clip" title="Enviar foto">📎</button><button type="button" class="ic" id="cam" title="Foto do pedido médico (exemplo)">📷</button></div>
    <button type="button" class="mic" id="mic" title="Gravar áudio">🎙</button></form></div>
    <input type="file" id="file" accept="image/*" hidden>`;
  const r = await api('/client/messages'); MSGS = r.messages; drawMsgs();
  $('#comp').onsubmit = (e) => { e.preventDefault(); const tx = e.target.text.value.trim(); if (!tx) return; e.target.text.value = ''; sendText(tx); };
  $('#comp input').oninput = (e) => { $('#mic').textContent = e.target.value ? '➤' : '🎙'; };
  $('#mic').onclick = () => { const tx = $('#comp input').value.trim(); if (tx) { $('#comp input').value = ''; $('#mic').textContent = '🎙'; sendText(tx); } else toggleRecord(); };
  $('#clip').onclick = () => $('#file').click();
  $('#file').onchange = async (e) => { const f = e.target.files[0]; if (f) sendImage(await resize(f)); e.target.value = ''; };
  $('#cam').onclick = () => sendImage(fakePedidoMedico());
}

function drawMsgs() {
  const box = $('#msgs'); if (!box) return;
  const lastOpt = [...MSGS].reverse().find((m) => m.type === 'options');
  const answered = new Set();
  // uma opção é considerada respondida se há mensagem do cliente depois dela
  MSGS.forEach((m, i) => { if (m.type === 'options' && MSGS.slice(i + 1).some((x) => x.sender === 'cliente')) answered.add(m.id); });
  let lastDay = '';
  box.innerHTML = MSGS.map((m) => {
    const day = utcToLocal(m.created_at).slice(0, 5); let sep = '';
    if (day !== lastDay) { sep = `<div class="day">${day}</div>`; lastDay = day; }
    return sep + msgHtml(m, m.type === 'options' && (answered.has(m.id) || m.id !== lastOpt?.id));
  }).join('') + '<div class="typing"><i></i><i></i><i></i></div>';
  $$('.opts button', box).forEach((b) => (b.onclick = () => { b.classList.add('chosen'); $$('button', b.parentElement).forEach((x) => (x.disabled = true)); sendText(b.dataset.label); }));
  scrollDown();
}
const scrollDown = () => { const b = $('#msgs'); if (b) b.scrollTop = b.scrollHeight; };
const time = (m) => `<div class="meta">${utcToLocal(m.created_at).slice(6)}${m.sender === 'cliente' ? ' ✓✓' : ''}</div>`;

function msgHtml(m, disabled) {
  if (m.sender === 'sistema' || m.type === 'note') return `<div class="sys">${esc(m.content)}</div>`;
  const me = m.sender === 'cliente';
  const lbl = m.sender === 'agente' ? '<span class="lbl">✳ agente IA</span>' : m.sender === 'humano' ? `<span class="lbl">🙋 ${esc(m.meta?.user || 'equipe')}</span>` : '';
  const cls = `b ${me ? 'me' : 'them'} ${m.sender === 'humano' ? 'human' : ''}`;
  switch (m.type) {
    case 'audio': return `<div class="${cls}">▶︎ <span style="letter-spacing:1px">ılıılıılııılıılı</span> ${m.meta?.duration ? '0:' + String(m.meta.duration).padStart(2, '0') : ''}<div class="small" style="color:#a7f3d0;margin-top:4px">✎ Transcrição</div>${esc(m.content)}${time(m)}</div>`;
    case 'image': return `<div class="${cls}">📷 Foto enviada${m.content ? '<br>' + esc(m.content) : ''}${time(m)}</div>`;
    case 'options': return `<div class="${cls}">${lbl}${esc(m.content)}${time(m)}</div><div class="opts">${(m.meta?.options || []).map((o) => `<button data-label="${esc(o.label)}" ${disabled ? 'disabled' : ''}>📅 ${esc(o.label)}</button>`).join('')}</div>`;
    case 'appointment': return `<div class="b them" style="padding:4px;background:transparent"><div class="cardmsg"><div class="row between"><b>${esc(m.meta?.service_name)}</b><span class="ok">✓ Confirmada</span></div>
      <div class="small" style="margin-top:6px;color:#333">📅 ${esc(dataLonga(m.meta.start))} · ${hora(m.meta.start)}<br>👤 ${esc(m.meta?.professional_name)}<br>📍 ${esc(m.meta?.place || ME.tenant.name)}</div></div></div>`;
    case 'package': return `<div class="b them">${lbl}<b>📅 ${ME.terms.sessoes} reservadas · ${m.meta.sessions.length}/${m.meta.total}</b><div class="small" style="margin-top:4px;color:#cbd5e1">${m.meta.sessions.map((s) => `${s.n}ª ${quando(s.start)} · ${esc(s.professional_name)} ✓`).join('<br>')}</div>${time(m)}</div>`;
    case 'location': return `<div class="${cls}"><a target="_blank" href="https://www.google.com/maps/search/?api=1&query=${m.meta?.lat && m.meta?.lng ? `${m.meta.lat},${m.meta.lng}` : encodeURIComponent(m.meta?.address || '')}"><div class="map"></div></a><b>${esc(m.meta?.name)}</b><br><span class="small">${esc(m.meta?.address)}</span>${time(m)}</div>`;
    default: return `<div class="${cls}">${lbl}${esc(m.content)}${time(m)}</div>`;
  }
}

async function send(body) {
  try { await api('/client/messages', { method: 'POST', body }); } catch (e) { toast(e.message, true); }
}
const sendText = (text) => send({ type: 'text', text });
const sendImage = (img) => send({ type: 'image', image: img });

// ---------- Áudio: grava + transcreve no navegador (Web Speech API) ----------
let rec = null;
async function toggleRecord() {
  if (rec) return rec.stop();
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  let stream;
  try { stream = await navigator.mediaDevices.getUserMedia({ audio: true }); } catch {
    const t = prompt('Microfone indisponível. Digite o que seria dito no áudio (simulação):', 'Oi, boa noite! Travei a lombar no trabalho hoje, tô com muita dor. Queria começar fisioterapia.');
    if (t) send({ type: 'audio', transcript: t, duration: 14 });
    return;
  }
  const chunks = []; let transcript = ''; const t0 = Date.now();
  const mr = new MediaRecorder(stream);
  let sr = null;
  if (SR) { sr = new SR(); sr.lang = 'pt-BR'; sr.continuous = true; sr.interimResults = false; sr.onresult = (e) => { transcript = [...e.results].map((x) => x[0].transcript).join(' '); }; try { sr.start(); } catch {} }
  mr.ondataavailable = (e) => chunks.push(e.data);
  mr.onstop = async () => {
    stream.getTracks().forEach((t) => t.stop()); sr?.stop(); $('#mic')?.classList.remove('rec'); $('#recbar')?.classList.remove('on'); rec = null;
    await new Promise((r) => setTimeout(r, 400)); // aguarda o último resultado da transcrição
    const blob = new Blob(chunks, { type: mr.mimeType || 'audio/webm' });
    const b64 = await new Promise((r) => { const fr = new FileReader(); fr.onload = () => r(fr.result.split(',')[1]); fr.readAsDataURL(blob); });
    if (!transcript) transcript = prompt('Seu navegador não transcreveu o áudio. Digite a transcrição (ou deixe em branco para o servidor transcrever com OPENAI_API_KEY):', '') || '';
    send({ type: 'audio', audio: { b64, mime: blob.type }, transcript, duration: Math.round((Date.now() - t0) / 1000) });
  };
  mr.start(); rec = mr; $('#mic').classList.add('rec'); $('#recbar').classList.add('on');
}

// ---------- Imagens ----------
async function resize(file, max = 1280) {
  const img = await new Promise((res, rej) => { const i = new Image(); i.onload = () => res(i); i.onerror = rej; i.src = URL.createObjectURL(file); });
  const s = Math.min(1, max / Math.max(img.width, img.height));
  const c = document.createElement('canvas'); c.width = img.width * s; c.height = img.height * s;
  c.getContext('2d').drawImage(img, 0, 0, c.width, c.height);
  return { b64: c.toDataURL('image/jpeg', 0.85).split(',')[1], mime: 'image/jpeg' };
}
function fakePedidoMedico() {
  const c = document.createElement('canvas'); c.width = 600; c.height = 800; const g = c.getContext('2d');
  g.fillStyle = '#f8f6ef'; g.fillRect(0, 0, 600, 800); g.fillStyle = '#111'; g.font = 'bold 30px serif'; g.fillText('PEDIDO MÉDICO', 40, 70);
  g.font = '20px serif';
  const lines = [`Paciente: ${ME.client.name || 'Paciente'}`, 'Data: ' + new Date().toLocaleDateString('pt-BR'), '', 'Solicito: Fisioterapia motora', '10 (dez) sessões', 'CID: M54.5 — Dor lombar baixa', '', 'Dr. Roberto Almeida — CRM 123456'];
  lines.forEach((l, i) => g.fillText(l, 40, 140 + i * 40));
  g.strokeStyle = '#1e3a8a'; g.beginPath(); g.moveTo(330, 520); g.bezierCurveTo(380, 480, 420, 560, 520, 500); g.stroke();
  return { b64: c.toDataURL('image/jpeg', 0.85).split(',')[1], mime: 'image/jpeg' };
}

// ---------- Agenda ----------
async function agenda(v) {
  v.innerHTML = `<div class="page"><h2>Meus horários</h2><div id="list" class="col"></div></div>`;
  const list = await api('/client/appointments');
  const now = new Date().toISOString().slice(0, 16);
  const fut = list.filter((a) => a.start >= now.slice(0, 10) && ['confirmado', 'pendente'].includes(a.status));
  const past = list.filter((a) => !fut.includes(a)).reverse();
  $('#list').innerHTML = (fut.length ? '' : '<div class="card empty">Nenhum horário futuro. Converse com a clínica ou use “Agendar”.</div>') +
    fut.map((a) => `<div class="card col" style="gap:6px"><div class="row between"><b>${esc(a.service_name)}${a.session_number ? ` · ${ME.terms.sessao} ${a.session_number}` : ''}</b>${statusBadge(a.status)}</div>
      <div class="small muted">${esc(dataLonga(a.start))} · ${hora(a.start)} · ${esc(a.professional_name)}</div>
      <div class="row"><button class="btn sm" data-a="confirm" data-id="${a.id}">Confirmar</button><button class="btn sm" data-a="reschedule" data-id="${a.id}" data-s="${a.service_id}">Remarcar</button><button class="btn sm danger" data-a="cancel" data-id="${a.id}">Cancelar</button></div></div>`).join('') +
    (past.length ? `<h4 style="margin-top:8px">Histórico</h4>` + past.slice(0, 20).map((a) => `<div class="row between small"><span>${quando(a.start)} · ${esc(a.service_name)}</span>${statusBadge(a.status)}</div>`).join('') : '');
  $$('[data-a]', v).forEach((b) => (b.onclick = async () => {
    const id = b.dataset.id;
    if (b.dataset.a === 'reschedule') return reschedulePicker(id, b.dataset.s);
    if (b.dataset.a === 'cancel' && !confirm('Cancelar este horário?')) return;
    try { await api(`/client/appointments/${id}/${b.dataset.a}`, { method: 'POST' }); toast('Feito!'); agenda(v); } catch (e) { toast(e.message, true); }
  }));
}
async function reschedulePicker(id, serviceId) {
  const opts = await api(`/client/availability?service_id=${serviceId}&count=8`);
  const ov = document.createElement('div'); ov.className = 'modal-bg';
  ov.innerHTML = `<div class="modal"><header><h3>Novo horário</h3><button class="btn ghost right" data-x>✕</button></header><div class="body"><div class="slots">${opts.map((o) => `<button class="btn" data-s="${o.start}" data-p="${o.professional_id}">${quando(o.start)}<br><span class="small muted">${esc(o.professional)}</span></button>`).join('') || 'Sem horários'}</div></div></div>`;
  app.appendChild(ov); ov.style.position = 'absolute';
  ov.onclick = async (e) => {
    if (e.target === ov || e.target.closest('[data-x]')) return ov.remove();
    const b = e.target.closest('[data-s]'); if (!b) return;
    try { await api(`/client/appointments/${id}/reschedule`, { method: 'POST', body: { start: b.dataset.s, professional_id: +b.dataset.p } }); ov.remove(); toast('Remarcado!'); render(); } catch (err) { toast(err.message, true); }
  };
}

// ---------- Tratamento ----------
async function trat(v) {
  v.innerHTML = `<div class="page"><h2>Meu tratamento</h2><div id="l" class="col"></div></div>`;
  const [ts, ap] = await Promise.all([api('/client/treatments'), api('/client/appointments')]);
  $('#l').innerHTML = ts.map((t) => {
    const ss = ap.filter((a) => a.treatment_id === t.id && a.session_number).sort((a, b) => a.session_number - b.session_number);
    return `<div class="card col"><div class="row between"><b>📅 ${ME.terms.sessoes[0].toUpperCase() + ME.terms.sessoes.slice(1)} · ${esc(ME.client.name || '')}</b><b>${t.done}/${t.total_sessions}</b></div>
      <div class="progress"><i style="width:${(t.done / t.total_sessions) * 100}%"></i></div>
      <table class="small"><tr><th>${ME.terms.sessao}</th><th>dia</th><th>horário</th><th></th></tr>${ss.map((a) => `<tr><td>${a.session_number}ª</td><td>${quando(a.start).split(' · ')[0]}</td><td>${hora(a.start)} · ${esc(a.professional_name)}</td><td>${a.status === 'realizado' ? '✅' : a.status === 'faltou' ? '❌' : a.status === 'confirmado' ? '✓' : ''}</td></tr>`).join('')}</table>
      <div class="small muted">${esc(t.service_name)} · ${money(t.session_price)}/${ME.terms.sessao} · total ${money(t.session_price * t.total_sessions)}</div></div>`;
  }).join('') || '<div class="card empty">Nenhum tratamento em andamento.</div>';
}

// ---------- Autoagendamento ----------
async function agendar(v) {
  const svcs = await api('/client/services');
  v.innerHTML = `<div class="page"><h2>Agendar</h2><label class="f">Serviço<select id="svc">${svcs.map((s) => `<option value="${s.id}">${esc(s.name)} · ${s.price ? money(s.price) : 'sem custo'}</option>`).join('')}</select></label>
    <label class="f">A partir de<input type="date" id="dt"></label><div class="slots" id="sl"></div>
    <label class="row small" id="pkgl"><input type="checkbox" id="pkg" checked> Já reservar as ${ME.terms.sessoes} do pacote</label>
    <button class="btn primary" id="ok" disabled>Confirmar</button></div>`;
  let sel = null;
  const load = async () => {
    const s = svcs.find((x) => x.id === +$('#svc').value); $('#pkgl').style.display = s?.package_sessions ? '' : 'none';
    const dt = $('#dt').value; const opts = await api(`/client/availability?service_id=${$('#svc').value}&count=10${dt ? '&date=' + dt : ''}`);
    $('#sl').innerHTML = opts.map((o) => `<button class="btn" data-s="${o.start}" data-p="${o.professional_id}">${quando(o.start)}<br><span class="small muted">${esc(o.professional)}</span></button>`).join('') || '<div class="muted small">Sem horários nesse dia</div>';
    $$('#sl button').forEach((b) => (b.onclick = () => { $$('#sl button').forEach((x) => x.classList.remove('sel')); b.classList.add('sel'); sel = b.dataset; $('#ok').disabled = false; }));
  };
  $('#svc').onchange = load; $('#dt').onchange = load; await load();
  $('#ok').onclick = async () => {
    try { const r = await api('/client/book', { method: 'POST', body: { service_id: +$('#svc').value, professional_id: +sel.p, start: sel.s, package: $('#pkg').checked } }); toast(`Agendado!${r.sessions ? ` + ${r.sessions} ${ME.terms.sessoes} reservadas` : ''}`); tab = 'agenda'; render(); } catch (e) { toast(e.message, true); }
  };
}

// ---------- Perfil ----------
function perfil(v) {
  const c = ME.client;
  v.innerHTML = `<form class="page" id="f"><h2>Meu perfil</h2><label class="f">Nome<input name="name" value="${esc(c.name || '')}"></label><label class="f">E-mail<input name="email" value="${esc(c.email || '')}"></label>
    <label class="f">Nascimento<input type="date" name="birthdate" value="${esc(c.birthdate || '')}"></label><div class="small muted">WhatsApp: ${esc(c.phone)}</div>
    <button class="btn primary">Salvar</button><button type="button" class="btn" id="out">Sair / trocar de empresa</button>
    <div class="card small muted">📍 ${esc(ME.tenant.name)}<br>${esc(ME.tenant.address || '')} ${esc(ME.tenant.city || '')}</div></form>`;
  $('#f').onsubmit = async (e) => { e.preventDefault(); await api('/client/me', { method: 'PUT', body: formData(e.target) }); ME = await api('/client/me'); toast('Salvo'); };
  $('#out').onclick = () => { localStorage.removeItem(TK); ES?.close(); ME = null; tab = 'chat'; renderLogin(); };
}

// ---------- Painel lateral de testes ----------
function renderTips() {
  const box = $('#tips');
  const steps = [
    ['🎙 Áudio: “Travei a lombar…”', () => send({ type: 'audio', transcript: 'Oi, boa noite! Travei a lombar no trabalho hoje, tô com muita dor. Queria começar fisioterapia.', duration: 14 })],
    ['📷 Enviar foto do pedido médico', () => sendImage(fakePedidoMedico())],
    ['1️⃣ Escolher a 1ª opção', () => sendText('1')],
    ['📍 Onde fica a clínica?', () => sendText('Qual o endereço?')],
    ['📅 Quais são meus horários?', () => sendText('Quais são meus horários?')],
    ['🔁 Quero remarcar', () => sendText('Quero remarcar')],
    ['💲 Quanto custa?', () => sendText('Quanto custa?')],
    ['🙋 Falar com atendente', () => sendText('Quero falar com um atendente')],
  ];
  box.innerHTML = `<div class="card col"><h3>Roteiro do vídeo</h3><div class="small muted">Clique em sequência para reproduzir o atendimento das 22h38. Você também pode digitar, gravar áudio (🎙) ou anexar fotos.</div>
    ${steps.map((s, i) => `<button class="btn sm" data-i="${i}">${s[0]}</button>`).join('')}</div>
    <div class="card col small"><b>Veja o outro lado</b><span class="muted">Abra o painel e acompanhe em tempo real: conversa, triagem (“O agente entendeu”), agenda e pacote de sessões.</span>
    <a class="btn sm" href="/admin#/conversas" target="_blank">Abrir painel admin ↗</a>
    <span class="muted">Na agenda do painel, marque uma ${'sessão'} como <b>Faltou</b> para ver a IA oferecer remarcação aqui.</span></div>`;
  $$('[data-i]', box).forEach((b) => (b.onclick = () => { if (!ME) return toast('Entre primeiro', true); tab = 'chat'; if (!$('#msgs')) render(); steps[b.dataset.i][1](); }));
}
