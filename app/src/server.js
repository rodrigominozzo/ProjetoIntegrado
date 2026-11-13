import express from 'express';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { seed } from './seed.js';
import adminRoutes from './routes/admin.js';
import clientRoutes from './routes/client.js';
import { startJobs } from './services/jobs.js';
import { agentMode } from './agent/index.js';
import { securityHeaders, rateLimit, checkProductionConfig } from './services/security.js';

checkProductionConfig();
const here = path.dirname(fileURLToPath(import.meta.url));
const app = express();
app.disable('x-powered-by');
app.set('trust proxy', process.env.TRUST_PROXY ? 1 : false);
app.use(securityHeaders);
// guarda o corpo bruto para validar a assinatura do webhook da Meta
app.use(express.json({ limit: '12mb', verify: (req, _res, buf) => { if (req.url.startsWith('/api/webhook')) req.rawBody = buf; } }));
app.use((err, req, res, next) => (err ? res.status(400).json({ error: 'Requisição inválida' }) : next()));

app.get('/health', (req, res) => res.json({ ok: true }));
app.use('/api', rateLimit({ key: 'api', max: Number(process.env.RATE_LIMIT_PER_MIN || 600), windowMs: 60_000 }));
app.use('/api', clientRoutes);
app.use('/api', adminRoutes);
app.use('/api', (req, res) => res.status(404).json({ error: 'Rota não encontrada' }));
app.use(express.static(path.join(here, '..', 'public'), { extensions: ['html'], dotfiles: 'deny' }));

if (seed()) console.log('Banco inicializado com dados de demonstração.');
startJobs(Number(process.env.JOBS_INTERVAL_MS || 60_000));

const port = Number(process.env.PORT || 3000);
app.listen(port, () => {
  console.log(`\n  Atende.AI rodando em http://localhost:${port}`);
  console.log(`  Painel admin:  http://localhost:${port}/admin   (gestor@vidaintegrada.com / gestor123)`);
  console.log(`  App cliente:   http://localhost:${port}/cliente`);
  console.log(`  Agente:        ${agentMode() === 'claude' ? 'Claude (IA)' : 'regras (defina ANTHROPIC_API_KEY para IA)'}\n`);
});
