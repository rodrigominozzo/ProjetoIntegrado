// Ferramentas que o agente pode executar (usadas pelo agente Claude e pelo agente de regras).
import { all, get, insert, update } from '../db.js';
import * as sched from '../services/scheduling.js';
import { addMessage, setState, getState, logStep } from '../services/conversations.js';
import { fmtHora, diaCurto, fmtData, fmtRelativo, fmtLongo, nowLocal } from '../services/time.js';
import { bus } from '../services/bus.js';

export const optionLabel = (o) => `${diaCurto(o.start)[0].toUpperCase() + diaCurto(o.start).slice(1)} ${fmtData(o.start)} · ${fmtHora(o.start)} · ${o.professional}`;

export function servicesCatalog(tenantId) {
  return all('SELECT * FROM services WHERE tenant_id=? AND active=1 ORDER BY is_entry DESC, id', tenantId).map((s) => ({
    ...s, professionals: sched.professionalsFor(tenantId, s.id).map((p) => ({ id: p.id, name: p.name })),
  }));
}

export function makeTools(ctx) {
  const { tenant, client, conv } = ctx;
  const say = (m) => addMessage(conv, { sender: 'agente', ...m });

  return {
    listar_servicos() {
      return servicesCatalog(tenant.id).map((s) => ({
        id: s.id, nome: s.name, duracao_min: s.duration_min, preco: s.price, porta_de_entrada: !!s.is_entry,
        pacote_sessoes: s.package_sessions || 0, preco_sessao_pacote: s.package_session_price, exige_documento: s.requires_document ? s.document_label : null,
        profissionais: s.professionals,
      }));
    },

    registrar_triagem({ queixa, pontos = [], objetivo, urgencia = 'normal', servico_sugerido_id }) {
      const triage = { queixa, pontos, objetivo, urgencia, servico_sugerido_id, at: nowLocal() };
      update('conversations', conv.id, { triage_json: JSON.stringify(triage) });
      logStep(tenant.id, conv.id, 'triagem', triage);
      bus.emit('conversation', { tenantId: tenant.id, conversationId: conv.id, type: 'triage' });
      return { ok: true };
    },

    salvar_cadastro({ nome, email, data_nascimento }) {
      const patch = {};
      if (nome) patch.name = nome;
      if (email) patch.email = email;
      if (data_nascimento) patch.birthdate = data_nascimento;
      update('clients', client.id, patch);
      Object.assign(client, patch);
      return { ok: true };
    },

    registrar_documento({ tipo, resumo, sessoes_prescritas }) {
      const doc = get('SELECT * FROM documents WHERE client_id=? ORDER BY id DESC LIMIT 1', client.id);
      if (doc) update('documents', doc.id, { kind: tipo || doc.kind, extracted: JSON.stringify({ resumo, sessoes_prescritas }) });
      setState(conv, { has_document: true });
      logStep(tenant.id, conv.id, 'documento', { tipo, resumo, sessoes_prescritas });
      return { ok: true };
    },

    oferecer_horarios({ servico_id, mensagem, data, periodo, profissional_id, quantidade = 2 }) {
      const t0 = Date.now();
      const opts = sched.findOptions(tenant.id, Number(servico_id), { date: data, period: periodo, professionalId: profissional_id, count: Math.min(4, quantidade) });
      logStep(tenant.id, conv.id, 'agenda', { consulta: 'horários livres', servico_id, encontrados: opts.length }, Date.now() - t0);
      if (!opts.length) return { opcoes: [], aviso: 'Sem horários livres nos próximos 14 dias para esse filtro.' };
      setState(conv, { offered: opts, service_id: Number(servico_id), stage: 'escolhendo_horario' });
      say({ type: 'options', content: mensagem || 'Tenho estes horários livres. Qual fica melhor pra você?', meta: { options: opts.map((o) => ({ id: o.option, label: optionLabel(o), start: o.start, professional_id: o.professional_id })) } });
      return { opcoes: opts.map((o) => ({ opcao: o.option, inicio: o.start, profissional_id: o.professional_id, profissional: o.professional, legenda: optionLabel(o) })), enviado_ao_cliente: true };
    },

    agendar({ servico_id, profissional_id, inicio, reservar_pacote = true, observacoes }) {
      const t0 = Date.now();
      const appt = sched.book({ tenantId: tenant.id, clientId: client.id, serviceId: Number(servico_id), professionalId: Number(profissional_id), start: inicio, createdBy: 'agente', status: 'confirmado', notes: observacoes });
      say({ type: 'appointment', content: `${appt.service_name} confirmada`, meta: { id: appt.id, service_name: appt.service_name, start: appt.start, end: appt.end, professional_name: appt.professional_name, status: 'confirmado', place: tenant.name } });
      let pacote = null;
      if (reservar_pacote && tenant.auto_book_package) {
        const r = sched.reservePackage({ tenantId: tenant.id, clientId: client.id, entryAppointment: appt });
        if (r) {
          pacote = { tratamento_id: r.treatment.id, sessoes: r.sessions.map((s) => s.start) };
          say({ type: 'package', content: `${r.sessions.length} sessões reservadas`, meta: { treatment_id: r.treatment.id, total: r.treatment.total_sessions, sessions: r.sessions.map((s) => ({ n: s.session_number, start: s.start, professional_name: s.professional_name })) } });
        }
      }
      setState(conv, { stage: 'agendado', offered: null });
      logStep(tenant.id, conv.id, 'agendamento', { appointment_id: appt.id, pacote: pacote?.sessoes?.length || 0 }, Date.now() - t0);
      return { ok: true, agendamento_id: appt.id, quando: fmtLongo(appt.start) + ' ' + fmtHora(appt.start), profissional: appt.professional_name, pacote };
    },

    enviar_localizacao() {
      say({ type: 'location', content: tenant.address, meta: { name: tenant.name, address: tenant.address, lat: tenant.lat, lng: tenant.lng } });
      return { ok: true };
    },

    meus_agendamentos() {
      return sched.clientUpcoming(tenant.id, client.id).map((a) => ({ id: a.id, servico: a.service_name, inicio: a.start, quando: fmtRelativo(a.start), profissional: a.professional_name, profissional_id: a.professional_id, servico_id: a.service_id, status: a.status, sessao: a.session_number }));
    },

    confirmar_agendamento({ agendamento_id }) {
      const a = own(agendamento_id); sched.setStatus(a.id, 'confirmado'); setState(conv, { pending: null });
      return { ok: true };
    },

    cancelar_agendamento({ agendamento_id }) {
      const a = own(agendamento_id); sched.cancel(a.id); setState(conv, { pending: null });
      return { ok: true };
    },

    remarcar_agendamento({ agendamento_id, inicio, profissional_id }) {
      const a = own(agendamento_id);
      const n = sched.reschedule(a.id, { start: inicio, professionalId: profissional_id ? Number(profissional_id) : undefined });
      setState(conv, { pending: null });
      say({ type: 'note', content: `Sessão remarcada · ${diaCurto(n.start)} ${fmtHora(n.start)}` });
      return { ok: true, novo_id: n.id, quando: fmtRelativo(n.start) };
    },

    horarios_para_remarcar({ agendamento_id, data, periodo }) {
      const a = own(agendamento_id);
      return sched.findOptions(tenant.id, a.service_id, { date: data, period: periodo, professionalId: a.professional_id, count: 3 })
        .map((o) => ({ inicio: o.start, legenda: optionLabel(o) }));
    },

    transferir_para_humano({ motivo }) {
      update('conversations', conv.id, { mode: 'humano' });
      addMessage(conv, { sender: 'sistema', type: 'note', content: `Conversa transferida para a equipe: ${motivo}` });
      bus.emit('conversation', { tenantId: tenant.id, conversationId: conv.id, type: 'handoff', motivo });
      return { ok: true };
    },
  };

  function own(id) {
    const a = get('SELECT * FROM appointments WHERE id=? AND client_id=? AND tenant_id=?', Number(id), client.id, tenant.id);
    if (!a) throw new Error('Agendamento não encontrado para este cliente');
    return a;
  }
}

