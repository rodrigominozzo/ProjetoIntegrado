// Ferramentas do agente. Regras de segurança aplicadas AQUI (não dependem do modelo obedecer):
// - só enxergam/alteram dados do próprio cliente da conversa;
// - preço e duração vêm sempre do cadastro (nenhuma ferramenta aceita preço);
// - respeitam a política de cancelamento e as regras de agenda da clínica;
// - não expõem custos, repasses, faturamento ou dados de outros clientes.
import { all, get, update } from '../db.js';
import * as sched from '../services/scheduling.js';
import { addMessage, setState, getState, logStep } from '../services/conversations.js';
import { fmtHora, diaCurto, fmtData, fmtRelativo, fmtLongo, nowLocal } from '../services/time.js';
import { bus } from '../services/bus.js';
import { offerReplacement, fillFromWaitlist, joinWaitlist } from '../services/proactive.js';

export const optionLabel = (o) => `${diaCurto(o.start)[0].toUpperCase() + diaCurto(o.start).slice(1)} ${fmtData(o.start)} · ${fmtHora(o.start)} · ${o.professional}`;

/** Catálogo público (o que o cliente pode saber). Nada de custo/repasse. */
export function publicCatalog(tenantId) {
  return all('SELECT * FROM services WHERE tenant_id=? AND active=1 ORDER BY category, is_entry DESC, name', tenantId).map((s) => {
    const profs = sched.professionalsFor(tenantId, s.id).map((p) => ({ id: p.id, nome: p.name, especialidade: p.specialty, duracao_min: p.ps_duration || s.duration_min, preco: p.ps_price ?? s.price }));
    const prices = [...new Set(profs.map((p) => p.preco).concat(s.price))];
    return {
      id: s.id, categoria: s.category, nome: s.name, descricao: s.description || undefined, duracao_min: s.duration_min,
      preco: prices.length > 1 ? { de: Math.min(...prices), ate: Math.max(...prices) } : s.price,
      modalidade: s.modality, preparo: s.preparation || undefined, retorno_incluso_dias: s.return_days || undefined,
      pacote: s.package_sessions ? { sessoes: s.package_sessions, preco_por_sessao: s.package_session_price, por_semana: s.sessions_per_week } : undefined,
      exige_documento: s.requires_document ? s.document_label : undefined, agendamento_pelo_whatsapp: !!s.online_booking,
      idade: s.min_age || s.max_age ? { min: s.min_age, max: s.max_age } : undefined, profissionais: profs,
    };
  });
}
/** Todos os valores que o agente pode citar (para o filtro de saída). */
export function allowedPrices(tenantId) {
  const v = new Set();
  for (const s of all('SELECT price, package_session_price, package_sessions FROM services WHERE tenant_id=? AND active=1', tenantId)) { v.add(s.price); if (s.package_sessions) { v.add(s.package_session_price); v.add(s.package_session_price * s.package_sessions); } }
  for (const p of all('SELECT ps.price FROM professional_services ps JOIN services s ON s.id=ps.service_id WHERE s.tenant_id=? AND ps.price IS NOT NULL', tenantId)) v.add(p.price);
  return [...v].filter((x) => x != null);
}

