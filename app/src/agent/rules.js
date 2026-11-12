// Agente determinístico (sem LLM). Garante que o sistema funcione e seja testável sem chave de API,
// e serve de fallback se a IA estiver indisponível. Cobre o fluxo completo do vídeo.
import { get, all } from '../db.js';
import { makeTools, optionLabel } from './tools.js';
import { addMessage, getState, setState } from '../services/conversations.js';
import { clientUpcoming } from '../services/scheduling.js';
import { fmtRelativo, minutes, timeOf, weekday, nowLocal, addDays, dateOf } from '../services/time.js';
import { termsFor } from '../services/presets.js';

const norm = (s) => String(s || '').toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '');
const has = (t, ...words) => words.some((w) => t.includes(norm(w)));
const first = (name) => (name || '').split(' ')[0];

const EMERGENCIA = ['dor no peito', 'falta de ar', 'nao consigo respirar', 'desmaiei', 'desmaio', 'sangramento', 'sangrando muito', 'quero morrer', 'me matar', 'suicid', 'avc', 'infarto', 'convulsao'];
const PARTES = ['lombar', 'coluna', 'joelho', 'ombro', 'pescoco', 'cervical', 'tornozelo', 'quadril', 'punho', 'costas', 'dente', 'gengiva', 'pele', 'cabeca'];
const DIAS = { dom: 0, seg: 1, ter: 2, qua: 3, qui: 4, sex: 5, sab: 6, domingo: 0, segunda: 1, terca: 2, quarta: 3, quinta: 4, sexta: 5, sabado: 6 };

