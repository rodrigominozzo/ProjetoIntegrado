// Motor de agenda: disponibilidade, marcação, pacotes de sessões, remarcação.
import { all, get, insert, update, parse } from '../db.js';
import { nowLocal, addMin, addDays, dateOf, timeOf, weekday, minutes, hhmm, toD } from './time.js';
import { bus } from './bus.js';

const ACTIVE = "('pendente','confirmado','realizado')";
const SLOT_STEP = 30;

export function professionalsFor(tenantId, serviceId) {
  return all(`SELECT p.* FROM professionals p JOIN professional_services ps ON ps.professional_id=p.id
              WHERE p.tenant_id=? AND ps.service_id=? AND p.active=1 ORDER BY p.id`, tenantId, serviceId);
}

export function isFree(tenantId, professionalId, start, end, ignoreId = 0) {
  const clash = get(`SELECT id FROM appointments WHERE tenant_id=? AND professional_id=? AND status IN ${ACTIVE}
                     AND id<>? AND start < ? AND end > ?`, tenantId, professionalId, ignoreId, end, start);
  if (clash) return false;
  const blk = get(`SELECT id FROM blocks WHERE tenant_id=? AND (professional_id IS NULL OR professional_id=?) AND start < ? AND end > ?`,
    tenantId, professionalId, end, start);
  return !blk;
}

function withinSchedule(prof, start, end) {
  const sched = parse(prof.schedule_json);
  const wins = sched[weekday(start)] || [];
  const s = minutes(timeOf(start)); const e = s + (toD(end) - toD(start)) / 60000;
  return wins.some(([a, b]) => s >= minutes(a) && e <= minutes(b));
}

/** Lista horários livres de um profissional num dia. */
export function freeSlotsDay(tenantId, prof, service, date, minStart = nowLocal()) {
  const sched = parse(prof.schedule_json);
  const out = [];
  for (const [a, b] of sched[weekday(date)] || []) {
    for (let m = minutes(a); m + service.duration_min <= minutes(b); m += SLOT_STEP) {
      const start = `${date}T${hhmm(m)}`;
      if (start <= addMin(minStart, 60)) continue; // antecedência mínima 1h
      const end = addMin(start, service.duration_min);
      if (isFree(tenantId, prof.id, start, end)) out.push({ start, end, professional_id: prof.id, professional: prof.name });
    }
  }
  return out;
}

/**
 * Busca opções de horário (padrão: 2, de profissionais diferentes quando possível — como no vídeo:
 * "Seg 7h00 · Dra. Ana" e "Seg 18h30 · Dr. Lucas").
 */
export function findOptions(tenantId, serviceId, { date, period, professionalId, count = 2, days = 14 } = {}) {
  const service = get('SELECT * FROM services WHERE id=? AND tenant_id=?', serviceId, tenantId);
  if (!service) return [];
  let profs = professionalsFor(tenantId, serviceId);
  if (professionalId) profs = profs.filter((p) => p.id === Number(professionalId));
  const today = dateOf(nowLocal());
  const startDate = date && date >= today ? date : today;
  const inPeriod = (s) => {
    const m = minutes(timeOf(s));
    if (period === 'manha') return m < 12 * 60;
    if (period === 'tarde') return m >= 12 * 60 && m < 18 * 60;
    if (period === 'noite') return m >= 18 * 60;
    return true;
  };
  for (let i = 0; i < days; i++) {
    const d = addDays(startDate, i);
    const perProf = profs.map((p) => freeSlotsDay(tenantId, p, service, d).filter((s) => inPeriod(s.start)));
    const flat = perProf.flat();
    if (!flat.length) continue;
    flat.sort((a, b) => a.start.localeCompare(b.start));
    const picks = [flat[0]];
    if (count > 1) {
      // 2ª opção: outro profissional e o horário mais distante (manhã x noite)
      const others = flat.filter((s) => s.professional_id !== flat[0].professional_id);
      const pool = others.length ? others : flat.slice(1);
      const far = pool.sort((a, b) => b.start.localeCompare(a.start))[0];
      if (far) picks.push(far);
    }
    for (const s of flat) { if (picks.length >= count) break; if (!picks.includes(s)) picks.push(s); }
    picks.sort((a, b) => a.start.localeCompare(b.start));
    return picks.slice(0, count).map((s, i) => ({ ...s, option: i + 1, service_id: serviceId }));
  }
  return [];
}

export function book({ tenantId, clientId, serviceId, professionalId, start, createdBy = 'agente', status = 'confirmado', treatmentId = null, sessionNumber = null, price, notes }) {
  const service = get('SELECT * FROM services WHERE id=? AND tenant_id=?', serviceId, tenantId);
  if (!service) throw new Error('Serviço não encontrado');
  const prof = get('SELECT * FROM professionals WHERE id=? AND tenant_id=?', professionalId, tenantId);
  if (!prof) throw new Error('Profissional não encontrado');
  const end = addMin(start, service.duration_min);
  if (!isFree(tenantId, professionalId, start, end)) throw new Error('Horário indisponível');
  const id = insert('appointments', {
    tenant_id: tenantId, client_id: clientId, service_id: serviceId, professional_id: professionalId,
    start, end, status, created_by: createdBy, treatment_id: treatmentId, session_number: sessionNumber,
    price: price ?? service.price, notes: notes || null,
  });
  bus.emit('agenda', { tenantId, type: 'created', id });
  return getAppointment(id);
}

/**
 * Reserva as próximas sessões do pacote (ex.: 10 sessões, 2x/semana, mesmo horário e profissional).
 * Se o horário-padrão estiver ocupado, busca o horário livre mais próximo no mesmo dia.
 */
