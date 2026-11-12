import { get, all, insert, update, run, parse } from '../db.js';
import { bus } from './bus.js';
import { sendWhatsApp } from '../channels/whatsapp.js';

export function normalizePhone(p) { return String(p || '').replace(/\D/g, ''); }

export function upsertClient(tenantId, phone, name) {
  phone = normalizePhone(phone);
  let c = get('SELECT * FROM clients WHERE tenant_id=? AND phone=?', tenantId, phone);
  if (!c) {
    const id = insert('clients', { tenant_id: tenantId, phone, name: name || null });
    c = get('SELECT * FROM clients WHERE id=?', id);
  } else if (name && !c.name) { update('clients', c.id, { name }); c.name = name; }
  return c;
}

export function getConversation(tenantId, clientId, channel = 'simulador') {
  let conv = get('SELECT * FROM conversations WHERE tenant_id=? AND client_id=? ORDER BY id DESC LIMIT 1', tenantId, clientId);
  if (!conv) {
    const id = insert('conversations', { tenant_id: tenantId, client_id: clientId, channel });
    conv = get('SELECT * FROM conversations WHERE id=?', id);
  }
  return conv;
}

export function addMessage(conv, { sender, type = 'text', content = '', meta = null }) {
  const id = insert('messages', { conversation_id: conv.id, sender, type, content, meta_json: meta ? JSON.stringify(meta) : null });
  run(`UPDATE conversations SET last_message_at=datetime('now'), unread = unread + ? WHERE id=?`, sender === 'cliente' ? 1 : 0, conv.id);
  const msg = get('SELECT * FROM messages WHERE id=?', id);
  const payload = { tenantId: conv.tenant_id, clientId: conv.client_id, conversationId: conv.id, message: { ...msg, meta: parse(msg.meta_json, null) } };
  bus.emit('message', payload);
  // Saída real pelo WhatsApp quando a conversa veio de lá
  if (conv.channel === 'whatsapp' && sender !== 'cliente' && type !== 'note') {
    const client = get('SELECT phone FROM clients WHERE id=?', conv.client_id);
    sendWhatsApp(conv.tenant_id, client.phone, { type, content, meta }).catch((e) => console.error('[whatsapp] envio falhou:', e.message));
  }
  return payload.message;
}

export function history(convId, limit = 40) {
  return all('SELECT * FROM (SELECT * FROM messages WHERE conversation_id=? ORDER BY id DESC LIMIT ?) ORDER BY id', convId, limit)
    .map((m) => ({ ...m, meta: parse(m.meta_json, null) }));
}

export function getState(conv) { return parse(get('SELECT state_json FROM conversations WHERE id=?', conv.id)?.state_json); }
export function setState(conv, patch) {
  const s = { ...getState(conv), ...patch };
  for (const k of Object.keys(s)) if (s[k] === undefined || s[k] === null) delete s[k];
  update('conversations', conv.id, { state_json: JSON.stringify(s) });
  return s;
}

export function logStep(tenantId, conversationId, step, detail, ms) {
  insert('automation_logs', { tenant_id: tenantId, conversation_id: conversationId, step, detail: typeof detail === 'string' ? detail : JSON.stringify(detail), ms: ms ?? null });
}
