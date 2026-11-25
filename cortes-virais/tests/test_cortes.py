"""Testes com vídeo, chat e live sintéticos (não acessam a internet)."""
import json
import subprocess
import time
from pathlib import Path

import numpy as np
import pytest

from cortes import chat, config, sinais, transcricao, vod
from cortes.banco import Banco
from cortes.live import MonitorLive


def _cfg(tmp_path):
    cfg = config.carregar(None)
    cfg["pasta_trabalho"] = str(tmp_path / "dados")
    cfg["ia"]["ativa"] = False
    # Os testes nunca chamam o Claude Code nem o Ollama de verdade (cada teste liga o que testa).
    cfg["ia"]["reserva"] = cfg["ia"]["local"] = "nenhuma"
    # Os testes antigos conferem a fila automática; o modo manual (padrão) tem teste próprio.
    cfg["publicar"]["manual"] = False
    cfg["publicar"]["youtube"]["ativo"] = cfg["publicar"]["instagram"]["ativo"] = False
    cfg["publicar"]["tiktok"]["ativo"] = False
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
    assert "Gancho,,0,0,0,," in ass and "}Ninguém esperava" in ass
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
    for _ in range(360):  # a análise inclui transcrever além do fim de cada corte
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
    facecam = enq.classificar(cena((0.1, 0.82, 0.07, 0.12)))
    assert "vstack" in enq.cadeia("dupla", dupla, 1920, 1080, 1.0, "e", "s", "p")
    assert "vstack" in enq.cadeia("dividido", facecam, 1920, 1080, 1.0, "e", "s", "p")


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


def test_plano_de_edicao_gameplay():
    from cortes import edicao

    layout = {"tipo": "facecam", "rosto": {"cx": 0.1, "cy": 0.8, "w": 0.05, "h": 0.09}}
    energia = np.full(30, -40.0)
    energia[18] = -5                                    # grito aos 18 s
    plano = edicao.planejar(layout, 100, 130, energia=energia, cfg={})
    vistas = [p["vista"] for p in plano["pedacos"]]
    assert vistas[0] == "reacao"                        # abre no rosto do jogador
    assert {"dividido", "jogo"} <= set(vistas)          # alterna tela dividida e jogo
    no_pico = next(p for p in plano["pedacos"] if p["a"] <= 118.6 < p["b"])
    assert no_pico["vista"] == "reacao"                 # volta ao rosto na reação
    assert plano["duracao"] == pytest.approx(30, abs=0.05)
    assert plano["pedacos"][0]["a"] == 100 and plano["pedacos"][-1]["b"] == pytest.approx(130)
    parado = edicao.planejar(layout, 100, 130, energia=energia, cfg={"dinamica": False})
    assert [p["vista"] for p in parado["pedacos"]] == ["dividido"]


def test_plano_corta_silencio_e_abre_pelo_pico():
    from cortes import edicao

    layout = {"tipo": "rosto", "rosto": {"cx": 0.5, "cy": 0.4, "w": 0.2, "h": 0.3}}
    falas = [(10 + i * 0.4, 10.3 + i * 0.4, f"a{i}") for i in range(10)]        # 10,0–13,9
    falas += [(18 + i * 0.4, 18.3 + i * 0.4, f"b{i}") for i in range(20)]       # 18,0–25,9
    plano = edicao.planejar(layout, 10, 26, palavras=falas, momento=22.0, abrir_com_pico=True,
                            cfg={})
    previa, resto = plano["pedacos"][0], plano["pedacos"][1:]
    assert previa["a"] == pytest.approx(21.7) and plano["flash"] == pytest.approx(1.7)
    assert not any(p["a"] < 16 < p["b"] for p in resto)       # o silêncio de 14–18 s saiu
    assert plano["duracao"] < 16 + 1.7 - 3
    assert any(p["zoom"] > 1.3 for p in resto)                # zoom fechado no momento-chave
    legendas = edicao.remapear(falas, plano["pedacos"])
    assert legendas[0][2] == "b10"                            # a prévia traz as falas do pico
    assert all(b > a >= 0 for a, b, _ in legendas)


def test_bases_de_conhecimento(tmp_path):
    from cortes import conhecimento

    cfg = {"conhecimento": {"pasta": str(tmp_path)}}
    conhecimento.salvar(cfg, "GTA VI", "palavras: gta 6, vice city\n---\nLucia e Jason.")
    conhecimento.salvar(cfg, "estilo", "sempre: sim\n---\nComece no meio da ação.")
    geral = conhecimento.selecionar("Live de Minecraft", cfg)
    assert "meio da ação" in geral and "Lucia" not in geral
    assert "Lucia" in conhecimento.selecionar("JOGANDO GTA 6 PELA PRIMEIRA VEZ", cfg)
    assert "Lucia" not in conhecimento.selecionar("gta 60 anos depois", cfg)   # palavra inteira


def test_ajustes_validam_e_gravam(tmp_path):
    import yaml

    from cortes import ajustes

    cfg = config.carregar(None)
    arq = tmp_path / "config.yaml"
    ajustes.salvar(cfg, {"cortes.duracao": "35", "ia.modelos.triagem": "claude-haiku-5-5",
                         "edicao.dinamica": False, "live.limiar": "4,5"}, arq)
    assert cfg["cortes"]["duracao"] == 35 and cfg["edicao"]["dinamica"] is False
    assert yaml.safe_load(arq.read_text(encoding="utf-8"))["live"]["limiar"] == 4.5
    with pytest.raises(ValueError, match="entre"):
        ajustes.salvar(cfg, {"ia.nota_minima": 500}, arq)
    with pytest.raises(ValueError, match="mínima"):
        ajustes.salvar(cfg, {"cortes.duracao_min": 60, "cortes.duracao_max": 30}, arq)
    assert cfg["cortes"]["duracao_min"] == 20                 # nada foi aplicado no erro
    assert sum(len(s["campos"]) for s in ajustes.descrever(cfg)) >= 30


def test_narracao_de_abertura(video, tmp_path):
    from cortes import narracao, render

    cfg = _cfg(tmp_path)
    assert not narracao.disponivel(cfg)                       # desligada por padrão
    assert narracao.sintetizar("Olá", tmp_path / "x.wav", cfg) is None

    voz = tmp_path / "voz.wav"                                # voz de mentira: tom de 880 Hz
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=f=880:d=2",
                    str(voz)], check=True)
    falas = [(20 + i * 0.5, 20.4 + i * 0.5, f"p{i}") for i in range(16)]
    feito = render.renderizar(
        video, 20, 30, tmp_path / "c.mp4", formato="vertical_blur", palavras=falas,
        narracoes=[{"arquivo": voz, "duracao": 2.0, "texto": "Contexto dito pelo canal",
                    "volume": 1.0, "fundo": 0.2, "t": None}],
        encerramento={"arquivo": voz, "duracao": 2.0, "texto": "E você, faria igual?"},
        cfg_cortes=cfg["cortes"], cfg_edicao=cfg["edicao"])
    ass = (tmp_path / "c.ass").read_text(encoding="utf-8")
    assert "CONTEXTO DITO PELO" in ass
    assert "P0" not in ass and "P3" not in ass and "P6" in ass    # falas cobertas saem da legenda

    def nivel(inicio):                                        # volume em torno de 880 Hz
        saida = subprocess.run(
            ["ffmpeg", "-ss", str(inicio), "-t", "1.5", "-i", str(feito["arquivo"]), "-af",
             "bandpass=f=880:width_type=h:w=60,volumedetect", "-f", "null", "-"],
            capture_output=True, text=True).stderr
        return float(saida.split("mean_volume:")[1].split()[0])

    assert nivel(0.3) > nivel(5) + 20                         # a voz não vaza para o meio
    assert feito["duracao"] == pytest.approx(10 + 2.7)        # quadro final congelado
    assert "E você, faria igual?" in ass and nivel(10.4) > nivel(5) + 20


def test_compilacao_e_campanha(video, tmp_path):
    cfg = _cfg(tmp_path)
    cfg["cortes"]["por_video"] = 3
    cfg["ia"]["nota_minima"] = 0
    cfg["compilacao"]["ativa"] = True                         # vem desligada por padrão
    banco = Banco(tmp_path / "e.db")
    ids = vod.processar(str(video), cfg, banco)
    cortes = {c["id"]: c for c in banco.todos_cortes()}
    assert len(ids) == 4                                       # 3 cortes + a compilação
    comp = next(c for c in cortes.values() if c["origem"] == "compilacao")
    assert comp["titulo"].startswith("Top 3 momentos") and "0:00 Abertura" in comp["descricao"]
    sonda = json.loads(subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,width,height:format=duration",
         "-of", "json", comp["arquivo"]], capture_output=True, text=True).stdout)
    v = next(s for s in sonda["streams"] if s["codec_type"] == "video")
    assert (v["width"], v["height"]) == (1920, 1080)
    assert float(sonda["format"]["duration"]) > 3 * 20        # três trechos mais as passagens
    assert comp["id"] in [c["id"] for c in banco.pendentes("yt")]
    assert comp["id"] not in [c["id"] for c in banco.pendentes("ig")]   # só no YouTube

    # campanha do canal: o texto exigido entra sozinho na descrição dos cortes
    banco.canal_confiavel("UC123", "Canal X")
    banco.campanha("UC123", 1.5, "#campanha @canalx", "autorizado por e-mail")
    meta = {"id": "v2", "titulo": "Outro", "canal": "Canal X", "canal_id": "UC123", "url": ""}
    c = {"inicio": 60.0, "fim": 70.0, "nota": 80, "titulo": "T", "descricao": "D", "hashtags": []}
    cid = vod.finalizar(c, video, meta, cfg, banco, tmp_path / "v2", "vod", [])
    assert banco.corte(cid)["descricao"].endswith("#campanha @canalx")
    banco.marcar_video("v2", "Outro", "Canal X", "feito")
    banco.publicado(cid, "yt", "abc")
    banco.medir("yt", "abc", vistas=20000, curtidas=10)
    assert banco.vistas_por_canal()["Canal X"] == 20000       # 20 mil × 1,50 = 30 de estimativa


def test_capa_tema_e_area_segura(video, tmp_path):
    from cortes import capa

    cfg = _cfg(tmp_path)
    cfg["cortes"].update(tema="impacto", marca="@GamePlayCortesBR")
    banco = Banco(tmp_path / "e.db")
    meta = {"id": "v", "titulo": "Live", "canal": "Canal X", "canal_id": "", "url": ""}
    c = {"inicio": 60.0, "fim": 70.0, "nota": 80, "titulo": "Título do corte", "descricao": "D",
         "hashtags": [], "gancho": "Ele não esperava *essa reação*", "texto_capa": "DEU RUIM",
         "momento": 4.0}
    falas = [(60 + i * 0.5, 60.4 + i * 0.5, f"p{i}") for i in range(18)]
    cid = vod.finalizar(c, video, meta, cfg, banco, tmp_path / "v", "vod", falas)
    corte = banco.corte(cid)
    assert corte["gancho"] == "Ele não esperava essa reação"         # asteriscos só no vídeo
    assert corte["capa_ms"] == 4000 and corte["capa"].endswith(".capa.jpg")
    dims = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=width,height",
                           "-of", "csv=p=0", corte["capa"]], capture_output=True, text=True).stdout
    assert dims.strip() == "1080,1920"
    ass = (tmp_path / "v" / "corte_000060.ass").read_text(encoding="utf-8")
    assert "@GamePlayCortesBR   ·   Créditos: Canal X" in ass          # assinatura no topo
    assert "&H2B22E8" in ass                                           # caixa vermelha do tema
    estilo = next(l for l in ass.splitlines() if l.startswith("Style: Fala"))
    margens = [int(x) for x in estilo.split(",")[19:22]]
    assert margens[0] >= 120 and margens[1] >= 120 and margens[2] >= 1920 * 0.25   # área segura
    assert capa._linhas("um dois três quatro cinco") == ["UM DOIS", "TRÊS QUATRO"]


