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

# (seção, descrição da seção, [campos])
SECOES = [
    ("Cortes", "Tamanho, quantidade e aparência dos cortes.", [
        ("cortes.duracao", "inteiro", "Duração alvo (segundos)",
         "O tamanho que o sistema procura. 30 é um bom ponto de partida.", {"min": 10, "max": 90}),
        ("cortes.duracao_min", "inteiro", "Duração mínima",
         "A IA pode encurtar o corte até aqui para ele terminar logo depois do desfecho.",
         {"min": 8, "max": 90}),
        ("cortes.duracao_max", "inteiro", "Duração máxima",
         "A IA pode estender o corte até aqui para não cortar o desfecho.", {"min": 10, "max": 180}),
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
        ("cortes.cor_destaque", "cor", "Cor de destaque",
         "Usada na palavra falada e na barra de progresso.", {}),
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
         "Linha fina no rodapé que avança com o vídeo; ajuda a pessoa a ficar até o fim.", {}),
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
        ("ia.nota_minima", "inteiro", "Nota mínima para virar corte",
         "De 0 a 100. Mais alto: menos cortes, mais selecionados. 60 a 70 costuma funcionar.",
         {"min": 0, "max": 100}),
        ("ia.modelos.triagem", "escolha", "Triagem dos candidatos",
         "Lê só o texto de muitos trechos e descarta os fracos. Tarefa simples e volumosa: "
         "o modelo mais rápido dá conta.", {"opcoes": MODELOS}),
        ("ia.modelos.ao_vivo", "escolha", "Avaliação durante a live",
         "Decide em segundos se um pico vira corte e escreve gancho e título. Precisa ser "
         "rápido para publicar antes dos outros.", {"opcoes": MODELOS}),
        ("ia.modelos.final", "escolha", "Julgamento final de vídeos gravados",
         "Vê imagens e texto dos finalistas, dá as notas, escreve o gancho e dirige a "
         "edição. É aqui que a qualidade do corte se decide.", {"opcoes": MODELOS}),
        ("ia.quadros", "inteiro", "Imagens por candidato",
         "Quantos quadros do vídeo a IA vê de cada trecho. Mais quadros: melhor avaliação "
         "visual e custo maior.", {"min": 1, "max": 8}),
    ]),
    ("Lives", "Sensibilidade da detecção em tempo real.", [
        ("live.limiar", "numero", "Sensibilidade (limiar de empolgação)",
         "O corte dispara quando a empolgação passa deste valor. Menor: mais cortes e mais "
         "falsos alarmes. Entre 3,5 e 5 é o usual.", {"min": 2, "max": 10}),
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
    ("Publicação", "Ritmo e limites de postagem.", [
        ("publicar.youtube.ativo", "booleano", "Publicar no YouTube", "", {}),
        ("publicar.youtube.privacidade", "escolha", "Visibilidade no YouTube",
         "Enquanto o projeto do Google não for auditado, o YouTube mantém os envios privados.",
         {"opcoes": [["public", "Público"], ["unlisted", "Não listado"], ["private", "Privado"]]}),
        ("publicar.youtube.max_por_dia", "inteiro", "Máximo por dia no YouTube",
         "A cota padrão da API permite poucos envios diários.", {"min": 0, "max": 100}),
        ("publicar.instagram.ativo", "booleano", "Publicar no Instagram", "", {}),
        ("publicar.instagram.max_por_dia", "inteiro", "Máximo por dia no Instagram", "",
         {"min": 0, "max": 100}),
        ("publicar.intervalo_min", "inteiro", "Minutos entre posts de vídeos gravados",
         "Espalha as postagens ao longo do dia. Cortes de live saem na hora.",
         {"min": 0, "max": 1440}),
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
    "ELEVENLABS_API_KEY": "Chave da ElevenLabs (voz mais natural, opcional)",
    "IG_USER_ID": "ID da conta do Instagram",
    "IG_ACCESS_TOKEN": "Token de acesso do Instagram",
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
