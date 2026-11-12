import { Router } from 'express';
import { all, get, insert, update, run, parse } from '../db.js';
import { requireUser, checkPassword, hashPassword, sign } from '../services/auth.js';
import * as sched from '../services/scheduling.js';
import { addMessage, history, getConversation } from '../services/conversations.js';
import { runJobs, recoverNoShow } from '../services/jobs.js';
import { sse } from '../services/bus.js';
import { SEGMENTS, termsFor } from '../services/presets.js';
import { createTenant } from '../seed.js';
import { nowLocal, addDays, dateOf, TZ } from '../services/time.js';
import { agentMode } from '../agent/index.js';
import { MODEL } from '../agent/llm.js';
import { whatsappEnabled } from '../channels/whatsapp.js';

const r = Router();
const staff = requireUser();
const managers = requireUser(['admin']);
const audit = (req, action, entity, id, detail) => insert('audit_logs', { tenant_id: req.tenantId, user_id: req.user.id, action, entity, entity_id: id ?? null, detail: detail ? JSON.stringify(detail) : null });
const wrap = (fn) => (req, res) => { try { const out = fn(req, res); if (out !== undefined) res.json(out); } catch (e) { res.status(400).json({ error: e.message }); } };
const pick = (o, keys) => Object.fromEntries(keys.filter((k) => o[k] !== undefined).map((k) => [k, o[k]]));

// ---------- Auth ----------
r.post('/auth/login', (req, res) => {
  const u = get('SELECT * FROM users WHERE email=? AND active=1', String(req.body.email || '').toLowerCase().trim());
  if (!u || !checkPassword(req.body.password || '', u.password_hash)) return res.status(401).json({ error: 'E-mail ou senha inválidos' });
  res.json({ token: sign({ uid: u.id }), user: { id: u.id, name: u.name, email: u.email, role: u.role, tenant_id: u.tenant_id } });
});
r.get('/me', staff, wrap((req) => {
  const tenant = get('SELECT * FROM tenants WHERE id=?', req.tenantId);
  return { user: req.user, tenant, terms: tenant ? termsFor(tenant) : null, agent: { mode: agentMode(), model: MODEL }, whatsapp: whatsappEnabled(), segments: Object.fromEntries(Object.entries(SEGMENTS).map(([k, v]) => [k, v.label])) };
}));
r.get('/events', staff, (req, res) => sse(req, res, (d) => d.tenantId === req.tenantId));

// ---------- Empresas (multi-tenant) ----------
r.get('/tenants', staff, wrap((req) => req.user.role === 'superadmin' ? all('SELECT id,name,segment,city,automation_active FROM tenants ORDER BY id') : all('SELECT id,name,segment,city,automation_active FROM tenants WHERE id=?', req.tenantId)));
r.post('/tenants', requireUser(['superadmin']), wrap((req) => {
  const b = req.body;
  if (!b.name) throw new Error('Informe o nome');
  const slug = (b.slug || b.name).toLowerCase().normalize('NFD').replace(/[^\w]+/g, '-').replace(/^-|-$/g, '') + '-' + Date.now().toString(36).slice(-4);
  const id = createTenant({ name: b.name, slug, segment: b.segment || 'generico', address: b.address, city: b.city, phone: b.phone, agent_name: b.agent_name });
  if (b.admin_email) insert('users', { tenant_id: id, name: b.admin_name || 'Gestor', email: b.admin_email.toLowerCase(), password_hash: hashPassword(b.admin_password || '123456'), role: 'admin' });
  audit(req, 'create', 'tenant', id);
  return get('SELECT * FROM tenants WHERE id=?', id);
}));
r.put('/tenant', managers, wrap((req) => {
  const b = req.body;
  const patch = pick(b, ['name', 'segment', 'address', 'city', 'lat', 'lng', 'phone', 'whatsapp_phone_number_id', 'agent_name', 'agent_tone', 'agent_instructions', 'automation_active', 'automation_cost_monthly', 'reminder_hours_before', 'noshow_recovery', 'auto_book_package']);
  if (b.hours) patch.hours_json = JSON.stringify(b.hours);
  if (b.terms) patch.terms_json = JSON.stringify(b.terms);
  for (const k of ['automation_active', 'noshow_recovery', 'auto_book_package']) if (k in patch) patch[k] = patch[k] ? 1 : 0;
  update('tenants', req.tenantId, patch);
  audit(req, 'update', 'tenant', req.tenantId, Object.keys(patch));
  return get('SELECT * FROM tenants WHERE id=?', req.tenantId);
}));

