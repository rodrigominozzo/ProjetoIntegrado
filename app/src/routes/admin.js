import { Router } from 'express';
import { all, get, insert, update, run, parse } from '../db.js';
import { requireUser, checkPassword, hashPassword, sign } from '../services/auth.js';
import * as sched from '../services/scheduling.js';
import { addMessage, history, getConversation } from '../services/conversations.js';
import { runJobs } from '../services/jobs.js';
import { offerReplacement, fillFromWaitlist, applyBlock, joinWaitlist } from '../services/proactive.js';
import { sse } from '../services/bus.js';
import { SEGMENTS, termsFor } from '../services/presets.js';
import { createTenant } from '../seed.js';
import { nowLocal, addDays, dateOf, TZ, weekday, minutes, toD } from '../services/time.js';
import { agentMode } from '../agent/index.js';
import { MODEL } from '../agent/llm.js';
import { whatsappEnabled } from '../channels/whatsapp.js';
import { V, rateLimit, loginBlocked, loginFailed, loginOk, publicError } from '../services/security.js';

const r = Router();
const staff = requireUser();
const managers = requireUser(['admin']);
const notProf = requireUser(['admin', 'recepcao']);
const audit = (req, action, entity, id, detail) => insert('audit_logs', { tenant_id: req.tenantId, user_id: req.user.id, action, entity, entity_id: id ?? null, detail: detail ? JSON.stringify(detail).slice(0, 1000) : null });
const wrap = (fn) => (req, res) => { try { const out = fn(req, res); if (out !== undefined) res.json(out); } catch (e) { res.status(400).json({ error: publicError(e) }); } };
const pick = (o, keys) => Object.fromEntries(keys.filter((k) => o[k] !== undefined).map((k) => [k, o[k]]));
const isManager = (req) => ['admin', 'superadmin'].includes(req.user.role);
const bool = (v) => (v ? 1 : 0);

// ---------- Auth (com bloqueio de força bruta) ----------
r.post('/auth/login', rateLimit({ key: 'login', max: 10, windowMs: 60_000 }), (req, res) => {
  const email = String(req.body.email || '').toLowerCase().trim().slice(0, 190);
  if (loginBlocked(req, email)) return res.status(429).json({ error: 'Muitas tentativas. Tente novamente em 15 minutos.' });
  const u = get('SELECT * FROM users WHERE email=? AND active=1', email);
  if (!u || !checkPassword(String(req.body.password || '').slice(0, 200), u.password_hash)) { loginFailed(req, email); return res.status(401).json({ error: 'E-mail ou senha inválidos' }); }
  loginOk(email);
  insert('audit_logs', { tenant_id: u.tenant_id, user_id: u.id, action: 'login', entity: 'user', entity_id: u.id });
  res.json({ token: sign({ uid: u.id, v: u.password_hash.slice(0, 8) }), user: { id: u.id, name: u.name, email: u.email, role: u.role, tenant_id: u.tenant_id } });
});
r.get('/me', staff, wrap((req) => {
  const tenant = get('SELECT * FROM tenants WHERE id=?', req.tenantId);
  return { user: req.user, tenant, terms: tenant ? termsFor(tenant) : null, agent: { mode: agentMode(), model: MODEL }, whatsapp: whatsappEnabled(), segments: Object.fromEntries(Object.entries(SEGMENTS).map(([k, v]) => [k, v.label])) };
}));
r.get('/events', staff, (req, res) => sse(req, res, (d) => d.tenantId === req.tenantId));

// ---------- Empresas ----------
r.get('/tenants', staff, wrap((req) => req.user.role === 'superadmin' ? all('SELECT id,name,segment,city,automation_active FROM tenants ORDER BY id') : all('SELECT id,name,segment,city,automation_active FROM tenants WHERE id=?', req.tenantId)));
r.post('/tenants', requireUser(['superadmin']), wrap((req) => {
  const b = req.body;
  if (!b.name) throw new sched.AppError('Informe o nome');
  const slug = String(b.name).toLowerCase().normalize('NFD').replace(/[^\w]+/g, '-').replace(/^-|-$/g, '').slice(0, 40) + '-' + Date.now().toString(36).slice(-4);
  const id = createTenant({ name: V.str(b.name, 120), slug, segment: SEGMENTS[b.segment] ? b.segment : 'clinica', address: V.str(b.address), city: V.str(b.city, 80), phone: V.str(b.phone, 20), agent_name: V.str(b.agent_name, 40) });
  if (b.admin_email) insert('users', { tenant_id: id, name: V.str(b.admin_name || 'Gestor', 80), email: V.email(b.admin_email), password_hash: hashPassword(V.password(b.admin_password)), role: 'admin' });
  audit(req, 'create', 'tenant', id);
  return get('SELECT * FROM tenants WHERE id=?', id);
}));
const TENANT_FIELDS = ['name', 'segment', 'address', 'city', 'lat', 'lng', 'phone', 'whatsapp_phone_number_id', 'agent_name', 'agent_tone', 'agent_instructions', 'welcome_message', 'policies', 'insurances', 'payment_methods',
  'automation_active', 'reminder_hours_before', 'noshow_recovery', 'auto_book_package', 'min_advance_hours', 'max_advance_days', 'slot_step_min', 'cancel_min_hours', 'options_count', 'quiet_start', 'quiet_end',
  'reoffer_cancel', 'waitlist_enabled', 'reactivation_days', 'return_reminder'];
