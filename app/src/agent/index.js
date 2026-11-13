// Pipeline de atendimento: WhatsApp → Transcreve → Proteção → Agente de IA → Agenda → Responde
import { get, insert, update } from '../db.js';
import { addMessage, getConversation, upsertClient, logStep, history, setState } from '../services/conversations.js';
import { transcribe } from '../services/transcription.js';
import { runLLM, llmEnabled } from './llm.js';
import { runRules } from './rules.js';
import { bus } from '../services/bus.js';
import { checkInput, rateLimited, securityEvent, repeatedAttacks, SAFE } from './guard.js';

/**
 * Entrada única para qualquer canal.
 * @param {object} p { tenantId, phone, name, channel, type: text|audio|image, text, audio:{b64,mime}, image:{b64,mime}, transcript }
 */
export async function handleIncoming(p) {
  const t0 = Date.now();
  const tenant = get('SELECT * FROM tenants WHERE id=?', p.tenantId);
  if (!tenant) throw new Error('Empresa não encontrada');
  const client = upsertClient(tenant.id, p.phone, p.name ? String(p.name).slice(0, 80) : undefined);
  const conv = getConversation(tenant.id, client.id, p.channel || 'simulador');

  // Anti-flood por número
  if (rateLimited(`${tenant.id}:${client.phone}`)) {
    securityEvent(tenant.id, 'flood', client.phone, 'excesso de mensagens');
    return { conversationId: conv.id, handled: false, throttled: true };
  }
  logStep(tenant.id, conv.id, 'whatsapp', { tipo: p.type || 'text' }, 0);

  let text = String(p.text || '').slice(0, 2000);
  if (p.type === 'audio') {
    const t1 = Date.now();
    text = (await transcribe(p.audio, p.transcript)).slice(0, 2000);
    const v = checkInput(text);
    addMessage(conv, { sender: 'cliente', type: 'audio', content: text, meta: { blocked: v.ok ? undefined : v.kind, duration: p.duration || null, audio_b64: p.audio?.b64?.length < 2_000_000 ? p.audio.b64 : null, mime: p.audio?.mime } });
    logStep(tenant.id, conv.id, 'transcreve', { caracteres: text.length }, Date.now() - t1);
  } else if (p.type === 'image') {
    const docId = insert('documents', { tenant_id: tenant.id, client_id: client.id, kind: 'imagem', mime: p.image.mime, data_b64: p.image.b64 });
    const v = checkInput(text);
    addMessage(conv, { sender: 'cliente', type: 'image', content: text, meta: { document_id: docId, blocked: v.ok ? undefined : v.kind } });
  }

  // Proteção: manipulação, pedido de dados de terceiros, desconto, fora do escopo
  const verdict = checkInput(text);
  if (p.type !== 'audio' && p.type !== 'image') addMessage(conv, { sender: 'cliente', content: text, meta: verdict.ok ? null : { blocked: verdict.kind } });
  const fresh = get('SELECT * FROM conversations WHERE id=?', conv.id);

  if (!tenant.automation_active || fresh.mode === 'humano') {
    bus.emit('conversation', { tenantId: tenant.id, conversationId: conv.id, type: 'needs_human' });
    return { conversationId: conv.id, handled: false };
  }

  if (!verdict.ok) {
    securityEvent(tenant.id, verdict.kind, client.phone, text.slice(0, 300));
    logStep(tenant.id, conv.id, 'protecao', { bloqueado: verdict.kind });
    if (['injection', 'data'].includes(verdict.kind) && repeatedAttacks(tenant.id, client.phone)) {
      addMessage(conv, { sender: 'agente', content: 'Vou passar sua conversa para nossa equipe, tudo bem?' });
      update('conversations', conv.id, { mode: 'humano' });
      addMessage(conv, { sender: 'sistema', type: 'note', content: 'Agente pausado: várias tentativas de manipulação/obtenção de dados nesta conversa.' });
      bus.emit('conversation', { tenantId: tenant.id, conversationId: conv.id, type: 'handoff', motivo: 'tentativas de manipulação' });
      return { conversationId: conv.id, handled: true, blocked: verdict.kind };
    }
    if (verdict.kind === 'discount') {
      addMessage(conv, { sender: 'agente', content: `${SAFE.discount.split('.')[0]}. Aceitamos ${tenant.payment_methods || 'Pix e cartão'}. Quer que eu veja um horário?` });
    } else addMessage(conv, { sender: 'agente', content: SAFE[verdict.kind] });
    return { conversationId: conv.id, handled: true, blocked: verdict.kind };
  }

  bus.emit('typing', { tenantId: tenant.id, conversationId: conv.id, clientId: client.id, typing: true });
  const ctx = { tenant, client, conv: fresh };
  try {
    if (llmEnabled() && process.env.AGENT_MODE !== 'rules') {
      try {
        await runLLM(ctx, { image: p.type === 'image' ? p.image : null });
      } catch (e) {
        console.error('[agente IA] falhou, usando agente de regras:', e.message);
        logStep(tenant.id, conv.id, 'erro_ia', String(e.message).slice(0, 200));
        await runRules(ctx, { text, isImage: p.type === 'image' });
      }
    } else {
      await runRules(ctx, { text, isImage: p.type === 'image' });
    }
  } finally {
    bus.emit('typing', { tenantId: tenant.id, conversationId: conv.id, clientId: client.id, typing: false });
  }
  logStep(tenant.id, conv.id, 'responde', { total_ms: Date.now() - t0 }, Date.now() - t0);
  return { conversationId: conv.id, handled: true, ms: Date.now() - t0 };
}

export const agentMode = () => (llmEnabled() && process.env.AGENT_MODE !== 'rules' ? 'claude' : 'regras');
export { history, setState };
