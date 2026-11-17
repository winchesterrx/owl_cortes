"""Utilitários compartilhados pelo clipper: pastas, tempo, Whisper e chamadas de programas."""
import json
import os
import re
import shutil
import subprocess
import sys
import unicodedata
from pathlib import Path

AQUI = Path(__file__).resolve().parent
if len(AQUI.parents) > 3 and AQUI.parents[3].name in (".agents", ".agent", "_agents", "_agent"):
    WORKSPACE = AQUI.parents[4]
else:
    WORKSPACE = Path.cwd()

CASA = Path(os.environ.get("CLIPPER_HOME", WORKSPACE / ".clipper"))
TRABALHO = CASA / "trabalho"   # áudio, transcrição e trechos de cada live
MODELOS = CASA / "modelos"     # detector de rosto (baixado no instalar)
CORTES = Path(os.environ.get("CLIPPER_CORTES_DIR", WORKSPACE / "cortes"))
YOUTUBE_POTENCIAL = Path(os.environ.get("CLIPPER_YOUTUBE_DIR", WORKSPACE / "YOUTUBE-POTENCIAL"))
YUNET = MODELOS / "face_detection_yunet_2023mar.onnx"
YUNET_URL = (
    "https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/"
    "face_detection_yunet_2023mar.onnx"
)
BLOCO_MIN = 12  # a IA lê a transcrição em blocos de 12 minutos


def configurar_utf8():
    """Garante saída UTF-8 nos consoles Windows sem falhar com acentos ou emojis."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


def slug(texto, limite=60):
    """Converte um texto arbitrário em identificador seguro para nomes de pasta."""
    t = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    t = re.sub(r"[^A-Za-z0-9]+", "-", t).strip("-").lower()
    return t[:limite].strip("-") or "live"


def hms(seg):
    """Formata segundos como HH:MM:SS."""
    seg = max(0, int(round(seg)))
    return f"{seg // 3600:02d}:{seg % 3600 // 60:02d}:{seg % 60:02d}"


def segundos(valor):
    """Aceita 3723, '3723', '1:02:03' ou '62:03' e devolve float em segundos."""
    if isinstance(valor, (int, float)):
        return float(valor)
    partes = [float(p) for p in str(valor).strip().split(":")]
    total = 0.0
    for p in partes:
        total = total * 60 + p
    return total


def rodar(cmd, **kw):
    """Executa um comando externo exibindo um resumo e falhando se retornar erro."""
    print("  $", " ".join(str(c) for c in cmd[:6]), "…" if len(cmd) > 6 else "", flush=True)
    return subprocess.run([str(c) for c in cmd], check=True, **kw)


def rodar_captura(cmd, check=False, **kw):
    """Executa um comando capturando stdout/stderr sempre em UTF-8."""
    return subprocess.run(
        [str(c) for c in cmd],
        check=check,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        **kw,
    )


def tem(programa):
    """Verifica se um executável está disponível no PATH."""
    return shutil.which(programa) is not None


def ffmpeg_embutido():
    """Sem ffmpeg no sistema, usa os binários do pacote static-ffmpeg."""
    if tem("ffmpeg") and tem("ffprobe"):
        return True
    try:
        import static_ffmpeg
        static_ffmpeg.add_paths(weak=True)
    except Exception:
        return False
    return tem("ffmpeg") and tem("ffprobe")


def ytdlp():
    """Retorna o comando base do yt-dlp do ambiente atual, com runtime JS se disponível."""
    local = Path(sys.executable).parent / ("yt-dlp.exe" if os.name == "nt" else "yt-dlp")
    cmd = [str(local)] if local.exists() else [sys.executable, "-m", "yt_dlp"]
    if tem("deno") or tem("node"):
        cmd += ["--js-runtimes", "deno" if tem("deno") else "node"]
    return cmd


def carregar_audio_16k(caminho):
    """Decodifica áudio/vídeo para array float32 mono 16 kHz sem depender do PyAV."""
    import wave
    import numpy as np

    p = Path(caminho)
    if p.suffix.lower() == ".wav":
        with wave.open(str(p), "rb") as f:
            if f.getnchannels() == 1 and f.getframerate() == 16000 and f.getsampwidth() == 2:
                return np.frombuffer(f.readframes(f.getnframes()), dtype=np.int16).astype(np.float32) / 32768.0
    r = subprocess.run(
        [
            "ffmpeg", "-nostdin", "-loglevel", "error", "-threads", "0",
            "-i", str(p), "-f", "s16le", "-ac", "1", "-acodec", "pcm_s16le", "-ar", "16000", "-",
        ],
        capture_output=True,
        check=True,
    )
    return np.frombuffer(r.stdout, dtype=np.int16).astype(np.float32) / 32768.0


def carregar_whisper(modelo):
    """Carrega o faster-whisper usando GPU CUDA se disponível, senão CPU int8."""
    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
    from faster_whisper import WhisperModel
    try:
        import ctranslate2
        if ctranslate2.get_cuda_device_count() > 0:
            return WhisperModel(modelo, device="cuda", compute_type="float16")
    except Exception:
        pass
    return WhisperModel(modelo, device="cpu", compute_type="int8")


def ler_json(caminho, padrao=None):
    """Lê JSON em UTF-8 devolvendo `padrao` se não existir ou estiver inválido."""
    try:
        return json.loads(Path(caminho).read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return padrao


def gravar_json(caminho, dados):
    """Grava JSON formatado em UTF-8 criando diretórios pai automaticamente."""
    Path(caminho).parent.mkdir(parents=True, exist_ok=True)
    Path(caminho).write_text(json.dumps(dados, ensure_ascii=False, indent=1), encoding="utf-8")


def pasta_da_live(nome):
    """Localiza a pasta de trabalho pelo nome exato, trecho do nome ou URL."""
    if (TRABALHO / nome).is_dir():
        return TRABALHO / nome
    if TRABALHO.exists():
        for p in sorted(TRABALHO.glob("*")):
            info = ler_json(p / "info.json", {})
            if nome in (info.get("url"), info.get("webpage_url")) or nome.lower() in p.name:
                return p
    sys.exit(f"Não achei a live '{nome}' em {TRABALHO}. Rode antes: clip.py preparar LINK")


def pasta_youtube_da_live(canal, live_nome):
    """Retorna YOUTUBE-POTENCIAL/<streamer>/<live>/ evitando prefixo repetido do canal."""
    streamer_dir = slug(canal or "geral", limite=40) or "geral"
    prefixo = f"{streamer_dir}-"
    live_dir = live_nome[len(prefixo):] if live_nome.startswith(prefixo) and len(live_nome) > len(prefixo) else live_nome
    return YOUTUBE_POTENCIAL / streamer_dir / (live_dir or live_nome)

