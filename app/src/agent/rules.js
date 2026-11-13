// Agente determinístico (sem LLM): funciona sem chave de IA e é o fallback se a IA cair.
// Mesmas ferramentas e proteções do agente Claude. Linguagem: humana, curta e direta.
import { get, all, update } from '../db.js';
import { makeTools, optionLabel, publicCatalog } from './tools.js';
import { addMessage, getState, setState } from '../services/conversations.js';
import { clientUpcoming, withinCancelWindow, findOptions, getAppointment } from '../services/scheduling.js';
import { fmtRelativo, minutes, timeOf, weekday, nowLocal, addDays, dateOf } from '../services/time.js';
import { termsFor } from '../services/presets.js';
import { norm } from './guard.js';

const has = (t, ...words) => words.some((w) => t.includes(norm(w)));
const first = (name) => (name || '').split(' ')[0];
const brl = (v) => (v ? 'R$ ' + Number(v).toFixed(2).replace('.', ',').replace(',00', '') : 'sem custo');
const cap = (s) => s.charAt(0).toUpperCase() + s.slice(1);

const EMERGENCIA = ['dor no peito', 'falta de ar', 'nao consigo respirar', 'desmaiei', 'desmaio', 'sangramento', 'sangrando muito', 'quero morrer', 'me matar', 'suicid', 'avc', 'infarto', 'convulsao', 'convulsionando'];
const DIAS = { dom: 0, seg: 1, ter: 2, qua: 3, qui: 4, sex: 5, sab: 6, domingo: 0, segunda: 1, terca: 2, quarta: 3, quinta: 4, sexta: 5, sabado: 6 };

