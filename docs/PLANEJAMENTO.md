# Atende.AI — Planejamento do produto

Plataforma genérica de **atendimento e agendamento com agente de IA no WhatsApp** para clínicas, consultórios e qualquer negócio que trabalha com hora marcada: fisioterapia, odontologia, psicologia, estética, veterinária, clínica médica, salões etc.

> Este documento parte da análise do vídeo de referência (86 quadros, 1 por segundo), descreve o que foi construído nesta primeira versão (painel administrativo + app do cliente, pasta `app/`) e planeja o que falta para virar um produto comercial.

---

## 1. O que o vídeo mostra (análise quadro a quadro)

| Tempo | O que aparece | Requisito que gera |
|---|---|---|
| 0–5 s | Fachada da "Clínica Movimento · Fisioterapia", selo **Agente 24h** (WhatsApp + IA), notificação "Pix recebido R$ 3.000" | Produto vendável como serviço mensal; cobrança da própria plataforma |
| 6–9 s | Tela de bloqueio: **sexta, 22h38** | O valor está no atendimento **fora do horário comercial** |
| 10–14 s | Notificação do WhatsApp de "Carlos M.": **mensagem de voz (0:14)**; ilustração da coluna com a **região lombar** destacada | Receber **áudio**, transcrever, entender a queixa |
| 15–18 s | Sem automação: "Sem resposta há 5 minutos" | Tempo de resposta é o problema a resolver |
| 19–22 s | Busca "fisioterapia aberto agora" no mapa: concorrente "FisioPlus — aberto 24h, agenda online" ganha o paciente ("Consulta marcada · amanhã 8h00") | Métrica: **pacientes recuperados** que iriam para o concorrente |
| 22–27 s | Painel **"Automação · Clínica Movimento"**, chave **Desligado → Ativo**, fluxo **WhatsApp → Transcreve → Agente de IA → Agenda → Responde**, contador **"24 horas · todos os dias · N atendimentos"** | Tela de automação com liga/desliga, etapas e contadores |
| 27–30 s | Áudio vira texto: "Oi, boa noite! Travei a lombar no trabalho hoje, tô com muita dor. Queria começar fisioterapia." | Transcrição exibida junto ao áudio |
| 30–33 s | Cartão **"O agente entendeu"**: dor lombar aguda · quer começar fisioterapia. Agente: "Sinto muito pela dor. Me manda uma foto do **pedido médico**?" | Triagem estruturada + empatia + pedido de documento (imagem) |
| 33–37 s | **Agenda · Fisioterapia** em colunas (Dra. Ana / Dr. Lucas), almoço bloqueado, horários livres destacados, **"Pra Carlos · horários livres" → Enviar opções** | Motor de disponibilidade por profissional; oferecer **2 horários** |
| 37–40 s | WhatsApp com botões **"Seg · 7h00 · Dra. Ana"** e **"Seg · 18h30 · Dr. Lucas"**; paciente escolhe segunda 7h | Mensagens interativas (botões) |
| 40–45 s | Cartão **"Avaliação de fisioterapia" Pendente → Confirmada**; **"Sessões · Carlos M." 4/10 → 10/10** (seg/qua, 7h, Dra. Ana) | Confirmação + **reserva automática do pacote** de sessões |
| 45 s | Mensagem com **mapa e endereço** + "Avaliação confirmada… venha com roupa confortável" | Envio de localização e orientações de preparo |
| 46–49 s | "Tudo em **menos de um minuto**": 0:06 transcreveu, 0:14 pedido médico, 0:31 agenda, **49 s** total | Log com tempo de cada etapa |
| 50–53 s | **"Recepção · agenda"** (segunda 07:02): "Carlos Martins — agendado pelo agente às 22:39 de sexta", **10 agendadas** | Visão da recepção com selo "agente" |
| 53–58 s | Recibo: 10 sessões × R$ 120 = **R$ 1.200 de um paciente** | Valor do tratamento/pacote |
| 58–63 s | 3 pacientes = R$ 3.600 × automação R$ 3.000 → **"Já se pagou ✓"** | **Dashboard de ROI** |
| 63–67 s | Sessão 4 **faltou** → IA: "Sentimos sua falta hoje. Quer remarcar pra quinta às 7h00?" → "Quero sim 👍" → **remarcada**; tratamento 4/10 | **Recuperação de faltas** e prevenção de abandono |
| 67–73 s | "R$ 10.000 por mês vendendo serviços como esse": **1 Atendimento 24h no WhatsApp · 2 Agenda automática · 3 Lembretes e remarcação** | Os três pilares do produto |
| 73–85 s | Chamada para live (marketing do autor do vídeo) | Não é requisito de produto |

