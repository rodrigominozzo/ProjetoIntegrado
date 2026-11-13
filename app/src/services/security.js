// Proteções HTTP do sistema: cabeçalhos seguros, limite de requisições, bloqueio de força bruta,
// validação de entrada, assinatura do webhook e erros sem vazamento de detalhes internos.
import crypto from 'node:crypto';
import { securityEvent } from '../agent/guard.js';

export function securityHeaders(req, res, next) {
  res.setHeader('Content-Security-Policy', [
    "default-src 'self'", "script-src 'self'", "style-src 'self' 'unsafe-inline'", "img-src 'self' data: blob:",
    "media-src 'self' blob:", "connect-src 'self'", "font-src 'self' data:", "object-src 'none'", "base-uri 'self'", "form-action 'self'", "frame-ancestors 'none'",
  ].join('; '));
  res.setHeader('X-Content-Type-Options', 'nosniff');
  res.setHeader('X-Frame-Options', 'DENY');
  res.setHeader('Referrer-Policy', 'no-referrer');
  res.setHeader('Permissions-Policy', 'camera=(), geolocation=(), microphone=(self)');
  res.setHeader('Cross-Origin-Opener-Policy', 'same-origin');
  if (process.env.NODE_ENV === 'production') res.setHeader('Strict-Transport-Security', 'max-age=31536000; includeSubDomains');
  if (req.path.startsWith('/api/')) res.setHeader('Cache-Control', 'no-store');
  next();
}

const ip = (req) => String(req.headers['x-forwarded-for'] || req.socket.remoteAddress || '').split(',')[0].trim();
const hits = new Map();
setInterval(() => { const now = Date.now(); for (const [k, v] of hits) if (now - v.start > v.win) hits.delete(k); }, 60_000).unref();

/** Limite simples por IP e rota (em produção: Redis ou o próprio proxy/WAF). */
export function rateLimit({ key = 'api', max = 300, windowMs = 60_000 } = {}) {
  return (req, res, next) => {
    const k = `${key}:${ip(req)}`; const now = Date.now();
    let h = hits.get(k); if (!h || now - h.start > windowMs) { h = { start: now, n: 0, win: windowMs }; hits.set(k, h); }
    if (++h.n > max) {
      if (h.n === max + 1) securityEvent(null, 'rate_limit', ip(req), `${key} ${req.method} ${req.path}`);
      res.setHeader('Retry-After', Math.ceil((h.start + windowMs - now) / 1000));
      return res.status(429).json({ error: 'Muitas requisições. Aguarde um instante.' });
    }
    next();
  };
}

// Bloqueio de força bruta no login: 5 falhas por e-mail ou 20 por IP em 15 min → bloqueia 15 min
const fails = new Map();
export function loginBlocked(req, email) {
  const now = Date.now();
  for (const k of [`e:${email}`, `i:${ip(req)}`]) { const f = fails.get(k); if (f && f.until > now) return true; }
  return false;
}
export function loginFailed(req, email) {
  const now = Date.now();
  for (const [k, lim] of [[`e:${email}`, 5], [`i:${ip(req)}`, 20]]) {
    const f = fails.get(k) && now - fails.get(k).first < 15 * 60e3 ? fails.get(k) : { n: 0, first: now, until: 0 };
    f.n++; if (f.n >= lim) { f.until = now + 15 * 60e3; securityEvent(null, 'login_bloqueado', k, `${f.n} falhas`); }
    fails.set(k, f);
  }
  securityEvent(null, 'login_falhou', ip(req), email);
}
export function loginOk(email) { fails.delete(`e:${email}`); }

// Validação de entrada
export const V = {
  str: (v, max = 200) => (v == null ? v : String(v).slice(0, max)),
  phone: (v) => { const d = String(v || '').replace(/\D/g, ''); if (d.length < 10 || d.length > 13) throw new ValidationError('Telefone inválido'); return d; },
  email: (v) => { const s = String(v || '').trim().toLowerCase(); if (s && !/^[^\s@]{1,64}@[^\s@]{1,190}\.[^\s@]{2,}$/.test(s)) throw new ValidationError('E-mail inválido'); return s; },
  date: (v) => { if (v && !/^\d{4}-\d{2}-\d{2}$/.test(v)) throw new ValidationError('Data inválida'); return v; },
  datetime: (v) => { if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(String(v))) throw new ValidationError('Data/horário inválido'); return v; },
  int: (v, min = 0, max = 1e9) => { const n = Number(v); if (!Number.isInteger(n) || n < min || n > max) throw new ValidationError('Número inválido'); return n; },
  num: (v, min = 0, max = 1e9) => { const n = Number(v); if (!Number.isFinite(n) || n < min || n > max) throw new ValidationError('Valor inválido'); return n; },
  password: (v) => { const s = String(v || ''); if (s.length < 8 || !/[A-Za-z]/.test(s) || !/\d/.test(s)) throw new ValidationError('A senha precisa ter 8+ caracteres, com letras e números'); return s; },
  media: (m, kinds, maxMb) => {
    if (!m) return m;
    if (typeof m.b64 !== 'string' || !/^[A-Za-z0-9+/=\s]*$/.test(m.b64.slice(0, 2000))) throw new ValidationError('Arquivo inválido');
    if (!kinds.some((k) => String(m.mime || '').startsWith(k))) throw new ValidationError('Tipo de arquivo não permitido');
    if (m.b64.length * 0.75 > maxMb * 1024 * 1024) throw new ValidationError(`Arquivo maior que ${maxMb} MB`);
    return { b64: m.b64, mime: String(m.mime).slice(0, 60) };
  },
};
export class ValidationError extends Error {}

/** Valida a assinatura X-Hub-Signature-256 da Meta (se WHATSAPP_APP_SECRET estiver definido). */
export function verifyMetaSignature(req) {
  const secret = process.env.WHATSAPP_APP_SECRET;
  if (!secret) return process.env.NODE_ENV !== 'production';
  const sig = String(req.headers['x-hub-signature-256'] || '');
  const exp = 'sha256=' + crypto.createHmac('sha256', secret).update(req.rawBody || '').digest('hex');
  return sig.length === exp.length && crypto.timingSafeEqual(Buffer.from(sig), Buffer.from(exp));
}

/** Erros: mensagens de negócio aparecem; erros internos viram mensagem genérica (sem stack/SQL). */
export function publicError(e) {
  if (e instanceof ValidationError || e?.constructor?.name === 'AppError' || e?.expose) return e.message;
  console.error('[erro interno]', e);
  return 'Não foi possível concluir a operação.';
}

export function checkProductionConfig() {
  if (process.env.NODE_ENV === 'production' && (!process.env.APP_SECRET || process.env.APP_SECRET.length < 32)) {
    console.error('APP_SECRET ausente ou curto (mín. 32 caracteres). Abortando em produção.');
    process.exit(1);
  }
}