r.put('/tenant', managers, wrap((req) => {
  const b = req.body; const patch = pick(b, TENANT_FIELDS);
  for (const k of ['automation_active', 'noshow_recovery', 'auto_book_package', 'reoffer_cancel', 'waitlist_enabled', 'return_reminder']) if (k in patch) patch[k] = bool(patch[k]);
  for (const [k, min, max] of [['min_advance_hours', 0, 720], ['max_advance_days', 1, 365], ['slot_step_min', 5, 120], ['cancel_min_hours', 0, 168], ['options_count', 1, 4], ['reminder_hours_before', 1, 168], ['reactivation_days', 1, 120]]) if (k in patch) patch[k] = V.num(patch[k], min, max);
  for (const k of ['quiet_start', 'quiet_end']) if (k in patch && !/^\d{2}:\d{2}$/.test(patch[k])) throw new sched.AppError('Horário inválido');
  for (const k of ['agent_instructions', 'policies', 'insurances', 'welcome_message']) if (k in patch) patch[k] = V.str(patch[k], 3000);
  if ('segment' in patch && !SEGMENTS[patch.segment]) delete patch.segment;
  if (b.hours) patch.hours_json = JSON.stringify(b.hours);
  if (b.terms) patch.terms_json = JSON.stringify(b.terms);
  update('tenants', req.tenantId, patch);
  audit(req, 'update', 'tenant', req.tenantId, Object.keys(patch));
  return get('SELECT * FROM tenants WHERE id=?', req.tenantId);
}));

// ---------- Dashboard (financeiro a partir da agenda + operação do agente) ----------
r.get('/dashboard', staff, wrap((req) => {
  const T = req.tenantId; const days = Math.min(365, Math.max(1, Number(req.query.days || 30)));
  const now = nowLocal(); const from = addDays(dateOf(now), -days); const ahead = addDays(dateOf(now), 30);
  const fin = isManager(req);
  const sum = (where, ...p) => get(`SELECT COUNT(*) n, COALESCE(SUM(price),0) receita, COALESCE(SUM(cost),0) custo, COALESCE(SUM(commission),0) repasse,
     COALESCE(SUM(price-cost-commission),0) lucro FROM appointments WHERE tenant_id=? AND ${where}`, T, ...p);
  const realizado = sum(`status='realizado' AND start >= ? AND start < ?`, from, now);
  const previsto = sum(`status IN ('confirmado','pendente') AND start >= ? AND start < ?`, now, ahead);
  const perdido = sum(`status IN ('faltou','cancelado') AND start >= ? AND start < ?`, from, now);
  const recuperado = get(`SELECT COUNT(*) n, COALESCE(SUM(price),0) v FROM appointments WHERE tenant_id=? AND status NOT IN ('cancelado') AND rescheduled_from IN (SELECT id FROM appointments WHERE tenant_id=? AND status IN ('faltou','cancelado'))`, T, T);
  const faltas = get(`SELECT SUM(status='faltou') faltas, SUM(status='cancelado') cancelados, SUM(status='realizado') realizados FROM appointments WHERE tenant_id=? AND start >= ? AND start < ?`, T, from, now);
  const porProf = all(`SELECT p.id, p.name, p.color, COUNT(a.id) n, COALESCE(SUM(a.price),0) receita, COALESCE(SUM(a.commission),0) repasse, COALESCE(SUM(a.price-a.cost-a.commission),0) lucro,
      (SELECT COUNT(*) FROM appointments x WHERE x.professional_id=p.id AND x.status='faltou' AND x.start >= ? AND x.start < ?) faltas
    FROM professionals p LEFT JOIN appointments a ON a.professional_id=p.id AND a.status='realizado' AND a.start >= ? AND a.start < ? WHERE p.tenant_id=? GROUP BY p.id ORDER BY receita DESC`, from, now, from, now, T);
  const porServ = all(`SELECT s.name, s.category, COUNT(a.id) n, COALESCE(SUM(a.price),0) receita, COALESCE(SUM(a.price-a.cost-a.commission),0) lucro FROM appointments a JOIN services s ON s.id=a.service_id
    WHERE a.tenant_id=? AND a.status='realizado' AND a.start >= ? AND a.start < ? GROUP BY s.id ORDER BY receita DESC LIMIT 8`, T, from, now);
  const porCat = all(`SELECT s.category, COALESCE(SUM(a.price),0) receita, COALESCE(SUM(a.price-a.cost-a.commission),0) lucro FROM appointments a JOIN services s ON s.id=a.service_id
    WHERE a.tenant_id=? AND a.status='realizado' AND a.start >= ? AND a.start < ? GROUP BY s.category ORDER BY receita DESC`, T, from, now);
  const serie = all(`SELECT substr(start,1,10) d, SUM(CASE WHEN status='realizado' THEN price ELSE 0 END) realizado, SUM(CASE WHEN status IN ('confirmado','pendente') THEN price ELSE 0 END) previsto
    FROM appointments WHERE tenant_id=? AND start >= ? AND start < ? GROUP BY d ORDER BY d`, T, addDays(dateOf(now), -13), addDays(dateOf(now), 15));
  // ocupação próximos 7 dias = minutos agendados / minutos de jornada
  let cap = 0; let used = 0;
  const occ = all('SELECT * FROM professionals WHERE tenant_id=? AND active=1', T).map((p) => {
    let c = 0; const sch = parse(p.schedule_json);
    for (let i = 0; i < 7; i++) for (const [a, b] of sch[weekday(addDays(dateOf(now), i))] || []) c += minutes(b) - minutes(a);
    const u = all(`SELECT start, end FROM appointments WHERE professional_id=? AND status IN ('confirmado','pendente') AND start >= ? AND start < ?`, p.id, now, addDays(dateOf(now), 7)).reduce((s, a) => s + (toD(a.end) - toD(a.start)) / 60000, 0);
    cap += c; used += u;
    return { name: p.name, color: p.color, pct: c ? Math.round((100 * u) / c) : 0 };
  });
  const agente = get(`SELECT SUM(created_by='agente') agente, COUNT(*) total FROM appointments WHERE tenant_id=? AND date(created_at) >= ? AND session_number IS NULL AND status <> 'remarcado'`, T, from);
  const tenant = get('SELECT hours_json FROM tenants WHERE id=?', T); const hours = parse(tenant.hours_json);
  const fmt = new Intl.DateTimeFormat('en-CA', { timeZone: TZ, weekday: 'short', hour: '2-digit', minute: '2-digit', hour12: false }); const wd = { Sun: 0, Mon: 1, Tue: 2, Wed: 3, Thu: 4, Fri: 5, Sat: 6 };
  let fora = 0;
  for (const a of all(`SELECT created_at FROM appointments WHERE tenant_id=? AND created_by='agente' AND date(created_at) >= ? AND session_number IS NULL`, T, from)) {
    const p = fmt.formatToParts(new Date(a.created_at.replace(' ', 'T') + 'Z')); const g = (k) => p.find((x) => x.type === k).value;
    const hm = `${g('hour').replace('24', '00')}:${g('minute')}`; const h = hours[wd[g('weekday')]];
    if (!h || hm < h[0] || hm >= h[1]) fora++;
  }
  const proativo = get(`SELECT COUNT(*) n FROM automation_logs WHERE tenant_id=? AND step LIKE 'proativo_%' AND date(created_at) >= ?`, T, from).n;
  const conversas = get(`SELECT COUNT(*) n FROM conversations WHERE tenant_id=? AND date(last_message_at) >= ?`, T, from).n;
  const humano = get(`SELECT COUNT(*) n FROM conversations WHERE tenant_id=? AND mode='humano'`, T).n;
  const bloqueios = get(`SELECT COUNT(*) n FROM security_events WHERE tenant_id=? AND date(created_at) >= ?`, T, from).n;
  const espera = get(`SELECT COUNT(*) n FROM waitlist WHERE tenant_id=? AND status='aguardando'`, T).n;
  const hide = (o) => (fin ? o : null);
  return {
    days, financeiro: fin,
    realizado: hide(realizado), previsto: hide(previsto), perdido: hide(perdido), recuperado: hide(recuperado),
    ticket_medio: hide(realizado.n ? realizado.receita / realizado.n : 0), margem: hide(realizado.receita ? (100 * realizado.lucro) / realizado.receita : 0),
    atendimentos: { realizados: faltas.realizados || 0, faltas: faltas.faltas || 0, cancelados: faltas.cancelados || 0, comparecimento: faltas.realizados ? Math.round((100 * faltas.realizados) / (faltas.realizados + (faltas.faltas || 0))) : null, futuros: previsto.n },
    porProf: fin ? porProf : porProf.map(({ receita, repasse, lucro, ...x }) => x), porServ: hide(porServ), porCat: hide(porCat), serie: fin ? serie : [],
    ocupacao: { geral: cap ? Math.round((100 * used) / cap) : 0, prof: occ },
    agente: { modo: agentMode(), agendamentos: agente.agente || 0, pct: agente.total ? Math.round((100 * (agente.agente || 0)) / agente.total) : 0, fora_do_horario: fora, reposicoes: proativo, recuperados: recuperado.n, conversas, humano, bloqueios, espera },
  };
}));

