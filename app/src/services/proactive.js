// Ações proativas do agente: ninguém precisa pedir — a clínica não perde o horário nem o paciente.
import { all, get, update, insert, parse } from '../db.js';
import { getConversation, addMessage, setState, logStep } from './conversations.js';
import { replacementOptions, findOptions, getAppointment } from './scheduling.js';
import { nowLocal, fmtRelativo, diaCurto, fmtData, fmtHora, addDays, dateOf } from './time.js';
import { termsFor } from './presets.js';

const first = (n) => (n ? ' ' + n.split(' ')[0] : '');
const label = (o) => `${diaCurto(o.start)[0].toUpperCase() + diaCurto(o.start).slice(1)} ${fmtData(o.start)} · ${fmtHora(o.start)} · ${o.professional}`;

/** Fora do horário silencioso da clínica? (não manda mensagem proativa de madrugada) */
export function canSendNow(tenant, now = nowLocal()) {
  const t = now.slice(11, 16); const a = tenant.quiet_start || '20:00'; const b = tenant.quiet_end || '08:00';
  const quiet = a > b ? t >= a || t < b : t >= a && t < b;
  return !quiet;
}

const REASONS = {
  falta: (n, s) => `Oi${n}! Sentimos sua falta hoje. Vamos remarcar ${s}? Tenho estes horários:`,
  cancelamento_cliente: (n, s) => `Cancelamento feito${n ? ',' + n : ''}. Pra você não ficar sem ${s}, já separei estes horários:`,
  cancelamento_clinica: (n, s) => `Oi${n}! Precisamos desmarcar ${s} — desculpe pelo transtorno. Escolha um novo horário:`,
  bloqueio: (n, s) => `Oi${n}! Houve uma mudança na agenda e ${s} precisou sair do horário. Escolha um novo horário:`,
};

/** Oferece novos horários para repor um atendimento perdido (falta/cancelamento/bloqueio). */
export function offerReplacement(appointmentId, reason) {
  const a = getAppointment(appointmentId);
  if (!a) return null;
  const tenant = get('SELECT * FROM tenants WHERE id=?', a.tenant_id);
  if (!tenant.automation_active) return null;
  const opts = replacementOptions(a, Math.max(2, tenant.options_count || 2));
  update('appointments', a.id, { recovery_sent: 1 });
  const conv = getConversation(a.tenant_id, a.client_id);
  const t = termsFor(tenant);
  const what = a.session_number ? `sua ${t.sessao} ${a.session_number}` : `sua ${a.service_name.toLowerCase()}`;
  if (!opts.length) {
    addMessage(conv, { sender: 'agente', content: `${REASONS[reason](first(a.client_name), what).replace(/ Tenho estes horários:| já separei estes horários:| Escolha um novo horário:/, '')} Não achei horário livre agora; nossa equipe vai te chamar.` });
    return null;
  }
  addMessage(conv, {
    sender: 'agente', type: 'options', content: REASONS[reason](first(a.client_name), what),
    meta: { kind: 'replacement', reason, appointment_id: a.id, options: opts.map((o) => ({ id: o.option, label: label(o), start: o.start, professional_id: o.professional_id })).concat([{ id: opts.length + 1, label: 'Nenhum desses' }]) },
  });
  setState(conv, { stage: 'remarcando', reschedule_id: a.id, offered: opts, pending: null, service_id: a.service_id });
  logStep(a.tenant_id, conv.id, 'proativo_' + reason, { appointment_id: a.id, opcoes: opts.length });
  return opts;
}

/** Um horário vagou → oferece ao primeiro da lista de espera compatível (encaixe). */
export function fillFromWaitlist(freedAppointmentId) {
  const a = getAppointment(freedAppointmentId);
  if (!a || a.start <= nowLocal()) return null;
  const tenant = get('SELECT * FROM tenants WHERE id=?', a.tenant_id);
  if (!tenant.waitlist_enabled || !tenant.automation_active) return null;
  const w = get(`SELECT w.*, c.name client_name FROM waitlist w JOIN clients c ON c.id=w.client_id WHERE w.tenant_id=? AND w.service_id=? AND w.status='aguardando'
    AND (w.professional_id IS NULL OR w.professional_id=?) AND w.client_id<>? ORDER BY w.id LIMIT 1`, a.tenant_id, a.service_id, a.professional_id, a.client_id);
  if (!w) return null;
  const slot = { option: 1, start: a.start, end: a.end, professional_id: a.professional_id, professional: a.professional_name };
  const conv = getConversation(a.tenant_id, w.client_id);
  addMessage(conv, { sender: 'agente', type: 'options', content: `Oi${first(w.client_name)}! Abriu uma vaga de ${a.service_name.toLowerCase()} ${fmtRelativo(a.start)} com ${a.professional_name}. Quer ficar com ela?`,
    meta: { kind: 'waitlist', options: [{ id: 1, label: label(slot), start: slot.start, professional_id: slot.professional_id }, { id: 2, label: 'Não, obrigado' }] } });
  setState(conv, { stage: 'escolhendo_horario', offered: [slot], service_id: a.service_id, waitlist_id: w.id });
  update('waitlist', w.id, { status: 'oferecido', offered_json: JSON.stringify(slot) });
  logStep(a.tenant_id, conv.id, 'encaixe_lista_espera', { waitlist_id: w.id, appointment_livre: a.id });
  return w;
}

