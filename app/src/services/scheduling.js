// Motor de agenda: disponibilidade, marcação, pacotes, remarcação e regras personalizáveis por clínica.
import { all, get, insert, update, parse } from '../db.js';
import { nowLocal, addMin, addDays, dateOf, timeOf, weekday, minutes, hhmm, toD } from './time.js';
import { bus } from './bus.js';

export class AppError extends Error {}
const ACTIVE = "('pendente','confirmado','realizado')";
const tenantOf = (id) => get('SELECT * FROM tenants WHERE id=?', id);

export function professionalsFor(tenantId, serviceId) {
  return all(`SELECT p.*, ps.duration_min AS ps_duration, ps.price AS ps_price, ps.commission_pct AS ps_commission
              FROM professionals p JOIN professional_services ps ON ps.professional_id=p.id
              WHERE p.tenant_id=? AND ps.service_id=? AND p.active=1 ORDER BY p.id`, tenantId, serviceId);
}

/**
 * Regras efetivas de um procedimento com um profissional (personalização):
 * duração, preço e repasse podem ser diferentes por profissional; intervalo = maior entre o do serviço e o do profissional.
 */
export function effective(serviceId, professionalId) {
  const s = get('SELECT * FROM services WHERE id=?', serviceId);
  const p = get('SELECT * FROM professionals WHERE id=?', professionalId);
  const ps = get('SELECT * FROM professional_services WHERE service_id=? AND professional_id=?', serviceId, professionalId) || {};
  const price = ps.price ?? s.price;
  const commissionPct = ps.commission_pct ?? p?.commission_pct ?? 0;
  return {
    service: s, professional: p,
    duration: ps.duration_min || s.duration_min,
    buffer: Math.max(s.buffer_min || 0, p?.buffer_min || 0),
    price, cost: s.cost || 0, commissionPct, commission: Math.round(price * commissionPct) / 100,
  };
}

export function isFree(tenantId, professionalId, start, end, ignoreId = 0) {
  // considera o intervalo (buffer) dos agendamentos existentes
  const clash = get(`SELECT a.id FROM appointments a JOIN services s ON s.id=a.service_id JOIN professionals p ON p.id=a.professional_id
                     WHERE a.tenant_id=? AND a.professional_id=? AND a.status IN ${ACTIVE} AND a.id<>?
                     AND a.start < ? AND datetime(a.end, '+' || MAX(s.buffer_min, p.buffer_min) || ' minutes') > datetime(?)`,
  tenantId, professionalId, ignoreId, end, start);
  if (clash) return false;
  const blk = get(`SELECT id FROM blocks WHERE tenant_id=? AND (professional_id IS NULL OR professional_id=?) AND start < ? AND end > ?`,
    tenantId, professionalId, end, start);
  return !blk;
}

function withinSchedule(prof, start, end) {
  const wins = parse(prof.schedule_json)[weekday(start)] || [];
  const s = minutes(timeOf(start)); const e = s + (toD(end) - toD(start)) / 60000;
  return wins.some(([a, b]) => s >= minutes(a) && e <= minutes(b));
}

/** Horários livres de um profissional num dia, respeitando duração personalizada, intervalo e regras da clínica. */
export function freeSlotsDay(tenantId, prof, service, date, minStart) {
  const tenant = tenantOf(tenantId);
  const eff = effective(service.id, prof.id);
  const earliest = addMin(minStart || nowLocal(), Math.round((tenant.min_advance_hours ?? 2) * 60));
  const step = tenant.slot_step_min || 15;
  const out = [];
  for (const [a, b] of parse(prof.schedule_json)[weekday(date)] || []) {
    for (let m = minutes(a); m + eff.duration <= minutes(b); m += step) {
      const start = `${date}T${hhmm(m)}`;
      if (start < earliest) continue;
      const end = addMin(start, eff.duration);
      if (isFree(tenantId, prof.id, start, addMin(end, eff.buffer))) out.push({ start, end, professional_id: prof.id, professional: prof.name, price: eff.price, duration: eff.duration });
    }
  }
  return out;
}

