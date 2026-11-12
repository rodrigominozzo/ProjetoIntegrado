// Datas no fuso da empresa. Armazenamos "YYYY-MM-DDTHH:MM" (horário local, sem fuso).
export const TZ = process.env.TZ_EMPRESA || 'America/Sao_Paulo';

export function nowLocal() {
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: TZ, year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false,
  }).formatToParts(new Date());
  const g = (t) => parts.find((p) => p.type === t).value;
  const hh = g('hour') === '24' ? '00' : g('hour');
  return `${g('year')}-${g('month')}-${g('day')}T${hh}:${g('minute')}`;
}

// Converte string local em Date "ingênuo" (UTC) só para aritmética.
export const toD = (s) => new Date(s.length === 10 ? s + 'T00:00:00Z' : s + ':00Z');
export const fromD = (d) => d.toISOString().slice(0, 16);
export const addMin = (s, m) => fromD(new Date(toD(s).getTime() + m * 60000));
export const addDays = (s, n) => fromD(new Date(toD(s).getTime() + n * 86400000)).slice(0, s.length === 10 ? 10 : 16);
export const dateOf = (s) => s.slice(0, 10);
export const timeOf = (s) => s.slice(11, 16);
export const weekday = (s) => toD(s).getUTCDay(); // 0=dom
export const minutes = (hhmm) => { const [h, m] = hhmm.split(':').map(Number); return h * 60 + m; };
export const hhmm = (min) => `${String(Math.floor(min / 60)).padStart(2, '0')}:${String(min % 60).padStart(2, '0')}`;

const DIAS = ['domingo', 'segunda', 'terça', 'quarta', 'quinta', 'sexta', 'sábado'];
const DIAS_CURTO = ['dom', 'seg', 'ter', 'qua', 'qui', 'sex', 'sáb'];
const MESES = ['janeiro', 'fevereiro', 'março', 'abril', 'maio', 'junho', 'julho', 'agosto', 'setembro', 'outubro', 'novembro', 'dezembro'];
export const diaSemana = (s) => DIAS[weekday(s)];
export const diaCurto = (s) => DIAS_CURTO[weekday(s)];
export function fmtHora(s) { const t = timeOf(s); return t.endsWith(':00') ? `${Number(t.slice(0, 2))}h` : `${Number(t.slice(0, 2))}h${t.slice(3)}`; }
export function fmtData(s) { const d = toD(s); return `${String(d.getUTCDate()).padStart(2, '0')}/${String(d.getUTCMonth() + 1).padStart(2, '0')}`; }
export function fmtLongo(s) { const d = toD(s); return `${DIAS[d.getUTCDay()]}, ${d.getUTCDate()} de ${MESES[d.getUTCMonth()]}`; }
export function fmtRelativo(s, now = nowLocal()) {
  const diff = Math.round((toD(dateOf(s)) - toD(dateOf(now))) / 86400000);
  if (diff === 0) return `hoje às ${fmtHora(s)}`;
  if (diff === 1) return `amanhã às ${fmtHora(s)}`;
  return `${DIAS[weekday(s)]} (${fmtData(s)}) às ${fmtHora(s)}`;
}
