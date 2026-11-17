# Cortes Virais

Sistema automático que acompanha lives e vídeos do YouTube, encontra os momentos de
maior impacto, gera cortes verticais de ~30 s com legenda e publica no YouTube
(Shorts) e no Instagram (Reels).

## Como funciona

```
descoberta ─► captura ─► sinais ─► candidatos ─► IA (nota, título) ─► render ─► fila ─► YouTube / Instagram
```

| Etapa | O que faz |
|---|---|
| Descoberta | Lives e gravações dos canais configurados, ou busca aberta por mais exibições, ou link direto. |
| Sinais | **Chat** (ritmo de mensagens, com peso para "KKKK", "clipa", emojis), **áudio** (gritos, risadas) e o gráfico **"mais repetidos"** do YouTube. Cada um é medido contra a linha de base do próprio vídeo. |
| IA | Claude vê quadros, transcrição e chat de cada candidato; dá nota geral e por critério (gancho, emoção, clareza, compartilhável), ajusta início e fim para começar no gancho, escreve a frase de gancho, título, descrição e hashtags, e reprova trechos sem graça ou arriscados. |
| Render | 1080×1920 com enquadramento que segue os rostos, gancho fixo no topo, legendas karaokê, áudio nivelado, crédito ao canal. |
| Aprendizado | De hora em hora mede as visualizações dos cortes publicados; a partir de 8 cortes medidos, a IA recebe os mais e os menos vistos do canal como referência. |
| Publicação | Fila com limite diário por plataforma. Cortes de live são publicados na hora; os de vídeo gravado são espaçados. |

**Live:** o ffmpeg grava a transmissão num buffer circular de 5 min. A cada 2 s o
detector compara chat e volume com os últimos minutos; num pico, recorta
`[pico − 22 s, pico + 8 s]`, avalia e publica — normalmente em 1 a 2 minutos.

**Vídeo gravado:** analisa o vídeo inteiro, gera o triplo de candidatos necessários
e fica com os de melhor nota.

### Um modelo de IA para cada papel

| Papel | Modelo padrão | Por quê |
|---|---|---|
| Triagem dos candidatos | Haiku 5.5 | Lê só texto de até 15 trechos e descarta os fracos. Tarefa simples e volumosa. |
| Avaliação durante a live | Sonnet 5.5 | Precisa decidir em segundos, com imagens, para publicar antes dos outros. |
| Julgamento final (vídeo gravado) | Opus 5.5 | Dá as notas, escreve o gancho e dirige a edição. É onde a qualidade se decide. |

Os três são trocáveis na aba Configurações.

### Edição dinâmica

O corte não fica num plano só. A partir do layout da cena e do momento-chave (indicado
pela IA, ou o pico de volume), o sistema monta uma sequência de planos:

- **Gameplay com facecam:** abre 1,5 s no rosto do jogador, alterna tela dividida e jogo
  em tela cheia, e volta ao rosto na reação.
- **Uma pessoa falando:** cortes com zoom a cada poucos segundos, mais fechado no
  momento-chave; pausas longas de fala são removidas.
- **Abertura pelo ápice:** quando o começo é morno, a IA pode abrir com 1,5 s do melhor
  momento antes de voltar ao início.
- **Tipografia:** fontes pesadas e modernas embutidas no projeto (Montserrat Black por
  padrão; também Montserrat ExtraBold, Poppins ExtraBold, Anton e Bangers), trocáveis na
  aba Configurações.
- **Acabamento:** gancho com entrada animada, legenda karaokê com palavras-chave em
  destaque, barra de progresso, nome do canal no canto.

### Narração do canal (opcional)

A IA escreve até três falas curtas no estilo dos narradores de canais de cortes —
abertura (por que ficar), tensão (para onde olhar) e reação (o que todo mundo pensou) — e
uma pergunta final para puxar comentários, dita sobre o último quadro congelado. Uma voz
sintética as diz por cima do vídeo, com o áudio original abaixado. A IA só narra quando
isso melhora o corte.