def test_horarios_limpeza_e_duplicados(tmp_path):
    from cortes import painel, publicar

    cfg = _cfg(tmp_path)
    meio_dia = time.mktime((2026, 11, 17, 12, 30, 0, 0, 0, -1))
    madrugada = time.mktime((2026, 11, 17, 3, 0, 0, 0, 0, -1))
    assert publicar.no_horario(cfg, madrugada)                         # sem janelas: sempre
    cfg["publicar"]["horarios"] = "11:00-14:00, 22:00-02:00"
    assert publicar.no_horario(cfg, meio_dia) and not publicar.no_horario(cfg, madrugada)
    assert publicar.no_horario(cfg, time.mktime((2026, 11, 17, 1, 0, 0, 0, 0, -1)))  # vira o dia
    with pytest.raises(ValueError):
        publicar.janelas("das 11 às 14")

    banco = Banco(tmp_path / "e.db")
    arq = tmp_path / "corte_000001.mp4"
    for sufixo in (".mp4", ".ass", ".capa.jpg"):
        arq.with_suffix(sufixo).write_text("x")
    cid = banco.novo_corte(video_id="v1", origem="vod", inicio=0, fim=30, nota=80, titulo="T",
                           descricao="", hashtags=[], arquivo=arq)
    assert banco.limpar_antigos(14, ["yt", "ig"]) == 0                 # ainda não publicado
    banco.publicado(cid, "yt", "a")
    banco._exec("UPDATE cortes SET yt_em=? WHERE id=?", (time.time() - 20 * 86400, cid))
    assert banco.limpar_antigos(14, ["yt", "ig"]) == 0                 # falta o Instagram
    assert banco.limpar_antigos(14, ["yt"]) == 1 and not arq.exists()
    assert not arq.with_suffix(".capa.jpg").exists() and banco.corte(cid) is not None

    # vídeo já cortado e publicado não é cortado de novo fora do modo teste
    banco.marcar_video("v1", "T", "C", "feito")
    ger = painel.Gerenciador(cfg, banco)
    tarefa = {"id": "t9", "alvo": "x", "teste": False, "origem": "manual", "status": "identificando"}
    ger.tarefas["t9"] = tarefa
    original = painel.fontes.info
    painel.fontes.info = lambda alvo: {"id": "v1", "titulo": "T", "canal": "C", "canal_id": "",
                                       "ao_vivo": False, "duracao": 60, "replay": [], "url": ""}
    try:
        ger._identificar(tarefa, False)
    finally:
        painel.fontes.info = original
    assert tarefa["status"] == "erro" and "modo teste" in tarefa["erro"]


def test_seguranca_entradas():
    from cortes import seguranca as s

    for bom in ("https://www.youtube.com/watch?v=x", "https://youtu.be/x", "https://twitch.tv/x"):
        assert s.validar_link(bom) == bom
    for ruim in ("http://127.0.0.1:8000/a", "http://192.168.0.1/admin", "file:///etc/passwd",
                 "https://evil.com/youtube.com", "https://youtube.com.evil.io/x",
                 "https://user:senha@youtube.com/x", "javascript:alert(1)", "-o /tmp/x"):
        with pytest.raises(ValueError):
            s.validar_link(ruim)
    with pytest.raises(ValueError):
        s.validar_arquivo("/etc/passwd")                           # existe, mas não é vídeo
    assert "'" not in s.nome_seguro("local-a'b; rm -rf ../x") and "/" not in s.nome_seguro("a/../b")
    limpo = s.sem_segredos("erro em https://graph.facebook.com/x?access_token=EAAB1234567890&f=1 "
                           "sk-ant-api03-abcdefghijklmnop key=AIzaSyA1234567890")
    assert "1234567890" not in limpo and "ghijklmnop" not in limpo and "access_token=***" in limpo
    assert s.sem_links("Segue em https://golpe.com/x e bit.ly/abc agora") == "Segue em e agora"
    with pytest.raises(ValueError):
        Banco(":memory:").pendentes("yt; DROP TABLE cortes")       # nome de coluna não é livre


def test_ia_nao_deixa_links_passarem(tmp_path, monkeypatch):
    from cortes import ia

    cfg = _cfg(tmp_path)
    cfg["ia"]["ativa"] = True
    cfg["conhecimento"]["pasta"] = str(tmp_path / "kb")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "teste")
    monkeypatch.setattr(ia, "quadros", lambda *a, **k: [])
    plantado = {"cortes": [{
        "indice": 0, "aprovado": True, "nota": 90,
        "notas": {"gancho": 90, "emocao": 90, "clareza": 90, "compartilhavel": 90},
        "gancho_texto": "Ganhe em golpe.com", "texto_capa": "ACESSE golpe.com",
        "titulo": "Veja https://golpe.com/x agora", "descricao": "Entre em www.golpe.com já",
        "hashtags": ["#gta 6", "<script>"], "narracoes": [{"segundo": 0, "texto": "vai em golpe.com"}],
        "comentario_final": "link: bit.ly/x", "motivo": "m", "momento_chave": 3,
        "abrir_com_pico": False, "palavras_chave": [], "ajuste_inicio": 0, "ajuste_fim": 0}]}
    monkeypatch.setattr(ia, "_pedir", lambda *a, **k: plantado)
    c = ia.avaliar([{"inicio": 10.0, "fim": 40.0, "transcricao": "t", "chat": [], "pontuacao": 1}],
                   {"titulo": "T", "canal": "C"}, "x.mp4", cfg)[0]
    textos = " ".join([c["titulo"], c["descricao"], c["gancho"], c["texto_capa"],
                       c["comentario_final"], *[n["texto"] for n in c["narracoes"]]])
    assert "golpe" not in textos and "bit.ly" not in textos and "http" not in textos
    assert c["hashtags"] == ["gta6", "script"]


def test_seguranca_do_painel(tmp_path, monkeypatch):
    import http.client
    import threading

    from cortes import painel

    cfg = _cfg(tmp_path)
    banco = Banco(tmp_path / "e.db")
    servidor, ger = painel.criar(cfg, banco, "127.0.0.1", 0, str(tmp_path / "c.yaml"))
    threading.Thread(target=servidor.serve_forever, daemon=True).start()
    porta = servidor.server_address[1]

    def pedir(metodo, rota, corpo=None, **cab):
        con = http.client.HTTPConnection("127.0.0.1", porta, timeout=10)
        con.request(metodo, rota, body=corpo, headers=cab)
        r = con.getresponse()
        dados = r.read()
        con.close()
        return r, dados

    r, _ = pedir("GET", "/api/estado")
    assert r.status == 200 and r.getheader("X-Frame-Options") == "DENY"
    assert "frame-ancestors 'none'" in r.getheader("Content-Security-Policy")
    # outro domínio apontado para 127.0.0.1 (DNS rebinding) e pedidos vindos de outro site
    assert pedir("GET", "/api/estado", Host="site-malicioso.com")[0].status == 403
    assert pedir("POST", "/api/publicacao_auto", '{"ligada":false}', **{
        "X-Painel": "1", "Origin": "https://site-malicioso.com"})[0].status == 403
    assert pedir("POST", "/api/publicacao_auto", '{"ligada":false}')[0].status == 403  # sem cabeçalho
    assert pedir("POST", "/api/publicacao_auto", '{"ligada":false}', **{"X-Painel": "1"})[0].status == 200
    assert pedir("POST", "/api/enviar", "[1,2]", **{"X-Painel": "1"})[0].status == 400
    assert pedir("POST", "/api/enviar", '{"alvo":"http://192.168.0.1/x"}', **{"X-Painel": "1"})[0].status == 400
    assert pedir("POST", "/api/enviar", "x", **{"X-Painel": "1", "Content-Length": "99999999"})[0].status == 413
    assert pedir("GET", "/api/analise/..%5C..%5Cx")[0].status == 404
    assert pedir("GET", "/oauth/youtube?code=abc&state=forjado")[1].count(b"Canal do YouTube conectado") == 0
    servidor.shutdown()

    # aberto à rede: exige senha forte, e depois exige a senha em cada pedido
    monkeypatch.delenv("PAINEL_SENHA", raising=False)
    with pytest.raises(SystemExit):
        painel.criar(cfg, banco, "0.0.0.0", 0, str(tmp_path / "c.yaml"))
    monkeypatch.setenv("PAINEL_SENHA", "senha-bem-longa")
    servidor, ger = painel.criar(cfg, banco, "0.0.0.0", 0, str(tmp_path / "c.yaml"))
    threading.Thread(target=servidor.serve_forever, daemon=True).start()
    porta = servidor.server_address[1]
    import base64
    assert pedir("GET", "/api/estado")[0].status == 401
    certo = "Basic " + base64.b64encode(b"eu:senha-bem-longa").decode()
    errado = "Basic " + base64.b64encode(b"eu:outra").decode()
    assert pedir("GET", "/api/estado", Authorization=errado)[0].status == 401
    assert pedir("GET", "/api/estado", Authorization=certo)[0].status == 200
    servidor.shutdown()


def test_plano_segue_quem_fala():
    from cortes import edicao

    layout = {"tipo": "dupla", "pessoas": [{"cx": 0.25, "cy": 0.4, "w": 0.1, "h": 0.2},
                                           {"cx": 0.75, "cy": 0.4, "w": 0.1, "h": 0.2}]}
    plano = edicao.planejar(layout, 0, 20, falantes=[(2.0, 8.0, 0), (11.0, 17.0, 1)], cfg={})
    vistas = [(p["vista"], round(p["a"]), round(p["b"])) for p in plano["pedacos"]]
    assert vistas == [("dupla", 0, 2), ("pessoa0", 2, 8), ("dupla", 8, 11), ("pessoa1", 11, 17),
                      ("dupla", 17, 20)]
    parado = edicao.planejar(layout, 0, 20, falantes=[(2.0, 8.0, 0)], cfg={"seguir_falante": False})
    assert [p["vista"] for p in parado["pedacos"]] == ["dupla"]


class _Resposta:
    def __init__(self, status, dados=None, texto=""):
        self.status_code, self._dados, self.text = status, dados, texto

    def json(self):
        return self._dados

    @property
    def ok(self):
        return self.status_code < 400


