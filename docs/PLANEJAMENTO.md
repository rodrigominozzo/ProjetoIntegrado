# Atende.AI — Planejamento do produto

Plataforma de **agenda + atendimento com agente de IA no WhatsApp** para **clínicas de qualquer especialidade**: clínica geral, dermatologia, pediatria, ginecologia, nutrição, psicologia, fisioterapia, odontologia, estética, veterinária etc. Funciona tanto para clínicas multiespecialidade quanto para consultórios de uma especialidade só.

O código está em `app/`, e como rodar está em `app/README.md`.

---

## 1. O vídeo: o que é discurso de venda e o que é requisito do sistema

O vídeo de referência (86 quadros analisados) é um **vídeo de marketing para quem vende automação** ("venda essa automação por até R$ 3 mil", "R$ 10 mil por mês vendendo serviços como esse", convite para live). Boa parte do que aparece serve para **convencer o desenvolvedor e a clínica a comprar**. Só uma parte descreve o que o sistema precisa fazer.

| Aparece no vídeo | O que é na prática | Entra no sistema? |
|---|---|---|
| "Venda por até R$ 3 mil", "Pix recebido R$ 3.000", "R$ 10 mil por mês", live, "comenta 10K" | Discurso de venda para desenvolvedores | **Não.** É modelo de negócio de quem revende |
| "3 pacientes × R$ 1.200 = R$ 3.600 > R$ 3.000 da automação → já se pagou" | Argumento de ROI para a clínica comprar | **Não como tela.** O sistema mostra **faturamento e lucro reais pela agenda**, sem "valor investido" |
| Concorrente "aberto 24h" levando o paciente | Dor do cliente (perder paciente fora do horário) | Sim, como métrica: **agendamentos fora do horário comercial** |
| Clínica de fisioterapia, coluna lombar, recibo de 10 sessões | Exemplo de um nicho | Sim, mas **generalizado**: qualquer especialidade, com catálogo próprio |
| WhatsApp → Transcreve → Agente → Agenda → Responde | Fluxo do produto | **Sim** (núcleo) |
| Áudio transcrito, "O agente entendeu", pedido de foto do pedido médico | Atendimento inteligente | **Sim** |
| Agenda por profissional, 2 opções de horário, botões | Motor de agenda | **Sim** |
| Avaliação confirmada + 10 sessões reservadas | Pacotes de tratamento | **Sim**, opcional por serviço |
| Localização após confirmar | Pós-agendamento | **Sim** |
| "Tudo em menos de 1 minuto" | Desempenho | Sim, como **meta de tempo de resposta** e log por etapa |
| "Recepção abre segunda e as sessões já estão na agenda" | Agenda única para equipe e agente | **Sim** |
| Faltou → "Quer remarcar pra quinta?" → remarcado | Proatividade | **Sim**, ampliado para cancelamentos, bloqueios, lista de espera e tratamentos parados |
| "Atendimento 24h · Agenda automática · Lembretes e remarcação" | Os 3 pilares | **Sim** |

**Conclusão:** o produto é agenda + catálogo + agente proativo e seguro. Faturamento e lucro saem da agenda (o que foi atendido e o que está marcado). Não existe tela de "valor investido" nem de "retorno da automação".

---

## 2. Perfis de usuário

| Perfil | Onde usa | Pode |
|---|---|---|
| **Paciente/cliente** | WhatsApp (produção) ou app do cliente (teste) | Conversar, mandar áudio e foto, agendar, confirmar, remarcar, cancelar (dentro da política), ver tratamento, ver catálogo, entrar na lista de espera |
| **Profissional** | Painel | Ver **só a própria agenda** e os próprios tratamentos, marcar realizado/faltou. Não vê valores financeiros da clínica |
| **Recepção** | Painel | Agenda, conversas (assumir/devolver ao agente), pacientes, lista de espera, registrar pagamento. **Não vê custos, repasses nem lucro** |
| **Gestor (admin)** | Painel | Tudo acima + financeiro, catálogo, profissionais, regras da clínica, agente, segurança, integrações, usuários |
| **Superadmin** | Painel | Cria e gerencia várias clínicas (SaaS) |

