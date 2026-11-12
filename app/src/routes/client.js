// API do app do cliente (simulador de WhatsApp + portal "Minha área").
import { Router } from 'express';
import { all, get, update, parse } from '../db.js';
import { requireClient, sign } from '../services/auth.js';
import { upsertClient, getConversation, history } from '../services/conversations.js';
import { handleIncoming } from '../agent/index.js';
import * as sched from '../services/scheduling.js';
import { sse } from '../services/bus.js';
import { termsFor } from '../services/presets.js';
import { parseWebhook } from '../channels/whatsapp.js';

const r = Router();
const wrap = (fn) => async (req, res) => { try { const out = await fn(req, res); if (out !== undefined) res.json(out); } catch (e) { console.error(e); res.status(400).json({ error: e.message }); } };

r.get('/public/tenants', wrap(() => all('SELECT id, name, segment, city, agent_name, address FROM tenants ORDER BY id')));

// Login simplificado para testes. Em produção: código OTP enviado pelo WhatsApp.
r.post('/client/login', wrap((req) => {
  const { tenant_id, phone, name } = req.body;
  if (!get('SELECT id FROM tenants WHERE id=?', tenant_id)) throw new Error('Empresa inválida');
  if (String(phone || '').replace(/\D/g, '').length < 10) throw new Error('Telefone inválido (DDD + número)');
  const c = upsertClient(Number(tenant_id), phone, name);
  if (req.body.consent) update('clients', c.id, { consent_lgpd: 1 });
  return { token: sign({ cid: c.id }, 24 * 30), client: c };
}));

r.get('/client/me', requireClient, wrap((req) => {
  const tenant = get('SELECT id,name,segment,address,city,lat,lng,agent_name,phone,terms_json,hours_json FROM tenants WHERE id=?', req.tenantId);
  return { client: req.client, tenant, terms: termsFor(tenant) };
}));
r.put('/client/me', requireClient, wrap((req) => {
  const p = {}; for (const k of ['name', 'email', 'birthdate']) if (req.body[k] !== undefined) p[k] = req.body[k];
  update('clients', req.client.id, p); return { ok: true };
}));
r.get('/client/events', requireClient, (req, res) => sse(req, res, (d) => d.clientId === req.client.id));

r.get('/client/messages', requireClient, wrap((req) => {
  const conv = getConversation(req.tenantId, req.client.id);
  return { conversation_id: conv.id, messages: history(conv.id, 200).map((m) => ({ ...m, meta: m.meta?.audio_b64 ? { ...m.meta, audio_b64: undefined } : m.meta, meta_json: undefined })) };
}));
r.post('/client/messages', requireClient, wrap(async (req) => {
  const b = req.body;
  // Responde rápido e processa em segundo plano: as respostas chegam por SSE.
  handleIncoming({ tenantId: req.tenantId, phone: req.client.phone, name: req.client.name, channel: 'simulador', type: b.type || 'text', text: b.text, audio: b.audio, image: b.image, transcript: b.transcript, duration: b.duration })
    .catch((e) => console.error('[cliente] erro no atendimento', e));
  return { ok: true };
}));

r.get('/client/appointments', requireClient, wrap((req) => all(`SELECT a.*, p.name professional_name, s.name service_name FROM appointments a
  JOIN professionals p ON p.id=a.professional_id JOIN services s ON s.id=a.service_id
  WHERE a.client_id=? AND a.status <> 'remarcado' ORDER BY a.start`, req.client.id)));
r.post('/client/appointments/:id/:action', requireClient, wrap((req) => {
  const a = get('SELECT * FROM appointments WHERE id=? AND client_id=?', req.params.id, req.client.id);
  if (!a) throw new Error('Agendamento não encontrado');
  if (req.params.action === 'confirm') return sched.setStatus(a.id, 'confirmado');
  if (req.params.action === 'cancel') return sched.cancel(a.id);
  if (req.params.action === 'reschedule') return sched.reschedule(a.id, { start: req.body.start, professionalId: req.body.professional_id, createdBy: 'cliente' });
  throw new Error('Ação inválida');
}));
r.get('/client/treatments', requireClient, wrap((req) => all(`SELECT t.*, s.name service_name, p.name professional_name,
  (SELECT COUNT(*) FROM appointments a WHERE a.treatment_id=t.id AND a.session_number IS NOT NULL AND a.status='realizado') done
  FROM treatments t JOIN services s ON s.id=t.service_id LEFT JOIN professionals p ON p.id=t.professional_id WHERE t.client_id=? ORDER BY t.id DESC`, req.client.id)));

// Autoagendamento pelo portal
r.get('/client/services', requireClient, wrap((req) => all('SELECT id,name,description,duration_min,price,package_sessions,package_session_price FROM services WHERE tenant_id=? AND active=1', req.tenantId)));
r.get('/client/availability', requireClient, wrap((req) => sched.findOptions(req.tenantId, Number(req.query.service_id), { date: req.query.date, count: Number(req.query.count || 8), days: req.query.date ? 1 : 14 })));
r.post('/client/book', requireClient, wrap((req) => {
  const a = sched.book({ tenantId: req.tenantId, clientId: req.client.id, serviceId: Number(req.body.service_id), professionalId: Number(req.body.professional_id), start: req.body.start, createdBy: 'cliente', status: 'confirmado' });
  const tenant = get('SELECT * FROM tenants WHERE id=?', req.tenantId);
  let pacote = null;
  if (req.body.package && tenant.auto_book_package) pacote = sched.reservePackage({ tenantId: req.tenantId, clientId: req.client.id, entryAppointment: a, createdBy: 'cliente' });
  return { appointment: a, sessions: pacote?.sessions?.length || 0 };
}));

// ---------- WhatsApp Cloud API webhook ----------
r.get('/webhook/whatsapp', (req, res) => {
  if (req.query['hub.mode'] === 'subscribe' && req.query['hub.verify_token'] === (process.env.WHATSAPP_VERIFY_TOKEN || 'atende-ai')) return res.send(req.query['hub.challenge']);
  res.sendStatus(403);
});
r.post('/webhook/whatsapp', async (req, res) => {
  res.sendStatus(200); // a Meta exige resposta rápida
  try {
    for (const m of await parseWebhook(req.body)) {
      const tenant = get('SELECT id FROM tenants WHERE whatsapp_phone_number_id=?', m.phoneNumberId);
      if (!tenant) { console.warn('[whatsapp] número sem empresa vinculada', m.phoneNumberId); continue; }
      await handleIncoming({ tenantId: tenant.id, phone: m.from, name: m.name, channel: 'whatsapp', type: m.type, text: m.text, audio: m.audio, image: m.image });
    }
  } catch (e) { console.error('[whatsapp webhook]', e); }
});

export default r;
export { parse };
