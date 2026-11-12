// Pipeline de atendimento: WhatsApp → Transcreve → Agente de IA → Agenda → Responde
import { get, insert } from '../db.js';
import { addMessage, getConversation, upsertClient, logStep, history, setState } from '../services/conversations.js';
import { transcribe } from '../services/transcription.js';
import { runLLM, llmEnabled } from './llm.js';
import { runRules } from './rules.js';
import { bus } from '../services/bus.js';

/**
 * Entrada única para qualquer canal.
 * @param {object} p { tenantId, phone, name, channel, type: text|audio|image, text, audio:{b64,mime}, image:{b64,mime}, transcript }
 */
export async function handleIncoming(p) {
  const t0 = Date.now();
  const tenant = get('SELECT * FROM tenants WHERE id=?', p.tenantId);
  if (!tenant) throw new Error('Empresa não encontrada');
  const client = upsertClient(tenant.id, p.phone, p.name);
  const conv = getConversation(tenant.id, client.id, p.channel || 'simulador');
  logStep(tenant.id, conv.id, 'whatsapp', { tipo: p.type || 'text' }, 0);

  let text = p.text || '';
  if (p.type === 'audio') {
    const t1 = Date.now();
    text = await transcribe(p.audio, p.transcript);
    addMessage(conv, { sender: 'cliente', type: 'audio', content: text, meta: { duration: p.duration || null, audio_b64: p.audio?.b64?.length < 2_000_000 ? p.audio.b64 : null, mime: p.audio?.mime } });
    logStep(tenant.id, conv.id, 'transcreve', { caracteres: text.length }, Date.now() - t1);
  } else if (p.type === 'image') {
    const docId = insert('documents', { tenant_id: tenant.id, client_id: client.id, kind: 'imagem', mime: p.image.mime, data_b64: p.image.b64 });
    addMessage(conv, { sender: 'cliente', type: 'image', content: p.text || '', meta: { document_id: docId } });
  } else {
    addMessage(conv, { sender: 'cliente', content: text });
  }

  const fresh = get('SELECT * FROM conversations WHERE id=?', conv.id);
  if (!tenant.automation_active || fresh.mode === 'humano') {
    bus.emit('conversation', { tenantId: tenant.id, conversationId: conv.id, type: 'needs_human' });
    return { conversationId: conv.id, handled: false };
  }

  bus.emit('typing', { tenantId: tenant.id, conversationId: conv.id, clientId: client.id, typing: true });
  const ctx = { tenant, client, conv: fresh };
  try {
    if (llmEnabled() && process.env.AGENT_MODE !== 'rules') {
      try {
        await runLLM(ctx, { image: p.type === 'image' ? p.image : null });
      } catch (e) {
        console.error('[agente IA] falhou, usando agente de regras:', e.message);
        logStep(tenant.id, conv.id, 'erro_ia', e.message);
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

/** Mensagem proativa (lembrete, recuperação de falta, campanha) */
export function proactive(tenantId, clientId, msg, statePatch) {
  const conv = getConversation(tenantId, clientId);
  const m = addMessage(conv, { sender: 'agente', ...msg });
  if (statePatch) setState(conv, statePatch);
  return m;
}

export const agentMode = () => (llmEnabled() && process.env.AGENT_MODE !== 'rules' ? 'claude' : 'regras');
export { history };