// ---------- Agenda ----------
r.get('/agenda', staff, wrap((req) => {
  const from = V.date(req.query.from) || dateOf(nowLocal());
  const to = addDays(from, Math.min(62, Number(req.query.days || 1)));
  let sql = `SELECT a.*, c.name client_name, c.phone client_phone, p.name professional_name, p.color, s.name service_name, s.category
    FROM appointments a JOIN clients c ON c.id=a.client_id JOIN professionals p ON p.id=a.professional_id JOIN services s ON s.id=a.service_id
    WHERE a.tenant_id=? AND a.start >= ? AND a.start < ? AND a.status <> 'remarcado'`;
  const args = [req.tenantId, from, to];
  let profs = all('SELECT * FROM professionals WHERE tenant_id=? AND active=1 ORDER BY id', req.tenantId);
  if (req.user.role === 'profissional') { sql += ' AND a.professional_id=?'; args.push(req.user.professional_id || 0); profs = profs.filter((p) => p.id === req.user.professional_id); }
  if (req.query.professional_id) { sql += ' AND a.professional_id=?'; args.push(Number(req.query.professional_id)); }
  const appts = all(sql + ' ORDER BY a.start', ...args).map((a) => (isManager(req) ? a : { ...a, cost: undefined, commission: undefined }));
  return { from, to, appointments: appts, professionals: profs, blocks: all('SELECT * FROM blocks WHERE tenant_id=? AND start < ? AND end > ?', req.tenantId, to, from) };
}));
r.get('/availability', staff, wrap((req) => sched.findOptions(req.tenantId, Number(req.query.service_id), { date: V.date(req.query.date), professionalId: req.query.professional_id, count: 40, days: 1 })));
r.get('/price', staff, wrap((req) => { const e = sched.effective(Number(req.query.service_id), Number(req.query.professional_id)); return { duration: e.duration, price: e.price, buffer: e.buffer }; }));
r.post('/appointments', notProf, wrap((req) => {
  const b = req.body;
  let clientId = b.client_id ? Number(b.client_id) : null;
  if (clientId && !get('SELECT id FROM clients WHERE id=? AND tenant_id=?', clientId, req.tenantId)) throw new sched.AppError('Cliente inválido');
  if (!clientId) {
    const phone = V.phone(b.client_phone);
    const ex = get('SELECT id FROM clients WHERE tenant_id=? AND phone=?', req.tenantId, phone);
    clientId = ex?.id || insert('clients', { tenant_id: req.tenantId, phone, name: V.str(b.client_name, 80), source: 'recepcao' });
  }
  const a = sched.book({ tenantId: req.tenantId, clientId, serviceId: Number(b.service_id), professionalId: Number(b.professional_id), start: V.datetime(b.start), createdBy: 'recepcao', status: b.status === 'pendente' ? 'pendente' : 'confirmado', notes: V.str(b.notes, 500), force: !!b.force && isManager(req) });
  if (b.package) sched.reservePackage({ tenantId: req.tenantId, clientId, entryAppointment: a, createdBy: 'recepcao' });
  audit(req, 'create', 'appointment', a.id);
  return a;
}));
r.patch('/appointments/:id', staff, wrap((req) => {
  const a = get('SELECT * FROM appointments WHERE id=? AND tenant_id=?', req.params.id, req.tenantId);
  if (!a) throw new sched.AppError('Não encontrado');
  if (req.user.role === 'profissional' && a.professional_id !== req.user.professional_id) throw new sched.AppError('Sem permissão');
  if (req.body.notes !== undefined) update('appointments', a.id, { notes: V.str(req.body.notes, 1000) });
  let out = sched.getAppointment(a.id);
  const st = req.body.status;
  if (st) {
    if (!['pendente', 'confirmado', 'realizado', 'faltou', 'cancelado'].includes(st)) throw new sched.AppError('Status inválido');
    if (st === 'cancelado') {
      out = sched.cancel(a.id, { by: req.body.by === 'cliente' ? 'cliente' : 'clinica', reason: V.str(req.body.reason, 200) });
      fillFromWaitlist(a.id);
      if (req.body.reoffer !== false) offerReplacement(a.id, req.body.by === 'cliente' ? 'cancelamento_cliente' : 'cancelamento_clinica');
    } else {
      out = sched.setStatus(a.id, st, st === 'faltou' ? { recovery_sent: 0 } : {});
      const tenant = get('SELECT * FROM tenants WHERE id=?', req.tenantId);
      if (st === 'faltou' && tenant.noshow_recovery) offerReplacement(a.id, 'falta');
    }
  }
  audit(req, 'update', 'appointment', a.id, req.body);
  return out;
}));
r.post('/appointments/:id/reschedule', notProf, wrap((req) => {
  const a = get('SELECT * FROM appointments WHERE id=? AND tenant_id=?', req.params.id, req.tenantId);
  if (!a) throw new sched.AppError('Não encontrado');
  const n = sched.reschedule(a.id, { start: V.datetime(req.body.start), professionalId: req.body.professional_id, createdBy: 'recepcao' });
  addMessage(getConversation(req.tenantId, a.client_id), { sender: 'agente', content: `Seu horário foi alterado para ${n.start.slice(8, 10)}/${n.start.slice(5, 7)} às ${n.start.slice(11, 16)} com ${n.professional_name}. Qualquer dúvida, é só responder aqui.` });
  fillFromWaitlist(a.id);
  audit(req, 'reschedule', 'appointment', a.id, { to: n.start });
  return n;
}));
r.get('/blocks', staff, wrap((req) => all(`SELECT b.*, p.name professional_name FROM blocks b LEFT JOIN professionals p ON p.id=b.professional_id WHERE b.tenant_id=? AND b.end >= ? ORDER BY b.start`, req.tenantId, nowLocal())));
r.post('/blocks', managers, wrap((req) => {
  const b = { tenant_id: req.tenantId, professional_id: req.body.professional_id ? Number(req.body.professional_id) : null, start: V.datetime(req.body.start), end: V.datetime(req.body.end), reason: V.str(req.body.reason, 200) };
  if (b.end <= b.start) throw new sched.AppError('Fim deve ser depois do início');
  if (b.professional_id && !get('SELECT id FROM professionals WHERE id=? AND tenant_id=?', b.professional_id, req.tenantId)) throw new sched.AppError('Profissional inválido');
  const id = insert('blocks', b);
  const afetados = req.body.reoffer === false ? 0 : applyBlock(b);
  audit(req, 'create', 'block', id, { afetados });
  return { id, afetados };
}));
r.delete('/blocks/:id', managers, wrap((req) => { run('DELETE FROM blocks WHERE id=? AND tenant_id=?', req.params.id, req.tenantId); return { ok: true }; }));

