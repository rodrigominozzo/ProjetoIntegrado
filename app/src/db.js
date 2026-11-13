// Banco de dados SQLite embutido (node:sqlite) — zero dependências nativas.
// Em produção, o mesmo schema migra 1:1 para PostgreSQL.
import { DatabaseSync } from 'node:sqlite';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const dataDir = process.env.DATA_DIR || path.join(here, '..', 'data');
fs.mkdirSync(dataDir, { recursive: true });
export const DB_PATH = path.join(dataDir, 'app.db');

export const db = new DatabaseSync(DB_PATH);
db.exec('PRAGMA journal_mode = WAL; PRAGMA foreign_keys = ON;');

db.exec(`
CREATE TABLE IF NOT EXISTS tenants (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  slug TEXT UNIQUE NOT NULL,
  segment TEXT NOT NULL DEFAULT 'clinica',
  address TEXT, city TEXT, lat REAL, lng REAL,
  phone TEXT, whatsapp_phone_number_id TEXT,
  hours_json TEXT NOT NULL DEFAULT '{}',
  terms_json TEXT NOT NULL DEFAULT '{}',
  agent_name TEXT DEFAULT 'Assistente',
  agent_tone TEXT DEFAULT 'acolhedor e objetivo',
  agent_instructions TEXT DEFAULT '',
  automation_active INTEGER NOT NULL DEFAULT 1,
  automation_cost_monthly REAL NOT NULL DEFAULT 0, -- legado (não usado)
  welcome_message TEXT,
  policies TEXT,             -- regras gerais que o agente informa (chegada, documentos, atraso...)
  insurances TEXT,           -- convênios aceitos (um por linha)
  payment_methods TEXT DEFAULT 'Pix, cartão de crédito/débito e dinheiro',
  min_advance_hours REAL NOT NULL DEFAULT 2,   -- antecedência mínima para agendar
  max_advance_days INTEGER NOT NULL DEFAULT 60,-- até quantos dias à frente
  slot_step_min INTEGER NOT NULL DEFAULT 15,   -- granularidade dos horários
  cancel_min_hours REAL NOT NULL DEFAULT 12,   -- cancelar/remarcar sozinho até X horas antes
  options_count INTEGER NOT NULL DEFAULT 2,    -- quantas opções de horário oferecer
  quiet_start TEXT NOT NULL DEFAULT '20:00',   -- não enviar mensagens proativas entre
  quiet_end TEXT NOT NULL DEFAULT '08:00',
  reoffer_cancel INTEGER NOT NULL DEFAULT 1,   -- após cancelamento, oferecer nova data
  waitlist_enabled INTEGER NOT NULL DEFAULT 1, -- lista de espera / encaixe automático
  reactivation_days INTEGER NOT NULL DEFAULT 10, -- tratamento parado há X dias → convidar a retomar
  return_reminder INTEGER NOT NULL DEFAULT 1,  -- avisar quando chega a hora do retorno
  reminder_hours_before INTEGER NOT NULL DEFAULT 24,
  noshow_recovery INTEGER NOT NULL DEFAULT 1,
  auto_book_package INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  tenant_id INTEGER REFERENCES tenants(id) ON DELETE CASCADE,
  name TEXT NOT NULL, email TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL,
  role TEXT NOT NULL DEFAULT 'recepcao', -- superadmin | admin | recepcao | profissional
  professional_id INTEGER,
  active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS professionals (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  name TEXT NOT NULL, specialty TEXT, council TEXT, registry TEXT, color TEXT DEFAULT '#3b82f6',
  email TEXT, phone TEXT, bio TEXT,
  commission_pct REAL NOT NULL DEFAULT 0,       -- repasse padrão (%)
  buffer_min INTEGER NOT NULL DEFAULT 0,        -- intervalo entre atendimentos deste profissional
  schedule_json TEXT NOT NULL DEFAULT '{}',
  active INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS services (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  name TEXT NOT NULL, description TEXT,
  category TEXT DEFAULT 'Consultas',
  duration_min INTEGER NOT NULL DEFAULT 60,
  buffer_min INTEGER NOT NULL DEFAULT 0,        -- preparo/limpeza da sala após o procedimento
  price REAL NOT NULL DEFAULT 0,
  cost REAL NOT NULL DEFAULT 0,                 -- custo direto (insumos, material)
  modality TEXT NOT NULL DEFAULT 'presencial',  -- presencial | online | ambos
  preparation TEXT,                             -- orientações de preparo enviadas ao cliente
  return_days INTEGER NOT NULL DEFAULT 0,       -- retorno incluso em até X dias
  online_booking INTEGER NOT NULL DEFAULT 1,    -- o agente/cliente pode agendar sozinho
  min_age INTEGER, max_age INTEGER,
  is_entry INTEGER NOT NULL DEFAULT 0,         -- serviço "porta de entrada" (ex.: avaliação)
  package_sessions INTEGER NOT NULL DEFAULT 0, -- nº de sessões do pacote após a entrada
  package_session_price REAL NOT NULL DEFAULT 0,
  package_service_id INTEGER,                  -- serviço usado nas sessões do pacote
  sessions_per_week INTEGER NOT NULL DEFAULT 2,
  requires_document INTEGER NOT NULL DEFAULT 0,
  document_label TEXT,
  keywords TEXT DEFAULT '',
  active INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS professional_services (
  professional_id INTEGER NOT NULL REFERENCES professionals(id) ON DELETE CASCADE,
  service_id INTEGER NOT NULL REFERENCES services(id) ON DELETE CASCADE,
  duration_min INTEGER,  -- personalização: este profissional leva X minutos neste procedimento
  price REAL,            -- personalização: preço deste profissional
  commission_pct REAL,   -- personalização: repasse deste procedimento
  PRIMARY KEY (professional_id, service_id)
);
CREATE TABLE IF NOT EXISTS clients (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  name TEXT, phone TEXT NOT NULL, email TEXT, birthdate TEXT, document TEXT,
  notes TEXT, tags TEXT DEFAULT '', source TEXT DEFAULT 'whatsapp',
  consent_lgpd INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE (tenant_id, phone)
);
CREATE TABLE IF NOT EXISTS treatments (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
  service_id INTEGER NOT NULL REFERENCES services(id),
  professional_id INTEGER REFERENCES professionals(id),
  total_sessions INTEGER NOT NULL,
  session_price REAL NOT NULL DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'ativo', -- ativo | concluido | abandonado | cancelado
  created_by TEXT DEFAULT 'agente',
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS appointments (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
  professional_id INTEGER NOT NULL REFERENCES professionals(id),
  service_id INTEGER NOT NULL REFERENCES services(id),
  treatment_id INTEGER REFERENCES treatments(id) ON DELETE SET NULL,
  session_number INTEGER,
  start TEXT NOT NULL, end TEXT NOT NULL,  -- horário local da empresa: YYYY-MM-DDTHH:MM
  status TEXT NOT NULL DEFAULT 'pendente', -- pendente | confirmado | realizado | faltou | cancelado | remarcado
  price REAL NOT NULL DEFAULT 0,
  cost REAL NOT NULL DEFAULT 0,        -- custo direto no momento do agendamento
  commission REAL NOT NULL DEFAULT 0,  -- repasse ao profissional (R$)
  created_by TEXT NOT NULL DEFAULT 'recepcao', -- agente | recepcao | cliente
  cancelled_by TEXT, cancel_reason TEXT,
  rescheduled_from INTEGER,
  reminder_sent INTEGER NOT NULL DEFAULT 0,
  recovery_sent INTEGER NOT NULL DEFAULT 0,
  notes TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_appt_time ON appointments(tenant_id, start);
CREATE TABLE IF NOT EXISTS blocks (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  professional_id INTEGER, start TEXT NOT NULL, end TEXT NOT NULL, reason TEXT
);
CREATE TABLE IF NOT EXISTS conversations (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
  channel TEXT NOT NULL DEFAULT 'simulador', -- simulador | whatsapp
  mode TEXT NOT NULL DEFAULT 'bot',           -- bot | humano
  unread INTEGER NOT NULL DEFAULT 0,
  triage_json TEXT, state_json TEXT NOT NULL DEFAULT '{}',
  last_message_at TEXT NOT NULL DEFAULT (datetime('now')),
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  conversation_id INTEGER NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
  sender TEXT NOT NULL, -- cliente | agente | humano | sistema
  type TEXT NOT NULL DEFAULT 'text', -- text | audio | image | options | location | appointment | note
  content TEXT, meta_json TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS documents (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
  kind TEXT, mime TEXT, data_b64 TEXT, extracted TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS automation_logs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  tenant_id INTEGER NOT NULL, conversation_id INTEGER,
  step TEXT NOT NULL, detail TEXT, ms INTEGER,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS payments (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
  treatment_id INTEGER, appointment_id INTEGER,
  amount REAL NOT NULL, method TEXT DEFAULT 'pix', status TEXT DEFAULT 'pago',
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS waitlist (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
  service_id INTEGER NOT NULL REFERENCES services(id) ON DELETE CASCADE,
  professional_id INTEGER, period TEXT, date_from TEXT, notes TEXT,
  status TEXT NOT NULL DEFAULT 'aguardando', -- aguardando | oferecido | atendido | cancelado
  offered_json TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS security_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  tenant_id INTEGER, kind TEXT NOT NULL, source TEXT, detail TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS integrations (
  tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  key TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 0, config_json TEXT NOT NULL DEFAULT '{}',
  PRIMARY KEY (tenant_id, key)
);
CREATE TABLE IF NOT EXISTS audit_logs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  tenant_id INTEGER, user_id INTEGER, action TEXT, entity TEXT, entity_id INTEGER, detail TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
`);