// ---------- Dashboard ----------
r.get('/dashboard', staff, wrap((req) => {
  const T = req.tenantId; const days = Math.min(365, Number(req.query.days || 30));
  const now = nowLocal(); const from = addDays(dateOf(now), -days);
  const tenant = get('SELECT * FROM tenants WHERE id=?', T);
  const q = (sql, ...p) => get(sql, T, ...p);
  const agentAppts = q(`SELECT COUNT(*) n, COALESCE(SUM(price),0) v FROM appointments WHERE tenant_id=? AND created_by='agente' AND status NOT IN ('cancelado','remarcado') AND date(created_at) >= ?`, from);
  const allAppts = q(`SELECT COUNT(*) n FROM appointments WHERE tenant_id=? AND date(created_at) >= ? AND status NOT IN ('remarcado')`, from);
  const convs = q(`SELECT COUNT(*) n FROM conversations WHERE tenant_id=? AND date(last_message_at) >= ?`, from);
  const msgs = q(`SELECT COUNT(*) n FROM messages m JOIN conversations c ON c.id=m.conversation_id WHERE c.tenant_id=? AND m.sender='agente' AND date(m.created_at) >= ?`, from);
  const resp = q(`SELECT AVG(ms) avg FROM automation_logs WHERE tenant_id=? AND step='responde' AND date(created_at) >= ?`, from);
  const past = q(`SELECT SUM(status='realizado') done, SUM(status='faltou') missed FROM appointments WHERE tenant_id=? AND start >= ? AND start < ?`, from, now);
  const recovered = q(`SELECT COUNT(*) n FROM appointments a WHERE a.tenant_id=? AND a.rescheduled_from IN (SELECT id FROM appointments WHERE status='faltou')`);
  const treatments = q(`SELECT SUM(status='ativo') ativos, SUM(status='concluido') concluidos, SUM(status='abandonado') abandonados FROM treatments WHERE tenant_id=?`);
  const handoffs = q(`SELECT COUNT(*) n FROM conversations WHERE tenant_id=? AND mode='humano'`);
  // fora do horário comercial (agendamentos feitos pelo agente)
  const hours = parse(tenant.hours_json);
  const fmt = new Intl.DateTimeFormat('en-CA', { timeZone: TZ, weekday: 'short', hour: '2-digit', minute: '2-digit', hour12: false });
  const wd = { Sun: 0, Mon: 1, Tue: 2, Wed: 3, Thu: 4, Fri: 5, Sat: 6 };
  let offHours = 0;
  for (const a of all(`SELECT created_at FROM appointments WHERE tenant_id=? AND created_by='agente' AND date(created_at) >= ? AND (session_number IS NULL OR session_number=0)`, T, from)) {
    const parts = fmt.formatToParts(new Date(a.created_at.replace(' ', 'T') + 'Z'));
    const d = wd[parts.find((p) => p.type === 'weekday').value];
    const hm = `${parts.find((p) => p.type === 'hour').value.replace('24', '00')}:${parts.find((p) => p.type === 'minute').value}`;
    const h = hours[d];
    if (!h || hm < h[0] || hm >= h[1]) offHours++;
  }
  const series = all(`SELECT date(created_at) d, SUM(created_by='agente') agente, SUM(created_by<>'agente') equipe FROM appointments WHERE tenant_id=? AND date(created_at) >= ? AND (session_number IS NULL OR session_number<=1) GROUP BY d ORDER BY d`, T, addDays(dateOf(now), -13));
  const occupancy = all(`SELECT p.name, p.color, COUNT(a.id) n FROM professionals p LEFT JOIN appointments a ON a.professional_id=p.id AND a.status IN ('confirmado','pendente') AND a.start >= ? AND a.start < ? WHERE p.tenant_id=? GROUP BY p.id`, now, addDays(dateOf(now), 7), T);
  const topServices = all(`SELECT s.name, COUNT(a.id) n, COALESCE(SUM(a.price),0) v FROM appointments a JOIN services s ON s.id=a.service_id WHERE a.tenant_id=? AND a.status NOT IN ('cancelado','remarcado') AND date(a.created_at) >= ? GROUP BY s.id ORDER BY v DESC LIMIT 5`, T, from);
  const cost = tenant.automation_cost_monthly * (days / 30);
  const pipeline = all(`SELECT step, COUNT(*) n, ROUND(AVG(ms)) avg_ms FROM automation_logs WHERE tenant_id=? AND date(created_at) >= ? GROUP BY step`, T, from);
  return {
    days, receita_agente: agentAppts.v, agendamentos_agente: agentAppts.n, agendamentos_total: allAppts.n,
    conversas: convs.n, mensagens_agente: msgs.n, tempo_medio_resposta_ms: Math.round(resp.avg || 0),
    realizados: past.done || 0, faltas: past.missed || 0, recuperados: recovered.n,
    comparecimento: past.done + past.missed ? Math.round((100 * past.done) / (past.done + past.missed)) : null,
    tratamentos: treatments, transferidos_humano: handoffs.n, fora_do_horario: offHours,
    custo_automacao: cost, roi: cost ? agentAppts.v / cost : null, series, occupancy, topServices, pipeline,
    agente: { modo: agentMode(), modelo: MODEL, ativo: !!tenant.automation_active },
  };
}));

