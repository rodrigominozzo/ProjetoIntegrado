# Atende.AI — painel administrativo + app do cliente

Atendimento 24h com agente de IA no WhatsApp para clínicas e qualquer negócio com hora marcada.
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
| `/admin` | Painel administrativo | `admin@atende.ai` / `admin123` (plataforma, vê todas as empresas)<br>`gestor@movimento.com` / `123456` (gestor da clínica)<br>`recepcao@movimento.com` / `123456` (recepção) |
| `/cliente` | App do cliente (simulador de WhatsApp + área do cliente) | qualquer nome e telefone |

Dados de demonstração: **Clínica Movimento** (fisioterapia, Dra. Ana e Dr. Lucas, agenda já ocupada, 3 pacientes captados pelo agente fora do horário) e **Sorriso Odontologia** (mostra que a plataforma é genérica).

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
| `WHATSAPP_VERIFY_TOKEN` | Token de verificação do webhook (padrão `atende-ai`) |
| `APP_SECRET` | Segredo para assinar os tokens de sessão (**obrigatório trocar em produção**) |
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
      llm.js                  agente Claude (tool use)
      rules.js                agente de regras (sem IA / fallback)
      tools.js                ferramentas do agente (agenda, pacote, localização, humano…)
    services/
      scheduling.js           disponibilidade, agendamento, pacote, remarcação
      jobs.js                 lembretes e recuperação de faltas
      conversations.js        mensagens, estado da conversa, logs
      transcription.js        áudio → texto
      presets.js              modelos por segmento (fisio, odonto, psico, estética, vet, médica…)
      auth.js, bus.js, time.js
    channels/whatsapp.js      WhatsApp Cloud API (webhook + envio)
    routes/admin.js           API do painel
    routes/client.js          API do app do cliente + webhook
  public/
    admin/                    painel (JS puro, sem build)
    cliente/                  app do cliente
  test/fluxo.test.js
```
