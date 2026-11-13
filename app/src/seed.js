// Dados de demonstração: "Clínica Vida Integrada" (multiespecialidade) + "Sorriso Odontologia".
import { db, get, insert, all, update } from './db.js';
import { hashPassword } from './services/auth.js';
import { SEGMENTS, DEFAULT_HOURS, DEFAULT_SCHEDULE } from './services/presets.js';
import { nowLocal, addDays, dateOf, weekday, addMin } from './services/time.js';
import { book, reservePackage, effective, isFree } from './services/scheduling.js';

export function createTenant({ name, slug, segment, address, city, lat, lng, phone, agent_name, insurances, policies }) {
  const id = insert('tenants', {
    name, slug, segment, address, city, lat, lng, phone, agent_name: agent_name || 'Assistente', agent_tone: 'humano, acolhedor e direto',
    hours_json: JSON.stringify(DEFAULT_HOURS), insurances: insurances || null, policies: policies || null,
  });
  const ids = {};
  const list = SEGMENTS[segment]?.services || SEGMENTS.generico.services;
  for (const { package_of, ...s } of list) ids[s.name] = insert('services', { tenant_id: id, ...s });
  for (const s of list) if (s.package_of) update('services', ids[s.name], { package_service_id: ids[s.package_of] });
  for (const key of ['whatsapp', 'ia', 'transcricao', 'google_calendar', 'pagamentos', 'mapas']) insert('integrations', { tenant_id: id, key });
  return id;
}

function prof(tenantId, p, services) {
  const id = insert('professionals', { tenant_id: tenantId, name: p.name, specialty: p.specialty, council: p.council, registry: p.registry, color: p.color, commission_pct: p.commission ?? 40, schedule_json: JSON.stringify(p.schedule || DEFAULT_SCHEDULE), bio: p.bio || null });
  for (const [svcId, o = {}] of services) insert('professional_services', { professional_id: id, service_id: svcId, duration_min: o.duration ?? null, price: o.price ?? null, commission_pct: o.commission ?? null });
  return id;
}

