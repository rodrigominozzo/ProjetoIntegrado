// Dados de demonstração: Clínica Movimento (fisioterapia, como no vídeo) + Sorriso (odontologia),
// para mostrar que a plataforma é genérica.
import { db, get, insert, all, update } from './db.js';
import { hashPassword } from './services/auth.js';
import { SEGMENTS, DEFAULT_HOURS, DEFAULT_SCHEDULE } from './services/presets.js';
import { nowLocal, addDays, dateOf, weekday, addMin } from './services/time.js';
import { book, reservePackage } from './services/scheduling.js';

export function createTenant({ name, slug, segment, address, city, lat, lng, phone, agent_name, cost = 3000 }) {
  const id = insert('tenants', {
    name, slug, segment, address, city, lat, lng, phone, agent_name: agent_name || 'Assistente',
    hours_json: JSON.stringify(DEFAULT_HOURS), automation_cost_monthly: cost,
  });
  const ids = {};
  for (const { package_of, ...s } of SEGMENTS[segment]?.services || SEGMENTS.generico.services) ids[s.name] = insert('services', { tenant_id: id, ...s });
  for (const s of SEGMENTS[segment]?.services || []) if (s.package_of) update('services', ids[s.name], { package_service_id: ids[s.package_of] });
  for (const key of ['whatsapp', 'ia', 'transcricao', 'google_calendar', 'pagamentos', 'mapas']) insert('integrations', { tenant_id: id, key });
  return id;
}

function addProfessional(tenantId, name, specialty, color, serviceIds) {
  const id = insert('professionals', { tenant_id: tenantId, name, specialty, color, schedule_json: JSON.stringify(DEFAULT_SCHEDULE) });
  for (const s of serviceIds) insert('professional_services', { professional_id: id, service_id: s });
  return id;
}

export function seed() {
  if (get('SELECT COUNT(*) n FROM tenants').n > 0) return false;
  db.exec('BEGIN');
  try {
    insert('users', { tenant_id: null, name: 'Administrador da Plataforma', email: 'admin@atende.ai', password_hash: hashPassword('admin123'), role: 'superadmin' });

    // --- Clínica Movimento (Fisioterapia) ---
    const t1 = createTenant({ name: 'Clínica Movimento', slug: 'clinica-movimento', segment: 'fisioterapia', address: 'R. das Palmeiras, 210 - Centro', city: 'São Paulo/SP', lat: -23.5505, lng: -46.6333, phone: '11999990001', agent_name: 'Lia', cost: 3000 });
    const s1 = all('SELECT id FROM services WHERE tenant_id=?', t1).map((s) => s.id);
    const ana = addProfessional(t1, 'Dra. Ana', 'Ortopedia e coluna', '#22c55e', s1);
    const lucas = addProfessional(t1, 'Dr. Lucas', 'Esportiva', '#3b82f6', s1);
    insert('users', { tenant_id: t1, name: 'Gestor Movimento', email: 'gestor@movimento.com', password_hash: hashPassword('123456'), role: 'admin' });
    insert('users', { tenant_id: t1, name: 'Recepção Movimento', email: 'recepcao@movimento.com', password_hash: hashPassword('123456'), role: 'recepcao' });

    // Agenda já ocupada para ficar realista (como no vídeo: Júlia, Pedro, Marta, Davi, Nina...)
    const pac = ['Júlia R.', 'Pedro S.', 'Marta L.', 'Bia T.', 'Leo F.', 'Davi P.', 'Nina A.', 'Caio M.', 'Lia R.', 'Iara N.'];
    const cids = pac.map((n, i) => insert('clients', { tenant_id: t1, name: n, phone: `1198888${String(1000 + i)}`, consent_lgpd: 1, source: 'recepcao' }));
    const today = dateOf(nowLocal());
    const eval1 = s1[1]; // sessões de fisioterapia
    for (let d = -14; d <= 10; d++) {
      const day = addDays(today, d);
      if ([0, 6].includes(weekday(day))) continue;
      const slotsAna = ['08:00', '09:00', '10:00', '17:00', '18:30'];
      const slotsLucas = ['07:00', '08:00', '09:00', '10:00', '17:00'];
      slotsAna.forEach((h, i) => { if ((d + i) % 3 !== 0) appt(t1, cids[i], ana, eval1, `${day}T${h}`, d); });
      slotsLucas.forEach((h, i) => { if ((d + i) % 4 !== 1) appt(t1, cids[5 + i], lucas, eval1, `${day}T${h}`, d); });
    }
    // Pacientes "recuperados" pelo agente fora do horário (como no vídeo: Carlos, Marina, João → 3 x R$ 1.200)
    seedAgentPatients(t1, s1[0], [ana, lucas]);
    // --- Sorriso Odontologia ---
    const t2 = createTenant({ name: 'Sorriso Odontologia', slug: 'sorriso-odonto', segment: 'odontologia', address: 'Av. Brasil, 1500 - Sala 32', city: 'Campinas/SP', lat: -22.9056, lng: -47.0608, phone: '19999990002', agent_name: 'Bia', cost: 1500 });
    const s2 = all('SELECT id FROM services WHERE tenant_id=?', t2).map((s) => s.id);
    addProfessional(t2, 'Dr. Rafael', 'Clínico geral', '#f59e0b', s2);
    addProfessional(t2, 'Dra. Camila', 'Ortodontia', '#a855f7', s2);
    insert('users', { tenant_id: t2, name: 'Gestora Sorriso', email: 'gestor@sorriso.com', password_hash: hashPassword('123456'), role: 'admin' });
    db.exec('COMMIT');
  } catch (e) { db.exec('ROLLBACK'); throw e; }
  return true;
}

