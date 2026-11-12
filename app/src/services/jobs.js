// Rotinas automáticas: lembretes antes do horário e recuperação de faltas ("se alguém falta, a IA remarca na hora").
import { all, update } from '../db.js';
import { nowLocal, addMin, fmtRelativo, fmtHora } from './time.js';
import { nextSlotSameProfessional } from './scheduling.js';
import { getConversation, addMessage, setState, logStep } from './conversations.js';

export function runJobs() {
  const now = nowLocal();
  const out = { lembretes: 0, faltas_detectadas: 0, recuperacoes: 0 };

  const quiet = now.slice(11) < '08:00' || now.slice(11) >= '20:00'; // não incomodar de madrugada
  for (const tenant of all('SELECT * FROM tenants WHERE automation_active=1')) {
    // 1) Lembretes: agendamentos dentro da janela (ex.: 24h antes)
    const limit = addMin(now, tenant.reminder_hours_before * 60);
    const due = all(`SELECT a.*, p.name professional_name, s.name service_name, c.name client_name FROM appointments a
      JOIN professionals p ON p.id=a.professional_id JOIN services s ON s.id=a.service_id JOIN clients c ON c.id=a.client_id
      WHERE a.tenant_id=? AND a.status IN ('pendente','confirmado') AND a.reminder_sent=0 AND a.start > ? AND a.start <= ? AND a.created_at <= datetime('now','-2 hours')`, tenant.id, now, limit);
    if (quiet) due.length = 0;
    for (const a of due) {
      const conv = getConversation(tenant.id, a.client_id);
      const when = fmtRelativo(a.start, now);
      addMessage(conv, {
        sender: 'agente', type: 'options',
        content: `Oi${a.client_name ? ', ' + a.client_name.split(' ')[0] : ''}! Lembrete: ${a.service_name} ${when} com ${a.professional_name}. Posso confirmar sua presença?`,
        meta: { options: [{ id: 1, label: 'Confirmar' }, { id: 2, label: 'Remarcar' }], kind: 'reminder', appointment_id: a.id },
      });
      setState(conv, { pending: { kind: 'reminder', appointment_id: a.id, when } });
      update('appointments', a.id, { reminder_sent: 1 });
      logStep(tenant.id, conv.id, 'lembrete', { appointment_id: a.id });
      out.lembretes++;
    }

    // 2) Recuperação de falta: status "faltou" ainda sem contato
    if (tenant.noshow_recovery) {
      const missed = all(`SELECT a.*, c.name client_name FROM appointments a JOIN clients c ON c.id=a.client_id
        WHERE a.tenant_id=? AND a.status='faltou' AND a.recovery_sent=0`, tenant.id);
      for (const a of missed) recoverNoShow(tenant, a, out);
    }
  }
  return out;
}

export function recoverNoShow(tenant, a, out = {}) {
  const slot = nextSlotSameProfessional(a);
  const conv = getConversation(tenant.id, a.client_id);
  update('appointments', a.id, { recovery_sent: 1 });
  if (!slot) return;
  const nome = a.client_name ? a.client_name.split(' ')[0] : '';
  addMessage(conv, {
    sender: 'agente', type: 'options',
    content: `Oi${nome ? ', ' + nome : ''}! Sentimos sua falta hoje. Quer remarcar pra ${fmtRelativo(slot.start)}?`,
    meta: { options: [{ id: 1, label: `Quero sim (${fmtHora(slot.start)})` }, { id: 2, label: 'Outro horário' }], kind: 'recovery', appointment_id: a.id },
  });
  setState(conv, { pending: { kind: 'recovery', appointment_id: a.id, slot } });
  logStep(tenant.id, conv.id, 'recuperacao_falta', { appointment_id: a.id, sugerido: slot.start });
  out.recuperacoes = (out.recuperacoes || 0) + 1;
}

export function startJobs(intervalMs = 60_000) {
  const tick = () => { try { runJobs(); } catch (e) { console.error('[jobs]', e); } };
  setTimeout(tick, 3000);
  return setInterval(tick, intervalMs);
}