export function seed() {
  if (get('SELECT COUNT(*) n FROM tenants').n > 0) return false;
  db.exec('BEGIN');
  try {
    insert('users', { tenant_id: null, name: 'Administrador da Plataforma', email: 'admin@atende.ai', password_hash: hashPassword('admin123'), role: 'superadmin' });

    const t1 = createTenant({
      name: 'Clínica Vida Integrada', slug: 'vida-integrada', segment: 'clinica', address: 'Av. Paulista, 1000 - 5º andar', city: 'São Paulo/SP', lat: -23.5649, lng: -46.6519, phone: '1133330000', agent_name: 'Lia',
      insurances: 'Unimed, Bradesco Saúde, SulAmérica', policies: 'Chegue 10 minutos antes com documento com foto. Atrasos acima de 15 minutos podem exigir remarcação.',
    });
    const S = Object.fromEntries(all('SELECT id, name FROM services WHERE tenant_id=?', t1).map((s) => [s.name, s.id]));
    const manha = { 1: [['07:00', '12:00']], 2: [['07:00', '12:00']], 3: [['07:00', '12:00']], 4: [['07:00', '12:00']], 5: [['07:00', '12:00']] };
    const tarde = { 1: [['13:00', '19:00']], 2: [['13:00', '19:00']], 3: [['13:00', '19:00']], 4: [['13:00', '19:00']], 5: [['13:00', '19:00']], 6: [['08:00', '12:00']] };
    const P = {
      paulo: prof(t1, { name: 'Dr. Paulo Mendes', specialty: 'Clínica geral', council: 'CRM-SP', registry: '123456', color: '#22c55e', commission: 40 }, [[S['Consulta clínica geral']], [S['Eletrocardiograma']]]),
      // personalização: a Dra. Carla faz a consulta clínica em 40 min e cobra R$ 280
      carla: prof(t1, { name: 'Dra. Carla Nunes', specialty: 'Clínica geral e geriatria', council: 'CRM-SP', registry: '234567', color: '#14b8a6', schedule: tarde, commission: 45 }, [[S['Consulta clínica geral'], { duration: 40, price: 280 }], [S['Eletrocardiograma']]]),
      helena: prof(t1, { name: 'Dra. Helena Rocha', specialty: 'Dermatologia', council: 'CRM-SP / RQE', registry: '345678', color: '#f97316', commission: 50 }, [[S['Consulta dermatológica']], [S['Remoção de sinal / lesão de pele']], [S['Peeling químico'], { duration: 60, commission: 35 }]]),
      lucas: prof(t1, { name: 'Dr. Lucas Prado', specialty: 'Pediatria', council: 'CRM-SP', registry: '456789', color: '#3b82f6', schedule: manha }, [[S['Consulta pediátrica']]]),
      beatriz: prof(t1, { name: 'Dra. Beatriz Lima', specialty: 'Ginecologia', council: 'CRM-SP', registry: '567890', color: '#ec4899', schedule: tarde }, [[S['Consulta ginecológica']]]),
      marina: prof(t1, { name: 'Marina Lopes', specialty: 'Nutrição', council: 'CRN-3', registry: '67890', color: '#84cc16', commission: 50 }, [[S['Consulta nutricional']], [S['Bioimpedância']]]),
      julia: prof(t1, { name: 'Júlia Castro', specialty: 'Psicologia', council: 'CRP-06', registry: '78901', color: '#a855f7', commission: 60, schedule: tarde }, [[S['Sessão de psicoterapia']]]),
      ana: prof(t1, { name: 'Dra. Ana Souza', specialty: 'Fisioterapia ortopédica', council: 'CREFITO-3', registry: '89012-F', color: '#eab308', commission: 50 }, [[S['Avaliação de fisioterapia']], [S['Sessão de fisioterapia']]]),
    };
    insert('users', { tenant_id: t1, name: 'Gestor Vida Integrada', email: 'gestor@vidaintegrada.com', password_hash: hashPassword('gestor123'), role: 'admin' });
    insert('users', { tenant_id: t1, name: 'Recepção', email: 'recepcao@vidaintegrada.com', password_hash: hashPassword('recepcao123'), role: 'recepcao' });
    insert('users', { tenant_id: t1, name: 'Dra. Helena Rocha', email: 'helena@vidaintegrada.com', password_hash: hashPassword('helena123'), role: 'profissional', professional_id: P.helena });

    const nomes = ['Júlia Ramos', 'Pedro Silva', 'Marta Lima', 'Bia Torres', 'Leo Faria', 'Davi Prado', 'Nina Alves', 'Caio Melo', 'Lia Rocha', 'Iara Nunes', 'Rui Costa', 'Sofia Dias', 'Theo Reis', 'Luna Paz', 'Enzo Cruz', 'Alice Mota', 'Gabriel Sá', 'Helena Vaz', 'Igor Leal', 'Clara Brito', 'Otávio Luz', 'Vera Pinto', 'Diego Assis', 'Rosa Freitas'];
    const cids = nomes.map((n, i) => insert('clients', { tenant_id: t1, name: n, phone: `11988${String(100000 + i * 137)}`, consent_lgpd: 1, source: i % 3 ? 'whatsapp' : 'recepcao' }));
    fillAgenda(t1, cids);
    seedAgentPatients(t1, S, P);
    insert('waitlist', { tenant_id: t1, client_id: cids[3], service_id: S['Consulta dermatológica'], professional_id: P.helena, notes: 'Prefere fim de tarde' });

    // --- Segunda empresa (mostra que a plataforma é genérica) ---
    const t2 = createTenant({ name: 'Sorriso Odontologia', slug: 'sorriso-odonto', segment: 'odontologia', address: 'Av. Brasil, 1500 - Sala 32', city: 'Campinas/SP', lat: -22.9056, lng: -47.0608, phone: '1933330002', agent_name: 'Bia', insurances: 'OdontoPrev, Amil Dental' });
    const s2 = all('SELECT id FROM services WHERE tenant_id=?', t2).map((s) => [s.id]);
    prof(t2, { name: 'Dr. Rafael Moura', specialty: 'Clínico geral', council: 'CRO-SP', registry: '11223', color: '#f59e0b' }, s2);
    prof(t2, { name: 'Dra. Camila Reis', specialty: 'Ortodontia', council: 'CRO-SP', registry: '33445', color: '#a855f7' }, s2.map(([id]) => [id, { duration: null }]));
    insert('users', { tenant_id: t2, name: 'Gestora Sorriso', email: 'gestor@sorriso.com', password_hash: hashPassword('gestor123'), role: 'admin' });
    db.exec('COMMIT');
  } catch (e) { db.exec('ROLLBACK'); throw e; }
  return true;
}

