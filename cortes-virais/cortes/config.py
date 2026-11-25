"""Carrega config.yaml (sobre os padrões abaixo) e o arquivo .env."""
from __future__ import annotations

import copy
import os
from pathlib import Path

import yaml

PADRAO = {
    "idioma": "pt",
    "pasta_trabalho": "dados",
    "fontes": {
        # IDs de canal (UC...) que autorizaram cortes. A descoberta automática
        # só olha para eles enquanto exigir_autorizacao for true.
        "canais_autorizados": [],
        "exigir_autorizacao": True,
        "duracao_max_h": 6,
        # Vídeos com restrição de idade: cookies de um navegador logado no YouTube
        # (firefox | chrome | edge | brave | opera | vivaldi) ou de um arquivo cookies.txt.
        "cookies_navegador": "",
        "cookies_arquivo": "",
        "busca": {"consultas": ["live"], "regiao": "BR", "max_resultados": 10, "dias": 2},
    },
    "cortes": {
        "duracao": 30,          # alvo; a IA pode ajustar dentro de duracao_min..duracao_max
        "duracao_min": 20,
        "duracao_max": 45,
        "por_video": 5,
        "intervalo_minimo": 45,  # segundos entre o início de dois cortes
        "formato": "auto",  # auto (segue rostos) | vertical_blur | vertical_crop | original
        "legendas": True,
        "fonte": "Montserrat Black",  # ou Montserrat ExtraBold, Poppins ExtraBold, Anton, Bangers
        "karaoke": True,          # destaca a palavra que está sendo falada
        "tema": "classico",       # classico | impacto | neon | limpo | personalizado
        "cor_destaque": "#FFE000",  # usada só no tema personalizado
        "capa": True,             # gera thumbnail e envia junto com o vídeo
        "gancho": True,           # frase de impacto fixa no topo do vídeo
        "marca": "@GamePlayCortesBR",  # nome do canal, discreto no canto do vídeo
        "fechar_frases": True,    # estende o corte até a fala terminar, em vez de cortar no meio
        "extensao_max": 40,       # segundos que o corte pode crescer para fechar o raciocínio
        "altura_max": 1080,
        "apagar_fonte": True,
    },
    "sinais": {
        "pesos": {"chat": 1.0, "audio": 0.6, "replay": 1.2},
        "atraso_chat": 6,  # o chat reage alguns segundos depois do momento
    },
    "transcricao": {"whisper": "small"},  # usado só se faster-whisper estiver instalado
    "ia": {
        "ativa": True, "nota_minima": 60, "quadros": 3,
        # Um modelo para cada papel: o mais rápido peneira, o mais capaz decide.
        "modelos": {"triagem": "claude-haiku-5-5", "ao_vivo": "claude-sonnet-5-5",
                    "final": "claude-opus-5-5"},
        "provedor": "anthropic",  # anthropic (Claude, pago) | nvidia (NVIDIA Build, grátis p/ testes)
        # Se a IA principal cair: o Claude Code deste computador, com a sua conta (como no Jarvis)
        "reserva": "claude_code",  # claude_code | nenhuma
        "reserva_modelo": "claude-sonnet-5-5",
        # Último recurso, sem nuvem: IA local (Ollama). Mais fraca: só valida os trechos que as
        # métricas escolheram. Modelo vazio = o melhor instalado.
        "local": "ollama",  # ollama | nenhuma
        "local_modelo": "",
        # Modelos abertos da NVIDIA; os que veem imagens avaliam melhor os quadros do vídeo.
        # (O Nemotron VL pensa demais e estoura a resposta, e recusa imagens de jogos violentos.)
        "nvidia": {"modelos": {"triagem": "google/gemma-4-31b-it",
                               "ao_vivo": "google/gemma-4-31b-it",
                               "final": "google/gemma-4-31b-it"}},
    },
    "edicao": {
        "dinamica": True,          # troca de plano e zoom ao longo do corte
        "abrir_no_rosto": True,    # gameplay: começa no rosto do jogador
        "seguir_falante": True,    # duas pessoas: fecha em quem está falando
        "cortar_silencios": True,  # tira as pausas longas de fala
        "pausa_minima": 1.2,       # segundos de silêncio para ser cortado
        "abertura_pico": True,     # permite abrir com 1,5 s do ápice (a IA decide quando)
        "barra_progresso": True,
        "realce": True,            # acabamento de cor, nitidez e vinheta leve
    },
    "narracao": {
        "ativa": False,            # falas do narrador do canal por cima do corte
        "motor": "piper",          # piper (local, gratuito) | elevenlabs (mais natural, pago)
        "voz_elevenlabs": "",      # ID da voz, se o motor for elevenlabs
        "max_falas": 3,
        "encerramento": True,      # quadro final com pergunta para os comentários
        "voz": "vozes/pt_BR-faber-medium.onnx",
        "volume": 1.0,
        "velocidade": 1.05,
        "fundo": 0.25,             # volume do áudio original enquanto a narração fala
    },
    # Vídeo longo horizontal "Top N" narrado, só no YouTube. Desligado: o foco são os curtos.
    "compilacao": {"ativa": False, "minimo": 3},
    "conhecimento": {"pasta": "conhecimento"},
    "live": {
        "limiar": 4.0,
        "palavras_limiar_menor": "GTA",  # lives com estas palavras no título cortam mais fácil
        "limiar_menor": 3.0,
        "historico": True,       # também analisa o que a live já tinha passado ao começar
        "historico_horas": 6,
        "min_mensagens": 8,
        "pre": 22,
        "pos": 8,
        "espera": 90,  # segundos mínimos entre dois cortes da mesma live
        "buffer_min": 5,
        "altura": 720,
        "max_simultaneas": 2,
    },
    "publicar": {
        "creditar_fonte": True,
        "manual": True,       # cortes novos esperam você decidir: publicar agora ou pôr na fila
        "auto_acima": 88,     # ...menos os de nota acima disto: entram sozinhos na fila (0 = nunca)
        "imediato_acima": 90, # e acima disto publicam já, sem esperar intervalo/horário (0 = nunca)
        "intervalo_min": 30,  # espaçamento entre posts de vídeos gravados
        "horarios": "",       # janelas para posts não urgentes, ex.: "11:00-14:00, 18:00-23:30"
        "youtube": {
            "ativo": True,
            "automatico": False,  # nunca publica sozinho: todo corte espera você avaliar
            "privacidade": "public",
            "categoria": "24",
            "max_por_dia": 6,
            "client_secret": "client_secret.json",
            "token": "youtube_token.json",
        },
        "instagram": {"ativo": True, "max_por_dia": 20, "versao_api": "v21.0",
                      "automatico": True,
                      "auto_live_acima": 78},  # corte de live com nota acima disto vai sozinho
        # Vai para a caixa de entrada do app do TikTok (você publica de lá). O TikTok aceita
        # no máximo 5 envios pendentes em 24 h por conta.
        "tiktok": {"ativo": True, "max_por_dia": 5, "token": "tiktok_token.json",
                   "automatico": False},
    },
    "auto": {"intervalo_min": 30},
    "monetizacao": {"moeda": "US$"},
    "limpeza": {"dias": 14},  # apaga do disco os cortes já publicados há mais que isso (0 = nunca)
}


def _mesclar(base: dict, extra: dict) -> dict:
    for chave, valor in extra.items():
        if isinstance(valor, dict) and isinstance(base.get(chave), dict):
            _mesclar(base[chave], valor)
        else:
            base[chave] = valor
    return base


def carregar_env(caminho: str | Path = ".env") -> None:
    caminho = Path(caminho)
    if not caminho.exists():
        return
    for linha in caminho.read_text(encoding="utf-8").splitlines():
        linha = linha.strip()
        if not linha or linha.startswith("#") or "=" not in linha:
            continue
        chave, valor = linha.split("=", 1)
        os.environ.setdefault(chave.strip(), valor.strip().strip("'\""))


def carregar(caminho: str | Path | None = "config.yaml") -> dict:
    cfg = copy.deepcopy(PADRAO)
    if caminho and Path(caminho).exists():
        _mesclar(cfg, yaml.safe_load(Path(caminho).read_text(encoding="utf-8")) or {})
    carregar_env()
    Path(cfg["pasta_trabalho"]).mkdir(parents=True, exist_ok=True)
    from . import fontes  # cookies para vídeos com restrição de idade

    fontes.configurar(cfg)
    return cfg
