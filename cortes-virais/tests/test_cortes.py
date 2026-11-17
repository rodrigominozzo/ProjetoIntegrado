"""Testes com vídeo, chat e live sintéticos (não acessam a internet)."""
import json
import subprocess
import time

import numpy as np
import pytest

from cortes import chat, config, sinais, transcricao, vod
from cortes.banco import Banco
from cortes.live import MonitorLive


def _cfg(tmp_path):
    cfg = config.carregar(None)
    cfg["pasta_trabalho"] = str(tmp_path / "dados")
    cfg["ia"]["ativa"] = False
    cfg["publicar"]["youtube"]["ativo"] = cfg["publicar"]["instagram"]["ativo"] = False
    return cfg


@pytest.fixture(scope="session")
def video(tmp_path_factory):
    """150 s com áudio baixo e dois estouros de volume: 60–70 s e 110–118 s."""
    saida = tmp_path_factory.mktemp("v") / "teste.mp4"
    vol = "if(between(t,60,70)+between(t,110,118),1,0.03)"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=640x360:r=15:d=150",
         "-f", "lavfi", "-i", f"sine=f=330:d=150,volume='{vol}':eval=frame",
         "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", str(saida)], check=True)
    return saida


def test_peso_do_chat():
    assert chat.peso("KKKKKKKK") == 2.0
    assert chat.peso("CLIPA ISSO") == 2.0
    assert chat.peso("bom dia pessoal") == 1.0


def test_replay_do_ytdlp(tmp_path):
    linha = {"replayChatItemAction": {"videoOffsetTimeMsec": "12500", "actions": [
        {"addChatItemAction": {"item": {"liveChatTextMessageRenderer": {
            "message": {"runs": [{"text": "kkkk "}, {"emoji": {"emojiId": "😂"}}]}}}}}]}}
    arq = tmp_path / "c.json"
    arq.write_text(json.dumps(linha) + "\n")
    assert chat.ler_replay(arq) == [(12.5, "kkkk 😂")]


def test_janelas_acham_os_picos():
    rng = np.random.default_rng(1)
    audio = rng.normal(-40, 1, 600).astype(np.float32)
    audio[200:215] += 20
    mensagens = [(float(t), "oi") for t in range(0, 600, 3)]
    mensagens += [(t / 10, "KKKKK") for t in range(4100, 4250)]  # rajada em 410–425 s
    cfg = config.carregar(None)
    pontos, usados = sinais.analisar(audio=audio, mensagens=mensagens, replay=None,
                                     duracao=600, cfg=cfg)
    assert set(usados) == {"audio", "chat"}
    janelas = sinais.melhores_janelas(pontos, 30, 2, 45)
    inicios = sorted(i for i, _ in janelas)
    assert inicios[0] <= 200 and inicios[0] + 30 >= 215
    # o chat é adiantado pelo atraso de reação (6 s): pico efetivo em 404–419 s
    assert inicios[1] <= 404 and inicios[1] + 30 >= 419


def test_detector_dispara_so_no_pico():
    det = sinais.DetectorPico(limiar=4, espera=90, min_mensagens=8)
    disparos = []
    for i in range(200):
        t = i * 2.0
        rajada = 150 <= i < 155
        if det.alimentar(t, 25.0 if rajada else 1.0, -40.0) is not None:
            disparos.append(i)
    assert len(disparos) == 1 and 150 <= disparos[0] < 155


def test_bordas_e_legendas():
    palavras = [(0.0, 0.4, "isso"), (0.5, 0.9, "foi"), (2.0, 2.4, "muito"), (2.5, 2.9, "bom"),
                (4.2, 4.6, "demais")]
    ini, fim = transcricao.ajustar_bordas(palavras, 1.5, 3.5)
    assert ini == pytest.approx(1.9) and fim == pytest.approx(3.05)
    ass = transcricao.gerar_ass(palavras, 0, 5, 1080, 1920, credito="Créditos: Canal",
                                gancho="Ninguém esperava", karaoke=False)
    assert "ISSO FOI" in ass and "MUITO BOM" in ass and "Créditos: Canal" in ass
    assert "Gancho,,0,0,0,,Ninguém esperava" in ass
    karaoke = transcricao.gerar_ass(palavras, 0, 5, 1080, 1920, cor_destaque="#FFE000")
    assert "{\\c&H00E0FF&}ISSO{\\c&HFFFFFF&} FOI" in karaoke   # 1ª palavra em destaque
    assert "ISSO {\\c&H00E0FF&}FOI{\\c&HFFFFFF&}" in karaoke   # depois a 2ª


