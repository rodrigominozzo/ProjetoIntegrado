# Atende.AI — painel administrativo + app do cliente

Agenda, catálogo e atendimento 24h com agente de IA no WhatsApp para clínicas de qualquer especialidade.
Planejamento completo em [`../docs/PLANEJAMENTO.md`](../docs/PLANEJAMENTO.md).

## Rodar

Requisito: **Node.js 22.5+** (usa o SQLite embutido do Node; nada mais para instalar).

```bash
cd app
npm install
npm start            # http://localhost:3000
npm test             # testes de ponta a ponta do fluxo do vídeo
npm run reset        # apaga o banco e recria os dados de demonstração
```

| Endereço | O quê | Acesso |
|---|---|---|
| `/` | Página inicial | — |
| `/admin` | Painel administrativo | `gestor@vidaintegrada.com` / `gestor123` (gestor)<br>`recepcao@vidaintegrada.com` / `recepcao123` (recepção — sem financeiro)<br>`helena@vidaintegrada.com` / `helena123` (profissional — só a própria agenda)<br>`admin@atende.ai` / `admin123` (plataforma, todas as clínicas) |
| `/cliente` | App do cliente (simulador de WhatsApp + área do cliente) | qualquer nome e telefone |

Dados de demonstração: **Clínica Vida Integrada** (multiespecialidade: clínica geral, dermatologia, pediatria, ginecologia, nutrição, psicologia e fisioterapia; 8 profissionais, com procedimentos que têm tempo e preço diferentes por profissional; agenda já ocupada) e **Sorriso Odontologia**.

## Variáveis de ambiente (todas opcionais)

| Variável | Efeito |
|---|---|
| `ANTHROPIC_API_KEY` | Liga o agente com IA generativa (Claude). Sem ela, roda o agente de regras, que cobre todo o fluxo. |
| `ANTHROPIC_MODEL` | Modelo do agente (padrão `claude-opus-5-5`) |
| `ANTHROPIC_EFFORT` | `low` (padrão), `medium`, `high` |
| `AGENT_MODE=rules` | Força o agente de regras mesmo com chave de IA |
| `OPENAI_API_KEY` | Transcrição de áudio no servidor (Whisper). No simulador, o navegador já transcreve. |
| `TRANSCRIBE_MODEL` | Padrão `whisper-1` |
| `WHATSAPP_TOKEN` | Token da WhatsApp Cloud API (Meta) — liga o envio real |
| `WHATSAPP_VERIFY_TOKEN` | Token de verificação do webhook (sem ele, a verificação é recusada) |
| `WHATSAPP_APP_SECRET` | Valida a assinatura `X-Hub-Signature-256` de cada chamada do webhook (obrigatório em produção) |
| `APP_SECRET` | Segredo para assinar as sessões. Em desenvolvimento é gerado em `data/.secret`; **em produção é obrigatório (32+ caracteres)** |
| `NODE_ENV=production` | Ativa HSTS e exige `APP_SECRET`/assinatura do webhook |
| `TRUST_PROXY=1` | Use atrás de proxy/load balancer (IP real para limites e bloqueios) |
| `RATE_LIMIT_PER_MIN` | Requisições por IP por minuto na API (padrão 600) |
| `PORT`, `DATA_DIR`, `TZ_EMPRESA`, `JOBS_INTERVAL_MS` | Porta, pasta do banco, fuso, intervalo das rotinas |

Webhook do WhatsApp: `GET/POST /api/webhook/whatsapp`. Vincule o `phone_number_id` em **Painel → Integrações → WhatsApp**.

## Estrutura

```
app/
  src/
    server.js                 servidor HTTP + arquivos estáticos + rotinas
    db.js                     schema SQLite (compatível com PostgreSQL)
    seed.js                   empresas e dados de demonstração
    agent/
      index.js                pipeline WhatsApp → Transcreve → Agente → Agenda → Responde
      guard.js                proteção: prompt injection, escopo, desconto, vazamento, abuso
      llm.js                  agente Claude (tool use) com filtro de saída
      rules.js                agente de regras (sem IA / fallback)
      tools.js                ferramentas com escopo do próprio paciente e preço só do cadastro
    services/
      scheduling.js           disponibilidade com duração/preço por profissional, intervalos, regras e política
      proactive.js            reoferta após falta/cancelamento/bloqueio, lista de espera, reativação, retorno
      jobs.js                 rotinas a cada minuto (respeitando horário silencioso)
      security.js             cabeçalhos, limites, bloqueio de força bruta, validação, assinatura do webhook
      conversations.js        mensagens, estado da conversa, logs
      transcription.js        áudio → texto
      presets.js              modelos por tipo de clínica (multiespecialidade, odonto, psico, fisio, estética, vet…)
      auth.js, bus.js, time.js
    channels/whatsapp.js      WhatsApp Cloud API (webhook + envio)
    routes/admin.js           API do painel
    routes/client.js          API do app do cliente + webhook
  public/
    admin/                    painel (JS puro, sem build)
    cliente/                  app do cliente
  test/fluxo.test.js
```