// Migração leve: adiciona colunas novas em bancos já existentes
for (const [table, ddl] of Object.entries({
  tenants: ['welcome_message TEXT', 'policies TEXT', 'insurances TEXT', "payment_methods TEXT", 'min_advance_hours REAL NOT NULL DEFAULT 2', 'max_advance_days INTEGER NOT NULL DEFAULT 60',
    'slot_step_min INTEGER NOT NULL DEFAULT 15', 'cancel_min_hours REAL NOT NULL DEFAULT 12', 'options_count INTEGER NOT NULL DEFAULT 2', "quiet_start TEXT NOT NULL DEFAULT '20:00'",
    "quiet_end TEXT NOT NULL DEFAULT '08:00'", 'reoffer_cancel INTEGER NOT NULL DEFAULT 1', 'waitlist_enabled INTEGER NOT NULL DEFAULT 1', 'reactivation_days INTEGER NOT NULL DEFAULT 10', 'return_reminder INTEGER NOT NULL DEFAULT 1'],
  professionals: ['council TEXT', 'email TEXT', 'phone TEXT', 'bio TEXT', 'commission_pct REAL NOT NULL DEFAULT 0', 'buffer_min INTEGER NOT NULL DEFAULT 0'],
  services: ["category TEXT DEFAULT 'Consultas'", 'buffer_min INTEGER NOT NULL DEFAULT 0', 'cost REAL NOT NULL DEFAULT 0', "modality TEXT NOT NULL DEFAULT 'presencial'", 'preparation TEXT',
    'return_days INTEGER NOT NULL DEFAULT 0', 'online_booking INTEGER NOT NULL DEFAULT 1', 'min_age INTEGER', 'max_age INTEGER'],
  professional_services: ['duration_min INTEGER', 'price REAL', 'commission_pct REAL'],
  appointments: ['cost REAL NOT NULL DEFAULT 0', 'commission REAL NOT NULL DEFAULT 0', 'cancelled_by TEXT', 'cancel_reason TEXT'],
})) {
  const cols = new Set(db.prepare(`PRAGMA table_info(${table})`).all().map((c) => c.name));
  for (const d of ddl) if (!cols.has(d.split(' ')[0])) db.exec(`ALTER TABLE ${table} ADD COLUMN ${d}`);
}

// Helpers
export const all = (sql, ...p) => db.prepare(sql).all(...p);
export const get = (sql, ...p) => db.prepare(sql).get(...p);
export const run = (sql, ...p) => db.prepare(sql).run(...p);
export const insert = (table, obj) => {
  const keys = Object.keys(obj);
  const r = run(`INSERT INTO ${table} (${keys.join(',')}) VALUES (${keys.map(() => '?').join(',')})`, ...keys.map((k) => obj[k]));
  return Number(r.lastInsertRowid);
};
export const update = (table, id, obj, idCol = 'id') => {
  const keys = Object.keys(obj);
  if (!keys.length) return;
  run(`UPDATE ${table} SET ${keys.map((k) => `${k}=?`).join(',')} WHERE ${idCol}=?`, ...keys.map((k) => obj[k]), id);
};
export const parse = (s, d = {}) => { try { return s ? JSON.parse(s) : d; } catch { return d; } };