---

## 2. Visão do produto

**Problema:** a maior parte das mensagens chega quando a recepção está fechada ou ocupada. Quem não responde em minutos perde o cliente para o concorrente que responde. Depois de marcado, o cliente falta ou abandona o tratamento no meio.

**Solução:** um agente que atende 24h no WhatsApp da empresa, entende texto, áudio e foto, consulta a agenda real, marca, reserva o pacote, confirma, lembra e remarca faltas, e entrega à equipe um painel com tudo e com o retorno financeiro.

**Genérico por desenho:** cada empresa escolhe um **segmento** (modelo) que pré-configura serviços, palavras-chave, documento exigido e **terminologia** (paciente/cliente/tutor, sessão/consulta, fisioterapeuta/dentista/veterinário). Tudo é editável.

### Perfis de usuário

| Perfil | Onde usa | O que faz |
|---|---|---|
| **Cliente final** (paciente, tutor…) | WhatsApp (produção) / app do cliente (teste) | Conversa, manda áudio/foto, escolhe horário, confirma, remarca, acompanha o tratamento |
| **Recepção** | Painel | Agenda, conversas (assumir/devolver ao agente), clientes, faltas, pagamentos |
| **Profissional** | Painel | Vê a própria agenda, marca realizado/faltou |
| **Gestor da empresa (admin)** | Painel | Tudo acima + serviços, profissionais, automação/IA, integrações, usuários, dashboard |
| **Administrador da plataforma (superadmin)** | Painel | Cria e gerencia empresas (multiempresa/SaaS), alterna entre elas |

---

## 3. Escopo funcional

Legenda: ✅ feito nesta versão · 🔜 próxima fase · 💡 futuro

### 3.1 Agente de atendimento (WhatsApp)
- ✅ Pipeline **WhatsApp → Transcreve → Agente de IA → Agenda → Responde**, com log e tempo de cada etapa
- ✅ Texto, **áudio** (transcrição), **imagem** (documento/pedido médico; com IA, a imagem é lida), botões, cartão de agendamento, **localização**
- ✅ Triagem estruturada ("O agente entendeu": queixa, pontos, objetivo, urgência)
- ✅ Pede documento quando o serviço exige (configurável por serviço); segue sem ele se o cliente não tiver
- ✅ Oferece **2 horários** reais, preferindo profissionais diferentes e períodos contrastantes (manhã x noite)
- ✅ Agenda + **reserva automática do pacote** (ex.: 10 sessões, 2x/semana, mesmo horário e profissional; contorna conflitos)
- ✅ Confirmar, cancelar, remarcar, listar horários, preços, endereço, horário de funcionamento
- ✅ **Lembrete** X horas antes (sem enviar de madrugada) com botões Confirmar/Remarcar
- ✅ **Recuperação de falta**: ao marcar "faltou", oferece o próximo horário com o mesmo profissional e remarca com um "sim"
- ✅ **Transferência para humano**: pedido explícito, convênio, emergência (orienta SAMU 192 / CVV 188), recusa da IA
- ✅ Dois motores: **Claude (IA generativa com ferramentas)** quando há `ANTHROPIC_API_KEY`; **agente de regras** determinístico sem chave (e como fallback se a IA falhar)
- 🔜 Confirmação de presença no dia, lista de espera (encaixe automático quando alguém cancela)
- 🔜 Cobrança do pacote por link Pix na própria conversa
- 💡 Campanhas: reativação de inativos, aniversário, retorno periódico (ex.: limpeza a cada 6 meses), pesquisa NPS pós-atendimento
- 💡 Atendimento em outros canais (Instagram Direct, site/chat, telefone com voz)

