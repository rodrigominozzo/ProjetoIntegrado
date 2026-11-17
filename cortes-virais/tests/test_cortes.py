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
    assert yaml.safe_load(arq.read_text())["live"]["limiar"] == 4.5
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
    ass = (tmp_path / "c.ass").read_text()
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
    ass = (tmp_path / "v" / "corte_000060.ass").read_text()
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