// ---------- Agenda ----------
r.get('/agenda', staff, wrap((req) => {
  const from = req.query.from || dateOf(nowLocal());
  const to = addDays(from, Math.min(62, Number(req.query.days || 1)));
  let sql = `SELECT a.*, c.name client_name, c.phone client_phone, p.name professional_name, p.color, s.name service_name
    FROM appointments a JOIN clients c ON c.id=a.client_id JOIN professionals p ON p.id=a.professional_id JOIN services s ON s.id=a.service_id
    WHERE a.tenant_id=? AND a.start >= ? AND a.start < ? AND a.status <> 'remarcado'`;
  const args = [req.tenantId, from, to];
  if (req.user.role === 'profissional' && req.user.professional_id) { sql += ' AND a.professional_id=?'; args.push(req.user.professional_id); }
  return {
    from, to, appointments: all(sql + ' ORDER BY a.start', ...args),
    professionals: all('SELECT * FROM professionals WHERE tenant_id=? AND active=1 ORDER BY id', req.tenantId),
    blocks: all('SELECT * FROM blocks WHERE tenant_id=? AND start < ? AND end > ?', req.tenantId, to, from),
  };
}));
r.get('/availability', staff, wrap((req) => sched.findOptions(req.tenantId, Number(req.query.service_id), { date: req.query.date, professionalId: req.query.professional_id, count: Number(req.query.count || 12), days: 1 })));
r.post('/appointments', staff, wrap((req) => {
  const b = req.body;
  let clientId = b.client_id;
  if (!clientId) {
    if (!b.client_phone) throw new Error('Informe o cliente');
    const phone = String(b.client_phone).replace(/\D/g, '');
    const ex = get('SELECT id FROM clients WHERE tenant_id=? AND phone=?', req.tenantId, phone);
    clientId = ex?.id || insert('clients', { tenant_id: req.tenantId, phone, name: b.client_name, source: 'recepcao' });
  }
  const a = sched.book({ tenantId: req.tenantId, clientId, serviceId: Number(b.service_id), professionalId: Number(b.professional_id), start: b.start, createdBy: 'recepcao', status: b.status || 'confirmado', notes: b.notes });
  if (b.package) sched.reservePackage({ tenantId: req.tenantId, clientId, entryAppointment: a, createdBy: 'recepcao' });
  audit(req, 'create', 'appointment', a.id);
  return a;
}));
r.patch('/appointments/:id', staff, wrap((req) => {
  const a = get('SELECT * FROM appointments WHERE id=? AND tenant_id=?', req.params.id, req.tenantId);
  if (!a) throw new Error('Não encontrado');
  if (req.body.notes !== undefined) update('appointments', a.id, { notes: req.body.notes });
  let out = sched.getAppointment(a.id);
  if (req.body.status) {
    out = sched.setStatus(a.id, req.body.status);
    if (req.body.status === 'faltou') {
      const tenant = get('SELECT * FROM tenants WHERE id=?', req.tenantId);
      if (tenant.noshow_recovery && tenant.automation_active) recoverNoShow(tenant, { ...out, client_name: out.client_name });
    }
  }
  audit(req, 'update', 'appointment', a.id, req.body);
  return out;
}));
r.post('/appointments/:id/reschedule', staff, wrap((req) => {
  const a = get('SELECT * FROM appointments WHERE id=? AND tenant_id=?', req.params.id, req.tenantId);
  if (!a) throw new Error('Não encontrado');
  return sched.reschedule(a.id, { start: req.body.start, professionalId: req.body.professional_id, createdBy: 'recepcao' });
}));
r.post('/blocks', managers, wrap((req) => ({ id: insert('blocks', { tenant_id: req.tenantId, professional_id: req.body.professional_id || null, start: req.body.start, end: req.body.end, reason: req.body.reason }) })));
r.delete('/blocks/:id', managers, wrap((req) => { run('DELETE FROM blocks WHERE id=? AND tenant_id=?', req.params.id, req.tenantId); return { ok: true }; }));