### 3.2 Painel administrativo
- ✅ **Dashboard**: receita gerada pelo agente, ROI vs custo da automação ("Já se pagou"), atendimentos fora do horário, tempo médio de atendimento, comparecimento, faltas recuperadas, tratamentos ativos, novos agendamentos (agente x equipe), pipeline, ocupação, serviços que mais faturam
- ✅ **Agenda** por dia (colunas por profissional, jornada, bloqueios, selo ✳️ do agente) e por mês (visão "Recepção · agenda"); criar, confirmar, realizado, faltou, cancelar, remarcar
- ✅ **Conversas** (inbox em tempo real): transcrições, imagens, botões; triagem; assumir/devolver ao agente; responder como equipe; linha do tempo da automação
- ✅ **Clientes (CRM)**: ficha com dados, triagem, tratamentos, documentos, pagamentos, histórico; exclusão de dados (LGPD)
- ✅ **Tratamentos/pacotes** com progresso, faltas e alerta "sem próxima sessão" (risco de abandono)
- ✅ **Financeiro**: contratado em pacotes, recebido, a receber; registro de pagamentos
- ✅ **Automação & IA**: liga/desliga, fluxo visual, nome/tom/instruções do agente, antecedência do lembrete, custo mensal, reserva automática de pacote, recuperação de faltas, log de execução
- ✅ **Serviços** (duração, preço, porta de entrada, pacote, sessões/semana, documento exigido, palavras-chave, profissionais)
- ✅ **Profissionais** (jornada com 2 turnos/dia, serviços, cor, registro profissional)
- ✅ **Integrações** (status das credenciais e configuração não sensível)
- ✅ **Empresa** (endereço, coordenadas, horário de funcionamento, terminologia)
- ✅ **Usuários e permissões** (admin, recepção, profissional) + **auditoria**
- ✅ **Multiempresa** (superadmin cria empresa a partir de um modelo de segmento)
- 🔜 Relatórios exportáveis (CSV/PDF), metas, comissões por profissional
- 🔜 Prontuário/evolução clínica simples (com controle de acesso por profissional)

### 3.3 App do cliente
- ✅ **Simulador de WhatsApp** (texto, gravação de áudio com transcrição no navegador, foto, botões, cartão de agendamento, mapa) com roteiro do vídeo em um clique
- ✅ **Minha agenda**: confirmar, remarcar (escolhendo horário livre), cancelar, histórico
- ✅ **Meu tratamento**: progresso N/10 e lista de sessões
- ✅ **Autoagendamento** com reserva de pacote
- ✅ **Perfil** e consentimento LGPD
- 🔜 Login por código (OTP) via WhatsApp/SMS, PWA instalável, notificações push
- 💡 Pagamento no app, teleconsulta (link de vídeo), documentos e recibos para download

---

## 4. Integrações necessárias

| Integração | Para quê | Opções recomendadas | Status |
|---|---|---|---|
| **WhatsApp** | Canal principal: receber/enviar texto, áudio, imagem, botões, localização | **WhatsApp Business Cloud API (Meta)** — oficial, sem risco de banimento. Alternativas via BSP: 360dialog, Twilio, Gupshup. Evitar APIs não oficiais (Evolution/Baileys) em clientes da área da saúde | ✅ Webhook e envio implementados (`/api/webhook/whatsapp`); falta cadastrar número e token |
| **IA (agente)** | Entender linguagem natural, ler fotos, decidir e usar ferramentas (agenda, pacote, localização) | **Claude (Anthropic)** com *tool use* — implementado; modelo configurável por `ANTHROPIC_MODEL` | ✅ Basta `ANTHROPIC_API_KEY` |
| **Transcrição de áudio** | Áudio do WhatsApp → texto | OpenAI Whisper / gpt-4o-transcribe (implementado), Deepgram, AssemblyAI, Google STT | ✅ Basta `OPENAI_API_KEY` (no simulador o navegador transcreve) |
| **Agenda externa** | Sincronizar com a agenda pessoal dos profissionais | Google Calendar API (OAuth por profissional), Microsoft Graph (Outlook) | 🔜 |
| **Pagamentos** | Cobrar pacote/sinal, baixa automática | Mercado Pago, Asaas, Pagar.me, Stripe (Pix + cartão + recorrência) | 🔜 (registro manual já existe) |
| **Mapas** | Pin da empresa, rota | Link Google Maps/Waze (implementado); Google Places para endereço | ✅ |
| **Nota fiscal** | NFS-e do serviço | eNotas, Focus NFe, NFE.io | 💡 |
| **Convênios / TISS** | Faturamento de planos de saúde | Integração TISS / portais das operadoras | 💡 |
| **E-mail/SMS** | OTP, recibos, fallback de lembrete | Amazon SES, Resend, Zenvia, Twilio | 🔜 |
| **Observabilidade** | Erros, métricas, alertas | Sentry, OpenTelemetry + Grafana/Datadog | 🔜 |

### Passo a passo para ligar o WhatsApp real (Cloud API)
1. Criar app em developers.facebook.com → produto WhatsApp → número de produção verificado (Business Manager verificado).
2. Gerar **token permanente** (usuário de sistema) → `WHATSAPP_TOKEN`.
3. Configurar webhook: URL `https://SEU_DOMINIO/api/webhook/whatsapp`, verify token = `WHATSAPP_VERIFY_TOKEN`; assinar o campo `messages`.
4. No painel → Integrações → WhatsApp: informar o `phone_number_id` da empresa.
5. Criar **modelos de mensagem (templates)** aprovados pela Meta para mensagens fora da janela de 24h (lembretes e recuperação de faltas). *Pendente: hoje os lembretes saem como texto livre, válido apenas dentro da janela de 24h.*

