"""Linha de comando: python -m cortes <comando>."""
from __future__ import annotations

import argparse
import logging
import threading
import time
from pathlib import Path

from . import config, desempenho, fontes, publicar, vod
from .banco import Banco
from .live import MonitorLive

log = logging.getLogger("cortes")


def _auto(cfg: dict, banco: Banco) -> None:
    """Modo contínuo: descobre, acompanha lives, corta gravações e publica a fila."""
    lives: dict[str, threading.Thread] = {}
    while True:
        try:
            publicar.publicar_pendentes(cfg, banco)
            desempenho.atualizar(cfg, banco)
            for achado in fontes.descobrir(cfg):
                lives = {k: t for k, t in lives.items() if t.is_alive()}
                if achado["ao_vivo"]:
                    if achado["id"] in lives or len(lives) >= cfg["live"]["max_simultaneas"]:
                        continue
                    monitor = MonitorLive(achado["url"], cfg, banco)
                    t = threading.Thread(target=monitor.rodar, daemon=True, name=achado["id"])
                    t.start()
                    lives[achado["id"]] = t
                elif not banco.status_video(achado["id"]):
                    try:
                        vod.processar(achado["url"], cfg, banco)
                    except Exception:  # noqa: BLE001
                        log.exception("Falha ao processar %s", achado["url"])
                        banco.marcar_video(achado["id"], achado["titulo"], achado["canal"], "erro")
                    publicar.publicar_pendentes(cfg, banco)
        except Exception:  # noqa: BLE001
            log.exception("Erro no ciclo automático; tentando de novo no próximo.")
        time.sleep(cfg["auto"]["intervalo_min"] * 60)


def main() -> None:
    ap = argparse.ArgumentParser(prog="cortes", description="Cortes virais automáticos.")
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--sem-publicar", action="store_true", help="só gera os arquivos dos cortes")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("vod", help="corta um vídeo gravado (URL ou arquivo local)")
    p.add_argument("alvo")
    p.add_argument("--chat", help="arquivo de chat para vídeo local")
    p.add_argument("--forcar", action="store_true")
    p = sub.add_parser("live", help="acompanha uma live e corta em tempo real")
    p.add_argument("url")
    p = sub.add_parser("painel", help="abre o painel visual no navegador")
    p.add_argument("--porta", type=int, default=8000)
    p.add_argument("--host", default="127.0.0.1",
                   help="use 0.0.0.0 para acessar de outro aparelho (o painel não tem senha)")
    p = sub.add_parser("app", help="abre o programa em janela própria")
    p.add_argument("--porta", type=int, default=8000)
    sub.add_parser("buscar", help="mostra o que a descoberta automática encontra")
    sub.add_parser("auto", help="roda tudo continuamente")
    sub.add_parser("publicar", help="publica os cortes pendentes na fila")
    sub.add_parser("login-youtube", help="autoriza a conta do YouTube (uma vez)")
    sub.add_parser("status", help="resumo do que já foi feito")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        datefmt="%H:%M:%S")
    cfg = config.carregar(args.config)
    if args.sem_publicar:
        cfg["publicar"]["youtube"]["ativo"] = cfg["publicar"]["instagram"]["ativo"] = False
    banco = Banco(Path(cfg["pasta_trabalho"]) / "estado.db")

    if args.cmd == "vod":
        vod.processar(args.alvo, cfg, banco, chat_arquivo=args.chat, forcar=args.forcar)
        publicar.publicar_pendentes(cfg, banco)
    elif args.cmd == "live":
        MonitorLive(args.url, cfg, banco).rodar()
    elif args.cmd == "painel":
        from . import painel
        painel.servir(cfg, banco, args.host, args.porta, args.config)
    elif args.cmd == "app":
        from . import app
        app.abrir(cfg, banco, args.config, args.porta)
    elif args.cmd == "buscar":
        for a in fontes.descobrir(cfg):
            print(f"{'AO VIVO' if a['ao_vivo'] else 'gravado':8} {a['audiencia']:>9}  "
                  f"{a['canal']}: {a['titulo']}  {a['url']}")
    elif args.cmd == "auto":
        _auto(cfg, banco)
    elif args.cmd == "publicar":
        print(f"{publicar.publicar_pendentes(cfg, banco)} publicações feitas.")
    elif args.cmd == "login-youtube":
        from .publicar import youtube
        youtube.login(cfg["publicar"]["youtube"])
        print("YouTube autorizado.")
    elif args.cmd == "status":
        for chave, valor in banco.resumo().items():
            print(f"{chave}: {valor}")


if __name__ == "__main__":
    main()