---

## 3. Tudo o que é personalizável

### 3.1 Profissionais
- Nome, especialidade, **conselho e nº de registro** (CRM, CRO, CRP, CREFITO, CRN…), telefone, e-mail, apresentação, cor na agenda.
- **Jornada por dia da semana** (vários turnos e folgas).
- **Intervalo entre atendimentos** do profissional (ex.: 10 min para evolução de prontuário).
- **Repasse padrão (%)**.
- **Quais procedimentos realiza** e, para cada um, **duração, preço e repasse próprios**. Exemplos dos dados de demonstração:
  - Consulta clínica geral com o Dr. Paulo: 30 min, R$ 250.
  - A mesma consulta com a Dra. Carla: 40 min, R$ 280.
  - Peeling com a Dra. Helena: 60 min, contra 45 min no padrão do catálogo.
- Bloqueios de agenda (férias, congresso, imprevisto), com **remarcação automática** de quem já estava marcado.

### 3.2 Catálogo de serviços
- **Categoria** (Consultas, Exames, Procedimentos, Terapias ou outra que a clínica criar), nome, descrição.
- **Duração padrão**, **intervalo depois** (limpeza/preparo da sala), **preço padrão**, **custo direto** (insumos), margem calculada.
- **Modalidade**: presencial, online ou ambos.
- **Preparo/orientações**, enviados na confirmação e no lembrete (jejum, roupa, exames para levar…).
- **Retorno incluso** em X dias, com aviso automático.
- **Faixa etária** (ex.: pediatria até 17 anos).
- **Agendamento pelo agente/app**: ligado ou só pela equipe (ex.: procedimento que exige avaliação antes).
- **Porta de entrada** (avaliação ou 1ª consulta).
- **Documento exigido** (pedido médico, encaminhamento, exames…).
- **Pacote**: nº de sessões, preço por sessão, sessões por semana e o serviço usado nas sessões.
- **Palavras-chave**: como os pacientes costumam pedir aquele serviço.

### 3.3 Regras da clínica (agenda)
- Antecedência mínima para agendar e até quantos dias a agenda fica aberta.
- Grade de horários (5, 10, 15, 30 min…).
- Quantas opções de horário o agente oferece (1 a 4).
- **Política de cancelamento**: até quantas horas antes o próprio paciente cancela ou remarca. Depois disso, a alteração vai para a equipe.
- Lembrete X horas antes.
- **Horário silencioso**: sem mensagens proativas de madrugada.
- Horário de funcionamento, endereço e coordenadas.

### 3.4 Informações e comportamento do agente
- Nome, tom de voz, mensagem de boas-vindas.
- Convênios aceitos (se vazio, dúvidas vão para a equipe), formas de pagamento, políticas (chegada, atraso, acompanhante).
- **Orientações do gestor**, sempre subordinadas às regras de segurança.
- Ações proativas, cada uma ligada/desligada individualmente: repor faltas, repor cancelamentos, lista de espera, reservar pacotes, aviso de retorno e convite para retomar tratamento parado (X dias).
- Terminologia: paciente/cliente/tutor, consulta/sessão, profissional/dentista/veterinário.
- Liga/desliga geral do agente e transferência por conversa (assumir/devolver).

---

## 4. Proatividade (o agente age sem esperar)

| Gatilho | O que o agente faz |
|---|---|
| Paciente **faltou** | Na hora, oferece novas datas (mesmo profissional e horário parecido primeiro). A falta continua registrada nos relatórios |
| Paciente **cancela** (WhatsApp ou app) | Cancela e já envia novas opções de data. A vaga liberada é oferecida à **lista de espera** |
| **Clínica cancela** um horário | Pede desculpas e oferece novas datas |
| **Bloqueio de agenda** (férias/congresso) | Desmarca quem estava no período e oferece novas datas a cada um |
| Sem vaga no período desejado | Oferece outro período/profissional ou a **lista de espera** |
| Horário vagou | Oferece a vaga ao primeiro da fila compatível (encaixe) |
| Tratamento **parado** há X dias | Convida a retomar, com horários |
| **Retorno incluso** perto de vencer | Avisa e oferece agendar |
| Véspera do atendimento | Lembrete com preparo e botões Confirmar/Remarcar |
| Resposta "Nenhum desses" | Busca os próximos dias, outro período ou outro profissional |