/** Opções de horário: a 1ª mais cedo e as demais variando profissional e período (manhã × fim do dia). */
export function findOptions(tenantId, serviceId, { date, period, professionalId, count, days } = {}) {
  const tenant = tenantOf(tenantId);
  const service = get('SELECT * FROM services WHERE id=? AND tenant_id=? AND active=1', serviceId, tenantId);
  if (!service) return [];
  count = count || tenant.options_count || 2;
  days = Math.min(days || 21, tenant.max_advance_days || 60);
  let profs = professionalsFor(tenantId, serviceId);
  if (professionalId) profs = profs.filter((p) => p.id === Number(professionalId));
  const today = dateOf(nowLocal());
  const lastDay = addDays(today, tenant.max_advance_days || 60);
  const startDate = date && date >= today ? date : today;
  const inPeriod = (s) => {
    const m = minutes(timeOf(s));
    if (period === 'manha') return m < 12 * 60;
    if (period === 'tarde') return m >= 12 * 60 && m < 18 * 60;
    if (period === 'noite') return m >= 18 * 60;
    return true;
  };
  const daySlots = (d) => profs.flatMap((p) => freeSlotsDay(tenantId, p, service, d).filter((s) => inPeriod(s.start))).sort((a, b) => a.start.localeCompare(b.start));
  for (let i = 0; i < days; i++) {
    const d = addDays(startDate, i);
    if (d > lastDay) break;
    const flat = daySlots(d);
    if (!flat.length) continue;
    // se o dia tem poucas opções/pouca variedade, inclui o próximo dia útil com vaga
    let pool = flat;
    const spread = minutes(timeOf(flat[flat.length - 1].start)) - minutes(timeOf(flat[0].start));
    if (count > 1 && (spread < 120 || flat.length < count)) {
      for (let j = i + 1; j < Math.min(days, i + 7); j++) { const nx = daySlots(addDays(startDate, j)); if (nx.length) { pool = flat.concat(nx); break; } }
    }
    const picks = [flat[0]];
    while (picks.length < count) {
      const used = new Set(picks.map((p) => p.professional_id));
      const rest = pool.filter((s) => !picks.includes(s));
      if (!rest.length) break;
      const otherProf = rest.filter((s) => !used.has(s.professional_id));
      const src = otherProf.length ? otherProf : rest;
      // mesmo dia primeiro; prioriza o horário mais distante dos já escolhidos (manhã × fim do dia)
      src.sort((a, b) => (b.start.slice(0, 10) === d) - (a.start.slice(0, 10) === d) || dist(b, picks) - dist(a, picks));
      const best = src.find((s) => s.start.slice(0, 10) !== d || dist(s, picks) >= 120) || src[0];
      picks.push(best);
    }
    picks.sort((a, b) => a.start.localeCompare(b.start));
    return picks.map((s, i) => ({ ...s, option: i + 1, service_id: serviceId }));
  }
  return [];
}
const dist = (s, picks) => Math.min(...picks.map((p) => Math.abs(minutes(timeOf(s.start)) - minutes(timeOf(p.start)))));

export function book({ tenantId, clientId, serviceId, professionalId, start, createdBy = 'agente', status = 'confirmado', treatmentId = null, sessionNumber = null, price, notes, force = false }) {
  if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(String(start))) throw new AppError('Data/horário inválido');
  const service = get('SELECT * FROM services WHERE id=? AND tenant_id=?', serviceId, tenantId);
  if (!service) throw new AppError('Serviço não encontrado');
  const prof = get('SELECT * FROM professionals WHERE id=? AND tenant_id=?', professionalId, tenantId);
  if (!prof) throw new AppError('Profissional não encontrado');
  const eff = effective(serviceId, professionalId);
  const end = addMin(start, eff.duration);
  if (!force) {
    if (!get('SELECT 1 FROM professional_services WHERE service_id=? AND professional_id=?', serviceId, professionalId)) throw new AppError(`${prof.name} não realiza este serviço`);
    if (!withinSchedule(prof, start, end)) throw new AppError('Fora da jornada do profissional');
  }
  if (!isFree(tenantId, professionalId, start, addMin(end, eff.buffer))) throw new AppError('Horário indisponível');
  const finalPrice = price ?? eff.price; // preço vem SEMPRE do cadastro (o agente não define preço)
  const id = insert('appointments', {
    tenant_id: tenantId, client_id: clientId, service_id: serviceId, professional_id: professionalId,
    start, end, status, created_by: createdBy, treatment_id: treatmentId, session_number: sessionNumber,
    price: finalPrice, cost: eff.cost, commission: Math.round(finalPrice * eff.commissionPct) / 100, notes: notes || null,
  });
  bus.emit('agenda', { tenantId, type: 'created', id });
  return getAppointment(id);
}