// ---------- Lista de espera ----------
r.get('/waitlist', staff, wrap((req) => all(`SELECT w.*, c.name client_name, c.phone client_phone, s.name service_name, p.name professional_name FROM waitlist w
  JOIN clients c ON c.id=w.client_id JOIN services s ON s.id=w.service_id LEFT JOIN professionals p ON p.id=w.professional_id WHERE w.tenant_id=? ORDER BY w.status='aguardando' DESC, w.id DESC LIMIT 300`, req.tenantId)));
r.post('/waitlist', notProf, wrap((req) => { if (!get('SELECT id FROM clients WHERE id=? AND tenant_id=?', req.body.client_id, req.tenantId)) throw new sched.AppError('Cliente inválido'); return { id: joinWaitlist({ tenantId: req.tenantId, clientId: Number(req.body.client_id), serviceId: Number(req.body.service_id), professionalId: req.body.professional_id ? Number(req.body.professional_id) : null, notes: V.str(req.body.notes, 300) }) }; }));
r.patch('/waitlist/:id', notProf, wrap((req) => { own('waitlist', req); if (!['aguardando', 'atendido', 'cancelado'].includes(req.body.status)) throw new sched.AppError('Status inválido'); update('waitlist', req.params.id, { status: req.body.status }); return { ok: true }; }));