export async function runRules(ctx, { text = '', isImage = false } = {}) {
  const { tenant, client, conv } = ctx;
  const tools = makeTools(ctx);
  const t = norm(text);
  const st = getState(conv);
  const terms = termsFor(tenant);
  const say = (content) => addMessage(conv, { sender: 'agente', content });
  const buttons = (content, options, patch) => { if (patch) setState(conv, patch); return addMessage(conv, { sender: 'agente', type: 'options', content, meta: { options } }); };
  const nome = first(client.name);
  const oi = nome ? `${nome}, ` : '';
  const yes = /^(1|sim|s|confirm|pode|quero|ok|claro|beleza|isso|bora|perfeito|fechado)\b/.test(t);
  const no = /^(2|nao|n\b|nunca|nenhum|deixa|agora nao)/.test(t);

  // 0) Emergência e pedido de humano
  if (has(t, ...EMERGENCIA)) {
    say('Isso pode ser uma emergência. Procure agora o pronto-socorro mais próximo ou ligue 192 (SAMU). Se estiver pensando em se machucar, ligue 188 (CVV, 24h). Já avisei nossa equipe.');
    return tools.transferir_para_humano({ motivo: 'Possível emergência: ' + text.slice(0, 120) });
  }
  if (has(t, 'atendente', 'humano', 'falar com a equipe', 'falar com alguem', 'falar com uma pessoa', 'pessoa de verdade', 'reclamacao', 'reclamar')) {
    say('Claro! Já chamei alguém da equipe pra continuar com você.');
    return tools.transferir_para_humano({ motivo: 'Paciente pediu atendimento humano' });
  }

  // 1) Respostas a mensagens proativas
  if (st.pending) {
    const p = st.pending;
    if (p.kind === 'reminder' && yes) { tools.confirmar_agendamento({ agendamento_id: p.appointment_id }); return say(`Confirmado! Te esperamos ${p.when}.`); }
    if (p.kind === 'reminder' && (no || has(t, 'remarc', 'outro dia', 'outro horario', 'nao vou poder', 'nao posso'))) return offerReschedule(p.appointment_id);
    if (p.kind === 'cancel' && yes) return doCancel(p.appointment_id);
    if (p.kind === 'cancel' && no) { setState(conv, { pending: null }); return say('Combinado, mantive seu horário.'); }
  }

  // 2) Escolha entre horários oferecidos (agendar, remarcar, encaixe, retomada de tratamento)
  if (st.offered?.length && ['escolhendo_horario', 'remarcando'].includes(st.stage)) {
    const pick = matchOption(t, st.offered);
    if (pick) {
      if (st.stage === 'remarcando') {
        try {
          const r = tools.remarcar_agendamento({ agendamento_id: st.reschedule_id, inicio: pick.start, profissional_id: pick.professional_id });
          return say(`Pronto, remarcado para ${r.quando} com ${r.profissional}. ✅`);
        } catch (e) { return policyOrError(e); }
      }
      try {
        const r = tools.agendar({ servico_id: st.service_id, profissional_id: pick.professional_id, inicio: pick.start, reservar_pacote: !st.treatment_id });
        if (st.treatment_id) attachToTreatment(r.agendamento_id, st.treatment_id);
        const extra = r.pacote ? ` Também deixei reservadas as próximas ${r.pacote.sessoes.length} ${terms.sessoes} no mesmo horário.` : '';
        say(`Fechado: ${r.quando}, com ${r.profissional}.${extra}${r.preparo ? `\nPreparo: ${r.preparo}` : ''}`);
        setState(conv, { treatment_id: null });
        return tools.enviar_localizacao();
      } catch (e) {
        say('Esse horário acabou de ser ocupado. Veja estas outras opções:');
        return tools.oferecer_horarios({ servico_id: st.service_id, mensagem: 'Qual fica melhor?' });
      }
    }
    if (has(t, 'nenhum', 'outro', 'outra', 'nao posso', 'nao da', 'mais tarde', 'mais cedo', 'manha', 'tarde', 'noite', 'amanha', 'semana que vem', 'proxima semana') || no) {
      if (st.waitlist_id && no) { update('waitlist', st.waitlist_id, { status: 'aguardando' }); setState(conv, { stage: null, offered: null, waitlist_id: null }); return say('Sem problema! Continuo de olho e te aviso se abrir outra vaga.'); }
      const periodo = has(t, 'manha', 'mais cedo') ? 'manha' : has(t, 'noite', 'mais tarde') ? 'noite' : has(t, 'tarde') ? 'tarde' : undefined;
      const dia = Object.keys(DIAS).find((d) => new RegExp(`\\b${d}`).test(t));
      let data = dia ? nextWeekday(DIAS[dia]) : has(t, 'amanha') ? addDays(dateOf(nowLocal()), 1) : has(t, 'semana que vem', 'proxima semana') ? nextWeekday(1) : undefined;
      if (!data && !periodo) data = addDays(st.offered[st.offered.length - 1].start.slice(0, 10), 1); // "nenhum desses" → próximos dias
      const opts = findOptions(tenant.id, st.service_id, { date: data, period: periodo, professionalId: st.stage === 'remarcando' ? st.offered[0].professional_id : undefined });
      if (!opts.length) return offerWaitlist(st.service_id);
      return buttons('Veja estas outras opções:', opts.map((o) => ({ id: o.option, label: optionLabel(o), start: o.start, professional_id: o.professional_id })).concat([{ id: opts.length + 1, label: 'Nenhum desses' }]), { offered: opts });
    }
  }
  if (st.stage === 'oferecendo_espera') {
    if (yes) { tools.entrar_lista_espera({ servico_id: st.service_id }); setState(conv, { stage: null }); return say('Feito! Você está na lista de espera e eu te aviso assim que abrir uma vaga.'); }
    if (no) { setState(conv, { stage: null }); return say('Tudo bem. Se precisar, é só me chamar.'); }
  }

  // 3) Documento (foto)
  if (st.stage === 'aguardando_documento') {
    if (isImage) { tools.registrar_documento({ tipo: st.document_label || 'documento', resumo: 'Imagem recebida pelo WhatsApp' }); return offer(st.service_id, 'Recebi, obrigado!'); }
    if (has(t, 'nao tenho', 'sem pedido', 'nao tem', 'depois', 'levo no dia', 'nao possuo', 'esqueci')) return offer(st.service_id, 'Sem problema, você pode trazer no dia.');
  }
  if (isImage) {
    tools.registrar_documento({ tipo: 'imagem', resumo: 'Imagem recebida' });
    return st.service_id ? offer(st.service_id, 'Recebi, obrigado!') : say('Recebi a imagem! Me conta o que você gostaria de agendar.');
  }

  // 4) Escolha de agendamento (cancelar/remarcar quando há mais de um)
  if (st.stage === 'escolhendo_agendamento' && st.appt_choices) {
    const n = Number((t.match(/\b(\d)\b/) || [])[1]);
    const c = st.appt_choices.find((x) => x.id === n);
    if (c) { setState(conv, { stage: null, appt_choices: null }); return st.appt_action === 'cancelar' ? askCancel(c.appointment_id) : offerReschedule(c.appointment_id); }
  }

  // 5) Intenções
  if (st.stage === 'menu' && /^[1-4]$/.test(t.trim())) {
    setState(conv, { stage: null });
    const k = t.trim();
    if (k === '1') return listServices('Qual atendimento você precisa?', all('SELECT * FROM services WHERE tenant_id=? AND active=1 AND online_booking=1 ORDER BY category, is_entry DESC, id', tenant.id));
    if (k === '2') return runRules(ctx, { text: 'meus horarios' });
    if (k === '3') return runRules(ctx, { text: 'valores' });
    return runRules(ctx, { text: 'falar com atendente' });
  }
  if (has(t, 'cancelar', 'desmarcar', 'cancela', 'nao vou mais')) return pickAppointment('cancelar');
  if (has(t, 'remarcar', 'reagendar', 'trocar o horario', 'mudar o horario', 'mudar meu horario', 'trocar o dia', 'mudar o dia', 'adiar')) return pickAppointment('remarcar');
  if (has(t, 'confirmar presenca', 'confirmo', 'vou sim', 'estarei la')) {
    const up = clientUpcoming(tenant.id, client.id)[0];
    if (up) { tools.confirmar_agendamento({ agendamento_id: up.id }); return say(`Confirmado! Te esperamos ${fmtRelativo(up.start)}.`); }
  }
  if (has(t, 'meus agendamentos', 'meus horarios', 'quando e minha', 'qual meu horario', 'tenho horario', 'minha consulta', 'minha sessao', 'proxima sessao', 'tenho consulta', 'que horas e')) {
    const up = clientUpcoming(tenant.id, client.id);
    if (!up.length) return say('Você não tem horários marcados. Quer agendar?');
    return say('Seus próximos horários:\n' + up.slice(0, 6).map((a) => `• ${a.service_name}${a.session_number ? ` (${a.session_number}ª)` : ''} — ${fmtRelativo(a.start)}, ${a.professional_name}`).join('\n'));
  }
  if (has(t, 'endereco', 'onde fica', 'localizacao', 'como chegar', 'onde voces ficam', 'estacionamento')) {
    say(`Ficamos em ${[tenant.address, tenant.city].filter(Boolean).join(' — ')}.`);
    return tools.enviar_localizacao();
  }
  if (has(t, 'convenio', 'plano de saude', 'unimed', 'amil', 'bradesco saude', 'sulamerica', 'hapvida', 'aceita plano')) {
    if (tenant.insurances) return say(`Atendemos: ${tenant.insurances.split(/\n|,/).map((s) => s.trim()).filter(Boolean).join(', ')}. Para outros planos, é particular. Quer agendar?`);
    say('Vou confirmar isso com a equipe e já te respondem por aqui.');
    return tools.transferir_para_humano({ motivo: 'Dúvida sobre convênio' });
  }
  if (has(t, 'forma de pagamento', 'formas de pagamento', 'aceita pix', 'aceita cartao', 'parcel', 'como pago', 'pagamento')) return say(`Aceitamos ${tenant.payment_methods || 'Pix e cartão'}.`);
  if (has(t, 'horario de funcionamento', 'que horas abre', 'que horas fecha', 'aberto', 'funciona', 'atende sabado', 'atende domingo')) {
    const h = JSON.parse(tenant.hours_json || '{}'); const d = ['dom', 'seg', 'ter', 'qua', 'qui', 'sex', 'sáb'];
    return say(`Funcionamos ${Object.entries(h).map(([k, [a, b]]) => `${d[k]} ${a}–${b}`).join(', ')}. Por aqui eu agendo a qualquer hora.`);
  }
  if (has(t, 'preparo', 'jejum', 'como me preparar', 'precisa levar', 'o que levar')) {
    const svc = detectService(tenant.id, t) || (st.service_id && get('SELECT * FROM services WHERE id=?', st.service_id));
    if (svc) return say(svc.preparation ? `Para ${svc.name.toLowerCase()}: ${svc.preparation}` : `${svc.name} não exige preparo especial. Traga um documento com foto.`);
    return say(`Me diz qual ${terms.sessao} ou exame que eu te passo o preparo.`);
  }
  const isPrice = has(t, 'preco', 'valor', 'quanto custa', 'quanto e', 'quanto fica', 'tabela', 'quanto sai');
  const prof = detectProfessional(tenant.id, t);
  const svcDetected = detectService(tenant.id, t, prof?.id);

  if (isPrice) {
    const cat = publicCatalog(tenant.id);
    if (svcDetected) {
      const s = cat.find((x) => x.id === svcDetected.id);
      const per = s.profissionais.filter((p) => p.preco !== s.profissionais[0].preco || p.duracao_min !== s.duracao_min);
      return say(`${s.nome}: ${typeof s.preco === 'object' ? `de ${brl(s.preco.de)} a ${brl(s.preco.ate)}, conforme o ${terms.profissional}` : brl(s.preco)} (${s.duracao_min} min).` +
        (per.length ? '\n' + s.profissionais.map((p) => `• ${p.nome}: ${brl(p.preco)} · ${p.duracao_min} min`).join('\n') : '') +
        (s.pacote ? `\nPacote: ${s.pacote.sessoes} ${terms.sessoes} de ${brl(s.pacote.preco_por_sessao)}.` : '') + '\nQuer agendar?');
    }
    const byCat = {};
    for (const s of cat) (byCat[s.categoria] ||= []).push(`• ${s.nome}: ${typeof s.preco === 'object' ? `${brl(s.preco.de)}–${brl(s.preco.ate)}` : brl(s.preco)}`);
    return say(Object.entries(byCat).map(([c, l]) => `*${c}*\n${l.join('\n')}`).join('\n\n') + '\n\nQual te interessa?');
  }

  // 6) Escolha de serviço em lista enviada
  if (st.stage === 'escolhendo_servico' && st.service_options) {
    const n = Number((t.match(/\b(\d{1,2})\b/) || [])[1]);
    const svc = st.service_options.find((s) => s.id === n) || st.service_options.find((s) => t.includes(norm(s.label).split(' ').slice(0, 2).join(' ')));
    if (svc) return startService(svc.service_id, text);
  }

  // 7) Pedido de serviço/profissional
  if (svcDetected) return startService(svcDetected.id, text, prof?.id);
  if (prof) {
    const ss = all(`SELECT s.* FROM services s JOIN professional_services ps ON ps.service_id=s.id WHERE ps.professional_id=? AND s.active=1 AND s.online_booking=1 ORDER BY s.category='Consultas' DESC, s.is_entry DESC, s.id`, prof.id);
    if (ss.length === 1) return startService(ss[0].id, text, prof.id);
    if (ss.length) return listServices(`Com ${prof.name}, qual atendimento você precisa?`, ss, prof.id);
  }
  if (has(t, 'agendar', 'marcar', 'consulta', 'horario', 'agenda', 'vaga', 'atendimento', 'comecar', 'quero', 'preciso', 'especialista', 'medico', 'doutor', 'exame')) {
    return listServices(`${nome ? 'Claro, ' + nome + '!' : 'Claro!'} Qual atendimento você precisa?`, all('SELECT * FROM services WHERE tenant_id=? AND active=1 AND online_booking=1 ORDER BY category, is_entry DESC, id', tenant.id));
  }
  if (has(t, 'obrigad', 'valeu', 'agradeco', 'show', 'otimo')) return say('Imagina! Qualquer coisa, é só chamar.');
  if (/^(oi|ola|bom dia|boa tarde|boa noite|e ai|opa|hey|alo)\b/.test(t) || !t) {
    return buttons(tenant.welcome_message || `Oi${nome ? ', ' + nome : ''}! Aqui é ${tenant.agent_name}, da ${tenant.name}. Como posso te ajudar?`, quick(), { stage: 'menu' });
  }
  if (st.stage === 'menu') {
    if (/^1\b|agendar/.test(t)) return listServices('Qual atendimento você precisa?', all('SELECT * FROM services WHERE tenant_id=? AND active=1 AND online_booking=1 ORDER BY category, is_entry DESC, id', tenant.id));
  }
  return buttons(`Não entendi muito bem${nome ? ', ' + nome : ''}. Me diz com qual destas opções eu te ajudo:`, quick(), { stage: 'menu' });

  // ---------------- helpers ----------------
  function quick() { return [{ id: 1, label: 'Agendar' }, { id: 2, label: 'Meus horários' }, { id: 3, label: 'Valores' }, { id: 4, label: 'Falar com a equipe' }]; }

  function listServices(msg, services, professionalId) {
    const opts = services.slice(0, 10).map((s, i) => ({ id: i + 1, label: `${s.name}`, service_id: s.id }));
    return buttons(msg, opts, { stage: 'escolhendo_servico', service_options: opts, professional_id: professionalId || null });
  }

  function startService(serviceId, raw, professionalId) {
    let s = get('SELECT * FROM services WHERE id=?', serviceId);
    const tt = norm(raw);
    if (!s.online_booking) {
      const alt = all(`SELECT s.* FROM services s WHERE s.tenant_id=? AND s.category='Consultas' AND s.online_booking=1 AND s.active=1 AND s.id IN
        (SELECT service_id FROM professional_services WHERE professional_id IN (SELECT professional_id FROM professional_services WHERE service_id=?))`, tenant.id, s.id)[0];
      if (!alt) { say(`${s.name} é agendado direto pela equipe. Já pedi para te chamarem.`); return tools.transferir_para_humano({ motivo: `Pedido de ${s.name}` }); }
      say(`${s.name} é feito depois de uma avaliação. Vou te mostrar horários para ${alt.name.toLowerCase()}.`);
      s = alt;
    }
    const pontos = [];
    if (has(tt, 'dor', 'doendo', 'doi', 'travou', 'travei', 'febre', 'mancha', 'coceira')) pontos.push(raw.slice(0, 80));
    pontos.push(`quer ${s.name.toLowerCase()}`);
    tools.registrar_triagem({ queixa: raw.slice(0, 200), pontos, objetivo: s.name, urgencia: has(tt, 'muita dor', 'travou', 'travei', 'urgente', 'febre alta') ? 'alta' : 'normal', servico_sugerido_id: s.id });
    setState(conv, { service_id: s.id, document_label: s.document_label, professional_id: professionalId || st.professional_id || null });
    const empatia = has(tt, 'dor', 'doendo', 'travou', 'travei', 'machuc', 'febre', 'mal') ? `Poxa${nome ? ', ' + nome : ''}, sinto muito. ` : nome ? `Certo, ${nome}! ` : 'Certo! ';
    if (s.requires_document && !st.has_document) {
      setState(conv, { stage: 'aguardando_documento' });
      return say(`${empatia}Para ${s.name.toLowerCase()}, me manda uma foto do ${s.document_label}? Se não tiver, tudo bem.`);
    }
    return offer(s.id, empatia.trim(), professionalId || st.professional_id);
  }

  function offer(serviceId, intro, professionalId) {
    const r = tools.oferecer_horarios({ servico_id: serviceId, profissional_id: professionalId || undefined, mensagem: `${intro ? intro + ' ' : ''}Tenho estes horários. Qual fica melhor?` });
    if (!r.opcoes.length) return offerWaitlist(serviceId);
  }

  function offerWaitlist(serviceId) {
    if (!tenant.waitlist_enabled) return say('Não achei horários livres nos próximos dias. Vou pedir para a equipe te chamar.');
    return buttons('Não encontrei horário livre nesse período. Quer entrar na lista de espera? Te aviso assim que abrir uma vaga.', [{ id: 1, label: 'Sim, me avise' }, { id: 2, label: 'Não, obrigado' }], { stage: 'oferecendo_espera', service_id: serviceId });
  }

  function pickAppointment(action) {
    const up = clientUpcoming(tenant.id, client.id);
    if (!up.length) return say(action === 'cancelar' ? 'Não encontrei horários marcados no seu nome.' : 'Você não tem horários marcados. Quer agendar um?');
    if (up.length === 1 || up[0].treatment_id) return action === 'cancelar' ? askCancel(up[0].id) : offerReschedule(up[0].id);
    const choices = up.slice(0, 5).map((a, i) => ({ id: i + 1, label: `${a.service_name} · ${fmtRelativo(a.start)}`, appointment_id: a.id }));
    return buttons(`Qual horário você quer ${action}?`, choices, { stage: 'escolhendo_agendamento', appt_choices: choices, appt_action: action });
  }

  function askCancel(id) {
    const a = getAppointment(id);
    if (!withinCancelWindow(a)) return lateChange(a);
    return buttons(`Cancelar ${a.service_name.toLowerCase()} ${fmtRelativo(a.start)} com ${a.professional_name}?`, [{ id: 1, label: 'Sim, cancelar' }, { id: 2, label: 'Não, manter' }], { pending: { kind: 'cancel', appointment_id: id } });
  }

  function doCancel(id) {
    try {
      const r = tools.cancelar_agendamento({ agendamento_id: id });
      if (!r.novas_opcoes_enviadas) say('Cancelado. Quando quiser remarcar, é só me chamar.');
    } catch (e) { return policyOrError(e); }
  }

  function offerReschedule(appointmentId) {
    const a = getAppointment(appointmentId);
    if (['pendente', 'confirmado'].includes(a.status) && !withinCancelWindow(a)) return lateChange(a);
    const opts = tools.horarios_para_remarcar({ agendamento_id: appointmentId });
    if (!opts.length) return say('Não achei horários livres agora. Vou pedir para a equipe te ajudar.');
    const offered = opts.map((o, i) => ({ option: i + 1, start: o.inicio, professional_id: o.profissional_id, professional: o.legenda.split(' · ').pop() }));
    return buttons('Sem problema! Tenho estes horários:', offered.map((o) => ({ id: o.option, label: optionLabel(o), start: o.start, professional_id: o.professional_id })).concat([{ id: offered.length + 1, label: 'Nenhum desses' }]),
      { stage: 'remarcando', reschedule_id: appointmentId, offered, pending: null, service_id: a.service_id });
  }

  function lateChange(a) {
    say(`Como faltam menos de ${tenant.cancel_min_hours}h para ${a.service_name.toLowerCase()}, essa alteração é feita pela equipe. Já pedi para te chamarem.`);
    return tools.transferir_para_humano({ motivo: `Alteração em cima da hora: agendamento #${a.id}` });
  }

  function policyOrError(e) {
    if (/política|menos de/.test(e.message)) { say(`Alterações com menos de ${tenant.cancel_min_hours}h de antecedência são feitas pela equipe. Já pedi para te chamarem.`); return tools.transferir_para_humano({ motivo: 'Alteração em cima da hora' }); }
    return say('Não consegui concluir isso agora. Vou pedir para a equipe te ajudar.');
  }

  function attachToTreatment(appointmentId, treatmentId) {
    const n = get(`SELECT COALESCE(MAX(session_number),0)+1 n FROM appointments WHERE treatment_id=? AND status IN ('realizado','confirmado','pendente')`, treatmentId).n;
    update('appointments', appointmentId, { treatment_id: treatmentId, session_number: n });
  }
}

