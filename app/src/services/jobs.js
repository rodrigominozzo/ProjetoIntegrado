// Rotinas automáticas (a cada minuto): lembretes, reposição de faltas/cancelamentos, encaixes, reativação, retornos.
import { all, update } from '../db.js';
import { nowLocal, addMin, fmtRelativo } from './time.js';
import { getConversation, addMessage, setState, logStep } from './conversations.js';
import { canSendNow, offerReplacement, fillFromWaitlist, reactivateTreatments, returnReminders } from './proactive.js';

export function runJobs({ force = false } = {}) {
  const now = nowLocal();
  const out = { lembretes: 0, reposicoes: 0, encaixes: 0, reativacoes: 0, retornos: 0 };
  for (const tenant of all('SELECT * FROM tenants WHERE automation_active=1')) {
    if (!force && !canSendNow(tenant, now)) continue; // respeita o horário silencioso

    // 1) Lembretes X horas antes (só para agendamentos criados há mais de 2h)
    const limit = addMin(now, tenant.reminder_hours_before * 60);
    const due = all(`SELECT a.*, p.name professional_name, s.name service_name, s.preparation, c.name client_name FROM appointments a
      JOIN professionals p ON p.id=a.professional_id JOIN services s ON s.id=a.service_id JOIN clients c ON c.id=a.client_id
      WHERE a.tenant_id=? AND a.status IN ('pendente','confirmado') AND a.reminder_sent=0 AND a.start > ? AND a.start <= ?
      AND a.created_at <= datetime('now','-2 hours')`, tenant.id, now, limit);
    for (const a of due) {
      const conv = getConversation(tenant.id, a.client_id);
      const when = fmtRelativo(a.start, now);
      addMessage(conv, {
        sender: 'agente', type: 'options',
        content: `Oi${a.client_name ? ', ' + a.client_name.split(' ')[0] : ''}! Lembrete: ${a.service_name} ${when} com ${a.professional_name}.${a.preparation ? '\nPreparo: ' + a.preparation : ''}\nPosso confirmar sua presença?`,
        meta: { options: [{ id: 1, label: 'Confirmar' }, { id: 2, label: 'Remarcar' }], kind: 'reminder', appointment_id: a.id },
      });
      setState(conv, { pending: { kind: 'reminder', appointment_id: a.id, when } });
      update('appointments', a.id, { reminder_sent: 1 });
      logStep(tenant.id, conv.id, 'lembrete', { appointment_id: a.id });
      out.lembretes++;
    }

    // 2) Faltas e cancelamentos ainda sem reposição → oferece nova data
    const lost = all(`SELECT id, status, cancelled_by, start FROM appointments WHERE tenant_id=? AND recovery_sent=0 AND
      ((status='faltou' AND ?) OR (status='cancelado' AND ? AND cancelled_by IN ('cliente','clinica') AND start >= datetime(?, '-1 day')))`,
    tenant.id, tenant.noshow_recovery ? 1 : 0, tenant.reoffer_cancel ? 1 : 0, now);
    for (const a of lost) {
      const reason = a.status === 'faltou' ? 'falta' : a.cancelled_by === 'clinica' ? 'cancelamento_clinica' : 'cancelamento_cliente';
      if (offerReplacement(a.id, reason)) out.reposicoes++;
      if (a.status === 'cancelado' && fillFromWaitlist(a.id)) out.encaixes++;
    }

    // 3) Tratamentos parados e retornos inclusos
    out.reativacoes += reactivateTreatments(tenant);
    if (tenant.return_reminder) out.retornos += returnReminders(tenant);
  }
  return out;
}

export function startJobs(intervalMs = 60_000) {
  const tick = () => { try { runJobs(); } catch (e) { console.error('[jobs]', e); } };
  setTimeout(tick, 3000);
  return setInterval(tick, intervalMs);
}
