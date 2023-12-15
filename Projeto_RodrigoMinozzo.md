**Documentação do Projeto**

# Introdução

## 1.1. Objetivo do Documento

Este documento tem como objetivo fornecer informações detalhadas sobre o desenvolvimento e os testes do Sistema de Gerenciamento de TI. Ele servirá como referência para a equipe de desenvolvimento, testes e demais stakeholders.

## 1.2. Escopo do Projeto

O projeto visa desenvolver e implementar um sistema abrangente para gerenciamento de ativos, monitoramento de rede, gestão de incidentes e geração de relatórios eficientes na empresa.

# Requisitos Funcionais

## 2.1. Cadastro de Ativos

### 2.1.1. Registro de Ativos

**Descrição:** O sistema deve permitir o registro de todos os ativos de hardware e software.

**Exemplo:**

{
  "id": 001,
  "tipo": "Hardware",
  "nome": "Laptop Dell XPS",
  "departamento": "Desenvolvimento",
  "usuario_responsavel": "João Silva",
  "data_aquisicao": "2023-01-15"
}

## 2.1.2. Associação de Ativos

**Descrição:** Os ativos devem ser associados a departamentos e usuários responsáveis.

**Exemplo:**

{
  "id": 001,
  "departamento": "Desenvolvimento",
  "usuario_responsavel": "João Silva"
}


## 2.1.3. Registro de Equipamentos Substituídos

**Descrição:** O sistema deve registrar equipamentos substituídos, associando-os ao usuário que teve o equipamento substituído.

**Exemplo:**
{
  "id_substituido": 001,
  "id_novo": 002,
  "usuario_substituido": "Maria Oliveira",
  "data_substituicao": "2023-02-20"
}

## 2.2. Monitoramento de Rede

### 2.2.1. Monitoramento em Tempo Real

**Descrição:** O sistema deve permitir o monitoramento em tempo real do tráfego de rede.

**Exemplo:**

{
  "data": "2023-03-01T12:30:00",
  "trafego_rede": "10 MBps"
}

### 2.2.2. Alertas Automáticos

**Descrição:**  Alertas automáticos devem ser enviados para eventos críticos, como falhas de conectividade.

**Exemplo:**

{
  "tipo_alerta": "Falha de Conectividade",
  "descricao": "Servidor principal indisponível",
  "data_alerta": "2023-03-01T12:45:00"
}

## 2.3. Gestão de Incidentes

### 2.3.1. Abertura, Acompanhamento e Fechamento de Chamados

**Descrição:** O sistema deve permitir a abertura, acompanhamento e fechamento de chamados.

**Exemplo:**

{
  "id_chamado": 001,
  "descricao": "Problema de conexão com a impressora",
  "status": "Aberto",
  "data_abertura": "2023-03-01T13:00:00",
  "usuario_reportante": "Ana Pereira"
}

### 2.3.2. Priorização Automática

**Descrição:**  Os chamados devem ser priorizados automaticamente com base na gravidade do incidente.

**Exemplo:**
{
  "id_chamado": 002,
  "descricao": "Servidor principal indisponível",
  "status": "Aberto",
  "gravidade": "Alta",
  "data_abertura": "2023-03-01T13:15:00"
}

## 2.4. Relatórios e Métricas

### 2.4.1. Geração de Relatórios Periódicos

**Descrição:** O sistema deve gerar relatórios periódicos sobre o desempenho da rede e incidentes.

**Exemplo:**

{
  "tipo_relatorio": "Desempenho da Rede",
  "periodo": "Mensal",
  "data_geracao": "2023-04-01",
  "dados": { /* Dados do relatório */ }
}

### 2.4.2. Métricas para Avaliação do Suporte de TI

**Descrição:**  Métricas devem ser disponibilizadas para avaliação da eficiência do suporte de TI.

**Exemplo:**
{
  "tipo_metrica": "Tempo Médio de Resolução",
  "periodo": "Semanal",
  "data_calculo": "2023-04-03",
  "valor": "2 horas"
}

# Requisitos Requisitos Não Funcionais

## 3.1. Segurança

### 3.1.1. Criptografia de Dados

**Descrição:** Dados sensíveis no sistema devem ser criptografados.


**Exemplo:**

{
  "dados_sensiveis": "Texto confidencial",
  "dados_criptografados": "f8b1e53c3e1a..."
}

## 3.1.2. Controle de Acesso

**Descrição:** Deve haver controle de acesso por usuário, baseado em permissões, garantindo a privacidade das informações.