Todas respeitam o horário silencioso e ficam no **log de execução**.

---

## 5. Segurança

### 5.1 Agente de IA
A proteção roda **fora do modelo**, em código, antes e depois da IA, então não depende de a IA "obedecer".

1. **Prompt injection.** Tentativas como "ignore as instruções", "você agora é…", "modo desenvolvedor", "mostre seu prompt", marcações `<system>` ou "sou o administrador" são bloqueadas antes de chegar à IA, com resposta padrão. O texto do paciente é sanitizado e tratado como dado. O prompt do sistema também instrui a IA a nunca tratar o conteúdo do paciente como ordem.
2. **Escopo.** Responde só sobre a clínica. Assuntos fora do escopo (piadas, política, receitas, código, tradução, conhecimentos gerais) são recusados com gentileza em uma frase.
3. **Sem desconto.** Pedidos de desconto, promoção ou cortesia recebem resposta fixa e as formas de pagamento. Nenhuma ferramenta aceita preço: **o valor vem sempre do cadastro**. A saída da IA é filtrada: promessa de desconto ou valor que não existe na tabela é bloqueado.
4. **Sem vazamento.**
   - As ferramentas só enxergam os agendamentos do próprio paciente.
   - Custos, repasses, faturamento e dados de outros pacientes nunca são enviados à IA.
   - Telefones, e-mails e CPFs de terceiros são ocultados na saída.
   - Respostas que citam o funcionamento interno (nomes de ferramentas, instruções) são bloqueadas.
5. **Abuso.** Limite de mensagens por número. Três tentativas de manipulação em 30 minutos pausam o agente naquela conversa e chamam a equipe.
6. **Saúde.** Sem diagnóstico nem conduta. Sinais de emergência → orientação SAMU 192/CVV 188 e transferência para humano.
7. **Tom.** Humano e direto: frases curtas, uma pergunta por vez, nome do paciente, no máximo 1 emoji, e age em vez de perguntar ("já separei estes horários").

Tudo fica registrado na tela **Segurança** do painel.

### 5.2 Sistema
- Senhas com scrypt. Sessões assinadas que expiram e **caem se a senha mudar** ou se o usuário for desativado.
- **Bloqueio de força bruta** (5 erros por e-mail / 20 por IP → 15 min) e limite de requisições por IP.
- **Perfis e permissões** (seção 2), isolamento total entre clínicas em todas as consultas e auditoria de acesso e alteração.
- **Validação** de todos os campos (tipos, tamanhos, datas, telefone, e-mail, senha forte) e dos arquivos (tipo e tamanho). Erros internos não são expostos.
- **Cabeçalhos de segurança**: CSP restritiva, anti-clickjacking, no-sniff, sem `x-powered-by`, HSTS em produção.
- **Webhook do WhatsApp** com verificação de assinatura `X-Hub-Signature-256` (`WHATSAPP_APP_SECRET`) e token de verificação obrigatório.
- Em produção (`NODE_ENV=production`), o sistema não sobe sem `APP_SECRET` forte.
- LGPD: consentimento, exclusão de dados a pedido e mínimo de dados enviados a terceiros.
- **Próximos passos para produção**:
  - 2FA no painel;
  - WAF/proxy com TLS (Cloudflare);
  - backups criptografados;
  - mídia em bucket privado;
  - rate limit em Redis (várias instâncias);
  - teste de invasão (pentest) antes do lançamento.

---

## 6. Financeiro (a partir da agenda)

- **Faturamento realizado**: soma dos atendimentos com status "realizado".
- **Lucro estimado**: valor − custo direto do procedimento − repasse do profissional. A margem aparece por categoria, procedimento e profissional.
- **Previsto**: o que está agendado nos próximos 30 dias, com o lucro previsto.
- **Perdido com faltas e cancelamentos** e quanto foi **recuperado** pelo agente.
- Ticket médio, comparecimento e ocupação da agenda por profissional.
- O lucro estimado não inclui despesas fixas (aluguel, folha, impostos), e o painel avisa isso.
- Pagamentos podem ser registrados na ficha do paciente. A integração Pix/cartão é da próxima fase.