---

## 5. Arquitetura

```
 Cliente (WhatsApp)          Cliente (app de teste)        Equipe (painel)
        │ webhook Meta                 │ HTTPS + SSE               │ HTTPS + SSE
        ▼                              ▼                           ▼
 ┌────────────────────────────── API Node.js (Express) ───────────────────────────┐
 │  canais/whatsapp.js   routes/client.js   routes/admin.js (auth, RBAC, auditoria)│
 │                 └──────────► agent/index.js (pipeline) ◄──────────┘            │
 │                    transcrição → agente (Claude | regras) → ferramentas         │
 │                                        │                                        │
 │   services/scheduling.js (disponibilidade, pacote, remarcação)                  │
 │   services/jobs.js (lembretes, recuperação de faltas — a cada minuto)           │
 │   services/bus.js (eventos em tempo real → SSE)                                 │
 └────────────────────────────────────────┬───────────────────────────────────────┘
                                          ▼
                         SQLite (dev)  →  PostgreSQL (produção)
```

**Decisões desta versão** (pensadas para rodar e testar sem instalar nada além do Node 22):
- Node.js + Express, front-end em JavaScript puro (sem build), SQLite nativo do Node (`node:sqlite`).
- Tempo real via **Server-Sent Events**.
- Agente com **ferramentas** (tool use): o modelo nunca inventa horários; ele chama `oferecer_horarios`, `agendar`, `remarcar_agendamento` etc., que validam conflitos no banco.
- Horários armazenados no fuso da empresa (`America/Sao_Paulo`).

**Para produção:**
- PostgreSQL gerenciado (schema já compatível) + backups e criptografia em repouso.
- Fila (BullMQ/Redis ou SQS) para mensagens recebidas e jobs; Redis Pub/Sub para SSE com várias instâncias.
- Armazenamento de mídia em bucket (S3/R2) com URLs assinadas, em vez de base64 no banco.
- Deploy em contêiner (Railway, Render, Fly.io, AWS ECS ou Cloud Run), domínio com HTTPS.
- Segredos em cofre (variáveis de ambiente do provedor / AWS Secrets Manager).

### Modelo de dados (tabelas principais)
`tenants` (empresa, segmento, horários, terminologia, configuração do agente) · `users` (perfis) · `professionals` (jornada) · `services` (duração, preço, pacote, documento) · `professional_services` · `clients` (CRM, consentimento LGPD) · `appointments` (status, origem: agente/recepção/cliente, sessão nº, remarcado de) · `treatments` (pacotes) · `blocks` (bloqueios/feriados) · `conversations` (modo bot/humano, triagem, estado) · `messages` · `documents` · `payments` · `integrations` · `automation_logs` · `audit_logs`.

---

## 6. Desenho do agente de IA

- **Prompt de sistema montado por empresa:** nome, tom, endereço, horários, serviços com preços e pacotes, profissionais, terminologia do segmento, próximos agendamentos do cliente e instruções livres do gestor.
- **Ferramentas:** `listar_servicos`, `registrar_triagem`, `salvar_cadastro`, `registrar_documento`, `oferecer_horarios`, `agendar`, `enviar_localizacao`, `meus_agendamentos`, `confirmar_agendamento`, `cancelar_agendamento`, `horarios_para_remarcar`, `remarcar_agendamento`, `transferir_para_humano`.
- **Salvaguardas:** sem diagnóstico ou prescrição; sinais de emergência → SAMU/CVV + humano; cancelamento só com pedido explícito; nunca inventa horário (só ferramenta); fallback automático para o agente de regras se a API falhar; recusa do modelo → humano.
- **Custos:** esforço baixo (`low`) por padrão para respostas rápidas; reduzir histórico enviado (30 últimas mensagens) e usar cache de prompt quando o volume crescer.
- **Avaliação contínua:** montar um conjunto de conversas reais anonimizadas (agendar, remarcar, emergência, convênio, áudio confuso) e medir taxa de agendamento, transferências e erros antes de trocar prompt/modelo.

---

## 7. Segurança, LGPD e regras do setor de saúde