// ---------- Serviços ----------
const SVC = ['name', 'description', 'duration_min', 'price', 'is_entry', 'package_sessions', 'package_session_price', 'package_service_id', 'sessions_per_week', 'requires_document', 'document_label', 'keywords', 'active'];
r.get('/services', staff, wrap((req) => all('SELECT * FROM services WHERE tenant_id=? ORDER BY active DESC, is_entry DESC, id', req.tenantId).map((s) => ({ ...s, professional_ids: all('SELECT professional_id FROM professional_services WHERE service_id=?', s.id).map((x) => x.professional_id) }))));
r.post('/services', managers, wrap((req) => { const id = insert('services', { tenant_id: req.tenantId, ...pick(req.body, SVC) }); linkProfs(id, req.body.professional_ids); return { id }; }));
r.put('/services/:id', managers, wrap((req) => { own('services', req); update('services', req.params.id, pick(req.body, SVC)); if (req.body.professional_ids) linkProfs(Number(req.params.id), req.body.professional_ids); return { ok: true }; }));
function linkProfs(serviceId, ids) { if (!ids) return; run('DELETE FROM professional_services WHERE service_id=?', serviceId); for (const p of ids) insert('professional_services', { professional_id: Number(p), service_id: serviceId }); }

// ---------- Profissionais ----------
r.get('/professionals', staff, wrap((req) => all('SELECT * FROM professionals WHERE tenant_id=? ORDER BY active DESC, id', req.tenantId).map((p) => ({ ...p, schedule: parse(p.schedule_json), service_ids: all('SELECT service_id FROM professional_services WHERE professional_id=?', p.id).map((x) => x.service_id) }))));
r.post('/professionals', managers, wrap((req) => {
  const b = req.body;
  const id = insert('professionals', { tenant_id: req.tenantId, name: b.name, specialty: b.specialty, registry: b.registry, color: b.color || '#3b82f6', schedule_json: JSON.stringify(b.schedule || {}) });
  for (const s of b.service_ids || []) insert('professional_services', { professional_id: id, service_id: Number(s) });
  return { id };
}));
r.put('/professionals/:id', managers, wrap((req) => {
  own('professionals', req);
  const b = req.body; const patch = pick(b, ['name', 'specialty', 'registry', 'color', 'active']);
  if (b.schedule) patch.schedule_json = JSON.stringify(b.schedule);
  update('professionals', req.params.id, patch);
  if (b.service_ids) { run('DELETE FROM professional_services WHERE professional_id=?', req.params.id); for (const s of b.service_ids) insert('professional_services', { professional_id: Number(req.params.id), service_id: Number(s) }); }
  return { ok: true };
}));