function detectService(tenantId, t, professionalId) {
  let best = null; let score = 0;
  const list = professionalId
    ? all('SELECT s.* FROM services s JOIN professional_services ps ON ps.service_id=s.id WHERE s.tenant_id=? AND s.active=1 AND ps.professional_id=?', tenantId, professionalId)
    : all('SELECT * FROM services WHERE tenant_id=? AND active=1', tenantId);
  for (const s of list) {
    const kws = [s.name, ...String(s.keywords || '').split(',')].map((k) => norm(k.trim())).filter((k) => k.length >= 3);
    const sc = kws.reduce((n, k) => n + (t.includes(k) ? k.length : 0), 0) + (sc0(s));
    if (sc > score && sc >= 4) { score = sc; best = s; }
  }
  return best;
}
const sc0 = (s) => (s.is_entry ? 0.5 : 0) + (s.category === 'Consultas' ? 0.3 : 0);

function detectProfessional(tenantId, t) {
  for (const p of all('SELECT * FROM professionals WHERE tenant_id=? AND active=1', tenantId)) {
    const base = norm(p.name).replace(/^(dra?\.?|doutora?)\s+/, '');
    const parts = base.split(' ').filter((x) => x.length >= 3);
    if (parts.length && (t.includes(base) || (t.match(/\b(dra?\.?|doutora?)\s+(\w+)/) || [])[2] === parts[0])) return p;
    if (norm(p.specialty || '') && t.includes(norm(p.specialty))) continue;
  }
  return null;
}