export function makeTools(ctx) {
  const { tenant, client, conv } = ctx;
  const say = (m) => addMessage(conv, { sender: 'agente', ...m });
  const own = (id) => {
    const a = get('SELECT * FROM appointments WHERE id=? AND client_id=? AND tenant_id=?', Number(id), client.id, tenant.id);
    if (!a) throw new sched.AppError('Agendamento não encontrado para este paciente');
    return a;
  };
  const policy = (a) => {
    if (!sched.withinCancelWindow(a)) throw new sched.AppError(`Pela política da clínica, alterações com menos de ${tenant.cancel_min_hours}h de antecedência são feitas pela equipe. Use transferir_para_humano.`);
  };
  const serviceOk = (id) => {
    const s = get('SELECT * FROM services WHERE id=? AND tenant_id=? AND active=1', Number(id), tenant.id);
    if (!s) throw new sched.AppError('Serviço não encontrado');
    if (!s.online_booking) throw new sched.AppError('Este serviço só é agendado pela equipe (exige avaliação prévia). Ofereça a consulta de avaliação ou transfira para humano.');
    return s;
  };

  return {
    listar_servicos: () => publicCatalog(tenant.id),

    registrar_triagem({ queixa, pontos = [], objetivo, urgencia = 'normal', servico_sugerido_id }) {
      const triage = { queixa: String(queixa || '').slice(0, 300), pontos: pontos.slice(0, 6).map((p) => String(p).slice(0, 80)), objetivo: String(objetivo || '').slice(0, 120), urgencia, servico_sugerido_id, at: nowLocal() };
      update('conversations', conv.id, { triage_json: JSON.stringify(triage) });
      logStep(tenant.id, conv.id, 'triagem', triage);
      bus.emit('conversation', { tenantId: tenant.id, conversationId: conv.id, type: 'triage' });
      return { ok: true };
    },

    salvar_cadastro({ nome, email, data_nascimento }) {
      const patch = {};
      if (nome) patch.name = String(nome).slice(0, 80);
      if (email && /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) patch.email = String(email).slice(0, 120);
      if (data_nascimento && /^\d{4}-\d{2}-\d{2}$/.test(data_nascimento)) patch.birthdate = data_nascimento;
      update('clients', client.id, patch); Object.assign(client, patch);
      return { ok: true };
    },

    registrar_documento({ tipo, resumo, sessoes_prescritas }) {
      const doc = get('SELECT * FROM documents WHERE client_id=? ORDER BY id DESC LIMIT 1', client.id);
      if (doc) update('documents', doc.id, { kind: String(tipo || doc.kind).slice(0, 60), extracted: JSON.stringify({ resumo: String(resumo || '').slice(0, 400), sessoes_prescritas }) });
      setState(conv, { has_document: true });
      logStep(tenant.id, conv.id, 'documento', { tipo });
      return { ok: true };
    },

    oferecer_horarios({ servico_id, mensagem, data, periodo, profissional_id }) {
      const t0 = Date.now();
      serviceOk(servico_id);
      const opts = sched.findOptions(tenant.id, Number(servico_id), { date: data, period: periodo, professionalId: profissional_id });
      logStep(tenant.id, conv.id, 'agenda', { consulta: 'horários livres', servico_id, encontrados: opts.length }, Date.now() - t0);
      if (!opts.length) return { opcoes: [], aviso: 'Sem horários livres nesse filtro. Ofereça outro período/profissional ou a lista de espera (entrar_lista_espera).' };
      setState(conv, { offered: opts, service_id: Number(servico_id), stage: 'escolhendo_horario' });
      say({ type: 'options', content: String(mensagem || 'Tenho estes horários. Qual fica melhor pra você?').slice(0, 300), meta: { options: opts.map((o) => ({ id: o.option, label: optionLabel(o), start: o.start, professional_id: o.professional_id })) } });
      return { opcoes: opts.map((o) => ({ opcao: o.option, inicio: o.start, profissional_id: o.professional_id, profissional: o.professional, legenda: optionLabel(o) })), enviado_ao_cliente: true };
    },

    agendar({ servico_id, profissional_id, inicio, reservar_pacote = true, observacoes }) {
      const t0 = Date.now();
      serviceOk(servico_id);
      // só aceita horários que foram oferecidos nesta conversa ou que estão livres pelas regras da clínica
      const free = sched.findOptions(tenant.id, Number(servico_id), { date: String(inicio).slice(0, 10), professionalId: profissional_id, count: 200, days: 1 });
      if (!free.find((o) => o.start === inicio)) throw new sched.AppError('Esse horário não está disponível. Ofereça novas opções com oferecer_horarios.');
      const st = getState(conv);
      const appt = sched.book({ tenantId: tenant.id, clientId: client.id, serviceId: Number(servico_id), professionalId: Number(profissional_id), start: inicio, createdBy: 'agente', status: 'confirmado', notes: observacoes ? String(observacoes).slice(0, 300) : null });
      say({ type: 'appointment', content: `${appt.service_name} confirmada`, meta: { id: appt.id, service_name: appt.service_name, start: appt.start, end: appt.end, professional_name: appt.professional_name, status: 'confirmado', place: tenant.name, preparation: appt.preparation } });
      let pacote = null;
      if (reservar_pacote && tenant.auto_book_package) {
        const r = sched.reservePackage({ tenantId: tenant.id, clientId: client.id, entryAppointment: appt });
        if (r) {
          pacote = { sessoes: r.sessions.map((s) => s.start) };
          say({ type: 'package', content: `${r.sessions.length} sessões reservadas`, meta: { treatment_id: r.treatment.id, total: r.treatment.total_sessions, sessions: r.sessions.map((s) => ({ n: s.session_number, start: s.start, professional_name: s.professional_name })) } });
        }
      }
      if (st.waitlist_id) update('waitlist', st.waitlist_id, { status: 'atendido' });
      setState(conv, { stage: 'agendado', offered: null, waitlist_id: null });
      logStep(tenant.id, conv.id, 'agendamento', { appointment_id: appt.id, pacote: pacote?.sessoes?.length || 0 }, Date.now() - t0);
      return { ok: true, agendamento_id: appt.id, quando: fmtLongo(appt.start) + ' às ' + fmtHora(appt.start), profissional: appt.professional_name, valor: appt.price, preparo: appt.preparation || null, pacote };
    },

    enviar_localizacao() {
      say({ type: 'location', content: tenant.address, meta: { name: tenant.name, address: tenant.address, lat: tenant.lat, lng: tenant.lng } });
      return { ok: true };
    },

    meus_agendamentos() {
      return sched.clientUpcoming(tenant.id, client.id).map((a) => ({ id: a.id, servico: a.service_name, inicio: a.start, quando: fmtRelativo(a.start), profissional: a.professional_name, status: a.status, sessao: a.session_number, pode_alterar_sozinho: sched.withinCancelWindow(a) }));
    },

    confirmar_agendamento({ agendamento_id }) {
      const a = own(agendamento_id); sched.setStatus(a.id, 'confirmado'); setState(conv, { pending: null });
      return { ok: true };
    },

    cancelar_agendamento({ agendamento_id, motivo }) {
      const a = own(agendamento_id); policy(a);
      sched.cancel(a.id, { by: 'cliente', reason: motivo ? String(motivo).slice(0, 200) : null });
      setState(conv, { pending: null });
      fillFromWaitlist(a.id); // vaga liberada vai para a lista de espera
      // proativo: já oferece nova data (a mensagem com botões é enviada pelo sistema)
      const opts = tenant.reoffer_cancel ? offerReplacement(a.id, 'cancelamento_cliente') : null;
      return { ok: true, novas_opcoes_enviadas: !!opts?.length };
    },

    horarios_para_remarcar({ agendamento_id }) {
      const a = own(agendamento_id); policy(a);
      return sched.replacementOptions(a, 3).map((o) => ({ inicio: o.start, profissional_id: o.professional_id, legenda: optionLabel(o) }));
    },

    remarcar_agendamento({ agendamento_id, inicio, profissional_id }) {
      const a = own(agendamento_id);
      if (['pendente', 'confirmado'].includes(a.status)) policy(a);
      const n = sched.reschedule(a.id, { start: inicio, professionalId: profissional_id ? Number(profissional_id) : undefined });
      setState(conv, { pending: null, stage: null, offered: null, reschedule_id: null });
      if (a.status !== 'faltou') fillFromWaitlist(a.id);
      say({ type: 'note', content: `Remarcado · ${diaCurto(n.start)} ${fmtData(n.start)} ${fmtHora(n.start)}` });
      return { ok: true, novo_id: n.id, quando: fmtRelativo(n.start), profissional: n.professional_name };
    },

    entrar_lista_espera({ servico_id, profissional_id, periodo }) {
      serviceOk(servico_id);
      joinWaitlist({ tenantId: tenant.id, clientId: client.id, serviceId: Number(servico_id), professionalId: profissional_id, period: periodo });
      logStep(tenant.id, conv.id, 'lista_espera', { servico_id });
      return { ok: true };
    },

    informacoes_clinica() {
      return { nome: tenant.name, endereco: [tenant.address, tenant.city].filter(Boolean).join(' — '), telefone: tenant.phone, horarios: JSON.parse(tenant.hours_json || '{}'), convenios: tenant.insurances || 'não informado', formas_pagamento: tenant.payment_methods, politicas: tenant.policies || null, cancelamento_ate_horas_antes: tenant.cancel_min_hours };
    },

    transferir_para_humano({ motivo }) {
      update('conversations', conv.id, { mode: 'humano' });
      addMessage(conv, { sender: 'sistema', type: 'note', content: `Conversa transferida para a equipe: ${String(motivo || '').slice(0, 200)}` });
      bus.emit('conversation', { tenantId: tenant.id, conversationId: conv.id, type: 'handoff', motivo });
      return { ok: true };
    },
  };
}

