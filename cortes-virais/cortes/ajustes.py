"""Configurações editáveis pelo painel: descrição de cada campo, validação e gravação.

Cada campo tem rótulo e ajuda em linguagem simples; a página monta o formulário a partir
desta lista, então acrescentar uma opção aqui já a faz aparecer na tela.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

import yaml

MODELOS = [
    ["claude-haiku-5-5", "Haiku 5.5 — o mais rápido e barato"],
    ["claude-sonnet-5-5", "Sonnet 5.5 — equilíbrio entre rapidez e qualidade"],
    ["claude-opus-5-5", "Opus 5.5 — o melhor julgamento criativo"],
]

# Catálogo gratuito do build.nvidia.com (muda com o tempo; dá para pôr outro no config.yaml).
MODELOS_NVIDIA = [
    ["google/gemma-4-31b-it", "Gemma 4 31B — vê imagens, bom em português, rápido (recomendado)"],
    ["nvidia/nemotron-3.5-super-vl-120b-a12b", "Nemotron 3.5 Super VL — vê imagens, mas recusa cenas violentas e às vezes estoura a resposta"],
    ["mistralai/mistral-large-4-1t-a52b", "Mistral Large 4 — só texto, escreve bem"],
    ["nvidia/nemotron-3-ultra-550b-a55b", "Nemotron 3 Ultra — só texto, o maior"],
    ["z-ai/glm-5.3-flash", "GLM 5.3 Flash — só texto, rápido"],
    ["openai/gpt-oss-20b", "GPT-OSS 20B — só texto, o mais leve"],
]

# (seção, descrição da seção, [campos])
SECOES = [
    ("Cortes", "Tamanho, quantidade e aparência dos cortes.", [
        ("fontes.duracao_max_h", "inteiro", "Vídeo mais longo aceito (horas)",
         "Vídeos gravados mais longos que isto não são analisados (lives gravadas costumam ter "
         "de 4 a 10 h). Quanto maior, mais tempo de download e de análise.", {"min": 1, "max": 24}),
        ("cortes.duracao", "inteiro", "Duração alvo (segundos)",
         "O tamanho que o sistema procura. 30 é um bom ponto de partida.", {"min": 10, "max": 90}),
        ("cortes.duracao_min", "inteiro", "Duração mínima",
         "A IA pode encurtar o corte até aqui para ele terminar logo depois do desfecho.",
         {"min": 8, "max": 90}),
        ("cortes.duracao_max", "inteiro", "Duração máxima",
         "A IA pode estender o corte até aqui para não cortar o desfecho.", {"min": 10, "max": 180}),
        ("cortes.fechar_frases", "booleano", "Não cortar ninguém no meio da fala",
         "A IA lê o que é dito depois do corte e o estende até a explicação, a história ou o "
         "raciocínio terminar (e, se ele começa no meio de uma frase, volta até o começo "
         "dela), mesmo passando da duração máxima. Sem IA, vale a próxima pausa da fala.",
         {}),
        ("cortes.extensao_max", "inteiro", "Quanto o corte pode crescer para fechar o raciocínio (segundos)",
         "Limite da extensão acima. Mais alto: explicações longas cabem inteiras, e alguns "
         "cortes ficam mais longos.", {"min": 0, "max": 90}),
        ("cortes.por_video", "inteiro", "Cortes por vídeo gravado",
         "Quantos cortes, no máximo, sair de cada vídeo. Só entram os que passam da nota mínima.",
         {"min": 1, "max": 20}),
        ("cortes.formato", "escolha", "Enquadramento",
         "Automático segue os rostos e escolhe o layout de cada cena. Os demais são fixos.",
         {"opcoes": [["auto", "Automático (recomendado)"],
                     ["vertical_blur", "Vídeo inteiro com fundo desfocado"],
                     ["vertical_crop", "Recorte central"], ["original", "Horizontal, sem recorte"]]}),
        ("cortes.legendas", "booleano", "Legendas", "Legenda grande queimada no vídeo.", {}),
        ("cortes.fonte", "escolha", "Fonte das legendas e do gancho",
         "Todas são pesadas e legíveis em tela pequena. Montserrat Black é o padrão dos "
         "grandes canais de cortes; Anton é estreita e alta; Bangers tem cara de quadrinhos, "
         "boa para humor.",
         {"opcoes": [[f, f] for f in ("Montserrat Black", "Montserrat ExtraBold",
                                      "Poppins ExtraBold", "Anton", "Bangers")]}),
        ("cortes.karaoke", "booleano", "Destacar a palavra falada",
         "A palavra dita no momento muda de cor, como nos vídeos curtos mais vistos.", {}),
        ("cortes.tema", "escolha", "Tema de cores",
         "Define a cor da palavra falada, das palavras-chave, da caixa do gancho e dos "
         "detalhes. Manter um tema só dá identidade ao canal.",
         {"opcoes": [["classico", "Clássico — amarelo e verde, gancho em caixa branca"],
                     ["impacto", "Impacto — gancho em caixa vermelha"],
                     ["neon", "Neon — ciano e rosa, gancho em caixa preta"],
                     ["limpo", "Limpo — amarelo único, gancho em caixa preta"],
                     ["personalizado", "Personalizado — usa a cor abaixo"]]}),
        ("cortes.cor_destaque", "cor", "Cor do tema personalizado",
         "Só vale quando o tema é “Personalizado”.", {}),
        ("cortes.capa", "booleano", "Gerar capa (thumbnail)",
         "Cria uma capa com o melhor quadro e de 1 a 3 palavras grandes, enviada ao YouTube. "
         "No Instagram, a capa é o quadro do momento-chave. O YouTube só aceita capa própria "
         "em canal verificado por telefone.", {}),
        ("cortes.gancho", "booleano", "Gancho na tela",
         "Frase curta escrita pela IA, fixa no topo, para despertar curiosidade.", {}),
        ("cortes.marca", "texto", "Nome do seu canal no vídeo",
         "Aparece discreto no canto, por exemplo @meucanal. Deixe vazio para não mostrar.", {}),
        ("publicar.creditar_fonte", "booleano", "Creditar o canal de origem",
         "Mostra o nome do canal original no vídeo e o link na descrição.", {}),
    ]),
    ("Edição dinâmica", "Como o corte é montado para prender a atenção.", [
        ("edicao.dinamica", "booleano", "Trocar de plano ao longo do corte",
         "Em gameplay alterna rosto, tela dividida e jogo; em vídeo de fala, dá cortes com "
         "zoom. Desligado, o corte usa um plano só.", {}),
        ("edicao.abrir_no_rosto", "booleano", "Gameplay: abrir no rosto do jogador",
         "O primeiro segundo e meio mostra a reação do jogador. Rosto é o que mais segura "
         "quem está rolando a tela.", {}),
        ("edicao.seguir_falante", "booleano", "Duas pessoas: fechar em quem fala",
         "Em podcasts e entrevistas, o corte alterna entre o close de quem está falando e o "
         "plano com os dois. A fala é estimada pelo movimento da boca.", {}),
        ("edicao.cortar_silencios", "booleano", "Cortar pausas longas de fala",
         "Tira o tempo morto entre as falas. Não se aplica a gameplay, onde o silêncio "
         "costuma ter ação.", {}),
        ("edicao.pausa_minima", "numero", "Pausa mínima para cortar (segundos)",
         "Pausas menores que isso ficam. Valores baixos deixam a fala atropelada.",
         {"min": 0.6, "max": 5}),
        ("edicao.abertura_pico", "booleano", "Permitir abrir pelo ápice",
         "Quando o começo é morno e o ápice é forte, a IA pode abrir com 1,5 s do melhor "
         "momento antes de voltar ao início.", {}),
        ("edicao.barra_progresso", "booleano", "Barra de progresso",
         "Linha fina no topo que avança com o vídeo; ajuda a pessoa a ficar até o fim.", {}),
        ("edicao.realce", "booleano", "Acabamento de cor",
         "Um pouco mais de saturação, contraste e nitidez, com vinheta leve nas bordas.", {}),
    ]),
    ("Narração do canal", "Uma frase de abertura dita por uma voz sintética, escrita pela IA: "
     "contexto e um olhar próprio sobre o trecho. A voz roda no seu computador, sem custo.", [
        ("narracao.motor", "escolha", "Voz",
         "A local é gratuita. A ElevenLabs soa mais natural, cobra por uso e exige a chave "
         "ELEVENLABS_API_KEY e o ID de uma voz.",
         {"opcoes": [["piper", "Local e gratuita (Piper)"], ["elevenlabs", "ElevenLabs (paga)"]]}),
        ("narracao.voz_elevenlabs", "texto", "ID da voz na ElevenLabs",
         "Copie em elevenlabs.io, na biblioteca de vozes. Só vale para o motor ElevenLabs.", {}),
        ("narracao.max_falas", "inteiro", "Falas por corte (máximo)",
         "A IA decide quantas usar, de zero até este limite: abertura, tensão e reação.",
         {"min": 0, "max": 3}),
        ("narracao.encerramento", "booleano", "Encerrar com pergunta ao público",
         "Congela o último quadro por 2 a 3 s enquanto o narrador faz uma pergunta para "
         "puxar comentários.", {}),
        ("narracao.ativa", "booleano", "Narrar os cortes",
         "Precisa da voz instalada (veja “Recursos opcionais” no topo desta página). Sem "
         "ela, os cortes saem normalmente, sem narração.", {}),
        ("narracao.voz", "texto", "Arquivo da voz",
         "Caminho do arquivo .onnx baixado. O padrão é uma voz masculina em português do Brasil.",
         {}),
        ("narracao.velocidade", "numero", "Velocidade da fala",
         "1 é o ritmo natural. Um pouco acima disso combina com vídeos curtos.",
         {"min": 0.7, "max": 1.6}),
        ("narracao.volume", "numero", "Volume da narração", "", {"min": 0.3, "max": 2}),
        ("narracao.fundo", "numero", "Volume do vídeo durante a narração",
         "0 silencia o original enquanto o narrador fala; 1 mantém no volume normal.",
         {"min": 0, "max": 1}),
    ]),
    ("Inteligência artificial", "Qual modelo faz cada parte e o quanto ele é exigente.", [
        ("ia.ativa", "booleano", "Usar IA",
         "Desligada, os cortes são escolhidos só por chat e áudio, com títulos genéricos.", {}),
        ("ia.provedor", "escolha", "Provedor da IA",
         "Claude escreve melhor e cobra por uso (chave ANTHROPIC_API_KEY). NVIDIA é gratuita, "
         "com limite de uso e textos um pouco mais simples, e a própria NVIDIA a indica para "
         "testes (chave NVIDIA_API_KEY). Os modelos de cada provedor são escolhidos abaixo.",
         {"opcoes": [["anthropic", "Claude (Anthropic) — pago, melhor qualidade"],
                     ["nvidia", "NVIDIA Build — gratuito, para testes"]]}),
        ("ia.reserva", "escolha", "IA reserva (se a principal cair)",
         "Quando a IA principal falha (fora do ar, limite de uso, recusa), o pedido vai para o "
         "Claude Code instalado neste computador, com a sua conta Claude, como no J.A.R.V.I.S. "
         "Gasta o limite de uso do seu plano, não créditos da API.",
         {"opcoes": [["claude_code", "Claude Code (sua conta Claude, neste computador)"],
                     ["nenhuma", "Nenhuma: o vídeo segue sem IA"]]}),
        ("ia.reserva_modelo", "escolha", "Modelo da IA reserva",
         "Sonnet equilibra qualidade e consumo do plano; Haiku gasta menos; Opus julga melhor.",
         {"opcoes": MODELOS}),
        ("ia.local", "escolha", "IA local (último recurso, sem internet)",
         "Se a principal e a reserva falharem, usa a IA local do Ollama, como no J.A.R.V.I.S. "
         "Ela é mais fraca: a nota vem só das métricas (chat, áudio, replays) e a IA local "
         "apenas aprova ou reprova cada trecho; a nota mínima não vale nesse caso.",
         {"opcoes": [["ollama", "Ollama neste computador"], ["nenhuma", "Nenhuma: segue sem IA"]]}),
        ("ia.local_modelo", "texto", "Modelo da IA local",
         "Vazio escolhe o melhor instalado (qwen3:30b, gpt-oss:20b, qwen3:14b, gemma3…). "
         "Ou escreva o nome exato, como gemma3:4b.", {}),
        ("ia.nota_minima", "inteiro", "Nota mínima para virar corte",
         "De 0 a 100. Mais alto: menos cortes, mais selecionados. 60 a 70 costuma funcionar.",
         {"min": 0, "max": 100}),
        ("ia.modelos.triagem", "escolha", "Claude: triagem dos candidatos",
         "Lê só o texto de muitos trechos e descarta os fracos. Tarefa simples e volumosa: "
         "o modelo mais rápido dá conta.", {"opcoes": MODELOS}),
        ("ia.modelos.ao_vivo", "escolha", "Claude: avaliação durante a live",
         "Decide em segundos se um pico vira corte e escreve gancho e título. Precisa ser "
         "rápido para publicar antes dos outros.", {"opcoes": MODELOS}),
        ("ia.modelos.final", "escolha", "Claude: julgamento final de vídeos gravados",
         "Vê imagens e texto dos finalistas, dá as notas, escreve o gancho e dirige a "
         "edição. É aqui que a qualidade do corte se decide.", {"opcoes": MODELOS}),
        ("ia.nvidia.modelos.triagem", "escolha", "NVIDIA: triagem dos candidatos",
         "Só vale com o provedor NVIDIA. Lê só texto; um modelo rápido basta.",
         {"opcoes": MODELOS_NVIDIA}),
        ("ia.nvidia.modelos.ao_vivo", "escolha", "NVIDIA: avaliação durante a live",
         "Só vale com o provedor NVIDIA. Prefira um que veja imagens e responda rápido.",
         {"opcoes": MODELOS_NVIDIA}),
        ("ia.nvidia.modelos.final", "escolha", "NVIDIA: julgamento final de vídeos gravados",
         "Só vale com o provedor NVIDIA. Prefira um que veja imagens: os de “só texto” "
         "avaliam apenas a transcrição e o chat.", {"opcoes": MODELOS_NVIDIA}),
        ("ia.quadros", "inteiro", "Imagens por candidato",
         "Quantos quadros do vídeo a IA vê de cada trecho. Mais quadros: melhor avaliação "
         "visual e custo maior.", {"min": 1, "max": 8}),
    ]),
    ("Lives", "Sensibilidade da detecção em tempo real.", [
        ("live.limiar", "numero", "Sensibilidade (limiar de empolgação)",
         "O corte dispara quando a empolgação passa deste valor. Menor: mais cortes e mais "
         "falsos alarmes. Entre 3,5 e 5 é o usual.", {"min": 2, "max": 10}),
        ("live.palavras_limiar_menor", "texto", "Lives com sensibilidade maior",
         "Palavras do título, separadas por vírgula (ex.: GTA, Minecraft). Lives com alguma "
         "delas usam o limiar abaixo, que corta com menos empolgação.", {}),
        ("live.limiar_menor", "numero", "Limiar dessas lives",
         "Vale só para as lives com as palavras acima. Menor que o normal: mais cortes.",
         {"min": 1, "max": 10}),
        ("live.historico", "booleano", "Olhar também o que a live já passou",
         "Ao começar a acompanhar, uma segunda frente baixa o áudio do que já foi transmitido, "
         "acha os melhores momentos e corta, enquanto a primeira segue em tempo real.", {}),
        ("live.historico_horas", "numero", "Até quantas horas para trás",
         "Lives muito longas: limita o quanto do passado é analisado.", {"min": 0.5, "max": 12}),
        ("live.min_mensagens", "inteiro", "Mensagens mínimas em 10 s",
         "Evita disparo em chat quase parado.", {"min": 1, "max": 200}),
        ("live.pre", "inteiro", "Segundos antes do pico", "Quanto do antes entra no corte.",
         {"min": 5, "max": 60}),
        ("live.pos", "inteiro", "Segundos depois do pico", "Quanto do depois entra no corte.",
         {"min": 2, "max": 30}),
        ("live.espera", "inteiro", "Intervalo entre cortes da mesma live (segundos)",
         "Evita vários cortes do mesmo momento.", {"min": 20, "max": 900}),
        ("live.max_simultaneas", "inteiro", "Lives automáticas ao mesmo tempo",
         "Limite para os canais acompanhados automaticamente. Links enviados por você não "
         "contam.", {"min": 1, "max": 10}),
    ]),
    ("Vídeos com restrição", "Vídeos com restrição de idade só abrem com uma conta logada no "
     "YouTube. O programa usa os cookies do navegador em que você já está logado, só neste "
     "computador (nada é enviado a outro lugar).", [
        ("fontes.cookies_navegador", "escolha", "Navegador logado no YouTube",
         "O Firefox funciona melhor. Chrome e Edge travam os cookies enquanto estão abertos e, "
         "nas versões novas, protegem os cookies: se der erro, use o Firefox ou um arquivo.",
         {"opcoes": [["", "Nenhum (vídeos com restrição vão falhar)"], ["firefox", "Firefox"],
                     ["chrome", "Chrome"], ["edge", "Edge"], ["brave", "Brave"],
                     ["opera", "Opera"], ["vivaldi", "Vivaldi"]]}),
        ("fontes.cookies_arquivo", "texto", "Ou um arquivo cookies.txt",
         "Caminho de um cookies.txt exportado do YouTube (extensão “Get cookies.txt LOCALLY”). "
         "Se preenchido, vale no lugar do navegador. Guarde-o como uma senha.", {}),
    ]),
    ("Publicação", "Ritmo e limites de postagem.", [
        ("publicar.manual", "booleano", "Você decide o que publicar",
         "Ligado (recomendado): nenhum corte entra na fila sozinho. Cada corte novo fica "
         "“Aguardando você”, e no botão Publicar… você escolhe publicar agora ou pôr na fila. "
         "Desligado: os cortes aprovados pela IA vão direto para a fila.", {}),
        ("publicar.auto_acima", "inteiro", "Nota para postar sozinho",
         "Cortes com nota da IA acima deste valor entram sozinhos na fila das plataformas que "
         "aceitam publicação automática (veja abaixo), mesmo com “Você decide” ligado. 0 = nunca. Vídeos em modo teste e notas "
         "da IA local (só métricas) não contam.", {"min": 0, "max": 100}),
        ("publicar.imediato_acima", "inteiro", "Nota para postar na hora",
         "Acima deste valor o corte é publicado assim que fica pronto, sem esperar o intervalo "
         "nem os horários (o limite diário de cada plataforma continua valendo). 0 = nunca.",
         {"min": 0, "max": 100}),
        ("publicar.youtube.ativo", "booleano", "Publicar no YouTube", "", {}),
        ("publicar.youtube.automatico", "booleano", "YouTube: publicar sozinho pela nota",
         "Desligado: todo corte espera você avaliar no YouTube, qualquer que seja a nota.", {}),
        ("publicar.youtube.privacidade", "escolha", "Visibilidade no YouTube",
         "Enquanto o projeto do Google não for auditado, o YouTube mantém os envios privados.",
         {"opcoes": [["public", "Público"], ["unlisted", "Não listado"], ["private", "Privado"]]}),
        ("publicar.youtube.max_por_dia", "inteiro", "Máximo por dia no YouTube",
         "A cota padrão da API permite poucos envios diários.", {"min": 0, "max": 100}),
        ("publicar.instagram.ativo", "booleano", "Publicar no Instagram", "", {}),
        ("publicar.instagram.automatico", "booleano", "Instagram: publicar sozinho pela nota",
         "Ligado: os cortes que passam das notas abaixo vão sozinhos para o Instagram.", {}),
        ("publicar.instagram.auto_live_acima", "inteiro", "Instagram: nota de live para postar sozinho",
         "Corte de live com nota acima disto vai sozinho para o Instagram (0 = desligado).",
         {"min": 0, "max": 100}),
        ("publicar.instagram.max_por_dia", "inteiro", "Máximo por dia no Instagram", "",
         {"min": 0, "max": 100}),
        ("publicar.tiktok.ativo", "booleano", "Enviar para o TikTok",
         "O vídeo chega às notificações do app do TikTok e você publica de lá.", {}),
        ("publicar.tiktok.automatico", "booleano", "TikTok: enviar sozinho pela nota",
         "Desligado: todo corte espera você avaliar antes de ir para o TikTok.", {}),
        ("publicar.tiktok.max_por_dia", "inteiro", "Máximo por dia no TikTok",
         "O TikTok aceita no máximo 5 envios pendentes em 24 h por conta.", {"min": 0, "max": 5}),
        ("publicar.intervalo_min", "inteiro", "Minutos entre posts de vídeos gravados",
         "Espalha as postagens ao longo do dia. Cortes de live saem na hora.",
         {"min": 0, "max": 1440}),
        ("publicar.horarios", "texto", "Horários de postagem",
         "Janelas em que os cortes de vídeos gravados podem sair, como 11:00-14:00, "
         "18:00-23:30. Vazio: qualquer hora. Cortes de live saem sempre na hora.", {}),
        ("limpeza.dias", "inteiro", "Apagar arquivos de cortes publicados após (dias)",
         "Libera espaço em disco. O registro e os números do corte continuam no painel. "
         "0 nunca apaga.", {"min": 0, "max": 365}),
        ("auto.intervalo_min", "inteiro", "Minutos entre buscas nos canais acompanhados", "",
         {"min": 5, "max": 1440}),
        ("compilacao.ativa", "booleano", "Montar a compilação “Top N” de cada vídeo",
         "Formato extra, fora do padrão de vídeo curto: vídeo horizontal com contagem "
         "regressiva narrada, publicado só no YouTube como vídeo comum. Soma horas de "
         "exibição e é o formato mais próximo do que a política de monetização aceita.",
         {}),
        ("compilacao.minimo", "inteiro", "Cortes mínimos para montar a compilação", "",
         {"min": 2, "max": 10}),
        ("monetizacao.moeda", "texto", "Moeda das campanhas", "Usada nos ganhos estimados.", {}),
        ("idioma", "texto", "Idioma dos textos e legendas", "Código de duas letras, como pt ou en.",
         {}),
    ]),
]

CHAVES = {
    "ANTHROPIC_API_KEY": "Chave da API do Claude",
    "NVIDIA_API_KEY": "Chave da NVIDIA Build (IA gratuita para testes)",
    "CLAUDE_CODE_OAUTH_TOKEN": "Token fixo do Claude Code (opcional; gere com claude setup-token)",
    "PAINEL_SENHA": "Senha do painel (só para acesso por outros aparelhos)",
    "ELEVENLABS_API_KEY": "Chave da ElevenLabs (voz mais natural, opcional)",
    "IG_USER_ID": "ID da conta do Instagram",
    "IG_ACCESS_TOKEN": "Token de acesso do Instagram",
    "TIKTOK_CLIENT_KEY": "Client Key do app do TikTok",
    "TIKTOK_CLIENT_SECRET": "Client Secret do app do TikTok",
    "YOUTUBE_API_KEY": "Chave da API do YouTube (só para a busca aberta)",
}


def _pegar(cfg: dict, caminho: str):
    for parte in caminho.split("."):
        cfg = cfg[parte]
    return cfg


def _por(cfg: dict, caminho: str, valor) -> None:
    *partes, ultima = caminho.split(".")
    for parte in partes:
        cfg = cfg[parte]
    cfg[ultima] = valor


def descrever(cfg: dict) -> list[dict]:
    """Seções e campos com os valores atuais, prontos para a página."""
    return [{"titulo": titulo, "descricao": descricao, "campos": [
        {"chave": chave, "tipo": tipo, "rotulo": rotulo, "ajuda": ajuda,
         "valor": _pegar(cfg, chave), **extra}
        for chave, tipo, rotulo, ajuda, extra in campos]}
        for titulo, descricao, campos in SECOES]


def _validar(tipo: str, rotulo: str, valor, extra: dict):
    if tipo == "booleano":
        return bool(valor)
    if tipo in {"inteiro", "numero"}:
        try:
            numero = float(str(valor).replace(",", "."))
        except ValueError:
            raise ValueError(f"“{rotulo}” precisa ser um número.") from None
        if not extra.get("min", numero) <= numero <= extra.get("max", numero):
            raise ValueError(f"“{rotulo}” deve ficar entre {extra['min']} e {extra['max']}.")
        return int(round(numero)) if tipo == "inteiro" else numero
    if tipo == "escolha":
        if valor not in [o[0] for o in extra["opcoes"]]:
            raise ValueError(f"Opção inválida em “{rotulo}”.")
        return valor
    if tipo == "cor":
        if not re.fullmatch(r"#[0-9a-fA-F]{6}", str(valor)):
            raise ValueError(f"“{rotulo}” precisa ser uma cor como #FFE000.")
        return str(valor).upper()
    return str(valor).strip()


def salvar(cfg: dict, valores: dict, caminho: str | Path) -> None:
    """Valida tudo, aplica no cfg em uso (vale na hora) e grava o config.yaml."""
    campos = {c[0]: c for _, _, cs in SECOES for c in cs}
    novos = {}
    for chave, valor in valores.items():
        if chave not in campos:
            raise ValueError(f"Configuração desconhecida: {chave}")
        _, tipo, rotulo, _, extra = campos[chave]
        novos[chave] = _validar(tipo, rotulo, valor, extra)
    if novos.get("publicar.horarios"):
        from .publicar import janelas
        janelas(novos["publicar.horarios"])  # valida o formato
    minimo = novos.get("cortes.duracao_min", cfg["cortes"]["duracao_min"])
    maximo = novos.get("cortes.duracao_max", cfg["cortes"]["duracao_max"])
    if minimo > maximo:
        raise ValueError("A duração mínima não pode ser maior que a máxima.")
    for chave, valor in novos.items():
        _por(cfg, chave, valor)
    Path(caminho).write_text(
        "# Gerado pelo painel (aba Configurações). Pode ser editado à mão também.\n"
        + yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False), encoding="utf-8")


def definir_chave(nome: str, valor: str, arquivo: str | Path = ".env") -> None:
    """Grava uma chave no .env e a ativa na hora. O valor nunca é devolvido à página."""
    if nome not in CHAVES:
        raise ValueError("Chave desconhecida.")
    valor = valor.strip()
    if not valor or "\n" in valor:
        raise ValueError("Cole a chave em uma única linha.")
    arquivo = Path(arquivo)
    linhas = arquivo.read_text(encoding="utf-8").splitlines() if arquivo.exists() else []
    linhas = [l for l in linhas if not l.strip().startswith(f"{nome}=")] + [f"{nome}={valor}"]
    arquivo.write_text("\n".join(linhas) + "\n", encoding="utf-8")
    arquivo.chmod(0o600)
    os.environ[nome] = valor


def chaves_definidas() -> dict[str, bool]:
    return {nome: bool(os.environ.get(nome)) for nome in CHAVES}