def test_video_gravado_ponta_a_ponta(video, tmp_path):
    cfg = _cfg(tmp_path)
    cfg["cortes"]["por_video"] = 2
    arq_chat = tmp_path / "chat.jsonl"
    linhas = [{"t": t, "texto": "oi"} for t in range(0, 150, 4)]
    linhas += [{"t": 66 + i * 0.1, "texto": "KKKKKK"} for i in range(80)]
    arq_chat.write_text("\n".join(json.dumps(l) for l in linhas))
    banco = Banco(tmp_path / "e.db")
    ids = vod.processar(str(video), cfg, banco, chat_arquivo=str(arq_chat))
    assert len(ids) == 2
    cortes = banco.pendentes("yt")
    inicios = sorted(c["inicio"] for c in cortes)
    assert inicios[0] <= 60 and inicios[0] + 30 >= 70      # pega o estouro de 60–70 s
    assert inicios[1] <= 110 and inicios[1] + 30 >= 118    # e o de 110–118 s
    sonda = json.loads(subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,width,height:format=duration",
         "-of", "json", cortes[0]["arquivo"]], capture_output=True, text=True).stdout)
    v = next(s for s in sonda["streams"] if s["codec_type"] == "video")
    assert (v["width"], v["height"]) == (1080, 1920)
    assert abs(float(sonda["format"]["duration"]) - 30) < 0.5
    assert vod.processar(str(video), cfg, banco) == []     # não reprocessa


class ChatFalso:
    """Uma mensagem a cada 2 s e uma rajada entre 30 e 36 s após o início."""
    def __init__(self):
        self.t0 = time.time()
        self.msgs = [(self.t0 + t, "oi") for t in range(0, 80, 2)]
        self.msgs += [(self.t0 + 30 + i * 0.15, "KKKKKK CLIPA") for i in range(40)]

    def desde(self, a, b=None):
        b = b or time.time()
        return [m for m in self.msgs if a <= m[0] < b]


def test_live_simulada(tmp_path):
    cfg = _cfg(tmp_path)
    cfg["live"].update(pre=12, pos=4)
    vol = "if(between(t,24,32),1,0.03)"
    entrada = ["-re", "-f", "lavfi", "-i", "testsrc2=s=640x360:r=15",
               "-f", "lavfi", "-i", f"sine=f=330,volume='{vol}':eval=frame",
               "-c:v", "libx264", "-preset", "ultrafast", "-g", "30", "-c:a", "aac"]
    det = sinais.DetectorPico(4, 90, 8, aquecimento=20)
    banco = Banco(tmp_path / "e.db")
    meta = {"id": "sim", "titulo": "Live de teste", "canal": "Canal", "url": ""}
    monitor = MonitorLive("sim", cfg, banco, meta=meta, entrada_ffmpeg=entrada,
                          chat=ChatFalso(), detector=det)
    ids = monitor.rodar(duracao_max=55)
    assert len(ids) == 1
    corte = banco.pendentes("yt")[0]
    assert corte["urgente"] == 1 and corte["origem"] == "live"
    dur = float(subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
         corte["arquivo"]], capture_output=True, text=True).stdout)
    assert abs(dur - 16) < 1.0
    assert not list(monitor.buffer.glob("seg_*.ts"))