/** Tratamento parado (sem próxima sessão) há X dias → convida a retomar. */
export function reactivateTreatments(tenant) {
  let n = 0;
  const list = all(`SELECT t.*, c.name client_name, s.name service_name,
      (SELECT MAX(start) FROM appointments WHERE treatment_id=t.id AND status IN ('realizado','faltou','cancelado')) last_start,
      (SELECT COUNT(*) FROM appointments WHERE treatment_id=t.id AND status='realizado' AND session_number IS NOT NULL) done
    FROM treatments t JOIN clients c ON c.id=t.client_id JOIN services s ON s.id=t.service_id
    WHERE t.tenant_id=? AND t.status='ativo'
      AND NOT EXISTS (SELECT 1 FROM appointments WHERE treatment_id=t.id AND status IN ('pendente','confirmado') AND start >= ?)`, tenant.id, nowLocal());
  for (const tr of list) {
    if (!tr.last_start || tr.last_start > addDays(dateOf(nowLocal()), -(tenant.reactivation_days || 10))) continue;
    if (get(`SELECT 1 FROM automation_logs WHERE tenant_id=? AND step='reativacao' AND detail LIKE ? AND created_at >= datetime('now','-14 days')`, tenant.id, `%"treatment_id":${tr.id}%`)) continue;
    const opts = findOptions(tenant.id, tr.service_id, { professionalId: tr.professional_id, count: 2 });
    if (!opts.length) continue;
    const conv = getConversation(tenant.id, tr.client_id);
    const t = termsFor(tenant);
    addMessage(conv, { sender: 'agente', type: 'options', content: `Oi${first(tr.client_name)}! Você fez ${tr.done} de ${tr.total_sessions} ${t.sessoes} de ${tr.service_name.toLowerCase()}. Vamos continuar pra não perder o resultado?`,
      meta: { kind: 'reactivation', options: opts.map((o) => ({ id: o.option, label: label(o), start: o.start, professional_id: o.professional_id })) } });
    setState(conv, { stage: 'escolhendo_horario', offered: opts, service_id: tr.service_id, treatment_id: tr.id });
    logStep(tenant.id, conv.id, 'reativacao', { treatment_id: tr.id });
    n++;
  }
  return n;
}

/** Retorno incluso: X dias após a consulta, lembra que o retorno está disponível. */
export function returnReminders(tenant) {
  let n = 0;
  const list = all(`SELECT a.*, s.return_days, s.name service_name, c.name client_name, p.name professional_name FROM appointments a
    JOIN services s ON s.id=a.service_id JOIN clients c ON c.id=a.client_id JOIN professionals p ON p.id=a.professional_id
    WHERE a.tenant_id=? AND a.status='realizado' AND s.return_days >= 7 AND a.session_number IS NULL
      AND date(substr(a.start,1,10), '+' || (s.return_days - 5) || ' days') = date(?)`, tenant.id, dateOf(nowLocal()));
  for (const a of list) {
    if (get(`SELECT 1 FROM automation_logs WHERE tenant_id=? AND step='retorno' AND detail LIKE ?`, tenant.id, `%"appointment_id":${a.id}%`)) continue;
    if (get(`SELECT 1 FROM appointments WHERE client_id=? AND service_id=? AND start > ? AND status IN ('pendente','confirmado')`, a.client_id, a.service_id, a.start)) continue;
    const conv = getConversation(tenant.id, a.client_id);
    addMessage(conv, { sender: 'agente', content: `Oi${first(a.client_name)}! Seu retorno de ${a.service_name.toLowerCase()} com ${a.professional_name} está disponível até ${fmtData(addDays(a.start.slice(0, 10), a.return_days))}. Quer que eu veja um horário?` });
    logStep(tenant.id, conv.id, 'retorno', { appointment_id: a.id });
    n++;
  }
  return n;
}

/** Bloqueio de agenda (férias, congresso, imprevisto): desmarca quem estava no período e já oferece nova data. */
export function applyBlock(block) {
  const affected = all(`SELECT id FROM appointments WHERE tenant_id=? AND status IN ('pendente','confirmado') AND start < ? AND end > ?
    ${block.professional_id ? 'AND professional_id=' + Number(block.professional_id) : ''}`, block.tenant_id, block.end, block.start);
  for (const { id } of affected) {
    update('appointments', id, { status: 'cancelado', cancelled_by: 'clinica', cancel_reason: block.reason || 'bloqueio de agenda', recovery_sent: 0 });
    offerReplacement(id, 'bloqueio');
  }
  return affected.length;
}

export function joinWaitlist({ tenantId, clientId, serviceId, professionalId, period, notes }) {
  const ex = get(`SELECT id FROM waitlist WHERE tenant_id=? AND client_id=? AND service_id=? AND status='aguardando'`, tenantId, clientId, serviceId);
  if (ex) return ex.id;
  return insert('waitlist', { tenant_id: tenantId, client_id: clientId, service_id: serviceId, professional_id: professionalId || null, period: period || null, notes: notes || null });
}
export { parse };