// ---------- Catálogo de serviços ----------
const SVC = ['name', 'description', 'category', 'duration_min', 'buffer_min', 'price', 'cost', 'modality', 'preparation', 'return_days', 'online_booking', 'min_age', 'max_age', 'is_entry', 'package_sessions', 'package_session_price', 'package_service_id', 'sessions_per_week', 'requires_document', 'document_label', 'keywords', 'active'];
function cleanService(b) {
  const s = pick(b, SVC);
  for (const k of ['name', 'category', 'document_label']) if (k in s) s[k] = V.str(s[k], 120);
  for (const k of ['description', 'preparation', 'keywords']) if (k in s) s[k] = V.str(s[k], 1000);
  for (const [k, min, max] of [['duration_min', 5, 600], ['buffer_min', 0, 240], ['price', 0, 1e6], ['cost', 0, 1e6], ['return_days', 0, 365], ['package_sessions', 0, 100], ['package_session_price', 0, 1e6], ['sessions_per_week', 1, 5]]) if (k in s && s[k] !== null && s[k] !== '') s[k] = V.num(s[k], min, max);
  for (const k of ['min_age', 'max_age', 'package_service_id']) if (k in s) s[k] = s[k] === '' || s[k] == null ? null : Number(s[k]);
  for (const k of ['online_booking', 'is_entry', 'requires_document', 'active']) if (k in s) s[k] = bool(s[k]);
  if ('modality' in s && !['presencial', 'online', 'ambos'].includes(s.modality)) s.modality = 'presencial';
  return s;
}
r.get('/services', staff, wrap((req) => all('SELECT * FROM services WHERE tenant_id=? ORDER BY active DESC, category, name', req.tenantId).map((s) => ({
  ...(isManager(req) ? s : { ...s, cost: undefined }),
  professionals: all('SELECT ps.*, p.name FROM professional_services ps JOIN professionals p ON p.id=ps.professional_id WHERE ps.service_id=?', s.id),
}))));
r.post('/services', managers, wrap((req) => { const id = insert('services', { tenant_id: req.tenantId, ...cleanService(req.body) }); linkProfs(req, id, req.body.professionals); audit(req, 'create', 'service', id); return { id }; }));
r.put('/services/:id', managers, wrap((req) => { own('services', req); update('services', req.params.id, cleanService(req.body)); if (req.body.professionals) linkProfs(req, Number(req.params.id), req.body.professionals); audit(req, 'update', 'service', Number(req.params.id)); return { ok: true }; }));
/** professionals: [{ professional_id, duration_min?, price?, commission_pct? }] — personalização por profissional */
function linkProfs(req, serviceId, list) {
  if (!Array.isArray(list)) return;
  run('DELETE FROM professional_services WHERE service_id=?', serviceId);
  for (const x of list) {
    const pid = Number(x.professional_id ?? x);
    if (!get('SELECT id FROM professionals WHERE id=? AND tenant_id=?', pid, req.tenantId)) continue;
    insert('professional_services', { professional_id: pid, service_id: serviceId, duration_min: x.duration_min ? V.int(x.duration_min, 5, 600) : null, price: x.price !== '' && x.price != null ? V.num(x.price, 0, 1e6) : null, commission_pct: x.commission_pct !== '' && x.commission_pct != null ? V.num(x.commission_pct, 0, 100) : null });
  }
}

