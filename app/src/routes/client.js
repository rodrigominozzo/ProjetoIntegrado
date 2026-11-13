// API do app do cliente (simulador de WhatsApp + área do cliente) e webhook do WhatsApp.
import { Router } from 'express';
import { all, get, update } from '../db.js';
import { requireClient, sign } from '../services/auth.js';
import { upsertClient, getConversation, history } from '../services/conversations.js';
import { handleIncoming } from '../agent/index.js';
import * as sched from '../services/scheduling.js';
import { offerReplacement, fillFromWaitlist, joinWaitlist } from '../services/proactive.js';
import { publicCatalog } from '../agent/tools.js';
import { sse } from '../services/bus.js';
import { termsFor } from '../services/presets.js';
import { parseWebhook } from '../channels/whatsapp.js';
import { V, rateLimit, publicError, verifyMetaSignature } from '../services/security.js';
import { securityEvent } from '../agent/guard.js';

const r = Router();
const wrap = (fn) => async (req, res) => { try { const out = await fn(req, res); if (out !== undefined) res.json(out); } catch (e) { res.status(400).json({ error: publicError(e) }); } };

r.get('/public/tenants', wrap(() => all('SELECT id, name, segment, city FROM tenants ORDER BY id')));

// Login simplificado para testes. Em produção: código OTP enviado pelo WhatsApp/SMS.
r.post('/client/login', rateLimit({ key: 'client-login', max: 10, windowMs: 60_000 }), wrap((req) => {
  const tenantId = Number(req.body.tenant_id);
  if (!get('SELECT id FROM tenants WHERE id=?', tenantId)) throw new sched.AppError('Empresa inválida');
  const c = upsertClient(tenantId, V.phone(req.body.phone), V.str(req.body.name, 80));
  if (req.body.consent) update('clients', c.id, { consent_lgpd: 1 });
  return { token: sign({ cid: c.id }, 24 * 30), client: { id: c.id, name: c.name, phone: c.phone } };
}));

r.get('/client/me', requireClient, wrap((req) => {
  const tenant = get('SELECT id,name,segment,address,city,lat,lng,agent_name,phone,terms_json,hours_json,insurances,payment_methods,policies,cancel_min_hours FROM tenants WHERE id=?', req.tenantId);
  const { id, name, phone, email, birthdate, consent_lgpd } = req.client;
  return { client: { id, name, phone, email, birthdate, consent_lgpd }, tenant, terms: termsFor(tenant) };
}));
r.put('/client/me', requireClient, wrap((req) => {
  const p = {};
  if (req.body.name !== undefined) p.name = V.str(req.body.name, 80);
  if (req.body.email !== undefined) p.email = req.body.email ? V.email(req.body.email) : null;
  if (req.body.birthdate !== undefined) p.birthdate = V.date(req.body.birthdate) || null;
  update('clients', req.client.id, p); return { ok: true };
}));
r.get('/client/events', requireClient, (req, res) => sse(req, res, (d) => d.clientId === req.client.id));

r.get('/client/messages', requireClient, wrap((req) => {
  const conv = getConversation(req.tenantId, req.client.id);
  return { conversation_id: conv.id, messages: history(conv.id, 200).map((m) => ({ id: m.id, sender: m.sender, type: m.type, content: m.content, created_at: m.created_at, meta: m.meta ? { ...m.meta, audio_b64: undefined, blocked: undefined } : null })) };
}));
r.post('/client/messages', requireClient, rateLimit({ key: 'client-msg', max: 30, windowMs: 60_000 }), wrap(async (req) => {
  const b = req.body;
  const type = ['text', 'audio', 'image'].includes(b.type) ? b.type : 'text';
  const payload = {
    tenantId: req.tenantId, phone: req.client.phone, name: req.client.name, channel: 'simulador', type,
    text: V.str(b.text, 2000), transcript: V.str(b.transcript, 2000), duration: Number(b.duration) || null,
    audio: V.media(b.audio, ['audio/'], 10), image: V.media(b.image, ['image/jpeg', 'image/png', 'image/webp'], 8),
  };
  if (type === 'text' && !payload.text?.trim()) throw new sched.AppError('Mensagem vazia');
  if (type === 'image' && !payload.image) throw new sched.AppError('Imagem ausente');
  handleIncoming(payload).catch((e) => console.error('[cliente] erro no atendimento', e));
  return { ok: true };
}));

r.get('/client/appointments', requireClient, wrap((req) => all(`SELECT a.id, a.start, a.end, a.status, a.price, a.session_number, a.treatment_id, a.service_id, a.professional_id,
  p.name professional_name, s.name service_name, s.preparation FROM appointments a
  JOIN professionals p ON p.id=a.professional_id JOIN services s ON s.id=a.service_id
  WHERE a.client_id=? AND a.status <> 'remarcado' ORDER BY a.start`, req.client.id)));