A voz padrão roda no seu computador, sem custo. O instalador já a baixa; se não baixou,
use o botão "Instalar a voz agora" na aba Configurações. Depois ative "Narrar os
cortes". Há também a opção ElevenLabs (mais natural, paga por uso).

### Compilação "Top N"

Formato extra, **desligado por padrão** (o foco do sistema são Shorts e Reels). Ligado
na aba Configurações, de cada vídeo com pelo menos três cortes sai também um vídeo horizontal com contagem
regressiva: abertura, cartão numerado antes de cada momento e narração nas passagens,
com capítulos na descrição. É publicado só no YouTube, como vídeo comum.

### Monetização

A aba Monetização reúne os caminhos de receita e o andamento de cada um:

1. **Campanhas que pagam por visualização.** Streamers e marcas pagam quem publica
   cortes deles (em torno de US$ 1 por mil visualizações, sem mínimo de inscritos).
   Cadastre na aba Canais o valor, o texto que a campanha exige na descrição e o
   comprovante de autorização; o sistema aplica o texto em todo corte daquele canal e
   estima os ganhos pelas visualizações medidas.
2. **Acordo direto com o criador.**
3. **Anúncios do YouTube.** Mostra inscritos e visualizações contra as metas do Programa
   de Parcerias e a parcela de cortes com narração.
4. **Instagram**, com alcance limitado para contas de republicação.

### Bases de conhecimento

Arquivos `.md` na pasta `conhecimento/`, editáveis na aba Configurações. A IA recebe uma
base quando o título, o canal ou a transcrição contém uma das palavras do cabeçalho.
Já vêm duas: `tecnicas-de-cortes` (sempre ativa) e `gta-vi`.

### Enquadramento automático (`formato: auto`)

| Cena detectada | Layout |
|---|---|
| Uma pessoa falando | Recorte 9:16 centrado no rosto |
| Duas pessoas (podcast, entrevista) | Uma em cima, outra embaixo |
| Rosto pequeno num canto (gameplay com facecam) | Câmera em cima, jogo embaixo |
| Nenhum rosto consistente | Vídeo inteiro sobre fundo desfocado |

O layout é escolhido uma vez por corte. Não há troca de enquadramento conforme quem fala.

## Instalação e abertura

Requer `ffmpeg` e **Python entre 3.10 e 3.13** (as versões 3.14 e 3.15 ainda não têm
todas as bibliotecas de vídeo e voz).

| Sistema | Instalar (uma vez) | Abrir |
|---|---|---|
| Windows | dois cliques em `instalar.bat` | dois cliques em `Cortes Virais.bat` |
| macOS | `./instalar.sh` no Terminal | dois cliques em `Cortes Virais.command` |
| Linux | `./instalar.sh` | `./cortes-virais.sh` |

No Windows, se faltar algo: `winget install Python.Python.3.12` e
`winget install Gyan.FFmpeg`. O instalador cria uma pasta isolada (`.venv`), instala
tudo, baixa a voz da narração e prepara o `config.yaml`.

O programa abre numa janela própria. **Enquanto ela estiver aberta, tudo roda**: lives
acompanhadas, análises, fila de publicação e canais seguidos. Ao fechar, o que estava em
andamento é guardado e retomado na próxima abertura. O registro fica em `dados/cortes.log`.

Instalação manual, se preferir: `pip install -r requirements.txt`, copiar
`config.exemplo.yaml` para `config.yaml` e rodar `python -m cortes app`.

### Contas

- **Claude:** `ANTHROPIC_API_KEY` no `.env`. Sem ela o sistema funciona, ordenando só
  pelos sinais e com títulos genéricos.
- **YouTube:** crie um projeto no Google Cloud, ative a *YouTube Data API v3*, crie uma
  credencial OAuth do tipo "app para computador", salve como `client_secret.json` e rode
  `python -m cortes login-youtube` uma vez, logado na conta do canal de destino.
- **Instagram:** conta profissional + app na Meta com `instagram_content_publish`.
  Coloque `IG_USER_ID` e um token de longa duração em `IG_ACCESS_TOKEN`.

## Painel

```bash
python -m cortes painel        # abre em http://localhost:8000
```