- Dados de saúde são **dados sensíveis** (LGPD art. 11): coletar consentimento (✅ no app do cliente), registrar finalidade, permitir exclusão (✅ botão "Excluir (LGPD)"), auditoria de acesso (✅ `audit_logs`), contrato de operador com a clínica (controladora).
- Criptografia em trânsito (HTTPS) e em repouso; mídia em bucket privado; retenção configurável.
- Senhas com scrypt (✅), tokens assinados (✅), RBAC por perfil (✅), isolamento por empresa em todas as consultas (✅). Próximo: 2FA no painel, limite de tentativas de login, CSP.
- Conselhos profissionais (CFM, COFFITO, CRO, CFP): o agente **não faz ato clínico**; apenas administra agenda e orienta. Mensagens de preparo devem ser revisadas pela empresa.
- WhatsApp: seguir a política comercial da Meta (opt-in, templates aprovados, botão de sair).
- Dados enviados à IA: só o necessário para atender; configurar provedor sem treino com dados do cliente.

---

## 8. Requisitos não funcionais
- Resposta ao cliente em < 60 s (meta do vídeo; regras respondem em milissegundos, IA em poucos segundos).
- Disponibilidade 99,5% (WhatsApp é canal crítico); fila com reprocessamento.
- Webhook responde em < 1 s (✅: responde 200 e processa em seguida).
- Escala: 1 instância atende dezenas de empresas; horizontalizar com fila + Redis.
- Acessível no celular (✅ painel responsivo; app do cliente em formato de telefone).

---

## 9. Roteiro (roadmap)

| Fase | Entregas | Estimativa |
|---|---|---|
| **0 — Protótipo funcional (esta entrega)** | Painel admin completo, app do cliente, agente IA + regras, agenda e pacotes, lembretes, recuperação de faltas, dashboard de ROI, multiempresa, webhook WhatsApp, testes automatizados | ✅ |
| **1 — Piloto com 1 clínica** | Número real no WhatsApp Cloud API, templates aprovados, PostgreSQL + deploy com HTTPS, mídia em bucket, OTP no app, transcrição Whisper, ajuste do prompt com conversas reais, monitoramento (Sentry) | 3–4 semanas |
| **2 — Produto comercial** | Pagamento Pix no WhatsApp, Google Agenda, lista de espera/encaixe, relatórios, NPS, onboarding self-service da empresa, cobrança da assinatura da plataforma, 2FA | 6–8 semanas |
| **3 — Escala** | Campanhas de reativação, Instagram/site, prontuário simples, NFS-e, convênios (TISS), app nativo/PWA com push, marketplace de modelos por segmento | contínuo |

---

## 10. Modelo de negócio (sugestão)
- **Implantação** (configuração, número WhatsApp, treinamento do agente): pagamento único.
- **Mensalidade por empresa** com faixas por volume de conversas/profissionais (o vídeo cita R$ 3.000 para uma clínica; o dashboard prova o retorno: 3 pacientes de R$ 1.200 já pagam).
- Custos variáveis a repassar: conversas do WhatsApp (cobradas pela Meta por conversa iniciada pela empresa), tokens de IA e transcrição.

## 11. Métricas de sucesso
Taxa de resposta < 1 min · % de conversas que viram agendamento · agendamentos fora do horário · receita via agente / custo (ROI) · comparecimento · faltas recuperadas · tratamentos concluídos vs abandonados · % transferido para humano · NPS.

## 12. Riscos e mitigação
| Risco | Mitigação |
|---|---|
| IA responder algo clínico/errado | Ferramentas com validação, instruções restritivas, transferência para humano, revisão das conversas no painel |
| Bloqueio do número no WhatsApp | API oficial, opt-in, templates aprovados, volume gradual |
| Agenda dupla (sistema x agenda pessoal) | Sincronização com Google Agenda (fase 2) e bloqueios no painel |
| Dependência de um provedor de IA | Agente de regras como fallback (✅); camada de ferramentas independente do modelo |
| Vazamento de dados sensíveis | LGPD by design, RBAC, auditoria, criptografia, mínimo necessário enviado a terceiros |

---

## 13. Como testar esta versão
Veja `app/README.md`. Resumo:
```bash
cd app && npm install && npm start
# Painel:  http://localhost:3000/admin   (admin@atende.ai / admin123 · gestor@movimento.com / 123456)
# Cliente: http://localhost:3000/cliente
```
Roteiro sugerido: no app do cliente, clique em sequência **Áudio → Foto do pedido médico → 1ª opção**; no painel, veja a conversa com "O agente entendeu", a agenda com o selo ✳️, o tratamento 0/10 e o dashboard. Depois marque uma sessão como **Faltou** e responda "Quero sim" no app do cliente.