r.post('/client/appointments/:id/:action', requireClient, wrap((req) => {
  const a = get('SELECT * FROM appointments WHERE id=? AND client_id=?', req.params.id, req.client.id);
  if (!a) throw new sched.AppError('Agendamento não encontrado');
  const tenant = get('SELECT * FROM tenants WHERE id=?', req.tenantId);
  if (req.params.action === 'confirm') { sched.setStatus(a.id, 'confirmado'); return { ok: true }; }
  if (!['cancel', 'reschedule'].includes(req.params.action)) throw new sched.AppError('Ação inválida');
  if (!['pendente', 'confirmado'].includes(a.status)) throw new sched.AppError('Este agendamento não pode ser alterado');
  if (!sched.withinCancelWindow(a)) throw new sched.AppError(`Alterações com menos de ${tenant.cancel_min_hours}h de antecedência são feitas pela equipe. Fale com a gente pela conversa.`);
  if (req.params.action === 'cancel') {
    sched.cancel(a.id, { by: 'cliente', reason: V.str(req.body?.reason, 200) });
    fillFromWaitlist(a.id);
    if (tenant.reoffer_cancel) offerReplacement(a.id, 'cancelamento_cliente'); // proativo: já manda novas datas na conversa
    return { ok: true, reoffered: !!tenant.reoffer_cancel };
  }
  const n = sched.reschedule(a.id, { start: V.datetime(req.body.start), professionalId: req.body.professional_id ? Number(req.body.professional_id) : undefined, createdBy: 'cliente' });
  fillFromWaitlist(a.id);
  return { ok: true, start: n.start };
}));
r.get('/client/treatments', requireClient, wrap((req) => all(`SELECT t.id, t.total_sessions, t.session_price, t.status, s.name service_name, p.name professional_name,
  (SELECT COUNT(*) FROM appointments a WHERE a.treatment_id=t.id AND a.session_number IS NOT NULL AND a.status='realizado') done
  FROM treatments t JOIN services s ON s.id=t.service_id LEFT JOIN professionals p ON p.id=t.professional_id WHERE t.client_id=? ORDER BY t.id DESC`, req.client.id)));

// Catálogo e autoagendamento
r.get('/client/catalog', requireClient, wrap((req) => publicCatalog(req.tenantId)));
r.get('/client/availability', requireClient, wrap((req) => {
  const s = get('SELECT * FROM services WHERE id=? AND tenant_id=? AND active=1', Number(req.query.service_id), req.tenantId);
  if (!s?.online_booking) return [];
  return sched.findOptions(req.tenantId, s.id, { date: V.date(req.query.date), professionalId: req.query.professional_id ? Number(req.query.professional_id) : undefined, count: Math.min(12, Number(req.query.count || 8)), days: req.query.date ? 1 : 21 });
}));
r.post('/client/book', requireClient, rateLimit({ key: 'client-book', max: 10, windowMs: 60_000 }), wrap((req) => {
  const s = get('SELECT * FROM services WHERE id=? AND tenant_id=? AND active=1', Number(req.body.service_id), req.tenantId);
  if (!s?.online_booking) throw new sched.AppError('Este serviço é agendado pela equipe');
  const start = V.datetime(req.body.start);
  const free = sched.findOptions(req.tenantId, s.id, { date: start.slice(0, 10), professionalId: Number(req.body.professional_id), count: 200, days: 1 });
  if (!free.find((o) => o.start === start)) throw new sched.AppError('Horário indisponível');
  const a = sched.book({ tenantId: req.tenantId, clientId: req.client.id, serviceId: s.id, professionalId: Number(req.body.professional_id), start, createdBy: 'cliente', status: 'confirmado' });
  const tenant = get('SELECT * FROM tenants WHERE id=?', req.tenantId);
  const pacote = req.body.package && tenant.auto_book_package ? sched.reservePackage({ tenantId: req.tenantId, clientId: req.client.id, entryAppointment: a, createdBy: 'cliente' }) : null;
  return { appointment: { id: a.id, start: a.start, professional_name: a.professional_name, service_name: a.service_name, price: a.price, preparation: a.preparation }, sessions: pacote?.sessions?.length || 0 };
}));
r.post('/client/waitlist', requireClient, wrap((req) => {
  const s = get('SELECT id FROM services WHERE id=? AND tenant_id=? AND active=1', Number(req.body.service_id), req.tenantId);
  if (!s) throw new sched.AppError('Serviço inválido');
  return { id: joinWaitlist({ tenantId: req.tenantId, clientId: req.client.id, serviceId: s.id, professionalId: req.body.professional_id ? Number(req.body.professional_id) : null }) };
}));

// ---------- WhatsApp Cloud API webhook ----------
r.get('/webhook/whatsapp', (req, res) => {
  const token = process.env.WHATSAPP_VERIFY_TOKEN;
  if (token && req.query['hub.mode'] === 'subscribe' && req.query['hub.verify_token'] === token) return res.type('text/plain').send(String(req.query['hub.challenge']).slice(0, 100));
  res.sendStatus(403);
});
r.post('/webhook/whatsapp', rateLimit({ key: 'webhook', max: 600, windowMs: 60_000 }), async (req, res) => {
  if (!verifyMetaSignature(req)) { securityEvent(null, 'webhook_assinatura_invalida', req.socket.remoteAddress, ''); return res.sendStatus(401); }
  res.sendStatus(200); // a Meta exige resposta rápida
  try {
    for (const m of await parseWebhook(req.body)) {
      const tenant = get('SELECT id FROM tenants WHERE whatsapp_phone_number_id=?', String(m.phoneNumberId || ''));
      if (!tenant) continue;
      await handleIncoming({ tenantId: tenant.id, phone: m.from, name: m.name, channel: 'whatsapp', type: m.type, text: m.text, audio: m.audio, image: m.image });
    }
  } catch (e) { console.error('[whatsapp webhook]', e.message); }
});

export default r;