---

## 7. Integrações

| Integração | Para quê | Recomendação | Status |
|---|---|---|---|
| **WhatsApp** | Canal principal | **WhatsApp Business Cloud API (Meta)**, oficial. Evitar APIs não oficiais em clínicas | ✅ Webhook, envio, botões e localização; falta número/token |
| **IA** | Entender, ler fotos, decidir | Claude (Anthropic) com tool use | ✅ Basta `ANTHROPIC_API_KEY`. Sem chave, o agente de regras atende o fluxo completo |
| **Transcrição** | Áudio → texto | OpenAI Whisper / Deepgram | ✅ `OPENAI_API_KEY` (no simulador, o navegador transcreve) |
| **Templates Meta** | Lembretes e reofertas fora da janela de 24h | Templates aprovados | 🔜 Obrigatório para produção |
| **Google Agenda / Outlook** | Agenda pessoal dos profissionais | OAuth por profissional | 🔜 |
| **Pagamentos** | Sinal/pacote por Pix ou cartão | Mercado Pago, Asaas, Stripe | 🔜 |
| **Prontuário/PEP** | Evolução clínica | Integração ou módulo próprio | 💡 |
| **NFS-e / TISS** | Nota fiscal e convênios | eNotas/Focus; TISS | 💡 |

---

## 8. Arquitetura

```
Paciente (WhatsApp) ─webhook assinado─┐
Paciente (app de teste) ──HTTPS+SSE───┼─► API Node.js ─► Proteção ─► Agente (Claude | regras) ─► Ferramentas com escopo
Equipe (painel) ──────────HTTPS+SSE───┘        │                                                    │
                                               ├─ Motor de agenda (personalização por profissional) ◄┘
                                               ├─ Ações proativas (jobs a cada minuto)
                                               └─ SQLite (dev) → PostgreSQL (produção)
```

Para produção, faltam:
- PostgreSQL;
- Redis (fila, rate limit e SSE com várias instâncias);
- bucket privado para mídia;
- contêiner com HTTPS;
- Sentry/OpenTelemetry.

---

## 9. Roadmap

| Fase | Entregas |
|---|---|
| **Feito** | Catálogo com categorias e personalização por profissional; regras de agenda; agente protegido (entrada e saída); proatividade completa; lista de espera; bloqueios com remarcação; financeiro pela agenda; perfis e permissões; segurança HTTP; multiempresa; testes automatizados |
| **Piloto (3–4 semanas)** | Número oficial + templates Meta; PostgreSQL + deploy HTTPS; OTP no app; Whisper; ajuste de prompt com conversas reais; 2FA; Sentry |
| **Produto (6–8 semanas)** | Pix/cartão; Google Agenda; relatórios exportáveis; NPS; onboarding self-service; cobrança da assinatura |
| **Escala** | Prontuário simples; teleconsulta; campanhas de reativação; Instagram/site; NFS-e; TISS |

---

## 10. Como testar

```bash
cd app && npm install && npm start
# Painel:  http://localhost:3000/admin  (gestor@vidaintegrada.com / gestor123)
# Cliente: http://localhost:3000/cliente
npm test   # 11 testes de ponta a ponta
```

Roteiro sugerido:
1. No app do cliente, use **Teste rápido**: "Quero marcar dermatologista", depois "1".
2. Pergunte o valor da consulta clínica. A resposta mostra preço e duração diferentes por profissional.
3. Em **Teste a proteção**, experimente o pedido de desconto, o prompt injection, o pedido de dados de terceiros e o assunto fora do escopo.
4. No painel:
   - marque um horário como **Faltou** ou **Cancelar (pela clínica)** e veja as novas datas chegarem no app;
   - crie um **bloqueio** de agenda e veja a remarcação automática;
   - abra **Segurança** para ver as tentativas bloqueadas.