// ---------- Profissionais ----------
r.get('/professionals', staff, wrap((req) => all('SELECT * FROM professionals WHERE tenant_id=? ORDER BY active DESC, name', req.tenantId).map((p) => ({
  ...(isManager(req) ? p : { ...p, commission_pct: undefined }), schedule: parse(p.schedule_json),
  services: all('SELECT ps.*, s.name, s.duration_min base_duration, s.price base_price, s.category FROM professional_services ps JOIN services s ON s.id=ps.service_id WHERE ps.professional_id=? ORDER BY s.category, s.name', p.id),
}))));
function cleanProf(b) {
  const p = pick(b, ['name', 'specialty', 'council', 'registry', 'color', 'email', 'phone', 'bio', 'commission_pct', 'buffer_min', 'active']);
  for (const k of ['name', 'specialty', 'council', 'registry', 'phone']) if (k in p) p[k] = V.str(p[k], 120);
  if ('email' in p) p.email = p.email ? V.email(p.email) : null;
  if ('bio' in p) p.bio = V.str(p.bio, 1000);
  if ('color' in p && !/^#[0-9a-f]{6}$/i.test(p.color)) p.color = '#3b82f6';
  if ('commission_pct' in p) p.commission_pct = V.num(p.commission_pct || 0, 0, 100);
  if ('buffer_min' in p) p.buffer_min = V.int(p.buffer_min || 0, 0, 240);
  if ('active' in p) p.active = bool(p.active);
  return p;
}
function cleanSchedule(s) {
  const out = {};
  for (const [d, wins] of Object.entries(s || {})) {
    if (!/^[0-6]$/.test(d)) continue;
    out[d] = (wins || []).filter((w) => /^\d{2}:\d{2}$/.test(w[0]) && /^\d{2}:\d{2}$/.test(w[1]) && w[0] < w[1]).slice(0, 4);
  }
  return out;
}
function linkServices(req, profId, list) {
  if (!Array.isArray(list)) return;
  run('DELETE FROM professional_services WHERE professional_id=?', profId);
  for (const x of list) {
    const sid = Number(x.service_id ?? x);
    if (!get('SELECT id FROM services WHERE id=? AND tenant_id=?', sid, req.tenantId)) continue;
    insert('professional_services', { professional_id: profId, service_id: sid, duration_min: x.duration_min ? V.int(x.duration_min, 5, 600) : null, price: x.price !== '' && x.price != null ? V.num(x.price, 0, 1e6) : null, commission_pct: x.commission_pct !== '' && x.commission_pct != null ? V.num(x.commission_pct, 0, 100) : null });
  }
}
r.post('/professionals', managers, wrap((req) => {
  const p = cleanProf(req.body); if (!p.name) throw new sched.AppError('Informe o nome');
  const id = insert('professionals', { tenant_id: req.tenantId, ...p, schedule_json: JSON.stringify(cleanSchedule(req.body.schedule)) });
  linkServices(req, id, req.body.services); audit(req, 'create', 'professional', id); return { id };
}));
r.put('/professionals/:id', managers, wrap((req) => {
  own('professionals', req);
  const p = cleanProf(req.body); if (req.body.schedule) p.schedule_json = JSON.stringify(cleanSchedule(req.body.schedule));
  update('professionals', req.params.id, p); linkServices(req, Number(req.params.id), req.body.services);
  audit(req, 'update', 'professional', Number(req.params.id)); return { ok: true };
}));

// ---------- Clientes ----------
const CLIENT = ['name', 'phone', 'email', 'birthdate', 'document', 'notes', 'tags'];
function cleanClient(b) {
  const c = pick(b, CLIENT);
  if ('phone' in c) c.phone = V.phone(c.phone);
  if ('email' in c) c.email = c.email ? V.email(c.email) : null;
  if ('birthdate' in c) c.birthdate = V.date(c.birthdate) || null;
  for (const k of ['name', 'document', 'tags']) if (k in c) c[k] = V.str(c[k], 120);
  if ('notes' in c) c.notes = V.str(c.notes, 3000);
  return c;
}
r.get('/clients', notProf, wrap((req) => {
  const q = `%${String(req.query.q || '').slice(0, 60)}%`;
  return all(`SELECT c.*, (SELECT MAX(start) FROM appointments WHERE client_id=c.id AND status='realizado') last_visit,
    (SELECT MIN(start) FROM appointments WHERE client_id=c.id AND status IN ('confirmado','pendente') AND start >= ?) next_visit,
    (SELECT COUNT(*) FROM appointments WHERE client_id=c.id AND status NOT IN ('cancelado','remarcado')) total
    FROM clients c WHERE c.tenant_id=? AND (c.name LIKE ? OR c.phone LIKE ?) ORDER BY c.id DESC LIMIT 300`, nowLocal(), req.tenantId, q, q);
}));
r.get('/clients/:id', staff, wrap((req) => {
  const c = get('SELECT * FROM clients WHERE id=? AND tenant_id=?', req.params.id, req.tenantId);
  if (!c) throw new sched.AppError('Não encontrado');
  const conv = get('SELECT * FROM conversations WHERE client_id=? ORDER BY id DESC LIMIT 1', c.id);
  audit(req, 'view', 'client', c.id);
  return {
    client: c,
    appointments: all(`SELECT a.*, p.name professional_name, s.name service_name FROM appointments a JOIN professionals p ON p.id=a.professional_id JOIN services s ON s.id=a.service_id WHERE a.client_id=? ORDER BY a.start DESC`, c.id),
    treatments: treatmentsQuery(req.tenantId, c.id),
    documents: all('SELECT id, kind, mime, extracted, created_at FROM documents WHERE client_id=? ORDER BY id DESC', c.id),
    payments: all('SELECT * FROM payments WHERE client_id=? ORDER BY id DESC', c.id),
    waitlist: all(`SELECT w.*, s.name service_name FROM waitlist w JOIN services s ON s.id=w.service_id WHERE w.client_id=? AND w.status='aguardando'`, c.id),
    conversation: conv ? { ...conv, triage: parse(conv.triage_json, null) } : null,
  };
}));
r.post('/clients', notProf, wrap((req) => ({ id: insert('clients', { tenant_id: req.tenantId, ...cleanClient(req.body), source: 'recepcao' }) })));
r.put('/clients/:id', notProf, wrap((req) => { own('clients', req); update('clients', req.params.id, cleanClient(req.body)); audit(req, 'update', 'client', Number(req.params.id)); return { ok: true }; }));
r.delete('/clients/:id', managers, wrap((req) => { own('clients', req); run('DELETE FROM clients WHERE id=?', req.params.id); audit(req, 'delete', 'client', Number(req.params.id), 'LGPD: exclusão de dados'); return { ok: true }; }));
r.get('/documents/:id', staff, (req, res) => {
  const d = get('SELECT * FROM documents WHERE id=? AND tenant_id=?', req.params.id, req.tenantId);
  if (!d || !/^image\/(jpeg|png|webp|gif)$|^application\/pdf$/.test(d.mime || '')) return res.status(404).end();
  res.setHeader('Content-Disposition', 'inline'); res.type(d.mime).send(Buffer.from(d.data_b64, 'base64'));
});

// ---------- Tratamentos ----------
function treatmentsQuery(T, clientId) {
  return all(`SELECT t.*, c.name client_name, s.name service_name, p.name professional_name,
    (SELECT COUNT(*) FROM appointments a WHERE a.treatment_id=t.id AND a.session_number IS NOT NULL AND a.status='realizado') done,
    (SELECT COUNT(*) FROM appointments a WHERE a.treatment_id=t.id AND a.session_number IS NOT NULL AND a.status='faltou') missed,
    (SELECT MIN(start) FROM appointments a WHERE a.treatment_id=t.id AND a.status IN ('confirmado','pendente') AND a.start >= ?) next_session
    FROM treatments t JOIN clients c ON c.id=t.client_id JOIN services s ON s.id=t.service_id LEFT JOIN professionals p ON p.id=t.professional_id
    WHERE t.tenant_id=? ${clientId ? 'AND t.client_id=' + Number(clientId) : ''} ORDER BY t.id DESC`, nowLocal(), T);
}
r.get('/treatments', staff, wrap((req) => treatmentsQuery(req.tenantId)));
r.patch('/treatments/:id', notProf, wrap((req) => { own('treatments', req); if (!['ativo', 'concluido', 'abandonado', 'cancelado'].includes(req.body.status)) throw new sched.AppError('Status inválido'); update('treatments', req.params.id, { status: req.body.status }); if (req.body.status === 'cancelado') run(`UPDATE appointments SET status='cancelado', cancelled_by='clinica', recovery_sent=1 WHERE treatment_id=? AND status IN ('confirmado','pendente')`, req.params.id); return { ok: true }; }));

// ---------- Conversas ----------
r.get('/conversations', notProf, wrap((req) => all(`SELECT v.*, c.name client_name, c.phone client_phone,
  (SELECT content FROM messages WHERE conversation_id=v.id ORDER BY id DESC LIMIT 1) last_text,
  (SELECT type FROM messages WHERE conversation_id=v.id ORDER BY id DESC LIMIT 1) last_type,
  (SELECT COUNT(*) FROM security_events e WHERE e.tenant_id=v.tenant_id AND e.source=c.phone) alerts
  FROM conversations v JOIN clients c ON c.id=v.client_id WHERE v.tenant_id=? ORDER BY v.last_message_at DESC LIMIT 200`, req.tenantId)
  .map((v) => ({ ...v, triage: parse(v.triage_json, null), state_json: undefined }))));
r.get('/conversations/:id', notProf, wrap((req) => {
  const v = get('SELECT * FROM conversations WHERE id=? AND tenant_id=?', req.params.id, req.tenantId);
  if (!v) throw new sched.AppError('Não encontrada');
  update('conversations', v.id, { unread: 0 });
  return { conversation: { ...v, triage: parse(v.triage_json, null), state_json: undefined }, client: get('SELECT * FROM clients WHERE id=?', v.client_id), messages: history(v.id, 200).map(stripAudio), logs: all('SELECT * FROM automation_logs WHERE conversation_id=? ORDER BY id DESC LIMIT 60', v.id) };
}));
const stripAudio = (m) => (m.meta?.audio_b64 ? { ...m, meta: { ...m.meta, audio_b64: undefined, has_audio: true } } : m);
r.get('/messages/:id/audio', notProf, (req, res) => {
  const m = get('SELECT m.meta_json FROM messages m JOIN conversations c ON c.id=m.conversation_id WHERE m.id=? AND c.tenant_id=?', req.params.id, req.tenantId);
  const meta = parse(m?.meta_json, null);
  if (!meta?.audio_b64) return res.status(404).end();
  res.type(/^audio\/[\w.+-]+$/.test(meta.mime || '') ? meta.mime : 'audio/webm').send(Buffer.from(meta.audio_b64, 'base64'));
});
r.post('/conversations/:id/reply', notProf, wrap((req) => {
  const v = get('SELECT * FROM conversations WHERE id=? AND tenant_id=?', req.params.id, req.tenantId);
  if (!v) throw new sched.AppError('Não encontrada');
  const text = V.str(req.body.text, 2000); if (!text?.trim()) throw new sched.AppError('Mensagem vazia');
  if (req.body.takeover !== false && v.mode !== 'humano') update('conversations', v.id, { mode: 'humano' });
  return addMessage(v, { sender: 'humano', content: text, meta: { user: req.user.name } });
}));
r.post('/conversations/:id/mode', notProf, wrap((req) => {
  const v = get('SELECT * FROM conversations WHERE id=? AND tenant_id=?', req.params.id, req.tenantId);
  if (!v) throw new sched.AppError('Não encontrada');
  update('conversations', v.id, { mode: req.body.mode === 'humano' ? 'humano' : 'bot' });
  addMessage(v, { sender: 'sistema', type: 'note', content: req.body.mode === 'humano' ? `${req.user.name} assumiu a conversa` : 'Agente reativado nesta conversa' });
  return { ok: true };
}));

// ---------- Automação, segurança e integrações ----------
r.get('/automation', staff, wrap((req) => ({
  tenant: get('SELECT * FROM tenants WHERE id=?', req.tenantId), agent: { mode: agentMode(), model: MODEL },
  logs: all('SELECT l.*, c.name client_name FROM automation_logs l LEFT JOIN conversations v ON v.id=l.conversation_id LEFT JOIN clients c ON c.id=v.client_id WHERE l.tenant_id=? ORDER BY l.id DESC LIMIT 120', req.tenantId),
  stats: all(`SELECT step, COUNT(*) n, ROUND(AVG(ms)) avg_ms FROM automation_logs WHERE tenant_id=? GROUP BY step`, req.tenantId),
})));
r.post('/jobs/run', notProf, wrap(() => runJobs({ force: true })));
r.get('/security', managers, wrap((req) => ({
  events: all(`SELECT * FROM security_events WHERE tenant_id=? OR (tenant_id IS NULL AND ?) ORDER BY id DESC LIMIT 200`, req.tenantId, req.user.role === 'superadmin' ? 1 : 0),
  resumo: all(`SELECT kind, COUNT(*) n FROM security_events WHERE (tenant_id=? OR (tenant_id IS NULL AND ?)) AND created_at >= datetime('now','-30 days') GROUP BY kind`, req.tenantId, req.user.role === 'superadmin' ? 1 : 0),
})));
r.get('/integrations', staff, wrap((req) => {
  const rows = all('SELECT * FROM integrations WHERE tenant_id=?', req.tenantId).map((i) => ({ ...i, config: parse(i.config_json) }));
  const env = { whatsapp: whatsappEnabled(), ia: agentMode() === 'claude', transcricao: Boolean(process.env.OPENAI_API_KEY), google_calendar: Boolean(process.env.GOOGLE_CLIENT_ID), pagamentos: Boolean(process.env.PAYMENT_PROVIDER_TOKEN), mapas: true };
  return rows.map((i) => ({ ...i, env_ready: env[i.key] }));
}));
r.put('/integrations/:key', managers, wrap((req) => {
  if (!['whatsapp', 'ia', 'transcricao', 'google_calendar', 'pagamentos', 'mapas'].includes(req.params.key)) throw new sched.AppError('Integração inválida');
  const cfg = {}; for (const [k, v] of Object.entries(req.body.config || {})) if (!/token|secret|key|senha|password/i.test(k)) cfg[k.slice(0, 40)] = V.str(v, 300);
  run('INSERT INTO integrations (tenant_id,key,enabled,config_json) VALUES (?,?,?,?) ON CONFLICT(tenant_id,key) DO UPDATE SET enabled=excluded.enabled, config_json=excluded.config_json', req.tenantId, req.params.key, bool(req.body.enabled), JSON.stringify(cfg));
  if (req.params.key === 'whatsapp' && cfg.phone_number_id) update('tenants', req.tenantId, { whatsapp_phone_number_id: cfg.phone_number_id });
  return { ok: true };
}));

// ---------- Financeiro ----------
r.get('/payments', managers, wrap((req) => all('SELECT p.*, c.name client_name FROM payments p JOIN clients c ON c.id=p.client_id WHERE p.tenant_id=? ORDER BY p.id DESC LIMIT 300', req.tenantId)));
r.post('/payments', notProf, wrap((req) => {
  if (!get('SELECT id FROM clients WHERE id=? AND tenant_id=?', req.body.client_id, req.tenantId)) throw new sched.AppError('Cliente inválido');
  return { id: insert('payments', { tenant_id: req.tenantId, client_id: Number(req.body.client_id), treatment_id: req.body.treatment_id || null, amount: V.num(req.body.amount, 0.01, 1e6), method: ['pix', 'cartao', 'dinheiro', 'convenio'].includes(req.body.method) ? req.body.method : 'pix', status: 'pago' }) };
}));

// ---------- Usuários ----------
r.get('/users', managers, wrap((req) => all('SELECT id,name,email,role,active,professional_id FROM users WHERE tenant_id=? ORDER BY id', req.tenantId)));
r.post('/users', managers, wrap((req) => {
  const b = req.body; if (!['admin', 'recepcao', 'profissional'].includes(b.role)) throw new sched.AppError('Perfil inválido');
  if (get('SELECT id FROM users WHERE email=?', V.email(b.email))) throw new sched.AppError('E-mail já cadastrado');
  const id = insert('users', { tenant_id: req.tenantId, name: V.str(b.name, 80), email: V.email(b.email), password_hash: hashPassword(V.password(b.password)), role: b.role, professional_id: b.professional_id ? Number(b.professional_id) : null });
  audit(req, 'create', 'user', id); return { id };
}));
r.put('/users/:id', managers, wrap((req) => {
  own('users', req); const patch = pick(req.body, ['name', 'active', 'professional_id']);
  if (req.body.role) { if (!['admin', 'recepcao', 'profissional'].includes(req.body.role)) throw new sched.AppError('Perfil inválido'); patch.role = req.body.role; }
  if ('active' in patch) patch.active = bool(patch.active);
  if (req.body.password) patch.password_hash = hashPassword(V.password(req.body.password));
  if (Number(req.params.id) === req.user.id && patch.active === 0) throw new sched.AppError('Você não pode desativar o próprio usuário');
  update('users', req.params.id, patch); audit(req, 'update', 'user', Number(req.params.id), Object.keys(patch)); return { ok: true };
}));
r.get('/audit', managers, wrap((req) => all('SELECT a.*, u.name user_name FROM audit_logs a LEFT JOIN users u ON u.id=a.user_id WHERE a.tenant_id=? ORDER BY a.id DESC LIMIT 200', req.tenantId)));

const OWNED = new Set(['services', 'professionals', 'clients', 'treatments', 'users', 'waitlist']);
function own(table, req) { if (!OWNED.has(table) || !get(`SELECT id FROM ${table} WHERE id=? AND tenant_id=?`, req.params.id, req.tenantId)) throw new sched.AppError('Registro não encontrado'); }

export default r;
