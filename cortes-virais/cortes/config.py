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
        "intervalo_min": 30,  # espaçamento entre posts de vídeos gravados
        "horarios": "",       # janelas para posts não urgentes, ex.: "11:00-14:00, 18:00-23:30"
        "youtube": {
            "ativo": True,
            "privacidade": "public",
            "categoria": "24",
            "max_por_dia": 6,
            "client_secret": "client_secret.json",
            "token": "youtube_token.json",
        },
        "instagram": {"ativo": True, "max_por_dia": 20, "versao_api": "v21.0"},
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
    return cfg