def _cfg_nvidia(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    cfg["ia"].update(ativa=True, provedor="nvidia")
    cfg["conhecimento"]["pasta"] = str(tmp_path / "kb")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-teste")
    return cfg


def test_ia_nvidia_converte_repete_e_completa(tmp_path, monkeypatch):
    import requests

    from cortes import ia

    cfg = _cfg_nvidia(tmp_path, monkeypatch)
    assert ia.disponivel(cfg)
    monkeypatch.setattr(ia, "quadros", lambda *a, **k: [b"\xff\xd8jpg"])
    pedidos = []
    # Modelo "só texto": recusa a 1ª tentativa (com imagem) e responde a 2ª com JSON cercado
    # de pensamento e ```, faltando campos e com tipos trocados.
    resposta = ('<think>pensando</think>```json\n{"cortes": [{"indice": "0", "aprovado": "true", '
                '"nota": "85", "titulo": "Virada incrível", "hashtags": ["jogo"], '
                '"narracoes": [{"segundo": "1", "texto": "Olha isso."}, "lixo"]}]}\n```')

    def post(url, json=None, headers=None, timeout=None):
        pedidos.append((url, json, headers))
        if len(pedidos) == 1:
            return _Resposta(400, texto="image input not supported")
        return _Resposta(200, {"choices": [{"finish_reason": "stop",
                                            "message": {"content": resposta}}]})

    monkeypatch.setattr(requests, "post", post)
    c = ia.avaliar([{"inicio": 10.0, "fim": 40.0, "transcricao": "t", "chat": [], "pontuacao": 1}],
                   {"titulo": "T", "canal": "C"}, "x.mp4", cfg)[0]
    assert c["nota"] == 85 and c["aprovado"] is True and c["titulo"] == "Virada incrível"
    assert c["narracoes"] == [{"segundo": 1.0, "texto": "Olha isso."}]
    url, corpo, cab = pedidos[0]
    assert url == "https://integrate.api.nvidia.com/v1/chat/completions"
    assert cab["Authorization"] == "Bearer nvapi-teste"
    assert corpo["model"] == cfg["ia"]["nvidia"]["modelos"]["final"]
    assert corpo["response_format"] == {"type": "json_object"}
    assert any(p["type"] == "image_url" and p["image_url"]["url"].startswith("data:image/jpeg;base64,")
               for p in corpo["messages"][1]["content"])
    _, corpo2, _ = pedidos[1]                                    # repetição: só texto, sem modo JSON
    assert isinstance(corpo2["messages"][1]["content"], str) and "response_format" not in corpo2


def test_ia_nvidia_erros_viram_mensagem_e_corte_sem_ia(tmp_path, monkeypatch):
    import requests

    from cortes import ia

    cfg = _cfg_nvidia(tmp_path, monkeypatch)
    monkeypatch.setattr(ia, "quadros", lambda *a, **k: [])
    monkeypatch.setattr(requests, "post", lambda *a, **k: _Resposta(401, texto="Unauthorized"))
    with pytest.raises(ValueError, match="NVIDIA_API_KEY inválida"):
        ia.testar(cfg)
    c = ia.avaliar([{"inicio": 0.0, "fim": 30.0, "transcricao": "", "chat": [], "pontuacao": 1}],
                   {"titulo": "Live boa", "canal": "C"}, "x.mp4", cfg)[0]
    assert c["motivo"].startswith("sem IA")                      # falha não derruba a análise
    monkeypatch.setattr(requests, "post", lambda *a, **k: _Resposta(200, {"choices": [
        {"finish_reason": "stop", "message": {"content": "não sei responder em JSON"}}]}))
    with pytest.raises(ValueError, match="não devolveu o JSON"):
        ia.testar(cfg)
    monkeypatch.setattr(requests, "post", lambda *a, **k: _Resposta(200, {"choices": [
        {"finish_reason": "stop", "message": {"content": '{"ok": true}'}}]}))
    assert "NVIDIA" in ia.testar(cfg)
    monkeypatch.delenv("NVIDIA_API_KEY")
    assert not ia.disponivel(cfg)
    with pytest.raises(ValueError, match="não foi colada"):
        ia.testar(cfg)
    monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-teste")             # chave da NVIDIA, provedor Claude
    cfg["ia"]["provedor"] = "anthropic"
    with pytest.raises(ValueError, match="salvou a chave da NVIDIA"):
        ia.testar(cfg)


def test_ajustes_provedor_da_ia(tmp_path):
    from cortes import ajustes

    cfg = _cfg(tmp_path)
    arq = tmp_path / "c.yaml"
    ajustes.salvar(cfg, {"ia.provedor": "nvidia", "ia.nvidia.modelos.final": "moonshotai/kimi-k3.1-pro"}, arq)
    assert cfg["ia"]["provedor"] == "nvidia"
    assert config.carregar(arq)["ia"]["nvidia"]["modelos"]["final"] == "moonshotai/kimi-k3.1-pro"
    with pytest.raises(ValueError, match="Opção inválida"):
        ajustes.salvar(cfg, {"ia.provedor": "outro"}, arq)
    assert "NVIDIA_API_KEY" in ajustes.CHAVES


def _fala(inicio, palavras, passo=0.4, pausa_final=1.2):
    """Palavras seguidas (sem pausa entre elas) a partir de `inicio`; devolve lista e fim."""
    lista = [(inicio + i * passo, inicio + (i + 1) * passo, w) for i, w in enumerate(palavras)]
    return lista, inicio + len(palavras) * passo + pausa_final


def test_corte_nao_interrompe_a_fala():
    # Frase 1: 10–14 s. Frase 2 começa em 15.2 s e só termina em 23.2 s (20 palavras).
    f1, prox = _fala(10, [f"a{i}" for i in range(10)])
    f2, _ = _fala(prox, [f"b{i}" for i in range(20)])
    palavras = f1 + f2
    # Corte terminando em 18 s, no meio da frase 2: estende até o fim dela (23.2 + folga).
    ini, fim = transcricao.fechar_fala(palavras, 10.0, 18.0, extra_fim=15)
    assert ini == 10.0 and abs(fim - (prox + 20 * 0.4 + 0.3)) < 0.01
    # Sem margem suficiente para fechar a frase, fica no limite que der (não encurta).
    assert transcricao.fechar_fala(palavras, 10.0, 18.0, extra_fim=2)[1] >= 18.0
    # Corte que já termina numa pausa não muda.
    assert transcricao.fechar_fala(palavras, 10.0, 14.2, extra_fim=15) == (10.0, 14.2)
    # Começando no meio da frase 2 (em 18 s), volta até o começo dela.
    ini, _ = transcricao.fechar_fala(palavras, 18.0, 30.0, extra_inicio=6)
    assert abs(ini - (prox - 0.2)) < 0.01
    # Pontuação (Whisper) conta como fim de frase mesmo sem pausa longa.
    com_ponto = [(0, 0.4, "Olha"), (0.4, 0.8, "isso."), (0.8, 1.2, "Agora"), (1.2, 1.6, "vai")]
    assert abs(transcricao.fechar_fala(com_ponto, 0.0, 0.6, extra_fim=5)[1] - 1.1) < 0.01


def test_cortes_repetidos_sao_descartados():
    falas = [(100 + i * 0.5, 100.4 + i * 0.5, f"palavra{i}") for i in range(40)]
    mesma_fala = [(300 + i * 0.5, 300.4 + i * 0.5, f"palavra{i}") for i in range(40)]
    a = {"inicio": 100.0, "fim": 120.0, "falas": falas}
    assert vod.repetido({"inicio": 110.0, "fim": 135.0, "falas": falas}, [a], [])  # mesmo trecho
    assert "mesma fala" in vod.repetido({"inicio": 300.0, "fim": 320.0, "falas": mesma_fala}, [a], [])
    assert vod.repetido({"inicio": 500.0, "fim": 530.0, "falas": []}, [a], [])  == ""
    assert "já feito" in vod.repetido({"inicio": 500.0, "fim": 530.0, "falas": []}, [], [(505, 535)])


def test_pausar_e_cancelar_analise(tmp_path, monkeypatch):
    import threading

    from cortes import painel

    cfg = _cfg(tmp_path)
    banco = Banco(tmp_path / "e.db")
    servidor, ger = painel.criar(cfg, banco, "127.0.0.1", 0, str(tmp_path / "c.yaml"))
    servidor.server_close()
    meta = {"id": "vid", "titulo": "Vídeo", "canal": "C"}
    passos = []

    def processar(alvo, cfg, banco, forcar, meta, progresso):
        for i in range(200):
            passos.append(i)
            if i == 1:  # um corte fica pronto antes do cancelamento
                banco.novo_corte(video_id="vid", origem="vod", inicio=10, fim=40, nota=80,
                                 titulo="t", descricao="d", hashtags=[], arquivo=str(tmp_path / "x.mp4"))
            progresso(f"etapa {i}", i / 200)
            time.sleep(0.01)
        return []

    monkeypatch.setattr(vod, "processar", processar)
    tarefa = {"id": "t1", "alvo": "x", "titulo": "x", "canal": "", "teste": True, "origem": "manual",
              "status": "fila", "etapa": "", "fracao": None, "erro": "", "video_id": "vid",
              "cortes": 0, "inicio": time.time(), "fim": None}
    ger.tarefas["t1"] = tarefa
    linha = threading.Thread(target=ger._analisar, args=(tarefa, meta))
    linha.start()
    ger.acao("tarefa/pausar", {"id": "t1"})
    for _ in range(100):
        if tarefa["status"] == "pausado":
            break
        time.sleep(0.05)
    assert tarefa["status"] == "pausado"
    parado_em = len(passos)
    time.sleep(0.4)
    assert len(passos) == parado_em                                   # pausada não avança
    ger.acao("tarefa/retomar", {"id": "t1"})
    time.sleep(0.2)
    assert len(passos) > parado_em and tarefa["status"] == "rodando"
    ger.acao("tarefa/cancelar", {"id": "t1"})
    linha.join(5)
    assert tarefa["status"] == "cancelado" and tarefa["cortes"] == 1   # o corte pronto ficou
    assert len(passos) < 200 and banco.status_video("vid") == "parcial"
    assert len(banco.cortes_do_video("vid")) == 1
    with pytest.raises(ValueError, match="já terminou"):
        ger.acao("tarefa/pausar", {"id": "t1"})
    ger.acao("tarefa/fechar", {"id": "t1"})
    assert "t1" not in ger.tarefas


def test_ia_nvidia_avalia_em_lotes(tmp_path, monkeypatch):
    from cortes import ia

    cfg = _cfg_nvidia(tmp_path, monkeypatch)
    monkeypatch.setattr(ia, "quadros", lambda *a, **k: [])
    chamadas = []

    def pedir(modelo, sistema, conteudo, esquema, cfg=None):
        n = sum(1 for b in conteudo if b["type"] == "text" and b["text"].startswith("--- Candidato"))
        chamadas.append(n)
        return {"cortes": [{"indice": i, "aprovado": True, "nota": 70 + i, "titulo": f"c{i}"}
                           for i in range(n)]}

    monkeypatch.setattr(ia, "_pedir", pedir)
    cands = [{"inicio": 100.0 * i, "fim": 100.0 * i + 30, "transcricao": "t", "chat": [],
              "pontuacao": 1} for i in range(14)]
    avaliados = ia.avaliar(cands, {"titulo": "T", "canal": "C"}, "x.mp4", cfg)
    assert chamadas == [6, 6, 2] and len(avaliados) == 14
    assert [c["inicio"] for c in avaliados] == [c["inicio"] for c in cands]   # índices por lote


def test_segunda_copia_do_programa_nao_sobe_outro_servidor(tmp_path):
    import http.server
    import socket
    import threading

    from cortes import app, painel

    cfg = _cfg(tmp_path)
    servidor, _ = painel.criar(cfg, Banco(tmp_path / "e.db"), "127.0.0.1", 0, str(tmp_path / "c.yaml"))
    porta = servidor.server_address[1]
    threading.Thread(target=servidor.serve_forever, daemon=True).start()
    try:
        assert app._ja_aberto(porta)
        with pytest.raises(OSError):  # a mesma porta não pode ser aberta duas vezes
            painel.criar(cfg, Banco(tmp_path / "f.db"), "127.0.0.1", porta, str(tmp_path / "c.yaml"))
    finally:
        servidor.shutdown()
        servidor.server_close()
    assert not app._ja_aberto(porta)                 # fechado de verdade: porta livre
    # Porta ocupada por um programa que não responde: conta como "já aberto" (ocupado).
    mudo = socket.socket()
    mudo.bind(("127.0.0.1", 0))
    mudo.listen(1)
    try:
        import urllib.request
        original = urllib.request.urlopen
        urllib.request.urlopen = lambda *a, **k: (_ for _ in ()).throw(TimeoutError("ocupado"))
        try:
            assert app._ja_aberto(mudo.getsockname()[1])
        finally:
            urllib.request.urlopen = original
    finally:
        mudo.close()
    # Porta de outro programa que responde 404: não é o painel.
    outro = http.server.HTTPServer(("127.0.0.1", 0), http.server.BaseHTTPRequestHandler)
    threading.Thread(target=outro.serve_forever, daemon=True).start()
    try:
        assert not app._ja_aberto(outro.server_address[1])
    finally:
        outro.shutdown()
        outro.server_close()


def test_ia_confere_o_raciocinio_e_so_alonga(tmp_path, monkeypatch):
    from cortes import ia

    cfg = _cfg_nvidia(tmp_path, monkeypatch)
    pedidos = []
    resposta = {"completo": False, "fim": 31.0, "inicio": -3.0, "motivo": "explicação continua"}
    monkeypatch.setattr(ia, "_pedir", lambda m, s, conteudo, e, cfg=None: pedidos.append(conteudo) or resposta)
    falas = [(95 + i * 0.5, 95.4 + i * 0.5, f"p{i}") for i in range(140)]   # 95 s a 165 s
    c = {"inicio": 100.0, "fim": 120.0, "titulo": "T"}
    assert ia.concluir_raciocinio(c, falas, cfg, extra_fim=40, extra_inicio=10) == (97.0, 131.0)
    texto = pedidos[0][0]["text"]
    assert "[INÍCIO ATUAL]" in texto and "[FIM ATUAL]" in texto and "(+20s)" in texto
    resposta.update(fim=500.0, inicio=-99.0)                                 # respeita os limites
    assert ia.concluir_raciocinio(c, falas, cfg, extra_fim=40, extra_inicio=10) == (90.0, 160.0)
    resposta.update(fim=5.0, inicio=4.0)                                     # nunca encurta
    assert ia.concluir_raciocinio(c, falas, cfg, extra_fim=40, extra_inicio=10) == (100.0, 120.0)
    monkeypatch.delenv("NVIDIA_API_KEY")
    assert ia.concluir_raciocinio(c, falas, cfg, extra_fim=40, extra_inicio=10) is None


def test_ia_que_nao_responde_nao_trava_o_fim_da_fala(tmp_path, monkeypatch):
    """A IA aceita o pedido e nunca responde: o ajuste do fim desiste no prazo e a análise
    segue com a pausa da fala (antes ficava em 'Conferindo o fim da fala' para sempre)."""
    import threading
    from cortes import ia

    cfg = _cfg_nvidia(tmp_path, monkeypatch)
    cfg["ia"]["prazo_raciocinio_s"] = 0.5
    solta = threading.Event()
    monkeypatch.setattr(ia, "_pedir", lambda *a, **k: solta.wait(30) and None)
    falas = [(95 + i * 0.5, 95.4 + i * 0.5, f"p{i}") for i in range(140)]
    t = time.time()
    assert ia.concluir_raciocinio({"inicio": 100.0, "fim": 120.0}, falas, cfg, 40, 10) is None
    assert time.time() - t < 5 and "não respondeu" in ia.ultimo_erro
    solta.set()


def test_nota_alta_publica_sozinha(tmp_path):
    cfg = _cfg(tmp_path)
    cfg["publicar"]["manual"] = True
    pa = vod.publicacao_automatica
    # Padrão: só o Instagram publica sozinho; YouTube e TikTok sempre esperam você.
    assert pa({"nota": 88}, {}, cfg) == ([], False)                     # 88 não passa de 88
    assert pa({"nota": 89}, {}, cfg) == (["ig"], False)                 # fila do Instagram
    assert pa({"nota": 90.5}, {}, cfg) == (["ig"], True)                # publica na hora
    assert pa({"nota": 79}, {}, cfg, "live") == (["ig"], False)         # live acima de 78
    assert pa({"nota": 78}, {}, cfg, "live") == ([], False)
    assert pa({"nota": 79}, {}, cfg, "vod") == ([], False)              # vídeo gravado: só > 88
    assert pa({"nota": 95}, {"teste": True}, cfg) == ([], False)        # teste nunca
    assert pa({"nota": 95, "validado_local": True}, {}, cfg) == ([], False)
    assert pa({"nota": 95, "motivo": "sem IA: ordenado pelos sinais"}, {}, cfg) == ([], False)
    cfg["publicar"]["youtube"]["automatico"] = True
    assert pa({"nota": 89}, {}, cfg) == (["yt", "ig"], False)
    cfg["publicar"].update(auto_acima=0, imediato_acima=0)
    cfg["publicar"]["instagram"]["auto_live_acima"] = 0
    assert pa({"nota": 99}, {}, cfg, "live") == ([], False)             # desligado


def test_corte_de_nota_alta_entra_na_fila_e_fura_o_intervalo(video, tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    cfg["publicar"]["manual"] = True
    banco = Banco(tmp_path / "n.db")
    monkeypatch.setattr(vod, "montar", lambda *a, **k: {"descricao": "d", "capa": "", "capa_ms": None,
                                                         "layout": "", "narracao": ""})
    ctx = {"id": "v1", "titulo": "T", "canal": "C"}
    base = {"inicio": 0.0, "fim": 20.0, "titulo": "t", "hashtags": [], "motivo": "bom"}
    ids = [vod.finalizar({**base, "inicio": float(i), "nota": n}, video, ctx, cfg, banco, tmp_path,
                         "live", []) for i, n in enumerate((70, 79, 93))]
    pend = {c["id"]: c for c in banco.pendentes("ig")}
    assert ids[0] not in pend                                           # 70: espera você
    assert not pend[ids[1]]["urgente"] and pend[ids[2]]["urgente"]      # 79: fila; 93: já
    for p in ("yt", "tt"):                                              # sempre você avalia
        assert banco.pendentes(p) == []
        assert all(banco.corte(i)[f"{p}_aguardando"] == 1 for i in ids)


def test_vigia_aponta_analise_presa_e_a_que_sumiu(tmp_path, caplog):
    import threading
    from cortes.painel import Gerenciador

    p = Gerenciador(_cfg(tmp_path), Banco(tmp_path / "v.db"))
    solta = threading.Event()
    presa = threading.Thread(target=lambda: solta.wait(30), daemon=True)
    presa.start()
    velho = time.time() - 3600
    p.tarefas["a"] = {"id": "a", "alvo": "x", "status": "rodando", "etapa": "Conferindo o fim da fala",
                      "mudou": velho, "inicio": velho, "thread": presa.ident}
    p.tarefas["b"] = {"id": "b", "alvo": "y", "status": "rodando", "etapa": "Conferindo o fim da fala",
                      "mudou": velho, "inicio": velho, "thread": -1}
    with caplog.at_level("WARNING"):
        p._vigiar()
    assert "parada há 60 min" in caplog.text and "wait" in caplog.text      # mostra a pilha
    assert p.tarefas["a"]["status"] == "rodando" and p.tarefas["a"]["vigiado"]
    assert p.tarefas["b"]["status"] == "erro"                                 # sumiu: vira erro
    solta.set()


def test_fechar_bordas_usa_a_ia_e_encaixa_na_pausa(tmp_path, monkeypatch):
    from cortes import ia

    cfg = _cfg(tmp_path)
    f1, prox = _fala(100, [f"a{i}" for i in range(50)])        # 100–120 s, pausa até 121.2
    f2, _ = _fala(prox, [f"b{i}" for i in range(30)])          # 121.2–133.2 s
    c = {"inicio": 100.0, "fim": 110.0, "falas": f1 + f2, "momento": 4.0,
         "narracoes": [{"segundo": 0.0, "texto": "oi"}]}
    # A IA diz que o raciocínio termina no segundo 18.7 (meio de palavra): encaixa na pausa (120 s).
    monkeypatch.setattr(ia, "concluir_raciocinio", lambda *a, **k: (100.0, 118.7))
    vod.fechar_bordas(c, cfg, 600)
    assert abs(c["fim"] - 120.3) < 0.01 and c["inicio"] == 100.0 and c["momento"] == 4.0


def test_refazer_corte_com_outro_comeco_e_fim(video, tmp_path):
    cfg = _cfg(tmp_path)
    cfg["cortes"].update(capa=False, legendas=False)
    banco = Banco(tmp_path / "e.db")
    pasta = tmp_path / "v"
    pasta.mkdir()
    meta = {"id": "v", "titulo": "Live", "canal": "Canal X", "canal_id": "", "url": "",
            "arquivo": str(video), "duracao": 150.0, "teste": True}
    c = {"inicio": 60.0, "fim": 70.0, "nota": 80, "titulo": "T", "descricao": "D", "hashtags": [],
         "gancho": "", "momento": 4.0, "narracoes": [], "palavras_chave": []}
    cid = vod.finalizar(c, video, meta, cfg, banco, pasta, "vod", [])
    antigo = Path(banco.corte(cid)["arquivo"])
    assert vod.pode_refazer(banco.corte(cid))
    vod.refazer(cid, -2, 5, cfg, banco)
    novo = banco.corte(cid)
    assert (novo["inicio"], novo["fim"]) == (58.0, 75.0)
    assert Path(novo["arquivo"]).exists() and not antigo.exists()
    dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of",
                                "csv=p=0", novo["arquivo"]], capture_output=True, text=True).stdout)
    assert abs(dur - 17) < 1.0
    receita = json.loads(vod.arquivo_receita(novo["arquivo"], cid).read_text(encoding="utf-8"))
    assert receita["corte"]["momento"] == 6.0                     # acompanha o novo começo
    with pytest.raises(ValueError, match="curto demais"):
        vod.refazer(cid, 15, 0, cfg, banco)
    banco._exec("UPDATE cortes SET yt_id='abc' WHERE id=?", (cid,))
    with pytest.raises(ValueError, match="já foi publicado"):
        vod.refazer(cid, 0, 5, cfg, banco)


