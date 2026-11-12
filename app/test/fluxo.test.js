// Testes de ponta a ponta do fluxo do vídeo usando o agente de regras (sem chave de IA).
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

process.env.DATA_DIR = fs.mkdtempSync(path.join(os.tmpdir(), 'atende-'));
process.env.AGENT_MODE = 'rules';
const { seed } = await import('../src/seed.js');
const { handleIncoming } = await import('../src/agent/index.js');
const { all, get } = await import('../src/db.js');
const sched = await import('../src/services/scheduling.js');
const { recoverNoShow } = await import('../src/services/jobs.js');
seed();

const phone = '11912345678';
const msgs = () => all(`SELECT m.* FROM messages m JOIN conversations c ON c.id=m.conversation_id JOIN clients k ON k.id=c.client_id WHERE k.phone=? ORDER BY m.id`, phone);
const say = (text, extra = {}) => handleIncoming({ tenantId: 1, phone, name: 'Carlos Martins', type: 'text', text, ...extra });

test('áudio → pede pedido médico → oferece 2 horários de profissionais diferentes', async () => {
  await handleIncoming({ tenantId: 1, phone, name: 'Carlos Martins', type: 'audio', transcript: 'Travei a lombar, tô com muita dor. Queria começar fisioterapia.' });
  assert.match(msgs().at(-1).content, /pedido médico/);
  await handleIncoming({ tenantId: 1, phone, type: 'image', image: { b64: 'iVBORw0KGgo=', mime: 'image/png' } });
  const opt = msgs().findLast((m) => m.type === 'options');
  const options = JSON.parse(opt.meta_json).options;
  assert.equal(options.length, 2);
  assert.notEqual(options[0].professional_id, options[1].professional_id);
});

test('escolha → agenda avaliação + reserva 10 sessões + envia localização', async () => {
  await say('1');
  const types = msgs().map((m) => m.type);
  assert.ok(types.includes('appointment') && types.includes('package') && types.includes('location'));
  const client = get('SELECT * FROM clients WHERE phone=?', phone);
  const t = get('SELECT * FROM treatments WHERE client_id=?', client.id);
  assert.equal(t.total_sessions, 10);
  assert.equal(get('SELECT COUNT(*) n FROM appointments WHERE treatment_id=? AND session_number IS NOT NULL', t.id).n, 10);
});

test('nenhum horário duplicado para o mesmo profissional', () => {
  const clash = get(`SELECT COUNT(*) n FROM appointments a JOIN appointments b ON a.professional_id=b.professional_id AND a.id<b.id
    AND a.start < b.end AND a.end > b.start WHERE a.status IN ('pendente','confirmado','realizado') AND b.status IN ('pendente','confirmado','realizado')`);
  assert.equal(clash.n, 0);
});

test('falta → IA oferece remarcação → cliente aceita → sessão remarcada', async () => {
  const client = get('SELECT * FROM clients WHERE phone=?', phone);
  const s = get('SELECT * FROM appointments WHERE client_id=? AND session_number=4', client.id);
  const a = sched.setStatus(s.id, 'faltou');
  recoverNoShow(get('SELECT * FROM tenants WHERE id=1'), a);
  assert.match(msgs().at(-1).content, /Sentimos sua falta/);
  await say('Quero sim!');
  const novo = get('SELECT * FROM appointments WHERE rescheduled_from=?', s.id);
  assert.ok(novo, 'nova sessão criada');
  assert.equal(novo.session_number, 4);
});

test('emergência é transferida para humano', async () => {
  await say('estou com dor no peito e falta de ar');
  const c = get('SELECT c.mode FROM conversations c JOIN clients k ON k.id=c.client_id WHERE k.phone=?', phone);
  assert.equal(c.mode, 'humano');
});