// Esquemas JSON (Claude tool use)
const obj = (properties, required = []) => ({ type: 'object', properties, required, additionalProperties: false });
export const TOOL_SCHEMAS = [
  { name: 'listar_servicos', description: 'Lista serviços ativos, preços, pacotes, documentos exigidos e profissionais habilitados.', input_schema: obj({}) },
  { name: 'registrar_triagem', description: 'Registra o que você entendeu do cliente (queixa, pontos-chave, objetivo, urgência). Chame assim que entender a necessidade.', input_schema: obj({ queixa: { type: 'string' }, pontos: { type: 'array', items: { type: 'string' } }, objetivo: { type: 'string' }, urgencia: { type: 'string', enum: ['baixa', 'normal', 'alta', 'emergencia'] }, servico_sugerido_id: { type: 'integer' } }, ['queixa']) },
  { name: 'salvar_cadastro', description: 'Salva nome/e-mail/data de nascimento do cliente quando informados.', input_schema: obj({ nome: { type: 'string' }, email: { type: 'string' }, data_nascimento: { type: 'string', description: 'YYYY-MM-DD' } }) },
  { name: 'registrar_documento', description: 'Registra o documento/foto que o cliente enviou (ex.: pedido médico), com resumo do que foi lido.', input_schema: obj({ tipo: { type: 'string' }, resumo: { type: 'string' }, sessoes_prescritas: { type: 'integer' } }, ['tipo', 'resumo']) },
  { name: 'oferecer_horarios', description: 'Consulta a agenda e ENVIA ao cliente botões com opções de horário (padrão 2, de profissionais diferentes). O texto em "mensagem" vai junto dos botões; não repita a lista na sua resposta.', input_schema: obj({ servico_id: { type: 'integer' }, mensagem: { type: 'string' }, data: { type: 'string', description: 'YYYY-MM-DD preferida (opcional)' }, periodo: { type: 'string', enum: ['manha', 'tarde', 'noite'] }, profissional_id: { type: 'integer' }, quantidade: { type: 'integer' } }, ['servico_id']) },
  { name: 'agendar', description: 'Marca o horário escolhido (confirmado) e, se o serviço tiver pacote, já reserva as próximas sessões no mesmo dia/horário da semana. Envia o cartão de confirmação ao cliente.', input_schema: obj({ servico_id: { type: 'integer' }, profissional_id: { type: 'integer' }, inicio: { type: 'string', description: 'YYYY-MM-DDTHH:MM (exatamente como retornado em oferecer_horarios)' }, reservar_pacote: { type: 'boolean' }, observacoes: { type: 'string' } }, ['servico_id', 'profissional_id', 'inicio']) },
  { name: 'enviar_localizacao', description: 'Envia o pin de localização/endereço da empresa.', input_schema: obj({}) },
  { name: 'meus_agendamentos', description: 'Lista próximos agendamentos do cliente.', input_schema: obj({}) },
  { name: 'confirmar_agendamento', description: 'Confirma presença em um agendamento.', input_schema: obj({ agendamento_id: { type: 'integer' } }, ['agendamento_id']) },
  { name: 'cancelar_agendamento', description: 'Cancela um agendamento (só após o cliente pedir explicitamente).', input_schema: obj({ agendamento_id: { type: 'integer' } }, ['agendamento_id']) },
  { name: 'horarios_para_remarcar', description: 'Busca horários livres com o mesmo profissional para remarcar um agendamento.', input_schema: obj({ agendamento_id: { type: 'integer' }, data: { type: 'string' }, periodo: { type: 'string', enum: ['manha', 'tarde', 'noite'] } }, ['agendamento_id']) },
  { name: 'remarcar_agendamento', description: 'Remarca um agendamento para um novo horário livre.', input_schema: obj({ agendamento_id: { type: 'integer' }, inicio: { type: 'string' }, profissional_id: { type: 'integer' } }, ['agendamento_id', 'inicio']) },
  { name: 'transferir_para_humano', description: 'Transfere a conversa para a equipe humana (reclamação, urgência médica, pedido explícito, assunto fora do escopo, pagamento/convênio complexo).', input_schema: obj({ motivo: { type: 'string' } }, ['motivo']) },
];