def test_gerar_corte_de_trecho_que_ficou_de_fora(video, tmp_path, monkeypatch):
    import shutil

    from cortes import painel

    cfg = _cfg(tmp_path)
    cfg["cortes"].update(capa=False, legendas=False)
    banco = Banco(tmp_path / "e.db")
    pasta = tmp_path / "dados" / "abcdefghijk"
    pasta.mkdir(parents=True)
    shutil.copy(video, pasta / "fonte.mp4")                     # o original ainda no disco
    banco.marcar_video("abcdefghijk", "Vídeo X", "Canal X", "feito")
    analise = {"duracao": 150, "pontos": [1, 2], "sinais": {}, "candidatos": [
        {"inicio": 20.0, "fim": 30.0, "nota": 55, "aprovado": True, "escolhido": False,
         "titulo": "Trecho bom", "motivo": "m", "gancho": "", "notas": {}},
        {"inicio": 60.0, "fim": 70.0, "nota": 65, "aprovado": True, "escolhido": False,
         "titulo": "Outro", "motivo": "m", "gancho": "", "notas": {}}]}
    (pasta / "analise.json").write_text(json.dumps(analise), encoding="utf-8")
    # Análise nova: o 2º candidato tem os dados completos guardados.
    c2 = {"inicio": 60.0, "fim": 70.0, "nota": 65, "titulo": "Título da IA", "descricao": "D",
          "hashtags": ["gta"], "gancho": "Olha *isso*", "momento": 3.0, "narracoes": [],
          "palavras_chave": [], "notas": {}}
    ctx = {"id": "abcdefghijk", "url": "", "titulo": "Vídeo X", "canal": "Canal X", "duracao": 150}
    (pasta / "candidatos.json").write_text(json.dumps(
        [vod._receita(analise["candidatos"][0], ctx, "vod", []), vod._receita(c2, ctx, "vod", [])]),
        encoding="utf-8")
    cid = vod.cortar_candidato("abcdefghijk", 1, cfg, banco)
    corte = banco.corte(cid)
    assert corte["teste"] == 1 and corte["titulo"] == "Título da IA" and corte["gancho"] == "Olha isso"
    assert Path(corte["arquivo"]).exists() and vod.pode_refazer(corte)  # pode ajustar depois
    salvo = json.loads((pasta / "analise.json").read_text(encoding="utf-8"))
    assert salvo["candidatos"][1]["gerado"] == cid and salvo["candidatos"][1]["situacao"] == "cortado"
    with pytest.raises(ValueError, match="já virou"):
        vod.cortar_candidato("abcdefghijk", 1, cfg, banco)
    # Análise antiga (sem dados completos): monta com o que foi registrado.
    (pasta / "candidatos.json").unlink()
    cid0 = vod.cortar_candidato("abcdefghijk", 0, cfg, banco)
    assert banco.corte(cid0)["titulo"] == "Trecho bom"
    with pytest.raises(ValueError, match="inválido"):
        vod.cortar_candidato("../x", 0, cfg, banco)
    # O vídeo aparece em "análises anteriores" para reabrir depois de reiniciar.
    servidor, ger = painel.criar(cfg, banco, "127.0.0.1", 0, str(tmp_path / "c.yaml"))
    servidor.server_close()
    anteriores = ger.estado()["anteriores"]
    assert [a["video_id"] for a in anteriores] == ["abcdefghijk"] and anteriores[0]["titulo"] == "Vídeo X"


def test_janela_nao_corta_o_pico_no_meio():
    serie = np.zeros(300)
    serie[50:66] = 1.0                       # pico que começa dentro da janela e passa do fim dela
    ini, fim = sinais.ajustar_ao_pico(serie, 30, 30)
    assert ini == 30 and 66 <= fim <= 72      # estende até a empolgação baixar, mais um respiro
    serie = np.zeros(300)
    serie[35:45] = 1.0                       # pico no meio, já terminado antes do fim
    assert sinais.ajustar_ao_pico(serie, 30, 30) == (29.0, 60.0)
    serie = np.zeros(300)
    serie[20:200] = 1.0                      # empolgação contínua: estende só até o limite
    assert sinais.ajustar_ao_pico(serie, 60, 30, extra_fim=20) == (52.0, 113.0)


