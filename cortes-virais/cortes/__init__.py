"""Cortes Virais — detecção, corte e publicação automática de momentos de lives e vídeos."""
import subprocess
import sys


def _sem_janelas_no_windows() -> None:
    """Aberto pelo atalho (pythonw, sem console), cada ffmpeg/ffprobe/yt-dlp que o programa
    chama abriria uma janela de prompt que pisca e some: numa análise são centenas. Aqui todo
    processo filho passa a nascer sem janela, inclusive os que o yt-dlp cria por conta própria.
    Rodando num terminal (python -m cortes ...), nada muda e a saída continua aparecendo nele."""
    if sys.platform != "win32" or not sys.executable.lower().endswith("pythonw.exe"):
        return
    original = subprocess.Popen.__init__
    if getattr(original, "_sem_janela", False):
        return

    def iniciar(self, *args, **kwargs):
        kwargs["creationflags"] = kwargs.get("creationflags", 0) | subprocess.CREATE_NO_WINDOW
        original(self, *args, **kwargs)

    iniciar._sem_janela = True
    subprocess.Popen.__init__ = iniciar


_sem_janelas_no_windows()
