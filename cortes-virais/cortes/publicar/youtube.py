"""Upload para o YouTube (Shorts) pela YouTube Data API v3 com OAuth."""
from __future__ import annotations

from pathlib import Path

ESCOPOS = ["https://www.googleapis.com/auth/youtube.upload",
           "https://www.googleapis.com/auth/youtube.readonly"]  # leitura: medir visualizações


def _credenciais(cfg_yt: dict, interativo: bool = False):
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    token = Path(cfg_yt["token"])
    cred = Credentials.from_authorized_user_file(str(token), ESCOPOS) if token.exists() else None
    if cred and cred.expired and cred.refresh_token:
        cred.refresh(Request())
        token.write_text(cred.to_json())
    if cred and cred.valid:
        return cred
    if not interativo:
        raise RuntimeError("YouTube não autorizado. Rode: python -m cortes login-youtube")
    from google_auth_oauthlib.flow import InstalledAppFlow

    fluxo = InstalledAppFlow.from_client_secrets_file(cfg_yt["client_secret"], ESCOPOS)
    cred = fluxo.run_local_server(port=0, open_browser=False)
    token.write_text(cred.to_json())
    return cred


def login(cfg_yt: dict) -> None:
    _credenciais(cfg_yt, interativo=True)


def enviar(arquivo: str | Path, titulo: str, descricao: str, hashtags: list[str],
           cfg_yt: dict) -> str:
    """Envia o vídeo e devolve o ID. Vertical com menos de 3 min vira Short sozinho."""
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload

    yt = build("youtube", "v3", credentials=_credenciais(cfg_yt), cache_discovery=False)
    titulo = titulo if "#shorts" in titulo.lower() or len(titulo) > 91 else f"{titulo} #shorts"
    pedido = yt.videos().insert(
        part="snippet,status",
        body={
            "snippet": {"title": titulo[:100], "description": descricao[:4900],
                        "tags": hashtags, "categoryId": str(cfg_yt["categoria"])},
            "status": {"privacyStatus": cfg_yt["privacidade"],
                       "selfDeclaredMadeForKids": False},
        },
        media_body=MediaFileUpload(str(arquivo), mimetype="video/mp4", resumable=True,
                                   chunksize=8 * 1024 * 1024),
    )
    resposta = None
    while resposta is None:
        _, resposta = pedido.next_chunk(num_retries=4)
    return resposta["id"]