def _corte_na_fila(banco, tmp_path, nota=80, urgente=False):
    arq = tmp_path / f"c{nota}{urgente}.mp4"
    arq.write_bytes(b"x")
    return banco.novo_corte(video_id="v", origem="vod", inicio=0, fim=30, nota=nota, titulo=f"t{nota}",
                            descricao="d", hashtags=[], arquivo=str(arq), urgente=urgente)


def test_previsao_da_fila_de_publicacao(tmp_path, monkeypatch):
    from cortes import publicar

    cfg = _cfg(tmp_path)
    cfg["publicar"]["youtube"].update(ativo=True, max_por_dia=3)
    cfg["publicar"]["intervalo_min"] = 30
    monkeypatch.setattr(publicar, "conectado", lambda p, cfg: True)
    banco = Banco(tmp_path / "e.db")
    agora = 1_800_000_000.0
    feito = _corte_na_fila(banco, tmp_path, nota=99)
    banco.publicado(feito, "yt", "x")                           # publicado agora há pouco
    banco._exec("UPDATE cortes SET yt_em=? WHERE id=?", (agora - 600, feito))
    a, b, c = (_corte_na_fila(banco, tmp_path, nota=n) for n in (90, 80, 70))
    u = _corte_na_fila(banco, tmp_path, nota=10, urgente=True)
    prev = publicar.previsao(cfg, banco, agora)["yt"]
    assert prev["bloqueio"] == ""
    pv = prev["cortes"]
    assert pv[u]["posicao"] == 1 and pv[u]["motivo"] == "agora"          # live fura a fila
    assert pv[a]["motivo"] == "intervalo" and pv[a]["quando"] == agora + 30 + 1800  # 30 min após a live
    assert pv[b]["motivo"] == "limite" and pv[b]["quando"] > agora + 80000  # 3 por dia: 1 + live + a
    assert pv[c]["quando"] >= pv[b]["quando"] + 1800                      # e o intervalo depois dele
    banco.definir_opcao("publicacao_auto", "0")
    assert publicar.previsao(cfg, banco, agora)["yt"]["cortes"][a]["motivo"] == "pausada"
    # Horários de postagem empurram para a próxima janela.
    banco.definir_opcao("publicacao_auto", "1")
    assert publicar._proxima_janela(time.mktime((2026, 11, 17, 9, 0, 0, 0, 0, -1)), [(11 * 60, 14 * 60)]) \
        == time.mktime((2026, 11, 17, 11, 0, 0, 0, 0, -1))
    assert publicar._proxima_janela(time.mktime((2026, 11, 17, 15, 0, 0, 0, 0, -1)), [(11 * 60, 14 * 60)]) \
        == time.mktime((2026, 11, 18, 11, 0, 0, 0, 0, -1))


def test_mesmo_corte_nao_e_enviado_duas_vezes(tmp_path, monkeypatch):
    import threading

    from cortes import publicar

    cfg = _cfg(tmp_path)
    banco = Banco(tmp_path / "e.db")
    cid = _corte_na_fila(banco, tmp_path)
    liberar, chamadas = threading.Event(), []

    def enviar_lento(*a, progresso=None, **k):
        chamadas.append(1)
        progresso("Enviando o vídeo", 0.4)
        liberar.wait(5)
        return "abc"

    monkeypatch.setattr(publicar.youtube, "enviar", enviar_lento)
    linha = threading.Thread(target=publicar.publicar_um, args=(cfg, banco, banco.corte(cid), "yt"))
    linha.start()
    for _ in range(100):
        if (publicar.ENVIANDO.get((cid, "yt")) or {}).get("fracao") is not None:
            break
        time.sleep(0.02)
    assert publicar.ENVIANDO[(cid, "yt")]["fracao"] == 0.4                # o painel mostra 40%
    assert publicar.publicar_um(cfg, banco, banco.corte(cid), "yt") is False  # 2º clique: ignorado
    liberar.set()
    linha.join(5)
    assert chamadas == [1] and banco.corte(cid)["yt_id"] == "abc" and not publicar.enviando(cid, "yt")


def test_ia_reserva_claude_code_quando_a_nvidia_cai(tmp_path, monkeypatch):
    import requests

    from cortes import ia

    cfg = _cfg_nvidia(tmp_path, monkeypatch)
    cfg["ia"]["reserva"] = "claude_code"
    monkeypatch.setattr(ia, "achar_claude_code", lambda: "C:/fake/claude.exe")
    monkeypatch.setattr(requests, "post", lambda *a, **k: _Resposta(503, texto="fora do ar"))
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "sk-ant-oat-fixo")
    monkeypatch.setenv("CLAUDECODE", "1")                       # de uma sessão do Claude: deve sair
    chamadas = []

    class Saida:
        stdout = "\n".join([json.dumps({"type": "system", "subtype": "init"}), json.dumps(
            {"type": "result", "subtype": "success", "is_error": False, "result": '```json\n{"ok": true}\n```'})])
        stderr = ""

    def run(args, **k):
        chamadas.append((args, k))
        return Saida()

    monkeypatch.setattr(ia.subprocess, "run", run)
    mensagem = ia.testar(cfg)
    assert "reserva" in mensagem and "Claude Code" in mensagem and "503" in mensagem
    args, k = chamadas[0]
    assert args[0] == "C:/fake/claude.exe" and args[args.index("--tools") + 1] == ""
    assert args[args.index("--model") + 1] == cfg["ia"]["reserva_modelo"]
    assert k["env"]["CLAUDE_CODE_OAUTH_TOKEN"] == "sk-ant-oat-fixo" and "CLAUDECODE" not in k["env"]
    entrada = json.loads(k["input"])
    assert entrada["type"] == "user" and entrada["message"]["content"][0]["type"] == "text"
    # Sem chave da NVIDIA, a reserva assume direto.
    monkeypatch.delenv("NVIDIA_API_KEY")
    assert ia.disponivel(cfg)
    # Claude Code deslogado: mensagem clara.
    Saida.stdout = json.dumps({"type": "result", "subtype": "error", "is_error": True,
                               "result": "Not logged in · Please run /login"})
    with pytest.raises(ValueError, match="não está logado"):
        ia.testar_reserva(cfg)


def test_ia_local_so_valida_e_a_nota_vem_das_metricas(tmp_path, monkeypatch):
    import requests

    from cortes import ia

    cfg = _cfg(tmp_path)
    cfg["ia"].update(ativa=True, local="ollama", nota_minima=70)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    instalados = ["gemma3:4b", "qwen3:30b-a3b", "qwen3:30b-a3b-instruct-2507-q4_K_M"]
    assert ia.modelo_local(cfg, instalados) == "qwen3:30b-a3b-instruct-2507-q4_K_M"
    monkeypatch.setattr(ia, "_garantir_ollama", lambda: instalados)
    monkeypatch.setattr(ia, "local_disponivel", lambda cfg: True)
    pedidos = []

    def post(url, json=None, timeout=None):
        pedidos.append((url, json))
        return _Resposta(200, {"message": {"content": '{"cortes": [{"indice": 0, "aprovado": true, '
                                                      '"motivo": "boa"}, {"indice": 1, "aprovado": false, "motivo": "vazio"}]}'}})

    monkeypatch.setattr(requests, "post", post)
    cands = [{"inicio": 10.0, "fim": 40.0, "transcricao": "t", "chat": [], "pontuacao": 0.4},
             {"inicio": 90.0, "fim": 120.0, "transcricao": "", "chat": [], "pontuacao": 0.2}]
    a, b = ia.avaliar(cands, {"titulo": "Vídeo"}, "x.mp4", cfg)
    assert a["aprovado"] and not b["aprovado"] and a["validado_local"]
    assert a["nota"] == 60.0 and a["titulo"] == "Vídeo"                 # nota e título sem IA
    assert "IA local" in a["motivo"] and "aprovou" in a["motivo"]
    url, corpo = pedidos[0]
    assert url.endswith("/api/chat") and corpo["format"] and corpo["think"] is False
    assert corpo["model"] == "qwen3:30b-a3b-instruct-2507-q4_K_M"


def test_reanalisar_nao_apaga_cortes_ja_feitos(tmp_path, monkeypatch):
    from cortes import painel

    cfg = _cfg(tmp_path)
    banco = Banco(tmp_path / "e.db")
    servidor, ger = painel.criar(cfg, banco, "127.0.0.1", 0, str(tmp_path / "c.yaml"))
    servidor.server_close()
    antigo = banco.novo_corte(video_id="vid", origem="vod", inicio=10, fim=40, nota=80, titulo="t",
                              descricao="d", hashtags=[], arquivo=str(tmp_path / "x.mp4"), teste=True)
    monkeypatch.setattr(vod, "processar", lambda *a, **k: [])
    tarefa = {"id": "t1", "alvo": "x", "titulo": "x", "canal": "", "teste": True, "origem": "retomado",
              "status": "fila", "etapa": "", "fracao": None, "erro": "", "video_id": "vid",
              "cortes": 0, "inicio": time.time(), "fim": None}
    ger._analisar(tarefa, {"id": "vid", "titulo": "V", "canal": "C"})
    assert tarefa["status"] == "feito" and banco.corte(antigo) is not None   # o corte anterior ficou


def test_fila_por_plataforma(tmp_path, monkeypatch):
    from cortes import painel, publicar

    cfg = _cfg(tmp_path)
    cfg["publicar"]["youtube"]["ativo"] = cfg["publicar"]["instagram"]["ativo"] = True
    banco = Banco(tmp_path / "e.db")
    arq = tmp_path / "a.mp4"
    arq.write_bytes(b"x")
    cid = banco.novo_corte(video_id="v", origem="vod", inicio=0, fim=30, nota=80, titulo="t",
                           descricao="d", hashtags=[], arquivo=str(arq), aguardando=True)
    assert banco.pendentes("yt") == [] and banco.pendentes("ig") == []       # nada entra sozinho
    servidor, ger = painel.criar(cfg, banco, "127.0.0.1", 0, str(tmp_path / "c.yaml"))
    servidor.server_close()
    assert "fila do YouTube" in ger.decidir_corte(cid, "fila", ("yt",))       # só no YouTube
    assert [c["id"] for c in banco.pendentes("yt")] == [cid] and banco.pendentes("ig") == []
    estado = ger.estado()["grupos"][0]["cortes"][0]
    assert estado["yt"]["situacao"] == "na fila" and estado["ig"]["situacao"] == "aguardando"
    assert estado["aguardando"] == ["ig", "tt"]
    assert banco.tirar_da_fila(cid, ("yt",)) == 1 and banco.pendentes("yt") == []
    # Publicar agora só no Instagram: as outras ficam como estão.
    enviados = []
    monkeypatch.setattr(publicar, "conectado", lambda p, cfg: True)
    monkeypatch.setattr(publicar, "publicar_um", lambda cfg, banco, corte, p: enviados.append(p))
    ger.decidir_corte(cid, "agora", ("ig",))
    time.sleep(0.2)
    assert enviados == ["ig"] and banco.corte(cid)["yt_aguardando"] == 1
    # Corte de teste aprovado só para o YouTube: o Instagram fica aguardando, não na fila.
    t = banco.novo_corte(video_id="v", origem="vod", inicio=60, fim=90, nota=80, titulo="t2",
                         descricao="d", hashtags=[], arquivo=str(arq), teste=True)
    banco.aprovar(t, ("yt",))
    assert banco.corte(t)["teste"] == 0 and banco.corte(t)["ig_aguardando"] == 1
    assert t in [c["id"] for c in banco.pendentes("yt")] and t not in [c["id"] for c in banco.pendentes("ig")]
    assert banco.tirar_da_fila() >= 1 and banco.pendentes("yt") == []          # tirar todos
    assert painel._plataformas("tt") == ("tt",)
    with pytest.raises(ValueError, match="pelo menos uma plataforma"):
        painel._plataformas("tiktok")