/** Reserva as próximas sessões do pacote nos mesmos dias da semana/horário, contornando conflitos. */
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
  const perWeek = Math.min(5, Math.max(1, service.sessions_per_week));
  const w = weekday(entryAppointment.start) || 1;
  const allowed = new Set(Array.from({ length: perWeek }, (_, i) => (((w - 1 + i * 2) % 5) + 1)));
  const baseTime = timeOf(entryAppointment.start);
  const sessions = [];
  let day = dateOf(entryAppointment.start);
  for (let guard = 0; sessions.length < service.package_sessions && guard < 180; guard++) {
    day = addDays(day, 1);
    if (!allowed.has(weekday(day))) continue;
    const eff = effective(sessionService.id, prof.id);
    const desired = `${day}T${baseTime}`;
    const end = addMin(desired, eff.duration);
    let chosen = null;
    if (withinSchedule(prof, desired, end) && isFree(tenantId, prof.id, desired, addMin(end, eff.buffer))) chosen = desired;
    else {
      const alt = freeSlotsDay(tenantId, prof, sessionService, day, entryAppointment.start)
        .sort((a, b) => Math.abs(minutes(timeOf(a.start)) - minutes(baseTime)) - Math.abs(minutes(timeOf(b.start)) - minutes(baseTime)))[0];
      if (alt) chosen = alt.start;
    }
    if (!chosen) continue;
    try {
      sessions.push(book({ tenantId, clientId, serviceId: sessionService.id, professionalId: prof.id, start: chosen, createdBy, treatmentId, sessionNumber: sessions.length + 1, price: service.package_session_price, status: 'confirmado', force: true }));
    } catch { /* conflito raro: tenta o próximo dia */ }
  }
  return { treatment: get('SELECT * FROM treatments WHERE id=?', treatmentId), sessions };
}

export function getAppointment(id) {
  return get(`SELECT a.*, c.name AS client_name, c.phone AS client_phone, p.name AS professional_name, p.color,
              s.name AS service_name, s.preparation FROM appointments a JOIN clients c ON c.id=a.client_id
              JOIN professionals p ON p.id=a.professional_id JOIN services s ON s.id=a.service_id WHERE a.id=?`, id);
}

export function clientUpcoming(tenantId, clientId) {
  return all(`SELECT a.*, p.name AS professional_name, s.name AS service_name FROM appointments a
              JOIN professionals p ON p.id=a.professional_id JOIN services s ON s.id=a.service_id
              WHERE a.tenant_id=? AND a.client_id=? AND a.status IN ('pendente','confirmado') AND a.start >= ?
              ORDER BY a.start`, tenantId, clientId, nowLocal());
}

export function setStatus(id, status, extra = {}) {
  update('appointments', id, { status, ...extra });
  const a = getAppointment(id);
  if (a?.treatment_id) refreshTreatment(a.treatment_id);
  bus.emit('agenda', { tenantId: a.tenant_id, type: 'status', id, status });
  return a;
}

/** Política de cancelamento: o próprio cliente/agente só cancela ou remarca até X horas antes. */
export function withinCancelWindow(appt) {
  const t = tenantOf(appt.tenant_id);
  return appt.start > addMin(nowLocal(), Math.round((t.cancel_min_hours ?? 12) * 60));
}

export function cancel(id, { by = 'cliente', reason } = {}) {
  return setStatus(id, 'cancelado', { cancelled_by: by, cancel_reason: reason || null, recovery_sent: 0 });
}

export function reschedule(id, { start, professionalId, createdBy = 'agente' }) {
  const old = getAppointment(id);
  if (!old) throw new AppError('Agendamento não encontrado');
  const appt = book({
    tenantId: old.tenant_id, clientId: old.client_id, serviceId: old.service_id, professionalId: professionalId || old.professional_id,
    start, createdBy, treatmentId: old.treatment_id, sessionNumber: old.session_number, price: old.price, status: 'confirmado', force: !!old.session_number,
  });
  // faltas e cancelamentos continuam registrados (relatórios); os demais viram "remarcado"
  if (!['faltou', 'cancelado'].includes(old.status)) update('appointments', id, { status: 'remarcado' });
  update('appointments', id, { recovery_sent: 1 });
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

/** Melhores horários para repor um atendimento perdido (mesmo profissional primeiro, horário parecido). */
export function replacementOptions(appt, count = 2) {
  const same = findOptions(appt.tenant_id, appt.service_id, { professionalId: appt.professional_id, count: 6 });
  const pref = same.sort((a, b) => Math.abs(minutes(timeOf(a.start)) - minutes(timeOf(appt.start))) - Math.abs(minutes(timeOf(b.start)) - minutes(timeOf(appt.start))) || a.start.localeCompare(b.start));
  let opts = pref.slice(0, count);
  if (opts.length < count) opts = opts.concat(findOptions(appt.tenant_id, appt.service_id, { count }).filter((o) => !opts.find((x) => x.start === o.start && x.professional_id === o.professional_id))).slice(0, count);
  return opts.sort((a, b) => a.start.localeCompare(b.start)).map((o, i) => ({ ...o, option: i + 1 }));
}
export const nextSlotSameProfessional = (appt) => replacementOptions(appt, 1)[0] || null;