**Exemplo:**

{
  "usuario": "JoaoSilva",
  "permissoes": ["leitura", "escrita"]
}

### 3.2 Desempenho

#### 3.2.1 Resposta Rápida do Sistema
**Descrição:** O sistema deve manter uma resposta rápida, mesmo em situações de alta carga.
**Exemplo:** Tempo de resposta menor que 2 segundos para consultas comuns.

#### 3.2.2 Otimização do Banco de Dados
**Descrição:** O banco de dados deve ser otimizado para consultas eficientes.
**Exemplo:** Uso de índices adequados para melhorar o desempenho.

### 3.3 Integração com Ferramentas Existentes

#### 3.3.1 Integração com Ferramentas de Monitoramento Externas
**Descrição:** O sistema deve ser integrado com ferramentas externas para monitoramento.
**Exemplo:** Recebimento de dados externos para análise.

#### 3.3.2 Compatibilidade com Sistemas de E-mail e APIs
**Descrição:** O sistema deve ser compatível com sistemas de e-mail para notificações e APIs de ferramentas externas.
**Exemplo:** Envio de notificações para o sistema de e-mails da empresa.

## 4 Divisão de Tarefas

### 4.1 Sprint 1: Configuração Inicial (1 semana)

#### 4.1.1 Configuração do Ambiente de Desenvolvimento
**Responsável:** [Nome do Responsável]
**Descrição:** Configuração inicial do ambiente de desenvolvimento.

#### 4.1.2 Inicialização do Repositório no GitLab
**Responsável:** [Nome do Responsável]
**Descrição:** Inicialização do repositório no GitLab para controle de versionamento.

#### 4.1.3 Revisão e Confirmação dos Requisitos com a Equipe
**Responsável:** [Nome do Responsável]
**Descrição:** Revisão e confirmação dos requisitos com a equipe de desenvolvimento.

### 4.2 Sprint 2: Desenvolvimento do Sistema (3 semanas)

#### 4.2.1 Backend: Configuração do Servidor e Banco de Dados
**Responsável:** [Nome do Responsável]
**Descrição:** Configuração do servidor e banco de dados.

#### 4.2.2 Backend: Implementação das Lógicas de Cadastro de Ativos
**Responsável:** [Nome do Responsável]
**Descrição:** Implementação das lógicas de cadastro de ativos no backend.

#### 4.2.3 Frontend: Desenvolvimento da Interface de Usuário para Cadastro de Ativos
**Responsável:** [Nome do Responsável]
**Descrição:** Desenvolvimento da interface de usuário para o cadastro de ativos.

### 4.3 Sprint 3: Integração e Monitoramento de Rede (2 semanas)

#### 4.3.1 Configuração de Ferramentas de Monitoramento de Rede
**Responsável:** [Nome do Responsável]
**Descrição:** Configuração de ferramentas de monitoramento de rede.

#### 4.3.2 Desenvolvimento de Módulos de Integração com o Sistema
**Responsável:** [Nome do Responsável]
**Descrição:** Desenvolvimento de módulos de integração com o sistema.

### 4.4 Sprint 4: Segurança e Desempenho (2 semanas)

#### 4.4.1 Implementação de Protocolos de Criptografia
**Responsável:** [Nome do Responsável]
**Descrição:** Implementação de protocolos de criptografia para dados sensíveis.

#### 4.4.2 Otimização do Sistema para Garantir Desempenho em Situações de Carga
**Responsável:** [Nome do Responsável]
**Descrição:** Otimização do sistema para garantir desempenho em situações de carga.

### 4.5 Sprint 5: Relatórios e Métricas (2 semanas)

#### 4.5.1 Desenvolvimento de Módulos de Geração de Relatórios
**Responsável:** [Nome do Responsável]
**Descrição:** Desenvolvimento de módulos de geração de relatórios.

#### 4.5.2 Implementação de Métricas para Avaliação do Desempenho do Suporte de TI
**Responsável:** [Nome do Responsável]
**Descrição:** Implementação de métricas para avaliação do desempenho do suporte de TI.

### 4.6 Sprint 6: Testes e Validação (2 semanas)

#### 4.6.1 Testes de Segurança e Desempenho
**Responsável:** [Nome do Responsável]
**Descrição:** Realização de testes de segurança e desempenho.

#### 4.6.2 Validação dos Módulos de Relatórios e Métricas
**Responsável:** [Nome do Responsável]
**Descrição:** Validação dos módulos de relatórios e métricas.