export function reservePackage({ tenantId, clientId, entryAppointment, createdBy = 'agente' }) {
  const service = get('SELECT * FROM services WHERE id=?', entryAppointment.service_id);
  if (!service?.package_sessions) return null;
  const prof = get('SELECT * FROM professionals WHERE id=?', entryAppointment.professional_id);
  const sessionService = (service.package_service_id && get('SELECT * FROM services WHERE id=?', service.package_service_id)) || service;
  const treatmentId = insert('treatments', {
    tenant_id: tenantId, client_id: clientId, service_id: sessionService.id, professional_id: prof.id,
    total_sessions: service.package_sessions, session_price: service.package_session_price, created_by: createdBy,
  });
  update('appointments', entryAppointment.id, { treatment_id: treatmentId });
  // Dias fixos na semana (ex.: 2x → seg/qua; 3x → seg/qua/sex), a partir do dia da entrada.
  const perWeek = Math.min(5, Math.max(1, service.sessions_per_week));
  const w = weekday(entryAppointment.start) || 1;
  const allowed = new Set(Array.from({ length: perWeek }, (_, i) => (((w - 1 + i * 2) % 5) + 1)));
  const baseTime = timeOf(entryAppointment.start);
  const sessions = [];
  let day = dateOf(entryAppointment.start);
  for (let guard = 0; sessions.length < service.package_sessions && guard < 180; guard++) {
    day = addDays(day, 1);
    if (!allowed.has(weekday(day))) continue;
    const desired = `${day}T${baseTime}`;
    const end = addMin(desired, sessionService.duration_min);
    let chosen = null;
    if (withinSchedule(prof, desired, end) && isFree(tenantId, prof.id, desired, end)) chosen = desired;
    else {
      const alt = freeSlotsDay(tenantId, prof, sessionService, day, entryAppointment.start)
        .sort((a, b) => Math.abs(minutes(timeOf(a.start)) - minutes(baseTime)) - Math.abs(minutes(timeOf(b.start)) - minutes(baseTime)))[0];
      if (alt) chosen = alt.start;
    }
    if (!chosen) continue;
    sessions.push(book({
      tenantId, clientId, serviceId: sessionService.id, professionalId: prof.id, start: chosen, createdBy,
      treatmentId, sessionNumber: sessions.length + 1, price: service.package_session_price, status: 'confirmado',
    }));
  }
  return { treatment: get('SELECT * FROM treatments WHERE id=?', treatmentId), sessions };
}

export function getAppointment(id) {
  return get(`SELECT a.*, c.name AS client_name, c.phone AS client_phone, p.name AS professional_name, p.color,
              s.name AS service_name FROM appointments a JOIN clients c ON c.id=a.client_id
              JOIN professionals p ON p.id=a.professional_id JOIN services s ON s.id=a.service_id WHERE a.id=?`, id);
}

export function clientUpcoming(tenantId, clientId) {
  return all(`SELECT a.*, p.name AS professional_name, s.name AS service_name FROM appointments a
              JOIN professionals p ON p.id=a.professional_id JOIN services s ON s.id=a.service_id
              WHERE a.tenant_id=? AND a.client_id=? AND a.status IN ('pendente','confirmado') AND a.start >= ?
              ORDER BY a.start`, tenantId, clientId, nowLocal());
}

export function setStatus(id, status) {
  update('appointments', id, { status });
  const a = getAppointment(id);
  if (a?.treatment_id) refreshTreatment(a.treatment_id);
  bus.emit('agenda', { tenantId: a.tenant_id, type: 'status', id, status });
  return a;
}

export function cancel(id) { return setStatus(id, 'cancelado'); }

export function reschedule(id, { start, professionalId, createdBy = 'agente' }) {
  const old = getAppointment(id);
  if (!old) throw new Error('Agendamento não encontrado');
  const appt = book({
    tenantId: old.tenant_id, clientId: old.client_id, serviceId: old.service_id, professionalId: professionalId || old.professional_id,
    start, createdBy, treatmentId: old.treatment_id, sessionNumber: old.session_number, price: old.price, status: 'confirmado',
  });
  update('appointments', id, { status: old.status === 'faltou' ? 'faltou' : 'remarcado' });
  update('appointments', appt.id, { rescheduled_from: id });
  bus.emit('agenda', { tenantId: old.tenant_id, type: 'rescheduled', id: appt.id });
  return getAppointment(appt.id);
}

export function refreshTreatment(treatmentId) {
  const t = get('SELECT * FROM treatments WHERE id=?', treatmentId);
  if (!t || t.status === 'cancelado') return;
  const done = get(`SELECT COUNT(*) n FROM appointments WHERE treatment_id=? AND status='realizado' AND session_number IS NOT NULL`, treatmentId).n;
  if (done >= t.total_sessions) update('treatments', treatmentId, { status: 'concluido' });
}

/** Próximo horário livre do mesmo profissional, para recuperar uma falta ("remarca na hora"). */
export function nextSlotSameProfessional(appt) {
  const service = get('SELECT * FROM services WHERE id=?', appt.service_id);
  const prof = get('SELECT * FROM professionals WHERE id=?', appt.professional_id);
  const today = dateOf(nowLocal());
  for (let i = 0; i < 14; i++) {
    const d = addDays(today, i);
    const slots = freeSlotsDay(appt.tenant_id, prof, service, d);
    if (!slots.length) continue;
    const pref = slots.find((s) => timeOf(s.start) === timeOf(appt.start)) || slots[0];
    return pref;
  }
  return null;
}