// ---------- Clientes ----------
r.get('/clients', staff, wrap((req) => {
  const q = `%${req.query.q || ''}%`;
  return all(`SELECT c.*, (SELECT MAX(start) FROM appointments WHERE client_id=c.id AND status IN ('realizado')) last_visit,
    (SELECT MIN(start) FROM appointments WHERE client_id=c.id AND status IN ('confirmado','pendente') AND start >= ?) next_visit,
    (SELECT COUNT(*) FROM appointments WHERE client_id=c.id AND status NOT IN ('cancelado','remarcado')) total
    FROM clients c WHERE c.tenant_id=? AND (c.name LIKE ? OR c.phone LIKE ?) ORDER BY c.id DESC LIMIT 300`, nowLocal(), req.tenantId, q, q);
}));
r.get('/clients/:id', staff, wrap((req) => {
  const c = get('SELECT * FROM clients WHERE id=? AND tenant_id=?', req.params.id, req.tenantId);
  if (!c) throw new Error('Não encontrado');
  const conv = get('SELECT * FROM conversations WHERE client_id=? ORDER BY id DESC LIMIT 1', c.id);
  return {
    client: c,
    appointments: all(`SELECT a.*, p.name professional_name, s.name service_name FROM appointments a JOIN professionals p ON p.id=a.professional_id JOIN services s ON s.id=a.service_id WHERE a.client_id=? ORDER BY a.start DESC`, c.id),
    treatments: treatmentsQuery(req.tenantId, c.id),
    documents: all('SELECT id, kind, mime, extracted, created_at FROM documents WHERE client_id=? ORDER BY id DESC', c.id),
    payments: all('SELECT * FROM payments WHERE client_id=? ORDER BY id DESC', c.id),
    conversation: conv ? { ...conv, triage: parse(conv.triage_json, null) } : null,
  };
}));
r.post('/clients', staff, wrap((req) => ({ id: insert('clients', { tenant_id: req.tenantId, ...pick(req.body, ['name', 'phone', 'email', 'birthdate', 'document', 'notes', 'tags']), phone: String(req.body.phone || '').replace(/\D/g, ''), source: 'recepcao' }) })));
r.put('/clients/:id', staff, wrap((req) => { own('clients', req); update('clients', req.params.id, pick(req.body, ['name', 'phone', 'email', 'birthdate', 'document', 'notes', 'tags'])); return { ok: true }; }));
r.delete('/clients/:id', managers, wrap((req) => { own('clients', req); run('DELETE FROM clients WHERE id=?', req.params.id); audit(req, 'delete', 'client', Number(req.params.id), 'LGPD: exclusão de dados'); return { ok: true }; }));
r.get('/documents/:id', staff, (req, res) => {
  const d = get('SELECT * FROM documents WHERE id=? AND tenant_id=?', req.params.id, req.tenantId);
  if (!d) return res.status(404).end();
  res.type(d.mime || 'image/jpeg').send(Buffer.from(d.data_b64, 'base64'));
});

// ---------- Tratamentos / pacotes ----------
function treatmentsQuery(T, clientId) {
  return all(`SELECT t.*, c.name client_name, s.name service_name, p.name professional_name,
    (SELECT COUNT(*) FROM appointments a WHERE a.treatment_id=t.id AND a.session_number IS NOT NULL AND a.status='realizado') done,
    (SELECT COUNT(*) FROM appointments a WHERE a.treatment_id=t.id AND a.session_number IS NOT NULL AND a.status='faltou') missed,
    (SELECT COUNT(*) FROM appointments a WHERE a.treatment_id=t.id AND a.session_number IS NOT NULL AND a.status IN ('confirmado','pendente')) scheduled,
    (SELECT MIN(start) FROM appointments a WHERE a.treatment_id=t.id AND a.status IN ('confirmado','pendente')) next_session
    FROM treatments t JOIN clients c ON c.id=t.client_id JOIN services s ON s.id=t.service_id LEFT JOIN professionals p ON p.id=t.professional_id
    WHERE t.tenant_id=? ${clientId ? 'AND t.client_id=' + Number(clientId) : ''} ORDER BY t.id DESC`, T);
}
r.get('/treatments', staff, wrap((req) => treatmentsQuery(req.tenantId)));
r.patch('/treatments/:id', staff, wrap((req) => { own('treatments', req); update('treatments', req.params.id, pick(req.body, ['status'])); if (req.body.status === 'cancelado') run(`UPDATE appointments SET status='cancelado' WHERE treatment_id=? AND status IN ('confirmado','pendente')`, req.params.id); return { ok: true }; }));