// Esquemas (Claude tool use) — strict: o modelo só consegue chamar com os campos previstos
const obj = (properties, required = []) => ({ type: 'object', properties, required, additionalProperties: false });
const S = { type: 'string' }; const I = { type: 'integer' };
export const TOOL_SCHEMAS = [
  { name: 'listar_servicos', description: 'Catálogo: serviços por categoria, duração, preço (pode variar por profissional), preparo, pacote, profissionais.', input_schema: obj({}) },
  { name: 'informacoes_clinica', description: 'Endereço, telefone, horário de funcionamento, convênios, formas de pagamento e políticas.', input_schema: obj({}) },
  { name: 'registrar_triagem', description: 'Registra o que você entendeu do paciente. Chame assim que entender a necessidade.', input_schema: obj({ queixa: S, pontos: { type: 'array', items: S }, objetivo: S, urgencia: { type: 'string', enum: ['baixa', 'normal', 'alta', 'emergencia'] }, servico_sugerido_id: I }, ['queixa']) },
  { name: 'salvar_cadastro', description: 'Salva nome, e-mail ou data de nascimento quando o paciente informar.', input_schema: obj({ nome: S, email: S, data_nascimento: { type: 'string', description: 'YYYY-MM-DD' } }) },
  { name: 'registrar_documento', description: 'Registra a foto/documento recebido (ex.: pedido médico) com um resumo curto.', input_schema: obj({ tipo: S, resumo: S, sessoes_prescritas: I }, ['tipo', 'resumo']) },
  { name: 'oferecer_horarios', description: 'Consulta a agenda e ENVIA botões com horários livres. O texto de "mensagem" vai junto; não repita a lista na resposta.', input_schema: obj({ servico_id: I, mensagem: S, data: { type: 'string', description: 'YYYY-MM-DD' }, periodo: { type: 'string', enum: ['manha', 'tarde', 'noite'] }, profissional_id: I }, ['servico_id']) },
  { name: 'agendar', description: 'Marca o horário escolhido (use exatamente o inicio retornado). Se houver pacote, reserva as próximas sessões. Envia o cartão de confirmação.', input_schema: obj({ servico_id: I, profissional_id: I, inicio: { type: 'string', description: 'YYYY-MM-DDTHH:MM' }, reservar_pacote: { type: 'boolean' }, observacoes: S }, ['servico_id', 'profissional_id', 'inicio']) },
  { name: 'enviar_localizacao', description: 'Envia o pin com o endereço da clínica.', input_schema: obj({}) },
  { name: 'meus_agendamentos', description: 'Próximos agendamentos DESTE paciente.', input_schema: obj({}) },
  { name: 'confirmar_agendamento', description: 'Confirma presença.', input_schema: obj({ agendamento_id: I }, ['agendamento_id']) },
  { name: 'cancelar_agendamento', description: 'Cancela (só com pedido explícito). O sistema já envia novas opções de data ao paciente.', input_schema: obj({ agendamento_id: I, motivo: S }, ['agendamento_id']) },
  { name: 'horarios_para_remarcar', description: 'Horários livres para remarcar (mesmo profissional primeiro).', input_schema: obj({ agendamento_id: I }, ['agendamento_id']) },
  { name: 'remarcar_agendamento', description: 'Remarca para um horário livre.', input_schema: obj({ agendamento_id: I, inicio: S, profissional_id: I }, ['agendamento_id', 'inicio']) },
  { name: 'entrar_lista_espera', description: 'Coloca o paciente na lista de espera; ele é avisado quando vagar um horário.', input_schema: obj({ servico_id: I, profissional_id: I, periodo: { type: 'string', enum: ['manha', 'tarde', 'noite'] } }, ['servico_id']) },
  { name: 'transferir_para_humano', description: 'Passa para a equipe: pedido explícito, urgência, reclamação, convênio/pagamento complexo, política de cancelamento, assunto que você não pode resolver.', input_schema: obj({ motivo: S }, ['motivo']) },
];