export async function runRules(ctx, { text = '', isImage = false } = {}) {
  const { tenant, client, conv } = ctx;
  const tools = makeTools(ctx);
  const t = norm(text);
  const st = getState(conv);
  const terms = termsFor(tenant);
  const say = (content) => addMessage(conv, { sender: 'agente', content });
  const nome = first(client.name);

  // 0) Emergência
  if (has(t, ...EMERGENCIA)) {
    say('Isso pode ser uma emergência. Por favor, procure agora o pronto-socorro mais próximo ou ligue 192 (SAMU). Se estiver pensando em se machucar, ligue 188 (CVV, 24h). Já avisei nossa equipe.');
    return tools.transferir_para_humano({ motivo: 'Possível emergência: ' + text.slice(0, 120) });
  }
  if (has(t, 'atendente', 'humano', 'falar com alguem', 'falar com uma pessoa', 'recepcao')) {
    say('Claro! Vou chamar alguém da equipe para continuar com você. 🙂');
    return tools.transferir_para_humano({ motivo: 'Cliente pediu atendimento humano' });
  }

  // 1) Respostas a mensagens proativas (lembrete / recuperação de falta / confirmação de cancelamento)
  if (st.pending) {
    const p = st.pending;
    const yes = /^(1|sim|s|confirm|pode|quero|ok|claro|beleza|isso)/.test(t);
    const no = /^(2|nao|n\b|remarc|outro|outra)/.test(t);
    if (p.kind === 'reminder' && yes) { tools.confirmar_agendamento({ agendamento_id: p.appointment_id }); return say(`Presença confirmada! Te esperamos ${p.when}. 💚`); }
    if ((p.kind === 'reminder' && no) || (p.kind === 'recovery' && no)) return offerReschedule(p.appointment_id);
    if (p.kind === 'recovery' && yes && p.slot) {
      const r = tools.remarcar_agendamento({ agendamento_id: p.appointment_id, inicio: p.slot.start });
      return say(`Prontinho! Remarcado para ${r.quando}. Até lá! 💪`);
    }
    if (p.kind === 'cancel' && yes) { tools.cancelar_agendamento({ agendamento_id: p.appointment_id }); return say('Cancelado. Se quiser remarcar depois, é só me chamar por aqui.'); }
    if (p.kind === 'cancel' && no) { setState(conv, { pending: null }); return say('Combinado, mantive seu horário.'); }
  }

  // 2) Escolha de horário entre opções oferecidas
  if (st.offered?.length && (st.stage === 'escolhendo_horario' || st.stage === 'remarcando')) {
    const pick = matchOption(t, st.offered);
    if (pick) {
      if (st.stage === 'remarcando') {
        const r = tools.remarcar_agendamento({ agendamento_id: st.reschedule_id, inicio: pick.start, profissional_id: pick.professional_id });
        setState(conv, { stage: null, offered: null, reschedule_id: null });
        return say(`Feito! Seu horário agora é ${r.quando} com ${pick.professional}. ✅`);
      }
      const r = tools.agendar({ servico_id: st.service_id, profissional_id: pick.professional_id, inicio: pick.start, reservar_pacote: true });
      const extra = r.pacote ? ` Já deixei reservadas as próximas ${r.pacote.sessoes.length} ${terms.sessoes} no mesmo horário.` : '';
      say(`${capital(r.quando)} com ${r.profissional} — confirmado!${extra} Venha com roupa confortável. 😉`);
      return tools.enviar_localizacao();
    }
    if (has(t, 'outro', 'outra', 'nenhum', 'nao posso', 'mais tarde', 'mais cedo', 'manha', 'tarde', 'noite', 'amanha')) {
      const periodo = has(t, 'manha', 'mais cedo') ? 'manha' : has(t, 'noite', 'mais tarde') ? 'noite' : has(t, 'tarde') ? 'tarde' : undefined;
      const dia = Object.keys(DIAS).find((d) => new RegExp(`\\b${d}`).test(t));
      return tools.oferecer_horarios({ servico_id: st.service_id, periodo, data: dia ? nextWeekday(DIAS[dia]) : undefined, mensagem: 'Sem problemas! Veja estas outras opções:' });
    }
  }

  // 3) Aguardando documento (foto)
  if (st.stage === 'aguardando_documento') {
    if (isImage) {
      tools.registrar_documento({ tipo: st.document_label || 'documento', resumo: 'Imagem recebida pelo WhatsApp' });
      return offer(st.service_id, `Recebi, obrigado! Agora deixa eu ver a agenda dos nossos ${terms.profissionais}...`);
    }
    if (has(t, 'nao tenho', 'sem pedido', 'nao tem', 'depois', 'levo no dia', 'nao possuo')) {
      setState(conv, { has_document: false });
      return offer(st.service_id, 'Sem problema, pode trazer no dia. Vamos ver os horários:');
    }
  }
  if (isImage) {
    tools.registrar_documento({ tipo: 'imagem', resumo: 'Imagem recebida' });
    if (!st.service_id) return say('Recebi a imagem! Me conta: o que você gostaria de agendar?');
    return offer(st.service_id, 'Recebi, obrigado!');
  }

  // 4) Intenções gerais
  if (has(t, 'cancelar', 'desmarcar')) {
    const up = clientUpcoming(tenant.id, client.id);
    if (!up.length) return say('Não encontrei agendamentos futuros no seu nome.');
    const a = up[0];
    setState(conv, { pending: { kind: 'cancel', appointment_id: a.id } });
    return addMessage(conv, { sender: 'agente', type: 'options', content: `Quer cancelar ${a.service_name} ${fmtRelativo(a.start)} com ${a.professional_name}?`, meta: { options: [{ id: 1, label: 'Sim, cancelar' }, { id: 2, label: 'Não, manter' }] } });
  }
  if (has(t, 'remarcar', 'reagendar', 'trocar o horario', 'mudar o horario', 'mudar meu horario')) {
    const up = clientUpcoming(tenant.id, client.id);
    if (!up.length) return say('Não encontrei agendamentos futuros. Quer marcar um novo horário?');
    return offerReschedule(up[0].id);
  }
  if (has(t, 'meus agendamentos', 'meus horarios', 'quando e minha', 'qual meu horario', 'tenho horario', 'minha consulta', 'minha sessao', 'proxima sessao')) {
    const up = clientUpcoming(tenant.id, client.id);
    if (!up.length) return say('Você não tem agendamentos futuros. Quer marcar?');
    return say('Seus próximos horários:\n' + up.slice(0, 6).map((a) => `• ${a.service_name}${a.session_number ? ` (${terms.sessao} ${a.session_number})` : ''} — ${fmtRelativo(a.start)} com ${a.professional_name}`).join('\n'));
  }
  if (has(t, 'endereco', 'onde fica', 'localizacao', 'como chegar', 'onde voces ficam')) {
    say(`Ficamos em ${tenant.address}${tenant.city ? ' — ' + tenant.city : ''}.`);
    return tools.enviar_localizacao();
  }
  if (has(t, 'preco', 'valor', 'quanto custa', 'quanto e', 'tabela')) {
    const svcs = tools.listar_servicos();
    return say('Nossos valores:\n' + svcs.map((s) => `• ${s.nome}: ${s.preco ? 'R$ ' + s.preco.toFixed(2).replace('.', ',') : 'sem custo'}${s.pacote_sessoes ? ` (pacote ${s.pacote_sessoes}x R$ ${s.preco_sessao_pacote.toFixed(2).replace('.', ',')})` : ''}`).join('\n') + '\n\nQuer agendar?');
  }
  if (has(t, 'horario de funcionamento', 'que horas abre', 'que horas fecha', 'aberto', 'funciona')) {
    const h = JSON.parse(tenant.hours_json || '{}'); const d = ['dom', 'seg', 'ter', 'qua', 'qui', 'sex', 'sáb'];
    return say(`Atendemos ${Object.entries(h).map(([k, [a, b]]) => `${d[k]} ${a}–${b}`).join(', ')}. Mas por aqui eu agendo 24h! Quer marcar?`);
  }
  if (has(t, 'convenio', 'plano de saude', 'unimed', 'amil', 'bradesco saude', 'sulamerica')) {
    say('Sobre convênios, vou confirmar com a equipe e já te retornam por aqui.');
    return tools.transferir_para_humano({ motivo: 'Dúvida sobre convênio' });
  }

  // 5) Escolha de serviço (lista enviada antes)
  if (st.stage === 'escolhendo_servico' && st.service_options) {
    const n = Number((t.match(/\b(\d)\b/) || [])[1]);
    const svc = st.service_options.find((s) => s.id === n) || st.service_options.find((s) => t.includes(norm(s.label).split(' ')[0]));
    if (svc) return startService(svc.service_id, text);
  }

  // 6) Detecção de serviço por palavras-chave
  const svc = detectService(tenant.id, t);
  if (svc) return startService(svc.id, text);

  if (has(t, 'agendar', 'marcar', 'consulta', 'horario', 'agenda', 'vaga', 'atendimento', 'comecar', 'quero')) {
    const services = all('SELECT * FROM services WHERE tenant_id=? AND active=1 ORDER BY is_entry DESC, id', tenant.id);
    if (services.length === 1) return startService(services[0].id, text);
    const opts = services.slice(0, 6).map((s, i) => ({ id: i + 1, label: s.name, service_id: s.id }));
    setState(conv, { stage: 'escolhendo_servico', service_options: opts });
    return addMessage(conv, { sender: 'agente', type: 'options', content: `Claro${nome ? ', ' + nome : ''}! Qual serviço você procura?`, meta: { options: opts } });
  }

  if (has(t, 'obrigad', 'valeu', 'agradeco')) return say('Imagina! Qualquer coisa é só chamar. 💚');

  return say(`Oi${nome ? ', ' + nome : ''}! Sou ${tenant.agent_name}, da ${tenant.name}. Posso agendar, remarcar, confirmar horários e tirar dúvidas — 24h por aqui. Me conta o que você precisa 🙂`);

  // ---------- helpers ----------
  function startService(serviceId, raw) {
    const s = get('SELECT * FROM services WHERE id=?', serviceId);
    const tt = norm(raw);
    const pontos = [];
    const parte = PARTES.find((p) => tt.includes(p));
    if (has(tt, 'dor', 'doendo', 'doi', 'travou', 'travei')) pontos.push(`dor${parte ? ' ' + parte : ''}${has(tt, 'muita dor', 'travou', 'travei', 'forte', 'insuportavel') ? ' aguda' : ''}`);
    else if (parte) pontos.push(parte);
    if (has(tt, 'comecar', 'iniciar', 'agendar', 'marcar', 'quero')) pontos.push(`quer começar ${s.name.toLowerCase()}`);
    tools.registrar_triagem({ queixa: raw.slice(0, 200), pontos, objetivo: s.name, urgencia: has(tt, 'muita dor', 'travou', 'travei', 'urgente') ? 'alta' : 'normal', servico_sugerido_id: s.id });
    setState(conv, { service_id: s.id, document_label: s.document_label });
    const empatia = has(tt, 'dor', 'doendo', 'travou', 'travei', 'machuc') ? `Oi${nome ? ', ' + nome : ''}! Sinto muito pela dor. ` : `Oi${nome ? ', ' + nome : ''}! `;
    if (s.requires_document && !st.has_document) {
      setState(conv, { stage: 'aguardando_documento' });
      return say(`${empatia}Me manda uma foto do ${s.document_label}? Se não tiver, tudo bem, seguimos assim mesmo.`);
    }
    return offer(s.id, `${empatia}Vou ver a agenda pra ${s.name.toLowerCase()}.`);
  }

  function offer(serviceId, intro) {
    if (intro) say(intro);
    const r = tools.oferecer_horarios({ servico_id: serviceId, mensagem: 'Tenho estes horários livres. Qual fica melhor pra você?' });
    if (!r.opcoes.length) say('Poxa, não encontrei horários livres nos próximos dias. Vou pedir para a recepção te chamar.');
  }

  function offerReschedule(appointmentId) {
    const a = get('SELECT * FROM appointments WHERE id=?', appointmentId);
    const opts = tools.horarios_para_remarcar({ agendamento_id: appointmentId });
    if (!opts.length) return say('Não achei horários livres com o mesmo profissional. Vou pedir para a recepção te ajudar.');
    const offered = opts.map((o, i) => ({ option: i + 1, start: o.inicio, professional_id: a.professional_id, professional: get('SELECT name FROM professionals WHERE id=?', a.professional_id).name }));
    setState(conv, { stage: 'remarcando', reschedule_id: appointmentId, offered, pending: null, service_id: a.service_id });
    return addMessage(conv, { sender: 'agente', type: 'options', content: 'Sem problemas! Tenho estes horários para remarcar:', meta: { options: offered.map((o) => ({ id: o.option, label: optionLabel(o), start: o.start, professional_id: o.professional_id })) } });
  }
}