### 4.7 Sprint 7: Documentação e Entrega (1 semana)

#### 4.7.1 Documentação do Código e do Projeto
**Responsável:** [Nome do Responsável]
**Descrição:** Documentação do projeto.

#### 4.7.2 Preparação para a Entrega do Sistema ao Cliente
**Responsável:** [Nome do Responsável]
**Descrição:** Preparação para a entrega do sistema ao cliente.

## 5 Ferramentas do Repositório

### 5.1 GitLab
**Descrição:** O GitLab será utilizado para controle de versionamento do código-fonte, gerenciamento de branches, e revisão de código por meio de merge requests.

### 5.2 Trello
**Descrição:** O Trello será empregado para gerenciar tarefas e iterações, utilizando um quadro kanban para visualizar o progresso das atividades.

### 5.3 Slack
**Descrição:** O Slack será utilizado para comunicação interna e colaboração em tempo real entre membros da equipe.

## Resultados do Desenvolvimento

O projeto de Sistema de Gerenciamento de TI foi concluído com sucesso, cumprindo todos os requisitos funcionais e não funcionais estabelecidos. Abaixo, apresentamos os principais resultados alcançados:

### 6. Desenvolvimento do Sistema

#### 6.1 Backend e Frontend

- **Configuração do Ambiente de Desenvolvimento:** Realizada com sucesso, permitindo um ambiente de trabalho eficiente para a equipe.
  
- **Implementação das Lógicas de Cadastro de Ativos:** O backend foi desenvolvido para permitir o cadastro eficiente de ativos, integrado ao frontend que oferece uma interface amigável para os usuários.

- **Monitoramento em Tempo Real e Alertas Automáticos:** Os módulos de monitoramento de rede foram implementados, proporcionando a visualização em tempo real do tráfego e alertas automáticos para eventos críticos.

- **Segurança e Otimização do Sistema:** Foram implementados protocolos de criptografia para dados sensíveis, garantindo a segurança das informações. O sistema foi otimizado para manter um desempenho excepcional mesmo em situações de carga elevada.

- **Relatórios Periódicos e Métricas:** Módulos de geração de relatórios periódicos foram desenvolvidos, fornecendo dados sobre o desempenho da rede e incidentes. Métricas para avaliação do suporte de TI foram implementadas, permitindo uma análise eficiente.

### 7. Testes e Validação

#### 7.1 Testes de Segurança e Desempenho

- **Testes de Segurança:** Foram realizados testes extensivos para garantir a integridade e segurança dos dados. O sistema resistiu a tentativas de violação e protegeu as informações sensíveis.

- **Testes de Desempenho:** O sistema foi submetido a testes de desempenho sob diferentes cenários de carga, cumprindo o requisito de resposta rápida, com tempo de resposta médio abaixo de 2 segundos.

#### 7.2 Validação dos Módulos de Relatórios e Métricas

- **Validação dos Relatórios:** Os relatórios gerados foram validados em relação à precisão e abrangência dos dados, proporcionando informações úteis para a tomada de decisões.

- **Avaliação das Métricas:** As métricas implementadas foram avaliadas, destacando áreas de melhoria e fornecendo insights sobre o desempenho do suporte de TI.

## Análise de Resultados

A análise dos resultados revela que o Sistema de Gerenciamento de TI atendeu com sucesso às expectativas e requisitos estabelecidos. As principais conquistas incluem:

- **Eficiência Operacional:** A automação de processos, o monitoramento em tempo real e os alertas automáticos contribuíram significativamente para a eficiência operacional.

- **Segurança e Confiabilidade:** A implementação de protocolos de criptografia e os testes de segurança demonstraram a robustez do sistema em termos de segurança.

- **Desempenho:** O sistema manteve um desempenho consistente, mesmo em situações de carga elevada, atendendo ao requisito de resposta rápida.

- **Tomada de Decisão Informada:** Os relatórios periódicos e métricas forneceram dados valiosos para uma tomada de decisão informada, contribuindo para a melhoria contínua do suporte de TI.

### Conclusões

O Sistema de Gerenciamento de TI representa uma solução sólida para as necessidades da empresa, integrando eficientemente o gerenciamento de ativos, monitoramento de rede, gestão de incidentes e geração de relatórios. A colaboração efetiva da equipe, aliada ao uso de ferramentas adequadas, resultou no sucesso deste projeto.

Este documento serve como um registro abrangente dos resultados alcançados, destacando os pontos-chave do desenvolvimento, testes e análises realizadas.