def test_migracao_do_aguardando_antigo(tmp_path):
    banco = Banco(tmp_path / "e.db")
    cid = banco.novo_corte(video_id="v", origem="vod", inicio=0, fim=30, nota=80, titulo="t",
                           descricao="d", hashtags=[], arquivo="x.mp4")
    banco._exec("UPDATE cortes SET aguardando=1 WHERE id=?", (cid,))       # como a 1ª versão gravava
    banco = Banco(tmp_path / "e.db")
    c = banco.corte(cid)
    assert (c["aguardando"], c["yt_aguardando"], c["ig_aguardando"]) == (0, 1, 1)


def test_instagram_versao_reels_e_nova_tentativa(video, tmp_path, monkeypatch):
    import shutil

    from cortes.publicar import instagram

    arq = tmp_path / "corte_000001.mp4"
    shutil.copy(video, arq)
    pronto = instagram.versao_reels(arq)
    info = json.loads(subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                                      "stream=codec_type,bit_rate,sample_rate", "-of", "json", str(pronto)],
                                     capture_output=True, text=True).stdout)
    audio = next(s for s in info["streams"] if s["codec_type"] == "audio")
    assert pronto.name == "corte_000001.ig.mp4" and int(audio["bit_rate"]) <= 130000
    assert instagram.versao_reels(arq) == pronto                             # feita uma vez só
    monkeypatch.setenv("IG_USER_ID", "1")
    monkeypatch.setenv("IG_ACCESS_TOKEN", "t")
    monkeypatch.setattr(instagram, "ESPERA_ENTRE_S", 0)
    tentativas = []

    def publicar(arquivo, *a, **k):
        tentativas.append(arquivo.name)
        if len(tentativas) < 3:
            raise instagram.FalhaProcessamento("falhou")
        return "id1", "https://instagram.com/p/x"

    monkeypatch.setattr(instagram, "_publicar", publicar)
    assert instagram.enviar(arq, "legenda", {"versao_api": "v21.0"}) == ("id1", "https://instagram.com/p/x")
    # Repetiu sozinho, cada vez com uma versão mais simples (a última, 720p).
    assert tentativas == ["corte_000001.ig.mp4", "corte_000001.ig2.mp4", "corte_000001.ig3.mp4"]
    leve = json.loads(subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                                      "stream=width,height,profile,pix_fmt", "-of", "json",
                                      str(tmp_path / "corte_000001.ig3.mp4")],
                                     capture_output=True, text=True).stdout)["streams"][0]
    assert (leve["width"], leve["height"], leve["profile"], leve["pix_fmt"]) == (720, 1280, "Main", "yuv420p")
    monkeypatch.setattr(instagram, "_publicar", lambda *a, **k: (_ for _ in ()).throw(
        instagram.FalhaProcessamento("de novo")))
    with pytest.raises(instagram.FalhaProcessamento):
        instagram.enviar(arq, "legenda", {"versao_api": "v21.0"})


def test_falha_do_instagram_volta_sozinha_mais_tarde(tmp_path, monkeypatch):
    from cortes import publicar
    from cortes.publicar import instagram

    cfg = _cfg(tmp_path)
    banco = Banco(tmp_path / "ig.db")
    arq = tmp_path / "c.mp4"
    arq.write_bytes(b"x")
    cid = banco.novo_corte(video_id="v", origem="vod", inicio=0, fim=30, nota=80, titulo="t",
                           descricao="d", hashtags=[], arquivo=arq)
    monkeypatch.setattr(instagram, "enviar", lambda *a, **k: (_ for _ in ()).throw(
        instagram.FalhaProcessamento("O Instagram não conseguiu processar o vídeo.")))
    corte = banco.corte(cid)
    for rodada in range(1, publicar.MAX_FALHAS_IG):
        assert not publicar.publicar_um(cfg, banco, corte, "ig")
        c = banco.corte(cid)
        assert c["ig_tentativas"] == 0 and "Nova tentativa automática às" in c["ig_erro"]
        assert publicar._esperar_ate[(cid, "ig")] > time.time() + 14 * 60   # espera, não insiste
    previsto = publicar.previsao(cfg, banco).get("ig", {}).get("cortes", {}).get(cid)
    assert previsto is None or previsto["motivo"] in {"nova_tentativa", "sem_conta", "desativada"}
    assert not publicar.publicar_um(cfg, banco, corte, "ig")                # última rodada
    assert banco.corte(cid)["ig_tentativas"] == 1 and "Desisti" in banco.corte(cid)["ig_erro"]
    monkeypatch.setattr(instagram, "enviar", lambda *a, **k: ("id9", "https://x"))
    assert publicar.publicar_um(cfg, banco, corte, "ig")                    # Publicar agora
    assert cid not in publicar._falhas_ig and (cid, "ig") not in publicar._esperar_ate


def test_restricao_de_idade_explicada_e_cookies(monkeypatch):
    from cortes import fontes

    erro = fontes.explicar_erro(RuntimeError("ERROR: [youtube] abc: Sign in to confirm your age. "
                                             "This video may be inappropriate for some users."))
    assert isinstance(erro, ValueError) and "restrição de idade" in str(erro)
    fontes.configurar({"fontes": {"cookies_navegador": "Firefox", "cookies_arquivo": ""}})
    assert fontes._opcoes_cookies() == {"cookiesfrombrowser": ("firefox",)}
    fontes.configurar({"fontes": {}})
    assert fontes._opcoes_cookies() == {}


def test_live_agendada_espera_e_comeca_sozinha(tmp_path, monkeypatch):
    from cortes import fontes, painel

    cfg = _cfg(tmp_path)
    banco = Banco(tmp_path / "e.db")
    servidor, ger = painel.criar(cfg, banco, "127.0.0.1", 0, str(tmp_path / "c.yaml"))
    servidor.server_close()
    respostas = [
        {"id": "L1", "titulo": "Live", "canal": "C", "canal_id": "", "url": "u", "duracao": 0,
         "ao_vivo": False, "agendada": time.time() - 5, "replay": []},          # na hora, mas não no ar
        {"id": "L1", "titulo": "Live", "canal": "C", "canal_id": "", "url": "u", "duracao": 0,
         "ao_vivo": True, "agendada": None, "replay": []}]
    monkeypatch.setattr(fontes, "info", lambda alvo: respostas.pop(0) if len(respostas) > 1 else respostas[0])
    iniciadas = []
    monkeypatch.setattr(ger, "_iniciar_live", lambda alvo, meta, entrada: iniciadas.append(meta["id"]))
    tarefa = {"id": "t9", "alvo": "https://www.youtube.com/watch?v=L1", "titulo": "", "canal": "",
              "teste": True, "origem": "manual", "status": "identificando", "etapa": "", "fracao": None,
              "erro": "", "video_id": "", "cortes": 0, "inicio": time.time(), "fim": None}
    ger.tarefas["t9"] = tarefa
    monkeypatch.setattr(ger, "_esperar_live", lambda t, **k: painel.Gerenciador._esperar_live(ger, t, verificar_a_cada=1))
    ger._identificar(tarefa, False)
    assert iniciadas == ["L1"] and "t9" not in ger.tarefas                 # começou sozinha
    # Cancelar a espera.
    tarefa2 = {**tarefa, "id": "t10", "status": "agendada", "inicio_live": time.time() + 3600}
    ger.tarefas["t10"] = tarefa2
    ger.controlar_tarefa("t10", "cancelar")
    painel.Gerenciador._esperar_live(ger, tarefa2)
    assert tarefa2["status"] == "cancelado"
    with pytest.raises(ValueError, match="só pode ser cancelada"):
        ger.tarefas["t11"] = {**tarefa, "id": "t11", "status": "agendada"}
        ger.controlar_tarefa("t11", "pausar")


def test_modo_manual_nada_entra_na_fila_sozinho(video, tmp_path):
    cfg = _cfg(tmp_path)
    cfg["publicar"]["manual"] = True                      # o padrão do programa
    cfg["cortes"].update(por_video=1, capa=False)
    cfg["ia"]["nota_minima"] = 0
    banco = Banco(tmp_path / "e.db")
    ids = vod.processar(str(video), cfg, banco)
    assert ids and banco.pendentes("yt") == [] and banco.pendentes("ig") == []
    c = banco.corte(ids[0])
    assert (c["yt_aguardando"], c["ig_aguardando"]) == (1, 1)


def test_limiar_menor_para_lives_de_gta():
    from cortes.live import limiar_da_live
    lv = {"limiar": 4.0, "limiar_menor": 3.0, "palavras_limiar_menor": "GTA, minecraft"}
    assert limiar_da_live("GTA 6 - O INICIO AO VIVO!", lv) == 3.0
    assert limiar_da_live("jogando Minecraft hardcore", lv) == 3.0
    assert limiar_da_live("Just chatting", lv) == 4.0
    assert limiar_da_live("GTA 6", {**lv, "palavras_limiar_menor": ""}) == 4.0


def test_chat_ao_vivo_le_as_mensagens_do_youtube():
    assert chat.id_do_video("https://www.youtube.com/watch?v=x50ONQrBPRM") == "x50ONQrBPRM"
    assert chat.id_do_video("https://youtu.be/08k8C6UTI7w?si=a") == "08k8C6UTI7w"
    assert chat.id_do_video("https://www.youtube.com/live/08k8C6UTI7w") == "08k8C6UTI7w"
    acoes = [
        {"addChatItemAction": {"item": {"liveChatTextMessageRenderer": {
            "timestampUsec": "1700000000000000", "message": {"runs": [{"text": "KKKKK que isso"}]}}}}},
        {"addChatItemAction": {"item": {"liveChatPaidMessageRenderer": {
            "timestampUsec": "1700000001000000", "message": {"runs": [{"text": "corta!"}]}}}}},
        {"addChatItemAction": {"item": {"liveChatViewerEngagementMessageRenderer": {}}}},
        {"markChatItemAsDeletedAction": {}},
    ]
    antigas = chat._mensagens_das_acoes(acoes)
    assert antigas == [(1700000000.0, "KKKKK que isso"), (1700000001.0, "corta!")]
    # mensagens novas contam na hora em que chegam (o YouTube manda em lotes)
    assert [t for t, _ in chat._mensagens_das_acoes(acoes, 123.0)] == [123.0, 123.0]


def test_pedacos_da_live_emendados_viram_um_arquivo(tmp_path):
    """Pedaços reais (5 s cada) baixados de uma live do YouTube desde o início."""
    from cortes import historico
    pedacos = sorted((Path(__file__).parent / "dados").glob("a_*.mp4"))
    assert len(pedacos) == 3
    junto = historico.juntar(pedacos, tmp_path / "junto.m4a")
    assert 14 <= len(sinais.volume_por_segundo(junto)) <= 15


class _RespostaTT:
    def __init__(self, dados, status=200):
        self._dados, self.status_code = dados, status
        self.content = b"1"

    def json(self):
        return self._dados


def _tiktok_conectado(tmp_path, monkeypatch):
    import json as _json
    from cortes.publicar import tiktok
    monkeypatch.setenv("TIKTOK_CLIENT_KEY", "chave-teste")
    monkeypatch.setenv("TIKTOK_CLIENT_SECRET", "segredo-teste")
    cfg = _cfg(tmp_path)
    cfg["publicar"]["tiktok"].update(ativo=True, token=str(tmp_path / "tt.json"))
    (tmp_path / "tt.json").write_text(_json.dumps({
        "access_token": "act.1", "refresh_token": "rft.1", "open_id": "u",
        "expira": time.time() + 3600, "refresh_expira": time.time() + 86400 * 300}))
    assert tiktok.conectado(cfg["publicar"]["tiktok"])
    return cfg


def test_tiktok_login_com_pkce_em_hexadecimal(monkeypatch):
    import hashlib
    from urllib.parse import parse_qs, urlsplit
    from cortes.publicar import tiktok
    monkeypatch.setenv("TIKTOK_CLIENT_KEY", "chave-teste")
    url, estado, verificador = tiktok.iniciar_login("http://localhost:8000/oauth/tiktok/")
    q = {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}
    assert url.startswith("https://www.tiktok.com/v2/auth/authorize/")
    assert q["client_key"] == "chave-teste" and q["state"] == estado
    assert q["scope"] == "user.info.basic,video.upload" and q["code_challenge_method"] == "S256"
    assert q["code_challenge"] == hashlib.sha256(verificador.encode()).hexdigest()
    assert 43 <= len(verificador) <= 128