/** Agenda realista: ~55% de ocupação, passado (realizado/faltou/cancelado) e futuro (confirmado). */
function fillAgenda(tenantId, cids) {
  const today = dateOf(nowLocal());
  let k = 0;
  const profs = all('SELECT * FROM professionals WHERE tenant_id=?', tenantId);
  for (let d = -21; d <= 12; d++) {
    const day = addDays(today, d);
    for (const p of profs) {
      const svcs = all('SELECT s.* FROM services s JOIN professional_services ps ON ps.service_id=s.id WHERE ps.professional_id=? AND s.online_booking=1', p.id);
      const wins = JSON.parse(p.schedule_json)[weekday(day)] || [];
      for (const [a, b] of wins) {
        let cur = `${day}T${a}`;
        while (cur < `${day}T${b}`) {
          k++;
          const svc = svcs[k % svcs.length];
          const eff = effective(svc.id, p.id);
          const end = addMin(cur, eff.duration);
          if (end > `${day}T${b}`) break;
          if ((k * 7) % 11 < 6 && isFree(tenantId, p.id, cur, addMin(end, eff.buffer))) {
            const past = d < 0 || (d === 0 && cur < nowLocal());
            const status = past ? ((k % 13 === 0) ? 'faltou' : (k % 17 === 0) ? 'cancelado' : 'realizado') : 'confirmado';
            insert('appointments', {
              tenant_id: tenantId, client_id: cids[k % cids.length], professional_id: p.id, service_id: svc.id, start: cur, end, status,
              price: eff.price, cost: eff.cost, commission: Math.round(eff.price * eff.commissionPct) / 100, created_by: k % 4 === 0 ? 'agente' : 'recepcao',
              reminder_sent: 1, recovery_sent: 1, cancelled_by: status === 'cancelado' ? 'cliente' : null,
              created_at: `${addDays(day, -2 - (k % 6))} ${String(9 + (k % 9)).padStart(2, '0')}:15:00`,
            });
            cur = addMin(end, eff.buffer);
          } else cur = addMin(cur, 30);
        }
      }
    }
  }
}

/** Pacientes captados pelo agente fora do horário comercial (noite/madrugada). */
function seedAgentPatients(tenantId, S, P) {
  const people = [['Carla Menezes', '11966660001', -9, '22:41', S['Avaliação de fisioterapia'], P.ana], ['João Pereira', '11966660002', -5, '23:12', S['Consulta dermatológica'], P.helena], ['Rafaela Souza', '11966660003', -2, '06:15', S['Consulta clínica geral'], P.carla]];
  for (const [name, phone, d, at, svc, pid] of people) {
    const clientId = insert('clients', { tenant_id: tenantId, name, phone, source: 'whatsapp', consent_lgpd: 1 });
    let day = addDays(dateOf(nowLocal()), d + 2);
    while ([0, 6].includes(weekday(day))) day = addDays(day, 1);
    let a = null;
    for (const h of ['13:00', '14:00', '15:00', '16:00', '17:00', '08:00', '09:00', '10:00', '11:00']) {
      try { a = book({ tenantId, clientId, serviceId: svc, professionalId: pid, start: `${day}T${h}`, createdBy: 'agente', status: 'confirmado' }); break; } catch {}
    }
    if (!a) continue;
    reservePackage({ tenantId, clientId, entryAppointment: a, createdBy: 'agente' });
    const created = new Date(`${addDays(dateOf(nowLocal()), d)}T${at}:00-03:00`).toISOString().slice(0, 19).replace('T', ' ');
    db.prepare('UPDATE appointments SET created_at=?, reminder_sent=1, recovery_sent=1 WHERE client_id=?').run(created, clientId);
    db.prepare("UPDATE appointments SET status='realizado' WHERE client_id=? AND start < ?").run(clientId, nowLocal());
    const convId = insert('conversations', { tenant_id: tenantId, client_id: clientId, channel: 'whatsapp', last_message_at: created, triage_json: JSON.stringify({ queixa: 'Agendamento fora do horário', pontos: ['quer agendar'], urgencia: 'normal' }) });
    insert('messages', { conversation_id: convId, sender: 'cliente', type: 'text', content: 'Oi! Vocês têm horário essa semana?', created_at: created });
    insert('messages', { conversation_id: convId, sender: 'agente', type: 'text', content: `Oi, ${name.split(' ')[0]}! Tenho sim — já deixei seu horário confirmado. ✅`, created_at: created });
    for (const [step, ms] of [['whatsapp', 0], ['agente_ia', 3000], ['agenda', 900], ['agendamento', 700], ['responde', 6000]]) insert('automation_logs', { tenant_id: tenantId, conversation_id: convId, step, ms, created_at: created });
  }
}

if (process.argv[1] && process.argv[1].endsWith('seed.js')) { console.log(seed() ? 'Seed criado.' : 'Banco já possui dados.'); }