// ---------- Conversas (inbox) ----------
r.get('/conversations', staff, wrap((req) => all(`SELECT v.*, c.name client_name, c.phone client_phone,
  (SELECT content FROM messages WHERE conversation_id=v.id ORDER BY id DESC LIMIT 1) last_text,
  (SELECT type FROM messages WHERE conversation_id=v.id ORDER BY id DESC LIMIT 1) last_type
  FROM conversations v JOIN clients c ON c.id=v.client_id WHERE v.tenant_id=? ORDER BY v.last_message_at DESC LIMIT 200`, req.tenantId)
  .map((v) => ({ ...v, triage: parse(v.triage_json, null) }))));
r.get('/conversations/:id', staff, wrap((req) => {
  const v = get('SELECT * FROM conversations WHERE id=? AND tenant_id=?', req.params.id, req.tenantId);
  if (!v) throw new Error('Não encontrada');
  update('conversations', v.id, { unread: 0 });
  return { conversation: { ...v, triage: parse(v.triage_json, null), state: parse(v.state_json) }, client: get('SELECT * FROM clients WHERE id=?', v.client_id), messages: history(v.id, 200).map(stripAudio), logs: all('SELECT * FROM automation_logs WHERE conversation_id=? ORDER BY id DESC LIMIT 60', v.id) };
}));
const stripAudio = (m) => (m.meta?.audio_b64 ? { ...m, meta: { ...m.meta, audio_b64: undefined, has_audio: true } } : m);
r.get('/messages/:id/audio', staff, (req, res) => {
  const m = get('SELECT m.meta_json FROM messages m JOIN conversations c ON c.id=m.conversation_id WHERE m.id=? AND c.tenant_id=?', req.params.id, req.tenantId);
  const meta = parse(m?.meta_json, null);
  if (!meta?.audio_b64) return res.status(404).end();
  res.type(meta.mime || 'audio/webm').send(Buffer.from(meta.audio_b64, 'base64'));
});
r.post('/conversations/:id/reply', staff, wrap((req) => {
  const v = get('SELECT * FROM conversations WHERE id=? AND tenant_id=?', req.params.id, req.tenantId);
  if (!v) throw new Error('Não encontrada');
  if (req.body.takeover !== false && v.mode !== 'humano') update('conversations', v.id, { mode: 'humano' });
  return addMessage(v, { sender: 'humano', content: req.body.text, meta: { user: req.user.name } });
}));
r.post('/conversations/:id/mode', staff, wrap((req) => {
  const v = get('SELECT * FROM conversations WHERE id=? AND tenant_id=?', req.params.id, req.tenantId);
  update('conversations', v.id, { mode: req.body.mode === 'humano' ? 'humano' : 'bot' });
  addMessage(v, { sender: 'sistema', type: 'note', content: req.body.mode === 'humano' ? `${req.user.name} assumiu a conversa` : 'Agente de IA reativado nesta conversa' });
  return { ok: true };
}));
r.post('/clients/:id/message', staff, wrap((req) => { own('clients', req); return addMessage(getConversation(req.tenantId, Number(req.params.id)), { sender: 'humano', content: req.body.text, meta: { user: req.user.name } }); }));

