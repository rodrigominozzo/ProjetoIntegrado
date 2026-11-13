import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import { get, DB_PATH } from '../db.js';

// Segredo de assinatura: APP_SECRET (obrigatório em produção) ou um segredo aleatório salvo na pasta de dados.
function loadSecret() {
  if (process.env.APP_SECRET) return process.env.APP_SECRET;
  const f = path.join(path.dirname(DB_PATH), '.secret');
  try { return fs.readFileSync(f, 'utf8'); } catch {}
  const s = crypto.randomBytes(32).toString('hex');
  fs.writeFileSync(f, s, { mode: 0o600 });
  return s;
}
const SECRET = loadSecret();

export function hashPassword(pw) {
  const salt = crypto.randomBytes(16).toString('hex');
  return `${salt}:${crypto.scryptSync(pw, salt, 32).toString('hex')}`;
}
export function checkPassword(pw, stored) {
  const [salt, hash] = String(stored).split(':');
  if (!salt || !hash) return false;
  const h = crypto.scryptSync(String(pw), salt, 32).toString('hex');
  return crypto.timingSafeEqual(Buffer.from(h), Buffer.from(hash));
}

// Token assinado (HMAC) simples: base64url(payload).assinatura
export function sign(payload, ttlHours = 12) {
  const body = Buffer.from(JSON.stringify({ ...payload, exp: Date.now() + ttlHours * 3600e3 })).toString('base64url');
  return `${body}.${crypto.createHmac('sha256', SECRET).update(body).digest('base64url')}`;
}
export function verify(token) {
  const [body, sig] = String(token || '').split('.');
  if (!body || !sig) return null;
  const exp = crypto.createHmac('sha256', SECRET).update(body).digest('base64url');
  if (sig.length !== exp.length || !crypto.timingSafeEqual(Buffer.from(sig), Buffer.from(exp))) return null;
  let p; try { p = JSON.parse(Buffer.from(body, 'base64url').toString()); } catch { return null; }
  return p.exp > Date.now() ? p : null;
}
const tokenOf = (req) => (req.headers.authorization || '').replace(/^Bearer /, '') || req.query.token;

/** Middleware do painel. Superadmin pode atuar em qualquer empresa via cabeçalho X-Tenant. */
export function requireUser(roles) {
  return (req, res, next) => {
    const p = verify(tokenOf(req));
    if (!p?.uid) return res.status(401).json({ error: 'Não autenticado' });
    const user = get('SELECT id, tenant_id, name, email, role, professional_id, password_hash FROM users WHERE id=? AND active=1', p.uid);
    // token deixa de valer se o usuário foi desativado ou trocou a senha
    if (!user || (p.v && user.password_hash.slice(0, 8) !== p.v)) return res.status(401).json({ error: 'Sessão inválida' });
    delete user.password_hash;
    if (roles && !roles.includes(user.role) && user.role !== 'superadmin') return res.status(403).json({ error: 'Sem permissão' });
    req.user = user;
    if (user.role === 'superadmin') {
      const wanted = Number(req.headers['x-tenant'] || req.query.tenant || user.tenant_id || 0);
      req.tenantId = get('SELECT id FROM tenants WHERE id=?', wanted)?.id || get('SELECT MIN(id) id FROM tenants')?.id;
    } else req.tenantId = user.tenant_id;
    next();
  };
}

/** Middleware do app do cliente (identificado por empresa + telefone). */
export function requireClient(req, res, next) {
  const p = verify(tokenOf(req));
  if (!p?.cid) return res.status(401).json({ error: 'Não autenticado' });
  req.client = get('SELECT * FROM clients WHERE id=?', p.cid);
  if (!req.client) return res.status(401).json({ error: 'Cliente inválido' });
  req.tenantId = req.client.tenant_id;
  next();
}