export function matchOption(t, offered) {
  const num = t.match(/^\s*(?:opcao\s*)?(\d)\s*$/) || t.match(/\bopcao\s*(\d)/) || t.match(/^(\d)\b(?!\s*(h|:|horas))/);
  if (num) { const o = offered.find((x) => x.option === Number(num[1])); if (o) return o; }
  const ord = t.match(/\b(primeir|segund|terceir|quart)[oa]?\b/);
  const ordIdx = ord ? { primeir: 0, segund: 1, terceir: 2, quart: 3 }[ord[1]] : -1;
  if (ord && (/opcao|horario|op\b/.test(t) || t.trim().split(/\s+/).length <= 2) && offered[ordIdx] && !/\d/.test(t)) return offered[ordIdx];
  const hm = t.match(/(\d{1,2})\s*(?:h|:|horas)\s*(\d{2})?/);
  const dia = Object.keys(DIAS).find((d) => new RegExp(`\\b${d}`).test(t));
  if (hm || dia !== undefined) {
    const c = offered.filter((o) => (!hm || minutes(timeOf(o.start)) === Number(hm[1]) * 60 + Number(hm[2] || 0)) && (dia === undefined || weekday(o.start) === DIAS[dia]));
    if (c.length) return c[0];
  }
  const prof = offered.find((o) => { const n = norm(o.professional).replace(/^(dra?\.?\s*)/, ''); return n && t.includes(n.split(' ')[0]); });
  if (prof) return prof;
  if (/^(sim|quero|pode|ok|isso|esse|essa|fechado)\b/.test(t) && offered.length === 1) return offered[0];
  if (/quero sim/.test(t)) return offered[0];
  return null;
}

function nextWeekday(wd) {
  let d = dateOf(nowLocal());
  for (let i = 0; i < 8; i++) { d = addDays(d, 1); if (weekday(d) === wd) return d; }
  return undefined;
}
export { cap };
