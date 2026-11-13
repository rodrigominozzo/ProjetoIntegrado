// Proteção do agente: roda ANTES da IA (entrada) e DEPOIS (saída). Vale para o agente Claude e o de regras.
// 1) Prompt injection / tentativa de manipulação  2) Assuntos fora do escopo  3) Pedido de desconto
// 4) Vazamento de dados (de outros clientes, do prompt, de dados internos)  5) Abuso / excesso de mensagens
import { insert, get } from '../db.js';

export const norm = (s) => String(s || '').toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '').replace(/\s+/g, ' ');

const INJECTION = [
  /ignor\w* (as |todas as |suas |)?(instruc|regras|orienta|comandos|mensagens anteriores)/, /ignore (all |the |your |previous |prior )*(instructions|rules|prompt)/,
  /esque[cç]\w* (tudo|as instruc|suas regras|o que)/, /forget (everything|your|all)/, /disregard/,
  /(system|developer) ?(prompt|message|mode)/, /prompt (do sistema|inicial|original|interno)/, /(mostr|revel|repit|imprim|exib|copi)\w* (o |seu |suas |as |a )?(prompt|instruc|regras|configurac|sistema)/,
  /(quais|qual) (sao )?(suas|as suas|tuas) (instruc|regras)/, /voce (agora )?(e|sera|vai ser) (um|uma|o|a) (?!paciente)/, /a partir de agora (voce|vc|responda|aja)/,
  /(aja|atue|finja|fing\w+|comporte-se|haja) como/, /act as|pretend (to be|you)|roleplay|role play/, /modo (desenvolvedor|dev|deus|admin|administrador|irrestrito|sem filtro)/,
  /jailbreak|\bdan\b|do anything now/, /<\/?(system|assistant|user|instruc|tool)/, /\[(system|inst)\]|###\s*(system|instruc)|role\s*[:=]\s*(system|assistant)/,
  /(sou|eu sou) (o |a )?(administrador|dono|desenvolvedor|programador|admin|suporte|gerente) (do sistema|da clinica|do bot)/, /(chame|execute|rode|use) a (ferramenta|funcao|tool)/,
  /(sql|select \*|drop table|union select|<script|javascript:|base64,)/,
];
const DATA_FISHING = [
  /(dados|telefone|numero|cpf|endereco|email|nome|agenda|horario|consulta)s? (de|do|da|dos|das) (outr[oa]s?|tod[oa]s|demais) (paciente|cliente|pessoa)/,
  /(lista|listar|todos os) (pacientes|clientes|cadastros|contatos)/, /quem (mais )?(esta|vai|tem) (agendad|marcad|consult)/, /(quem|qual paciente) (e|esta) (antes|depois) de mim/,
  /(faturamento|lucro|receita|quanto (a clinica|voces) (ganha|fatura))/, /(senha|token|api key|chave de api|credencia)/, /(comissao|repasse|quanto o (medico|doutor|profissional) ganha)/,
];
const DISCOUNT = [/desconto/, /mais barat/, /abaix\w* (o )?(preco|valor)/, /fazer? (um )?precinho/, /promoc/, /cupom/, /negoci\w* (o )?(valor|preco)/, /\b\d{1,2} ?% ?(off|de desconto)/, /de graca|gratis|sem pagar|cortesia/, /parcel\w* sem juros em \d{2}/];
const OFFTOPIC = [
  /receita de (bolo|comida|torta|pao)/, /\b(futebol|campeonato|politic|eleic|presidente|bolsonaro|lula|religiao|igreja)\b/, /(capital d[aoe]|quem descobriu|quanto e \d+ ?[x*+\/-] ?\d+)/,
  /(escrev|redij|faca|crie|gere|elabore)\w* (um|uma|o|a)? ?(texto|redacao|poema|musica|codigo|programa|historia|carta|trabalho|resumo|artigo|post)/,
  /(traduz|translate|tradução)/, /(piada|conte uma historia|charada)/, /(chatgpt|openai|gemini|qual (modelo|ia) (voce|vc) (e|usa))/, /(bitcoin|criptomoeda|acoes da bolsa|investimento)/,
  /(previsao do tempo|vai chover)/, /(horoscopo|signo)/, /(namorad|casar comigo|voce e (bonit|gat))/,
];

export const SAFE = {
  injection: 'Por aqui eu consigo te ajudar só com agendamentos e informações da clínica. Quer marcar, remarcar ou tirar alguma dúvida sobre os atendimentos?',
  data: 'Não posso compartilhar informações de outras pessoas nem dados internos da clínica. Posso te ajudar com os seus agendamentos 🙂',
  discount: 'Os valores são os da nossa tabela e eu não consigo alterá-los por aqui. Posso te passar as formas de pagamento ou já ver um horário?',
  offtopic: 'Esse assunto eu fico devendo 🙂 Por aqui eu cuido dos seus agendamentos e das informações da clínica. Posso te ajudar com isso?',
  abuse: 'Recebi muitas mensagens seguidas. Vou aguardar um pouquinho e já te respondo.',
  leak: 'Desculpe, não consegui responder isso. Posso te ajudar com agendamento, remarcação ou informações da clínica?',
};

