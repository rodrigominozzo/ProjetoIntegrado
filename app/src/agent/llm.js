// Agente com Claude (Anthropic) — tool use em loop manual.
import Anthropic from '@anthropic-ai/sdk';
import { all } from '../db.js';
import { makeTools, TOOL_SCHEMAS, servicesCatalog } from './tools.js';
import { history, logStep, addMessage } from '../services/conversations.js';
import { nowLocal, fmtLongo, fmtHora, fmtRelativo } from '../services/time.js';
import { termsFor } from '../services/presets.js';
import { clientUpcoming } from '../services/scheduling.js';

export const MODEL = process.env.ANTHROPIC_MODEL || 'claude-opus-5-5';
let client;
export const llmEnabled = () => Boolean(process.env.ANTHROPIC_API_KEY || process.env.ANTHROPIC_AUTH_TOKEN);

function systemPrompt({ tenant, client: c }) {
  const t = termsFor(tenant);
  const hours = JSON.parse(tenant.hours_json || '{}');
  const dias = ['dom', 'seg', 'ter', 'qua', 'qui', 'sex', 'sáb'];
  const horario = Object.entries(hours).map(([d, [a, b]]) => `${dias[d]} ${a}–${b}`).join(', ');
  const servicos = servicesCatalog(tenant.id).map((s) =>
    `- [id ${s.id}] ${s.name} — ${s.duration_min} min — R$ ${s.price.toFixed(2)}${s.is_entry ? ' (porta de entrada)' : ''}` +
    `${s.package_sessions ? ` → pacote de ${s.package_sessions} ${t.sessoes} a R$ ${s.package_session_price.toFixed(2)} cada, ${s.sessions_per_week}x/semana` : ''}` +
    `${s.requires_document ? ` — pedir foto do ${s.document_label}` : ''} — palavras-chave: ${s.keywords}` +
    ` — ${t.profissionais}: ${s.professionals.map((p) => p.name).join(', ')}`).join('\n');
  const now = nowLocal();
  const prox = clientUpcoming(tenant.id, c.id).slice(0, 5).map((a) => `- #${a.id} ${a.service_name} ${fmtRelativo(a.start)} com ${a.professional_name} (${a.status})`).join('\n') || 'nenhum';

  return `Você é ${tenant.agent_name}, atendente virtual de "${tenant.name}" (${tenant.segment}) no WhatsApp. Tom: ${tenant.agent_tone}.
Agora são ${fmtLongo(now)}, ${fmtHora(now)} (horário local). Você atende 24 horas, inclusive fora do expediente (${horario}).
Endereço: ${tenant.address}${tenant.city ? ', ' + tenant.city : ''}.

Chame o cliente de ${t.cliente}. Profissionais são "${t.profissionais}". Atendimentos são "${t.sessoes}".

Serviços:
${servicos}

${t.cliente[0].toUpperCase() + t.cliente.slice(1)} atual: ${c.name || 'nome ainda não informado'} (tel. ${c.phone}).
Próximos agendamentos dele:
${prox}

Fluxo ideal (rápido, em poucas mensagens):
1. Entenda a necessidade (áudios chegam já transcritos). Demonstre empatia breve e chame registrar_triagem.
2. Se o serviço exige documento e ele ainda não enviou, peça a foto (ex.: ${t.documento}). Se ele não tiver, siga mesmo assim e avise que pode trazer no dia.
3. Use oferecer_horarios (o sistema envia os botões). Não invente horários.
4. Quando ele escolher, chame agendar com o horário exato retornado. Se houver pacote, as próximas ${t.sessoes} já são reservadas — informe isso.
5. Confirme em uma frase curta e chame enviar_localizacao.
Também: remarcar, cancelar (só quando pedido), confirmar presença, informar preços e endereço.
Se o nome não for conhecido, pergunte de forma natural e use salvar_cadastro.

Regras: mensagens curtas, estilo WhatsApp, português do Brasil, no máximo 1 emoji. Nunca dê diagnóstico nem prescreva tratamento.
Sinais de emergência (dor no peito, falta de ar, sangramento intenso, ideação suicida, perda de consciência): oriente a procurar o SAMU (192)/pronto-socorro (ou CVV 188) e chame transferir_para_humano.
Se não souber algo (convênios, valores não listados), diga que vai verificar e chame transferir_para_humano.
${tenant.agent_instructions ? '\nInstruções da empresa:\n' + tenant.agent_instructions : ''}`;
}

