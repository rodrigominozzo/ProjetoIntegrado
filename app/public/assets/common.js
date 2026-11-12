// Utilidades compartilhadas entre painel admin e app do cliente.
export const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
export const $ = (sel, el = document) => el.querySelector(sel);
export const $$ = (sel, el = document) => [...el.querySelectorAll(sel)];

export function makeApi(tokenKey, extraHeaders = () => ({})) {
  return async function api(path, { method = 'GET', body } = {}) {
    const token = localStorage.getItem(tokenKey);
    const r = await fetch('/api' + path, {
      method, headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: 'Bearer ' + token } : {}), ...extraHeaders() },
      body: body ? JSON.stringify(body) : undefined,
    });
    if (r.status === 401) { localStorage.removeItem(tokenKey); location.hash = '#/login'; throw new Error('Sessão expirada'); }
    const data = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(data.error || 'Erro ' + r.status);
    return data;
  };
}

export function toast(msg, err = false) {
  let box = document.getElementById('toasts');
  if (!box) { box = document.createElement('div'); box.id = 'toasts'; document.body.appendChild(box); }
  const t = document.createElement('div'); t.className = 'toast' + (err ? ' err' : ''); t.textContent = msg;
  box.appendChild(t); setTimeout(() => t.remove(), 3500);
}

export function modal(title, bodyHtml, { onSave, saveLabel = 'Salvar', wide } = {}) {
  const bg = document.createElement('div'); bg.className = 'modal-bg';
  bg.innerHTML = `<div class="modal" style="${wide ? 'width:min(900px,100%)' : ''}"><header><h3>${esc(title)}</h3><button class="btn ghost right" data-x>✕</button></header>
    <div class="body">${bodyHtml}</div>${onSave ? `<footer><button class="btn" data-x>Cancelar</button><button class="btn primary" data-save>${saveLabel}</button></footer>` : ''}</div>`;
  document.body.appendChild(bg);
  const close = () => bg.remove();
  bg.addEventListener('click', (e) => { if (e.target === bg || e.target.closest('[data-x]')) close(); });
  bg.querySelector('[data-save]')?.addEventListener('click', async (e) => {
    e.target.disabled = true;
    try { if ((await onSave(bg)) !== false) close(); } catch (err) { toast(err.message, true); } finally { e.target.disabled = false; }
  });
  return { el: bg, close };
}

export const formData = (root) => Object.fromEntries($$('[name]', root).map((i) => [i.name, i.type === 'checkbox' ? i.checked : i.type === 'number' ? (i.value === '' ? null : Number(i.value)) : i.multiple ? [...i.selectedOptions].map((o) => o.value) : i.value]));

export const money = (v) => 'R$ ' + Number(v || 0).toLocaleString('pt-BR', { minimumFractionDigits: 0, maximumFractionDigits: 2 });
export const money2 = (v) => 'R$ ' + Number(v || 0).toLocaleString('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const DIAS = ['dom', 'seg', 'ter', 'qua', 'qui', 'sex', 'sáb'];
const MESES = ['jan', 'fev', 'mar', 'abr', 'mai', 'jun', 'jul', 'ago', 'set', 'out', 'nov', 'dez'];
export const d = (s) => new Date((s.length === 10 ? s + 'T00:00' : s.slice(0, 16)) + ':00Z');
export const ymd = (dt) => dt.toISOString().slice(0, 10);
export const addDays = (s, n) => ymd(new Date(d(s).getTime() + n * 864e5));
export const hora = (s) => { const t = s.slice(11, 16); return t.endsWith(':00') ? `${+t.slice(0, 2)}h` : `${+t.slice(0, 2)}h${t.slice(3)}`; };
export const hm = (s) => s.slice(11, 16);
export const dataCurta = (s) => `${s.slice(8, 10)}/${s.slice(5, 7)}`;
export const diaSem = (s) => DIAS[d(s).getUTCDay()];
export const dataLonga = (s) => `${DIAS[d(s).getUTCDay()]}, ${+s.slice(8, 10)} ${MESES[+s.slice(5, 7) - 1]}`;
export const quando = (s) => `${diaSem(s)} ${dataCurta(s)} · ${hora(s)}`;
export function todayLocal() {
  const p = new Intl.DateTimeFormat('en-CA', { timeZone: 'America/Sao_Paulo', year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date());
  return p;
}
export function utcToLocal(sqlUtc) { // "YYYY-MM-DD HH:MM:SS" (UTC) → "dd/mm HH:MM" local
  if (!sqlUtc) return '';
  const dt = new Date(sqlUtc.replace(' ', 'T') + 'Z');
  return dt.toLocaleString('pt-BR', { timeZone: 'America/Sao_Paulo', day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' });
}
export const STATUS = {
  pendente: ['Pendente', 'amber'], confirmado: ['Confirmada', 'green'], realizado: ['Realizada', 'blue'], faltou: ['Faltou', 'red'],
  cancelado: ['Cancelada', ''], remarcado: ['Remarcada', 'purple'],
};
export const statusBadge = (s) => `<span class="badge ${STATUS[s]?.[1] || ''}">${STATUS[s]?.[0] || s}</span>`;