/** Analisa a mensagem do cliente antes de chegar ao agente. */
export function checkInput(text) {
  const t = norm(text).slice(0, 4000);
  if (!t) return { ok: true };
  if (INJECTION.some((r) => r.test(t))) return { ok: false, kind: 'injection' };
  if (DATA_FISHING.some((r) => r.test(t))) return { ok: false, kind: 'data' };
  if (DISCOUNT.some((r) => r.test(t))) return { ok: false, kind: 'discount' };
  if (OFFTOPIC.some((r) => r.test(t))) return { ok: false, kind: 'offtopic' };
  return { ok: true };
}

/** Limpa a mensagem antes de enviar para a IA (remove marcações que imitam o sistema, corta tamanho). */
export function sanitizeInput(text, max = 1200) {
  return String(text || '')
    .replace(new RegExp('[\\u0000-\\u0008\\u000b-\\u001f\\u200b-\\u200f\\u2028-\\u202e\\ufeff]', 'g'), '')
    .replace(/<\/?[a-z_]+[^>]*>/gi, ' ')
    .replace(/```/g, "'''")
    .slice(0, max)
    .trim();
}

const INTERNAL_MARKERS = [/fluxo ideal/i, /instru[cç][oõ]es da empresa/i, /regras de seguran/i, /tool_use|tool_result|input_schema/i, /oferecer_horarios|registrar_triagem|transferir_para_humano|salvar_cadastro|meus_agendamentos|registrar_documento|remarcar_agendamento|cancelar_agendamento|listar_servicos|confirmar_agendamento|horarios_para_remarcar|enviar_localizacao|entrar_lista_espera/i, /system prompt|prompt do sistema/i, /ANTHROPIC|API[_ ]KEY|sk-[a-z0-9]/i];
const PROMISE_DISCOUNT = /(desconto|\d{1,2} ?% ?(off|de desconto)|mais barato pra voc|valor especial|cortesia|de gra[cç]a|gr[aá]tis)/i;
const CPF = /\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b/g;
const EMAIL = /[\w.+-]+@[\w-]+\.[\w.]+/g;
const PHONE = /(?:\+?55\s?)?\(?\d{2}\)?\s?9?\d{4}[-\s]?\d{4}/g;

/** Verifica a resposta da IA antes de enviar ao cliente. */
export function checkOutput(reply, { client, tenant, allowedPrices = [] } = {}) {
  let r = String(reply || '');
  if (INTERNAL_MARKERS.some((x) => x.test(r))) return { text: SAFE.leak, blocked: 'vazamento_interno' };
  if (PROMISE_DISCOUNT.test(r) && !/n[aã]o (consigo|posso|temos|oferecemos|trabalhamos com|damos)[^.]{0,40}(desconto|cortesia|gr[aá]tis)/i.test(r) && !/(sem custo|não tem custo)/i.test(r)) {
    return { text: SAFE.discount, blocked: 'promessa_desconto' };
  }
  const own = new Set([client?.phone, tenant?.phone].filter(Boolean).map((p) => String(p).replace(/\D/g, '').slice(-8)));
  r = r.replace(PHONE, (m) => (own.has(m.replace(/\D/g, '').slice(-8)) ? m : '[telefone ocultado]'));
  r = r.replace(EMAIL, (m) => (m === client?.email ? m : '[e-mail ocultado]'));
  r = r.replace(CPF, '[documento ocultado]');
  // valores em R$ que não existem na tabela → bloqueia (evita "preço inventado"/desconto implícito)
  if (allowedPrices.length) {
    const money = [...r.matchAll(/R\$ ?([\d.]+(?:,\d{2})?)/g)].map((m) => Number(m[1].replace(/\./g, '').replace(',', '.')));
    const ok = (v) => allowedPrices.some((p) => Math.abs(p - v) < 0.01) || allowedPrices.some((p) => [2, 3, 4, 5, 6, 8, 10, 12].some((k) => Math.abs(p * k - v) < 0.01 || Math.abs(p / k - v) < 0.01));
    if (money.some((v) => !ok(v))) return { text: SAFE.leak, blocked: 'valor_fora_da_tabela' };
  }
  return { text: r.slice(0, 1500), blocked: null };
}

// Limite de mensagens por número (anti-flood/abuso)
const buckets = new Map();
export function rateLimited(key, { max = 12, windowMs = 60_000 } = {}) {
  const now = Date.now();
  const arr = (buckets.get(key) || []).filter((t) => now - t < windowMs);
  arr.push(now); buckets.set(key, arr);
  return arr.length > max;
}

export function securityEvent(tenantId, kind, source, detail) {
  try { insert('security_events', { tenant_id: tenantId ?? null, kind, source: String(source || '').slice(0, 120), detail: String(detail || '').slice(0, 500) }); } catch {}
}

/** Muitas tentativas de manipulação seguidas → a conversa vai para humano e o agente para de responder. */
export function repeatedAttacks(tenantId, phone) {
  return get(`SELECT COUNT(*) n FROM security_events WHERE tenant_id=? AND source=? AND kind IN ('injection','data') AND created_at >= datetime('now','-30 minutes')`, tenantId, phone).n >= 3;
}