function appt(tenantId, clientId, profId, serviceId, start, d) {
  const status = d < 0 ? (Math.abs(d * 7 + start.length) % 9 === 0 ? 'faltou' : 'realizado') : 'confirmado';
  insert('appointments', { tenant_id: tenantId, client_id: clientId, professional_id: profId, service_id: serviceId, start, end: addMin(start, 60), status, price: 120, created_by: 'recepcao', reminder_sent: 1, recovery_sent: 1, created_at: start.slice(0, 10) > dateOf(nowLocal()) ? `${addDays(dateOf(nowLocal()), -1 - (clientId % 9))} 14:00:00` : `${addDays(start.slice(0, 10), -5)} 14:00:00` });
}

if (process.argv[1] && process.argv[1].endsWith('seed.js')) { console.log(seed() ? 'Seed criado.' : 'Banco já possui dados.'); }


function seedAgentPatients(tenantId, entryServiceId, profs) {
  const people = [['Marina Costa', '11966660001', -9, '22:41'], ['João Pereira', '11966660002', -5, '23:12'], ['Rafaela Souza', '11966660003', -2, '06:15']];
  people.forEach(([name, phone, d, at], i) => {
    const clientId = insert('clients', { tenant_id: tenantId, name, phone, source: 'whatsapp', consent_lgpd: 1 });
    let day = addDays(dateOf(nowLocal()), d + 1);
    while ([0, 6].includes(weekday(day))) day = addDays(day, 1);
    const start = `${day}T${['13:00', '14:00', '15:00'][i]}`;
    const a = book({ tenantId, clientId, serviceId: entryServiceId, professionalId: profs[i % 2], start, createdBy: 'agente', status: 'confirmado' });
    reservePackage({ tenantId, clientId, entryAppointment: a, createdBy: 'agente' });
    // horário de criação em UTC equivalente ao horário local (fora do expediente)
    const created = new Date(`${addDays(dateOf(nowLocal()), d)}T${at}:00-03:00`).toISOString().slice(0, 19).replace('T', ' ');
    db.prepare("UPDATE appointments SET created_at=?, reminder_sent=1 WHERE client_id=?").run(created, clientId);
    db.prepare("UPDATE appointments SET status='realizado' WHERE client_id=? AND start < ?").run(clientId, nowLocal());
    const convId = insert('conversations', { tenant_id: tenantId, client_id: clientId, channel: 'whatsapp', last_message_at: created, triage_json: JSON.stringify({ queixa: 'Dor e vontade de iniciar tratamento', pontos: ['quer começar fisioterapia'], urgencia: 'normal' }) });
    insert('messages', { conversation_id: convId, sender: 'cliente', type: 'text', content: 'Oi! Vocês têm horário pra fisioterapia?', created_at: created });
    insert('messages', { conversation_id: convId, sender: 'agente', type: 'text', content: `Oi, ${name.split(' ')[0]}! Temos sim. Já deixei sua avaliação e as 10 sessões reservadas. ✅`, created_at: created });
    for (const [step, ms] of [['whatsapp', 0], ['transcreve', 6000], ['agente_ia', 8000], ['agenda', 17000], ['agendamento', 900], ['responde', 49000]]) insert('automation_logs', { tenant_id: tenantId, conversation_id: convId, step, ms, created_at: created });
  });
}