Cole o link de um vídeo ou de uma live no topo; o sistema identifica o tipo sozinho.

| Aba | O que mostra |
|---|---|
| **Lives** | Cada live acompanhada (várias ao mesmo tempo): tempo, mensagens por minuto, gráfico da empolgação contra o limiar de corte e os picos detectados. |
| **Análises** | Vídeos gravados em processamento, com etapa e progresso. Ao terminar, "Ver análise" mostra a linha do tempo com todos os trechos considerados, a nota e o motivo de cada um. |
| **Cortes** | Os cortes prontos, agrupados pelo vídeo ou live de origem, com player. |
| **Publicações** | Situação das contas, limite diário e a fila: o que saiu, o que falhou (com o erro) e botões para publicar ou tentar de novo. |
| **Configurações** | Passo a passo para ligar a IA e conectar YouTube e Instagram, todas as opções com explicação, escolha dos modelos e editor das bases de conhecimento. |
| **Monetização** | Caminhos de receita, ganhos estimados das campanhas, metas do Programa de Parcerias e originalidade do canal. |
| **Canais** | Canais dos links que você enviou, tratados como confiáveis. Ligue "Acompanhar automaticamente" para cortar as lives e vídeos novos deles sem enviar link. |

**Modo teste:** com a chave ligada, o vídeo ou a live é processado normalmente, mas os
cortes ficam só na aba Cortes. Nada é publicado até você clicar em "Aprovar e publicar".
Para testar sem internet, cole o caminho de um arquivo de vídeo local; "Simular live"
reproduz o arquivo em tempo real como se fosse uma transmissão.

O painel não tem senha e por padrão só aceita conexões do próprio computador. Lives em
acompanhamento não são retomadas se o painel for reiniciado; cortes e fila, sim.

## Linha de comando

```bash
python -m cortes vod  "https://www.youtube.com/watch?v=..."   # vídeo ou live já encerrada
python -m cortes live "https://www.youtube.com/watch?v=..."   # live em andamento
python -m cortes buscar        # mostra o que a descoberta encontra
python -m cortes auto          # tudo automático, em laço
python -m cortes publicar      # publica o que está na fila
python -m cortes status
```

`--sem-publicar` (antes do comando) gera só os arquivos, em `dados/<id>/`:
`python -m cortes --sem-publicar vod video.mp4 --chat chat.jsonl`

Para rodar 24 h, deixe `python -m cortes auto` num servidor (systemd, tmux ou Docker).

## Pontos de atenção

- **Direitos autorais.** Publicar trechos de vídeos de terceiros sem autorização gera
  reivindicações e strikes — três strikes encerram o canal. Por isso o modo automático
  só usa `fontes.canais_autorizados` por padrão; muitos criadores autorizam cortes
  publicamente. A busca aberta existe (`exigir_autorizacao: false`), por sua conta.
- **Uploads privados no YouTube.** Projetos de API não auditados pelo Google têm os
  uploads travados como *privados*. Para publicar como público é preciso passar pela
  auditoria de conformidade da API (formulário do Google).
- **Cota do YouTube.** A cota padrão permite poucos uploads por dia (`max_por_dia: 6`);
  cada consulta da busca aberta custa 100 das 10 000 unidades diárias.
- **Monetização.** O YouTube nega monetização a "conteúdo reutilizado" mesmo com
  autorização do dono, e passou a distribuir menos os Shorts repostados. Gancho, legenda
  e reenquadramento ajudam na retenção, mas o que a política pede é contribuição própria
  (comentário, narração, análise). A narração de abertura vai nessa direção, mas uma
  frase por vídeo, com voz sintética, é pouco: o YouTube também nega monetização a
  conteúdo "inautêntico" produzido em série por modelo. Trate a narração como apoio, e
  não como garantia de aprovação.
- **Sem chat nem "mais repetidos"** (vídeo comum, pouco assistido), a detecção usa só o
  áudio, e a IA passa a ser o filtro principal.

## Testes

```bash
pip install pytest && python -m pytest tests
```

Usam vídeo, chat e live sintéticos gerados pelo ffmpeg; não acessam a internet.