// ---------- Automação ----------
r.get('/automation', staff, wrap((req) => {
  const tenant = get('SELECT * FROM tenants WHERE id=?', req.tenantId);
  return {
    tenant, agent: { mode: agentMode(), model: MODEL },
    logs: all('SELECT l.*, c.name client_name FROM automation_logs l LEFT JOIN conversations v ON v.id=l.conversation_id LEFT JOIN clients c ON c.id=v.client_id WHERE l.tenant_id=? ORDER BY l.id DESC LIMIT 120', req.tenantId),
    stats: all(`SELECT step, COUNT(*) n, ROUND(AVG(ms)) avg_ms FROM automation_logs WHERE tenant_id=? GROUP BY step`, req.tenantId),
  };
}));
r.post('/jobs/run', staff, wrap(() => runJobs()));

// ---------- Integrações ----------
r.get('/integrations', staff, wrap((req) => {
  const rows = all('SELECT * FROM integrations WHERE tenant_id=?', req.tenantId).map((i) => ({ ...i, config: parse(i.config_json) }));
  const env = { whatsapp: whatsappEnabled(), ia: agentMode() === 'claude', transcricao: Boolean(process.env.OPENAI_API_KEY), google_calendar: Boolean(process.env.GOOGLE_CLIENT_ID), pagamentos: Boolean(process.env.PAYMENT_PROVIDER_TOKEN), mapas: true };
  return rows.map((i) => ({ ...i, env_ready: env[i.key] }));
}));
r.put('/integrations/:key', managers, wrap((req) => {
  // Segredos NÃO são salvos aqui — ficam em variáveis de ambiente/cofre. Só configuração não sensível.
  const cfg = { ...req.body.config }; for (const k of Object.keys(cfg)) if (/token|secret|key|senha|password/i.test(k)) delete cfg[k];
  run('INSERT INTO integrations (tenant_id,key,enabled,config_json) VALUES (?,?,?,?) ON CONFLICT(tenant_id,key) DO UPDATE SET enabled=excluded.enabled, config_json=excluded.config_json', req.tenantId, req.params.key, req.body.enabled ? 1 : 0, JSON.stringify(cfg));
  if (req.params.key === 'whatsapp' && cfg.phone_number_id) update('tenants', req.tenantId, { whatsapp_phone_number_id: cfg.phone_number_id });
  return { ok: true };
}));

// ---------- Financeiro ----------
r.get('/payments', staff, wrap((req) => all('SELECT p.*, c.name client_name FROM payments p JOIN clients c ON c.id=p.client_id WHERE p.tenant_id=? ORDER BY p.id DESC LIMIT 300', req.tenantId)));
r.post('/payments', staff, wrap((req) => ({ id: insert('payments', { tenant_id: req.tenantId, ...pick(req.body, ['client_id', 'treatment_id', 'appointment_id', 'amount', 'method', 'status']) }) })));

// ---------- Usuários ----------
r.get('/users', managers, wrap((req) => all('SELECT id,name,email,role,active,professional_id FROM users WHERE tenant_id=? ORDER BY id', req.tenantId)));
r.post('/users', managers, wrap((req) => {
  const b = req.body; if (b.role === 'superadmin' && req.user.role !== 'superadmin') throw new Error('Sem permissão');
  return { id: insert('users', { tenant_id: req.tenantId, name: b.name, email: String(b.email).toLowerCase(), password_hash: hashPassword(b.password || '123456'), role: b.role || 'recepcao', professional_id: b.professional_id || null }) };
}));
r.put('/users/:id', managers, wrap((req) => {
  own('users', req); const patch = pick(req.body, ['name', 'role', 'active', 'professional_id']);
  if (req.body.password) patch.password_hash = hashPassword(req.body.password);
  update('users', req.params.id, patch); return { ok: true };
}));
r.get('/audit', managers, wrap((req) => all('SELECT a.*, u.name user_name FROM audit_logs a LEFT JOIN users u ON u.id=a.user_id WHERE a.tenant_id=? ORDER BY a.id DESC LIMIT 200', req.tenantId)));

function own(table, req) { if (!get(`SELECT id FROM ${table} WHERE id=? AND tenant_id=?`, req.params.id, req.tenantId)) throw new Error('Registro não encontrado'); }

export default r;