function describe(m) {
  if (m.type === 'options') return `${m.content}\n[botões enviados: ${(m.meta?.options || []).map((o) => `(${o.id}) ${o.label} — inicio ${o.start}, profissional_id ${o.professional_id}`).join('; ')}]`;
  if (m.type === 'appointment') return `[cartão: ${m.meta?.service_name} confirmado ${m.meta?.start} com ${m.meta?.professional_name}]`;
  if (m.type === 'package') return `[${m.meta?.sessions?.length} sessões do pacote reservadas]`;
  if (m.type === 'location') return '[localização enviada]';
  if (m.type === 'audio') return `[áudio transcrito] ${m.content}`;
  if (m.type === 'image') return `[imagem enviada${m.content ? ': ' + m.content : ''}]`;
  if (m.type === 'note') return `[nota do sistema: ${m.content}]`;
  return m.content || '';
}

function buildMessages(conv, image) {
  const msgs = [];
  for (const m of history(conv.id, 30)) {
    const role = m.sender === 'cliente' ? 'user' : 'assistant';
    const text = describe(m);
    if (!text) continue;
    const last = msgs[msgs.length - 1];
    if (last && last.role === role) last.content[0].text += '\n' + text;
    else msgs.push({ role, content: [{ type: 'text', text }] });
  }
  while (msgs.length && msgs[0].role !== 'user') msgs.shift();
  if (image && msgs.length) {
    msgs[msgs.length - 1].content.unshift({ type: 'image', source: { type: 'base64', media_type: image.mime, data: image.b64 } });
  }
  return msgs;
}

export async function runLLM(ctx, { image } = {}) {
  client ||= new Anthropic();
  const tools = makeTools(ctx);
  const messages = buildMessages(ctx.conv, image);
  const system = systemPrompt(ctx);
  for (let step = 0; step < 8; step++) {
    const t0 = Date.now();
    const res = await client.beta.messages.create({
      model: MODEL,
      max_tokens: 4000,
      system,
      tools: TOOL_SCHEMAS,
      messages,
      output_config: { effort: process.env.ANTHROPIC_EFFORT || 'low' },
      betas: ['server-side-fallback-2026-07-01'],
      fallbacks: 'default',
    });
    logStep(ctx.tenant.id, ctx.conv.id, 'agente_ia', { model: MODEL, stop: res.stop_reason, in: res.usage?.input_tokens, out: res.usage?.output_tokens }, Date.now() - t0);
    if (res.stop_reason === 'refusal') {
      addMessage(ctx.conv, { sender: 'agente', content: 'Vou pedir para alguém da equipe te responder, tudo bem?' });
      tools.transferir_para_humano({ motivo: 'Agente recusou a solicitação' });
      return;
    }
    const results = [];
    for (const block of res.content) {
      if (block.type === 'text' && block.text.trim()) addMessage(ctx.conv, { sender: 'agente', content: block.text.trim() });
      if (block.type === 'tool_use') {
        let out; let isError = false;
        try { out = await tools[block.name](block.input || {}); } catch (e) { out = { erro: e.message }; isError = true; }
        logStep(ctx.tenant.id, ctx.conv.id, `tool:${block.name}`, { input: block.input, ok: !isError });
        results.push({ type: 'tool_result', tool_use_id: block.id, content: JSON.stringify(out), is_error: isError });
      }
    }
    if (res.stop_reason !== 'tool_use' && res.stop_reason !== 'pause_turn') return;
    messages.push({ role: 'assistant', content: res.content });
    if (results.length) messages.push({ role: 'user', content: results });
  }
}

export const _test = { systemPrompt, buildMessages, all };