def test_painel_modo_teste(video, tmp_path):
    import urllib.request
    from http.server import ThreadingHTTPServer
    import threading

    from cortes import painel

    cfg = _cfg(tmp_path)
    cfg["cortes"]["por_video"] = 1
    banco = Banco(tmp_path / "e.db")
    ger = painel.Gerenciador(cfg, banco)
    servidor = ThreadingHTTPServer(("127.0.0.1", 0), painel._manipulador(ger))
    threading.Thread(target=servidor.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{servidor.server_address[1]}"

    def chamar(rota, dados=None, cabecalhos=None):
        req = urllib.request.Request(base + rota, data=json.dumps(dados).encode() if dados else None,
                                     headers=cabecalhos or {})
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()

    painel_ok = {"X-Painel": "1"}
    assert chamar("/api/enviar", {"alvo": str(video), "teste": True})[0] == 403  # sem cabeçalho
    assert chamar("/api/enviar", {"alvo": "nada"}, painel_ok)[0] == 400
    assert chamar("/api/enviar", {"alvo": str(video), "teste": True}, painel_ok)[0] == 200
    for _ in range(120):
        estado = json.loads(chamar("/api/estado")[1])
        if estado["tarefas"] and estado["tarefas"][0]["status"] in {"feito", "erro"}:
            break
        time.sleep(1)
    assert estado["tarefas"][0]["status"] == "feito" and estado["tarefas"][0]["cortes"] == 1
    corte = estado["grupos"][0]["cortes"][0]
    assert corte["teste"] and estado["fila"] == [] and banco.pendentes("yt") == []

    analise = json.loads(chamar("/api/analise/local-teste")[1])
    assert any(c["escolhido"] for c in analise["candidatos"]) and len(analise["pontos"]) == 150
    codigo, parte = chamar(f"/midia/{corte['id']}", cabecalhos={"Range": "bytes=0-99"})
    assert codigo == 206 and len(parte) == 100

    assert chamar("/api/corte/aprovar", {"id": corte["id"]}, painel_ok)[0] == 200
    assert len(banco.pendentes("yt")) == 1
    servidor.shutdown()


def test_layouts_por_rosto():
    from cortes import enquadramento as enq

    def cena(*rostos, quadros=10):
        return [list(rostos) for _ in range(quadros)]

    assert enq.classificar(cena())["tipo"] == "blur"
    assert enq.classificar(cena((0.45, 0.4, 0.2, 0.3)))["tipo"] == "rosto"
    dupla = enq.classificar(cena((0.75, 0.4, 0.15, 0.25), (0.25, 0.42, 0.14, 0.24)))
    assert dupla["tipo"] == "dupla" and dupla["pessoas"][0]["cx"] < dupla["pessoas"][1]["cx"]
    assert enq.classificar(cena((0.1, 0.82, 0.07, 0.12)))["tipo"] == "facecam"
    # rosto que aparece em poucos quadros é ruído
    ruido = [[(0.5, 0.5, 0.2, 0.3)]] + [[] for _ in range(9)]
    assert enq.classificar(ruido)["tipo"] == "blur"
    for layout in (dupla, enq.classificar(cena((0.1, 0.82, 0.07, 0.12)))):
        assert "vstack" in enq.filtro(layout, 1920, 1080)


def test_ia_recebe_referencias_do_canal(tmp_path):
    from cortes import desempenho

    banco = Banco(tmp_path / "e.db")
    assert desempenho.referencias(banco) == ""          # sem dados, não inventa
    for i in range(9):
        cid = banco.novo_corte(video_id="v", origem="vod", inicio=0, fim=30, nota=80,
                               titulo=f"Corte {i}", descricao="", hashtags=[], arquivo="x.mp4",
                               gancho=f"Gancho {i}")
        banco.publicado(cid, "yt", f"yt{i}")
        banco._exec("UPDATE cortes SET yt_em=? WHERE id=?", (time.time() - 2 * 86400, cid))
        banco.medir("yt", f"yt{i}", vistas=1000 * i, curtidas=i)
    texto = desempenho.referencias(banco)
    assert texto.index("Corte 8") < texto.index("Menos vistos") < texto.index("Corte 0")
    assert 'gancho: "Gancho 8"' in texto
