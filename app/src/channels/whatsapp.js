// Integração WhatsApp Business Cloud API (Meta). Ativa quando WHATSAPP_TOKEN está definido
// e a empresa tem whatsapp_phone_number_id configurado.
// Docs: https://developers.facebook.com/docs/whatsapp/cloud-api
import { get } from '../db.js';
import { fmtRelativo } from '../services/time.js';

const GRAPH = 'https://graph.facebook.com/v21.0';
const token = () => process.env.WHATSAPP_TOKEN;

export const whatsappEnabled = () => Boolean(token());

async function graph(path, body) {
  const r = await fetch(`${GRAPH}/${path}`, {
    method: 'POST', headers: { Authorization: `Bearer ${token()}`, 'Content-Type': 'application/json' }, body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(`Graph API ${r.status}: ${await r.text()}`);
  return r.json();
}

/** Converte a mensagem interna no formato da Cloud API (texto, botões, localização). */
export async function sendWhatsApp(tenantId, to, { type, content, meta }) {
  if (!whatsappEnabled()) return;
  const tenant = get('SELECT * FROM tenants WHERE id=?', tenantId);
  if (!tenant?.whatsapp_phone_number_id) return;
  const base = { messaging_product: 'whatsapp', to };
  let body;
  if (type === 'options' && meta?.options?.length) {
    const opts = meta.options.slice(0, 3); // limite de 3 botões de resposta
    body = { ...base, type: 'interactive', interactive: { type: 'button', body: { text: content }, action: { buttons: opts.map((o, i) => ({ type: 'reply', reply: { id: String(o.id ?? i + 1), title: o.label.slice(0, 20) } })) } } };
  } else if (type === 'location') {
    body = { ...base, type: 'location', location: { latitude: tenant.lat, longitude: tenant.lng, name: tenant.name, address: tenant.address } };
  } else if (type === 'appointment' && meta) {
    body = { ...base, type: 'text', text: { body: `✅ ${meta.service_name}\n📅 ${fmtRelativo(meta.start)}\n👤 ${meta.professional_name}\n📍 ${tenant.name}` } };
  } else {
    body = { ...base, type: 'text', text: { body: content } };
  }
  return graph(`${tenant.whatsapp_phone_number_id}/messages`, body);
}

/** Baixa mídia recebida (áudio/imagem) → { buffer, mime } */
export async function downloadMedia(mediaId) {
  const meta = await (await fetch(`${GRAPH}/${mediaId}`, { headers: { Authorization: `Bearer ${token()}` } })).json();
  const r = await fetch(meta.url, { headers: { Authorization: `Bearer ${token()}` } });
  return { buffer: Buffer.from(await r.arrayBuffer()), mime: meta.mime_type };
}

/** Normaliza o webhook da Meta para o formato interno de entrada. */
export async function parseWebhook(body) {
  const out = [];
  for (const entry of body.entry || []) for (const ch of entry.changes || []) {
    const v = ch.value || {};
    const phoneNumberId = v.metadata?.phone_number_id;
    const name = v.contacts?.[0]?.profile?.name;
    for (const m of v.messages || []) {
      const item = { phoneNumberId, from: m.from, name, type: 'text', text: '' };
      if (m.type === 'text') item.text = m.text.body;
      else if (m.type === 'interactive') item.text = m.interactive.button_reply?.title || m.interactive.list_reply?.title || '';
      else if (m.type === 'button') item.text = m.button.text;
      else if (m.type === 'audio') { item.type = 'audio'; const { buffer, mime } = await downloadMedia(m.audio.id); item.audio = { b64: buffer.toString('base64'), mime }; }
      else if (m.type === 'image') { item.type = 'image'; const { buffer, mime } = await downloadMedia(m.image.id); item.image = { b64: buffer.toString('base64'), mime }; item.text = m.image.caption || ''; }
      out.push(item);
    }
  }
  return out;
}