def test_tiktok_partes_do_envio():
    from cortes.publicar import tiktok
    assert tiktok.partes(30 * 2**20) == (30 * 2**20, 1)          # cabe inteiro
    assert tiktok.partes(64 * 2**20) == (64 * 2**20, 1)
    tam, n = tiktok.partes(150 * 2**20)                             # em partes de 10 MB
    assert tam == 10 * 2**20 and n == 15


def test_tiktok_envia_para_a_caixa_de_entrada(tmp_path, monkeypatch):
    from cortes.publicar import tiktok
    cfg = _tiktok_conectado(tmp_path, monkeypatch)
    arq = tmp_path / "c.mp4"
    arq.write_bytes(b"v" * 1000)
    pedidos, envios = [], []

    def post(url, json=None, **k):
        pedidos.append((url, json))
        if url.endswith("/inbox/video/init/"):
            return _RespostaTT({"data": {"publish_id": "p_1", "upload_url": "https://up/x"},
                                "error": {"code": "ok"}})
        return _RespostaTT({"data": {"status": "SEND_TO_USER_INBOX"}, "error": {"code": "ok"}})

    def put(url, data=None, headers=None, **k):
        envios.append(headers["Content-Range"])
        return _RespostaTT({}, 201)

    monkeypatch.setattr(tiktok.requests, "post", post)
    monkeypatch.setattr(tiktok.requests, "put", put)
    assert tiktok.enviar(arq, cfg["publicar"]["tiktok"]) == ("p_1", "")
    assert pedidos[0][1] == {"source_info": {"source": "FILE_UPLOAD", "video_size": 1000,
                                             "chunk_size": 1000, "total_chunk_count": 1}}
    assert envios == ["bytes 0-999/1000"]


def test_tiktok_no_limite_volta_mais_tarde_sem_gastar_tentativa(tmp_path, monkeypatch):
    from cortes import publicar
    from cortes.publicar import tiktok
    cfg = _tiktok_conectado(tmp_path, monkeypatch)
    banco = Banco(tmp_path / "tt.db")
    arq = tmp_path / "c.mp4"
    arq.write_bytes(b"x")
    cid = banco.novo_corte(video_id="v", origem="vod", inicio=0, fim=30, nota=80, titulo="t",
                           descricao="d", hashtags=["gta"], arquivo=arq)
    comp = banco.novo_corte(video_id="v", origem="compilacao", inicio=0, fim=300, nota=80,
                            titulo="c", descricao="d", hashtags=[], arquivo=arq)
    assert [c["id"] for c in banco.pendentes("tt")] == [cid]       # compilação só no YouTube
    monkeypatch.setattr(tiktok.requests, "post", lambda *a, **k: _RespostaTT(
        {"error": {"code": "spam_risk_too_many_pending_share", "message": "limite"}}, 403))
    assert not publicar.publicar_um(cfg, banco, banco.corte(cid), "tt")
    c = banco.corte(cid)
    assert c["tt_tentativas"] == 0 and "Nova tentativa às" in c["tt_erro"]
    assert publicar._esperar_ate[(cid, "tt")] > time.time() + 50 * 60
    monkeypatch.setattr(tiktok, "enviar", lambda *a, **k: ("p_9", ""))
    assert publicar.publicar_um(cfg, banco, banco.corte(cid), "tt")
    assert banco.corte(cid)["tt_id"] == "p_9" and (cid, "tt") not in publicar._esperar_ate
    assert not banco.remover_corte(cid)                               # já foi para o TikTok
    assert banco.remover_corte(comp)


def test_tiktok_renova_o_acesso_vencido(tmp_path, monkeypatch):
    import json as _json
    from cortes.publicar import tiktok
    cfg = _tiktok_conectado(tmp_path, monkeypatch)
    caminho = tmp_path / "tt.json"
    dados = _json.loads(caminho.read_text())
    dados["expira"] = time.time() - 10
    caminho.write_text(_json.dumps(dados))
    pedidos = []

    def post(url, data=None, **k):
        pedidos.append(data)
        return _RespostaTT({"access_token": "act.2", "refresh_token": "rft.2", "expires_in": 86400,
                            "refresh_expires_in": 31536000, "open_id": "u", "scope": "video.upload"})

    monkeypatch.setattr(tiktok.requests, "post", post)
    assert tiktok._token(cfg["publicar"]["tiktok"]) == "act.2"
    assert pedidos[0]["grant_type"] == "refresh_token" and pedidos[0]["refresh_token"] == "rft.1"
    assert _json.loads(caminho.read_text())["access_token"] == "act.2"


def test_descarte_mostra_a_nota_quando_a_ia_aprova_mas_abaixo_da_minima():
    from cortes.ia import motivo_descarte
    assert motivo_descarte({"aprovado": True, "nota": 65, "motivo": "conflito claro"}, 70) == \
        "nota 65, abaixo da mínima (70). conflito claro"
    assert motivo_descarte({"aprovado": False, "nota": 30, "motivo": "morno"}, 70).startswith(
        "reprovado pela IA (nota 30)")
    assert motivo_descarte({"aprovado": True, "nota": 50, "validado_local": True}, 70) == ""
    assert motivo_descarte({"aprovado": True, "nota": 80}, 70) == ""
    assert motivo_descarte(None, 70) == "a IA não respondeu"


def test_live_retomada_continua_de_onde_parou(tmp_path):
    """Programa fechado no meio da live: ao reabrir, cartão, cortes e o que já foi visto
    continuam; a segunda frente só procura no que ninguém viu."""
    from cortes import historico
    cfg = _cfg(tmp_path)
    banco = Banco(tmp_path / "e.db")
    meta = {"id": "sim", "titulo": "GTA de teste", "canal": "Canal", "url": ""}
    entrada = ["-re", "-f", "lavfi", "-i", "testsrc2=s=320x240:r=15", "-f", "lavfi", "-i",
               "sine=f=330", "-c:v", "libx264", "-preset", "ultrafast", "-g", "30", "-c:a", "aac"]
    m1 = MonitorLive("sim", cfg, banco, meta=dict(meta), entrada_ffmpeg=entrada, chat=ChatFalso())
    m1.estado["picos"].append({"hora": time.time(), "nota": 5.5, "resultado": "Recortando…"})
    cid = banco.novo_corte(video_id="sim", origem="live", inicio=0, fim=20, nota=80, titulo="t",
                           descricao="d", hashtags=[], arquivo=tmp_path / "x.mp4")
    (m1.pasta / "passado" / "a").mkdir(parents=True)
    (m1.pasta / "passado" / "a" / "a_0000001.mp4").write_bytes(b"x")
    m1.progresso.marcar_avaliado(100, 110)
    m1.rodar(duracao_max=6)                      # "fecha o programa" (não é fim da live)
    assert (m1.pasta / "passado" / "a" / "a_0000001.mp4").exists()   # áudio baixado fica
    inicio1, cobertura1 = m1.estado["inicio"], m1.progresso.d["cobertura"][-1]
    assert cobertura1[1] - cobertura1[0] >= 4

    m2 = MonitorLive("sim", cfg, banco, meta=dict(meta), entrada_ffmpeg=entrada, chat=ChatFalso())
    assert m2.estado["inicio"] == inicio1 and m2.cortes == [cid]
    assert m2.estado["picos"][0]["nota"] == 5.5 and "Interrompido" in m2.estado["picos"][0]["resultado"]
    assert m2.progresso.avaliado(105) and not m2.progresso.avaliado(110)
    # A busca no passado ignora o que a frente ao vivo já viu e o que já foi avaliado.
    frente = historico.AnalisePassado(m2)
    agora_sq, frag = 200, 5.0
    seq = list(range(80, 200))                    # 10 min de pedaços de 5 s
    relogio = cobertura1[1] + 10                  # o "agora" logo depois de reabrir
    # pedaços cobertos pela frente ao vivo: os de relógio entre cobertura1[0] e cobertura1[1]
    pont = frente._sem_o_que_ja_foi_visto(np.ones(len(seq) * 5), seq, frag, agora_sq, relogio)
    def valor(sq):
        return pont[(sq - 80) * 5]
    assert valor(105) == 0                        # já avaliado
    assert valor(198) == 0                        # tempo em que a frente ao vivo acompanhava
    assert valor(150) == 1                        # ninguém viu: entra na busca
    m2.parado_pelo_usuario = True                 # parar de vez apaga os pedaços de áudio
    m2.rodar(duracao_max=3)
    assert not (m2.pasta / "passado").exists()


def test_limite_diario_do_youtube_espera_sem_gastar_tentativa(tmp_path, monkeypatch):
    from cortes import publicar
    from cortes.publicar import youtube
    cfg = _cfg(tmp_path)
    banco = Banco(tmp_path / "yt.db")
    arq = tmp_path / "c.mp4"
    arq.write_bytes(b"x")
    cid = banco.novo_corte(video_id="v", origem="vod", inicio=0, fim=30, nota=80, titulo="t",
                           descricao="d", hashtags=[], arquivo=arq)
    monkeypatch.setattr(youtube, "enviar", lambda *a, **k: (_ for _ in ()).throw(RuntimeError(
        "<HttpError 400 ... 'reason': 'uploadLimitExceeded'>")))
    assert not publicar.publicar_um(cfg, banco, banco.corte(cid), "yt")
    c = banco.corte(cid)
    assert c["yt_tentativas"] == 0 and "limite diário de envios" in c["yt_erro"]
    assert publicar._esperar_ate[(cid, "yt")] > time.time() + 110 * 60
    publicar._esperar_ate.pop((cid, "yt"), None)


class _RespostaTexto:
    def __init__(self, texto="", dados=None, conteudo=b""):
        self.text, self._dados, self.content, self.status_code = texto, dados, conteudo, 200

    def json(self):
        return self._dados


def test_twitch_fonte_do_passado_e_cabecalho(tmp_path, monkeypatch):
    from cortes import historico
    lista = ("#EXTM3U\n#EXT-X-TARGETDURATION:10\n#EXT-X-PLAYLIST-TYPE:EVENT\n"
             '#EXT-X-MAP:URI="init-0.mp4"\n#EXTINF:10.000,\n0.mp4\n#EXTINF:10.000,\n1.mp4\n'
             "#EXTINF:10.000,\n2-muted.mp4\n")

    def post(url, json=None, **k):
        return _RespostaTexto(dados={"data": {"user": {"stream": {"archiveVideo": {"id": "999", "status": "RECORDING"}}}}})

    def get(url, **k):
        if url.endswith(".m3u8"):
            return _RespostaTexto(texto=lista)
        return _RespostaTexto(conteudo=b"INIT" if "init" in url else b"SEG")

    class Ydl:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def extract_info(self, url, download=False):
            assert url == "https://www.twitch.tv/videos/999"
            return {"formats": [
                {"format_id": "Audio_Only", "vcodec": "none", "url": "https://cdn/x/audio_only/index.m3u8"},
                {"format_id": "720p60", "vcodec": "avc1", "height": 720, "url": "https://cdn/x/720p60/index.m3u8"},
                {"format_id": "1080p60", "vcodec": "avc1", "height": 1080, "url": "https://cdn/x/1080p60/index.m3u8"}]}

    monkeypatch.setattr(historico.requests, "post", post)
    monkeypatch.setattr(historico.requests, "get", get)
    monkeypatch.setattr(historico.fontes, "_ydl", lambda *a, **k: Ydl())
    historico._cabecalhos.clear()
    f = historico.fonte_do_passado("https://www.twitch.tv/Alanzoka", 720)
    assert isinstance(f, historico.FonteTwitch) and f.video_com_audio and f.frag == 10.0
    assert f.cabeca() == 3
    assert f.url("a", 2) == "https://cdn/x/audio_only/2-muted.mp4"       # trecho silenciado
    assert f.url("v", 0) == "https://cdn/x/720p60/0.mp4"                  # melhor até 720
    assert f.init("v", 1) == "https://cdn/x/720p60/init-0.mp4"
    pedacos = []
    for i in range(3):
        arq = tmp_path / f"v_{i:07d}.mp4"
        arq.write_bytes(b"SEG")
        pedacos.append(arq)
    junto = historico.juntar(pedacos, tmp_path / "j.mp4", f, "v")
    assert junto.read_bytes() == b"INITSEGSEGSEG"                          # cabeçalho uma vez só
    assert historico.login_twitch("https://www.twitch.tv/alanzoka?x=1") == "alanzoka"
    assert isinstance(historico.fonte_do_passado.__call__, object)