function capital(s) { return s.charAt(0).toUpperCase() + s.slice(1); }

function detectService(tenantId, t) {
  let best = null; let score = 0;
  for (const s of all('SELECT * FROM services WHERE tenant_id=? AND active=1', tenantId)) {
    const kws = [s.name, ...String(s.keywords || '').split(',')].map((k) => norm(k.trim())).filter(Boolean);
    const sc = kws.reduce((n, k) => n + (t.includes(k) ? k.length : 0), 0) + (s.is_entry ? 0.5 : 0);
    if (sc > score && sc >= 3) { score = sc; best = s; }
  }
  return best;
}

export function matchOption(t, offered) {
  const num = t.match(/^\s*(?:opcao\s*)?(\d)\s*$/) || t.match(/\bopcao\s*(\d)/) || t.match(/^(\d)\b/);
  if (num) { const o = offered.find((x) => x.option === Number(num[1])); if (o) return o; }
  const ord = t.match(/\b(primeir|segund|terceir|quart)[oa]?\b/);
  const ordIdx = ord ? { primeir: 0, segund: 1, terceir: 2, quart: 3 }[ord[1]] : -1;
  if (ord && (/opcao|horario|op\b/.test(t) || t.trim().split(/\s+/).length <= 2) && offered[ordIdx] && !(ord[1] === 'segund' && offered.some((o) => weekday(o.start) === 1) && /\d/.test(t))) return offered[ordIdx];
  const hm = t.match(/(\d{1,2})\s*(?:h|:)\s*(\d{2})?/);
  const dia = Object.keys(DIAS).find((d) => new RegExp(`\\b${d}`).test(t));
  const cands = offered.filter((o) => {
    if (hm) { const m = Number(hm[1]) * 60 + Number(hm[2] || 0); if (minutes(timeOf(o.start)) !== m) return false; }
    if (dia !== undefined && weekday(o.start) !== DIAS[dia]) return false;
    return hm || dia !== undefined;
  });
  if (cands.length) return cands[0];
  const prof = offered.find((o) => t.includes(norm(o.professional).replace(/^(dra?\.?\s*)/, '')));
  if (prof) return prof;
  if (has(t, 'primeir', 'cedo', 'manha')) return offered[0];
  if (has(t, 'segund') && offered[1] && dia === undefined) return offered[1];
  if (has(t, 'ultim', 'noite', 'tarde')) return offered[offered.length - 1];
  return null;
}

function nextWeekday(wd) {
  let d = dateOf(nowLocal());
  for (let i = 0; i < 8; i++) { d = addDays(d, 1); if (weekday(d) === wd) return d; }
  return undefined;
}
