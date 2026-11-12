import express from 'express';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { seed } from './seed.js';
import adminRoutes from './routes/admin.js';
import clientRoutes from './routes/client.js';
import { startJobs } from './services/jobs.js';
import { agentMode } from './agent/index.js';

const here = path.dirname(fileURLToPath(import.meta.url));
const app = express();
app.use(express.json({ limit: '15mb' })); // imagens/áudios em base64

app.get('/health', (req, res) => res.json({ ok: true, agent: agentMode() }));
app.use('/api', clientRoutes);
app.use('/api', adminRoutes);
app.use(express.static(path.join(here, '..', 'public'), { extensions: ['html'] }));

if (seed()) console.log('Banco inicializado com dados de demonstração.');
startJobs(Number(process.env.JOBS_INTERVAL_MS || 60_000));

const port = Number(process.env.PORT || 3000);
app.listen(port, () => {
  console.log(`\n  Atende.AI rodando em http://localhost:${port}`);
  console.log(`  Painel admin:  http://localhost:${port}/admin   (admin@atende.ai / admin123)`);
  console.log(`  App cliente:   http://localhost:${port}/cliente`);
  console.log(`  Agente:        ${agentMode() === 'claude' ? 'Claude (IA)' : 'regras (defina ANTHROPIC_API_KEY para IA)'}\n`);
});