def test_twitch_chat_e_canal_seguido(monkeypatch):
    from cortes import fontes
    assert isinstance(chat.para_live("https://www.twitch.tv/alanzoka", "123"), chat.ChatTwitch)
    assert chat.para_live("https://www.twitch.tv/alanzoka", "123").canal == "alanzoka"
    assert type(chat.para_live("https://www.youtube.com/watch?v=x50ONQrBPRM", "x50ONQrBPRM")) is chat.ChatAoVivo
    assert fontes._canal_twitch({"extractor": "twitch:stream", "uploader_id": "Alanzoka"}, "") == "twitch:alanzoka"
    assert fontes._canal_twitch({}, "https://www.youtube.com/watch?v=x") == ""
    import requests
    respostas = [{"data": {"user": {"displayName": "alanzoka", "stream": {"id": "319", "title": "GTA", "viewersCount": 9}}}},
                 {"data": {"user": {"displayName": "alanzoka", "stream": None}}}]
    monkeypatch.setattr(requests, "post", lambda *a, **k: _RespostaTexto(dados=respostas.pop(0)))
    achados = fontes._do_canal("twitch:alanzoka", 5)
    assert achados == [{"id": "319", "url": "https://www.twitch.tv/alanzoka", "titulo": "GTA",
                        "canal": "alanzoka", "canal_id": "twitch:alanzoka", "ao_vivo": True, "audiencia": 9}]
    assert fontes._do_canal("twitch:alanzoka", 5) == []                  # fora do ar


def test_limite_do_instagram_espera_sem_gastar_tentativa(tmp_path, monkeypatch):
    from cortes import publicar
    from cortes.publicar import instagram
    cfg = _cfg(tmp_path)
    banco = Banco(tmp_path / "ig2.db")
    arq = tmp_path / "c.mp4"
    arq.write_bytes(b"x")
    cid = banco.novo_corte(video_id="v", origem="live", inicio=0, fim=30, nota=80, titulo="t",
                           descricao="d", hashtags=[], arquivo=arq)
    monkeypatch.setattr(instagram, "enviar", lambda *a, **k: (_ for _ in ()).throw(RuntimeError(
        "Instagram 400: (#9) Application request limit reached")))
    assert not publicar.publicar_um(cfg, banco, banco.corte(cid), "ig")
    c = banco.corte(cid)
    assert c["ig_tentativas"] == 0 and "limite de publicações" in c["ig_erro"]
    publicar._esperar_ate.pop((cid, "ig"), None)
    # Um erro qualquer (ex.: taxa de quadros) continua contando como falha.
    monkeypatch.setattr(instagram, "enviar", lambda *a, **k: (_ for _ in ()).throw(RuntimeError(
        "Instagram 400: unsupported frame rate")))
    assert not publicar.publicar_um(cfg, banco, banco.corte(cid), "ig")
    assert banco.corte(cid)["ig_tentativas"] == 1


def test_live_corrige_audio_que_comeca_depois_do_video(tmp_path):
    """Vídeo e áudio separados começando em pontos diferentes da transmissão (na live do
    Cellbit, 5 s): o som do segundo X tem de continuar no segundo X da imagem."""
    from cortes import fontes
    v, a = tmp_path / "v.ts", tmp_path / "a.ts"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=320x240:r=30", "-t", "30",
                    "-c:v", "libx264", "-preset", "ultrafast", "-g", "30", "-output_ts_offset", "100", str(v)],
                   check=True)
    # bipe aos 110 s do relógio da transmissão = 10 s depois do começo da imagem
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
                    "aevalsrc='if(between(t,5,5.3),sin(2*PI*880*t),0)':s=48000", "-t", "25",
                    "-c:a", "aac", "-output_ts_offset", "105", str(a)], check=True)
    cfg = _cfg(tmp_path)
    meta = {"id": "defasada", "titulo": "t", "canal": "c", "url": ""}
    m = MonitorLive("x", cfg, Banco(tmp_path / "d.db"), meta=meta, chat=ChatFalso(),
                    entrada_ffmpeg=fontes.entrada_ffmpeg_live([str(v), str(a)]))
    m._iniciar_captura().wait(timeout=120)
    assert abs(m._defasagem(1) - 5.0) < 0.1
    midia = m._midia()
    pedido = {"a": time.time(), "ma": 0.0, "mb": 20.0, "geracao": 1, "nota": 9,
              "pico": {"resultado": ""}, "mensagens": []}
    m._produzir = lambda p: None
    m._recortar(pedido, midia)
    o = subprocess.run(["ffmpeg", "-i", str(pedido["bruto"]), "-af", "silencedetect=n=-30dB:d=0.1", "-f", "null", "-"],
                       capture_output=True, text=True).stderr
    bipe = [float(l.split("silence_end: ")[1].split()[0]) for l in o.splitlines() if "silence_end" in l][0]
    assert abs(bipe - 10.0) < 0.3, bipe
    m._fechar_registro()


def test_erros_do_youtube_diferenciados():
    """Cada bloqueio do YouTube tem a sua explicação: não é tudo "restrição de idade"."""
    from cortes import fontes

    def msg(erro, avisos=()):
        return str(fontes.explicar_erro(RuntimeError(erro), avisos))

    # nov/2026: player novo, yt-dlp antigo não resolvia o desafio JS e sobrava "sem formatos"
    js = ['[youtube] [jsc] Error solving n challenge request using "deno" provider: TypeError',
          "[youtube] abc: n challenge solving failed: Some formats may be missing."]
    assert "desafio JavaScript" in msg("[youtube] abc: No video formats found!", js)
    assert msg("[youtube] abc: Requested format is not available", js).startswith("O YouTube mudou o player")
    assert "restrição de idade" in msg("Sign in to confirm your age. This video may be inappropriate")
    assert "robô" in msg("Sign in to confirm you're not a bot. Use --cookies-from-browser")
    assert "privado" in msg("ERROR: [youtube] abc: Private video. Sign in if you've been granted access")
    assert "removido" in msg("ERROR: [youtube] abc: Video unavailable. This video has been removed")
    assert "Firefox" in msg("Could not copy Chrome cookie database. See https://github.com/...")
    assert "Firefox" in msg("Failed to decrypt with DPAPI")
    assert "processando" in msg("[youtube] abc: Requested format is not available")
    outro = RuntimeError("HTTP Error 500")
    assert fontes.explicar_erro(outro) is outro


def test_info_sem_formatos_explica_pelo_aviso(monkeypatch):
    """Sem formatos e sem restrição de idade nos dados: a explicação vem dos avisos do yt-dlp."""
    from cortes import fontes

    class YdlFalso:
        def __init__(self):
            self.avisos = []

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def extract_info(self, alvo, download=False):
            self.avisos.append("[youtube] x: n challenge solving failed: Some formats may be missing.")
            return {"id": "x", "formats": [{"vcodec": "none", "acodec": "none"}], "age_limit": 0}

    monkeypatch.setattr(fontes, "_ydl", lambda opcoes: YdlFalso())
    with pytest.raises(ValueError, match="desafio JavaScript"):
        fontes.info("https://www.youtube.com/watch?v=dmuDVzxFeVs")


def test_tentar_de_novo_reenvia_com_as_mesmas_opcoes(tmp_path, monkeypatch):
    from cortes import painel

    ger = painel.Gerenciador(_cfg(tmp_path), Banco(tmp_path / "r.db"))
    enviados = []
    monkeypatch.setattr(ger, "enviar", lambda alvo, teste, como_live=False, origem="manual",
                        permitir_arquivo=True: enviados.append((alvo, teste, como_live, origem, permitir_arquivo)))
    base = {"titulo": "", "canal": "", "etapa": "", "fracao": None, "video_id": "", "cortes": 0,
            "fim": None}
    ger.tarefas.update({
        "t1": {**base, "id": "t1", "alvo": "https://youtu.be/a", "teste": True, "origem": "manual",
               "como_live": False, "status": "erro", "erro": "x", "inicio": 1},
        "t2": {**base, "id": "t2", "alvo": "https://youtu.be/b", "teste": False, "origem": "canal",
               "como_live": True, "status": "erro", "erro": "x", "inicio": 2},
        "t3": {**base, "id": "t3", "alvo": "https://youtu.be/c", "teste": False, "origem": "manual",
               "status": "rodando", "erro": "", "inicio": 3}})
    ger.acao("tarefa/tentar_de_novo", {"id": "t1"}, True)
    assert enviados == [("https://youtu.be/a", True, False, "manual", True)] and "t1" not in ger.tarefas
    with pytest.raises(ValueError, match="não está mais com erro"):
        ger.tentar_de_novo("t3")
    with pytest.raises(ValueError, match="não está mais com erro"):
        ger.tentar_de_novo("t1")                                   # clique duplo
    r = ger.acao("tarefa/tentar_todas", {}, False)
    assert "1 análise enviada" in r["mensagem"]
    assert enviados[-1] == ("https://youtu.be/b", False, True, "canal", False) and "t3" in ger.tarefas
    with pytest.raises(ValueError, match="Nenhuma análise com erro"):
        ger.acao("tarefa/tentar_todas", {}, True)


def test_video_removido_pelos_avisos_e_longo_demais(tmp_path, monkeypatch):
    from cortes import fontes, painel

    # Link inexistente: o "unavailable" só aparece nos avisos; o erro final é "sem formatos".
    erro = fontes.explicar_erro(RuntimeError("Requested format is not available"),
                                ["[youtube] This video is unavailable", "No video formats found!"])
    assert "removido" in str(erro)
    # Vídeo mais longo que o limite: erro explicado no cartão (antes: "Concluído" sem nada).
    ger = painel.Gerenciador(_cfg(tmp_path), Banco(tmp_path / "l.db"))
    ger.cfg["fontes"]["duracao_max_h"] = 6
    monkeypatch.setattr(fontes, "info", lambda alvo: {
        "id": "L", "titulo": "Live longa", "canal": "C", "canal_id": "", "url": alvo,
        "duracao": 6.1 * 3600, "ao_vivo": False, "agendada": None, "replay": []})
    t = ger.enviar("https://www.youtube.com/watch?v=lzuEsAY_TEc", True)
    for _ in range(100):
        if t["status"] == "erro":
            break
        time.sleep(0.05)
    assert t["status"] == "erro" and "6.1 h" in t["erro"] and "Vídeo mais longo aceito" in t["erro"]


def test_modelo_nvidia_fora_do_ar_troca_sozinho(monkeypatch):
    """Modelo retirado do catálogo (410): passa para o próximo que vê imagens, em vez de cair
    nas notas pelas métricas (25/11/2026: Gemma 4 saiu do ar e as notas viraram 99)."""
    import requests
    from cortes import ia

    pedidos = []

    class Resp:
        def __init__(self, status, corpo):
            self.status_code, self._corpo, self.text = status, corpo, json.dumps(corpo)

        def json(self):
            return self._corpo

    def post(url, json=None, **k):
        pedidos.append(json["model"])
        if json["model"] == "google/gemma-4-31b-it":
            return Resp(410, {"detail": "has reached its end of life"})
        return Resp(200, {"choices": [{"finish_reason": "stop", "message": {"content": '{"ok": true}'}}]})

    monkeypatch.setattr(requests, "post", post)
    monkeypatch.setattr(ia, "_substituto", {})
    esquema = {"type": "object", "required": ["ok"]}
    conteudo = [{"type": "text", "text": "oi"}]
    assert ia._pedir_compativel("google/gemma-4-31b-it", "s", conteudo, esquema, ia.PROVEDORES["nvidia"]) == {"ok": True}
    assert pedidos == ["google/gemma-4-31b-it", ia.SUBSTITUTOS_NVIDIA[0]]
    ia._pedir_compativel("google/gemma-4-31b-it", "s", conteudo, esquema, ia.PROVEDORES["nvidia"])
    assert pedidos[-1] == ia.SUBSTITUTOS_NVIDIA[0]                        # lembra a troca
