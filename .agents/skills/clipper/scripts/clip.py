#!/usr/bin/env python3
"""Clipper de Lives: transforma lives longas em cortes verticais prontos pra postar.

Comandos:
  clip.py instalar                          confere e instala tudo que falta
  clip.py buscar [TERMOS...] [--gta6]       acha as maiores lives de hoje no YouTube
  clip.py baixar LINK [LINK...]             baixa só áudio e chat (rede)
  clip.py processar LIVE [--modelo base]    transcreve, marca picos e gera blocos (offline)
  clip.py preparar LINK [LINK...]           executa baixar + processar
  clip.py escolher LIVE [--manter 3]        junta as notas e fica com os melhores momentos
  clip.py fazer LIVE [--so-baixar]          monta os cortes verticais (Shorts/Reels/TikTok)
  clip.py potencial [LIVE]                  lista lives com potencial para vídeo longo no YouTube
  clip.py youtube LIVE [--videos 1 ...]     gera vídeos longos 16:9 (1080p + thumb) em YOUTUBE-POTENCIAL/
  clip.py status                            mostra em que passo cada live está
"""
import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import quote_plus

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI))
from comum import (  # noqa: E402
    CASA,
    CORTES,
    MODELOS,
    TRABALHO,
    YUNET,
    YUNET_URL,
    configurar_utf8,
    ffmpeg_embutido,
    hms,
    ler_json,
    pasta_da_live,
    rodar_captura,
    tem,
    ytdlp,
)

VENV = CASA / "ambiente"
VENV_PY = VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
PACOTES = ["faster-whisper", "opencv-python-headless", "numpy", "pillow", "yt-dlp[default]", "certifi", "static-ffmpeg"]

GTA6 = re.compile(r"gta\s*-?\s*(6|vi)(?![0-9a-z])", re.IGNORECASE)
GTA5 = re.compile(r"gta\s*-?\s*(5|v|iv|4|rp)(?![0-9a-z])", re.IGNORECASE)


def no_ambiente():
    """Roda sempre com o Python do próprio clipper sem perder o processo pai no Windows."""
    if VENV_PY.exists() and Path(sys.prefix).resolve() != VENV.resolve() and sys.argv[1:2] != ["instalar"]:
        raise SystemExit(subprocess.call([str(VENV_PY), __file__, *sys.argv[1:]]))


def instalar(_):
    """Cria o ambiente virtual, instala pacotes, baixa YuNet e pré-baixa modelos Whisper."""
    print("Conferindo o que o computador precisa…\n")
    falta = []
    if sys.version_info < (3, 10):
        falta.append("python")
        print(f"  ✗ Python {sys.version.split()[0]} é antigo. Precisa do 3.10 ou mais novo.")
        if os.name == "nt":
            print("      Instale com:  winget install -e --id Python.Python.3.12 --scope user")
        else:
            print("      Baixe em https://www.python.org/downloads/ e abra o instalador.")
    else:
        print(f"  ✓ Python {sys.version.split()[0]}")

    if "python" not in falta:
        if not VENV_PY.exists():
            print("  … criando o ambiente do clipper em", VENV)
            subprocess.run([sys.executable, "-m", "venv", str(VENV)], check=True)
        print("  … instalando pacotes:", ", ".join(PACOTES))
        subprocess.run([str(VENV_PY), "-m", "pip", "install", "-q", "--upgrade", "pip"], check=True)
        subprocess.run([str(VENV_PY), "-m", "pip", "install", "-q", "--upgrade", *PACOTES], check=True)
        subprocess.run([str(VENV_PY), "-m", "pip", "install", "-q", "--upgrade", "--pre", "yt-dlp[default]"], check=True)
        print("  ✓ pacotes do Python")
        if tem("ffmpeg") and tem("ffprobe"):
            print("  ✓ ffmpeg e ffprobe")
        else:
            print("  … baixando o ffmpeg (uma vez só)")
            r = subprocess.run([
                str(VENV_PY), "-c",
                "import sys,static_ffmpeg,shutil;static_ffmpeg.add_paths();"
                "sys.exit(0 if shutil.which('ffmpeg') and shutil.which('ffprobe') else 1)",
            ])
            if r.returncode == 0:
                print("  ✓ ffmpeg")
            else:
                falta.append("ffmpeg")
                print("  ✗ não consegui baixar o ffmpeg. Confira a internet e rode novamente.")

    if not YUNET.exists():
        print("  … baixando o detector de rosto (OpenCV YuNet, 0,2 MB)")
        MODELOS.mkdir(parents=True, exist_ok=True)
        if tem("curl"):
            subprocess.run(["curl", "-fsSL", "-o", str(YUNET), YUNET_URL], check=True)
        else:
            subprocess.run([
                str(VENV_PY), "-c",
                "import sys,ssl,certifi,urllib.request as u;"
                "c=ssl.create_default_context(cafile=certifi.where());"
                "open(sys.argv[2],'wb').write(u.urlopen(sys.argv[1],context=c).read())",
                YUNET_URL, str(YUNET),
            ], check=True)
    print("  ✓ detector de rosto")

    if "python" not in falta:
        print("  … baixando os modelos locais de transcrição (base e small, uma vez só)")
        subprocess.run([str(VENV_PY), "-c", "from faster_whisper import WhisperModel as W; W('base'); W('small')"], check=True)
        print("  ✓ modelos de escuta")

    for p in (TRABALHO, CORTES):
        p.mkdir(parents=True, exist_ok=True)
    if falta:
        print("\nFALTA:", ", ".join(falta), "— instale e rode 'clip.py instalar' de novo.")
        sys.exit(1)
    print(f"\nTUDO PRONTO. Os cortes vão sair em {CORTES}")


def buscar(a):
    """Busca as maiores lives no YouTube para os termos informados."""
    termos = a.termos_flag or a.termos
    if not termos:
        if a.br:
            termos = (
                [
                    "GTA 6 ao vivo",
                    "Flow Games GTA 6",
                    "Davy Jones GTA 6",
                    "Gameplayrj GTA 6",
                    "Alanzoka GTA 6",
                    "Paulinho o Loko GTA 6",
                    "Coringa GTA 6",
                    "Gabepeixe GTA 6",
                    "Bistecone GTA 6",
                    "SanInPlay GTA 6",
                ]
                if a.gta6
                else [
                    "live ao vivo br",
                    "Flow Games live",
                    "Gameplayrj live",
                    "Alanzoka live",
                    "Paulinho o Loko live",
                    "Coringa live",
                    "Gabepeixe live",
                    "Bistecone live",
                ]
            )
        else:
            termos = ["GTA 6 live", "GTA 6 ao vivo", "GTA VI stream"] if a.gta6 else ["live ao vivo", "gameplay ao vivo"]
    eh_gta6 = a.gta6 or any(GTA6.search(t) for t in termos)

    periodo = "tudo" if a.todas_datas else ("mes" if a.mes else ("semana" if a.semana else "hoje"))
    filtros_sp = {
        "hoje": "&sp=EgQIAhgC" if a.min_min >= 20 else "&sp=EgIIAg%253D%253D",
        "semana": "&sp=EgQIAxgC" if a.min_min >= 20 else "&sp=EgIIAw%253D%253D",
        "mes": "&sp=EgQIBBgC" if a.min_min >= 20 else "&sp=EgIIBA%253D%253D",
        "tudo": "",
    }
    filtro = filtros_sp[periodo]
    vistos = {}
    for termo in termos:
        url = f"https://www.youtube.com/results?search_query={quote_plus(termo)}{filtro}"
        r = rodar_captura(ytdlp() + ["--flat-playlist", "-J", "--playlist-end", "40", "--no-warnings", url])
        try:
            itens = (json.loads(r.stdout).get("entries") if r.stdout else None) or []
        except json.JSONDecodeError:
            itens = []
        if not itens and r.returncode != 0 and r.stderr.strip():
            print(f"  (aviso na busca de '{termo}': {r.stderr.strip().splitlines()[-1]})")
        for v in itens:
            if not isinstance(v, dict):
                continue
            titulo = v.get("title") or ""
            if not v.get("id") or (v.get("duration") or 0) < a.min_min * 60:
                continue
            if eh_gta6 and (not GTA6.search(titulo) or GTA5.search(titulo)):
                continue
            vistos[v["id"]] = v

    lista = sorted(vistos.values(), key=lambda v: -(v.get("view_count") or 0))[: a.quantas]
    if not lista:
        print("Não achei lives longas para esses termos. Tente --semana, --mes, --todas-datas ou um link direto.")
        return
    escopos = {"hoje": "de hoje", "semana": "desta semana", "mes": "deste mês", "tudo": "de todas as datas"}
    print(f"As {len(lista)} maiores lives {escopos[periodo]}:\n")
    for i, v in enumerate(lista, 1):
        views = f"{v.get('view_count') or 0:,}".replace(",", ".")
        print(
            f"  {i}. {v.get('title')}\n"
            f"     {v.get('channel') or v.get('uploader')} | {hms(v.get('duration') or 0)} | {views} views\n"
            f"     https://www.youtube.com/watch?v={v['id']}\n"
        )


def baixar_cmd(a):
    from ouvir import baixar
    for link in a.links:
        baixar(link)


def processar_cmd(a):
    from ouvir import processar
    from youtube import imprimir_aviso_youtube
    p = pasta_da_live(a.live)
    processar(p, a.modelo, a.idioma)
    imprimir_aviso_youtube(p)


def preparar(a):
    from ouvir import preparar as prep
    from youtube import imprimir_aviso_youtube
    for link in a.links:
        p = prep(link, a.modelo, a.idioma)
        imprimir_aviso_youtube(p)


def escolher(a):
    from cortar import escolher as esc
    from youtube import imprimir_aviso_youtube
    p = pasta_da_live(a.live)
    esc(p, a.manter, a.minimo, a.maximo)
    imprimir_aviso_youtube(p)


def fazer(a):
    from cortar import fazer as faz
    faz(pasta_da_live(a.live), a.modelo, so_baixar=a.so_baixar, cortes_ids=a.cortes, so_capa=a.so_capa)


def youtube_cmd(a):
    from youtube import fazer_youtube
    fazer_youtube(pasta_da_live(a.live), video_ids=a.videos, so_baixar=a.so_baixar, so_thumb=a.so_thumb)


def potencial_cmd(a):
    from youtube import potencial_cmd as pot
    pot(a.live)


def status(_):
    """Lista todas as lives em trabalho e quantos blocos/cortes existem."""
    from youtube import avaliar_potencial_youtube
    if not TRABALHO.exists() or not any(TRABALHO.iterdir()):
        print("Nenhuma live ainda.")
        return
    for p in sorted(TRABALHO.iterdir()):
        if not p.is_dir():
            continue
        info = ler_json(p / "info.json", {})
        nb = len(list((p / "blocos").glob("bloco_*.txt")))
        nm = len(list((p / "momentos").glob("bloco_*.json")))
        esc = ler_json(p / "escolhidos.json", {}).get("cortes")
        prontos = len(list((CORTES / p.name).glob("corte_*.mp4")))
        av = avaliar_potencial_youtube(p)
        aviso_yt = f" | YOUTUBE-POTENCIAL: {av['nivel']} (prontos: {av['prontos']})" if av["tem_potencial"] or av["prontos"] else ""
        print(
            f"{p.name}\n  {info.get('title', '')}\n"
            f"  blocos lidos: {nm}/{nb} | escolhidos: {len(esc) if esc else 0} | cortes prontos: {prontos}{aviso_yt}"
        )


def certificados():
    """Configura certificados TLS via certifi (útil no macOS/Python.org)."""
    try:
        import certifi
        os.environ.setdefault("SSL_CERT_FILE", certifi.where())
        os.environ.setdefault("REQUESTS_CA_BUNDLE", certifi.where())
    except ImportError:
        pass


def main():
    configurar_utf8()
    no_ambiente()
    certificados()
    ap = argparse.ArgumentParser(description="Clipper de Lives (OWL CORTES)")
    sub = ap.add_subparsers(dest="cmd")

    sub.add_parser("instalar").set_defaults(f=instalar)

    b = sub.add_parser("buscar")
    b.add_argument("termos", nargs="*", help="termos de busca no YouTube")
    b.add_argument("--termos", dest="termos_flag", nargs="+")
    b.add_argument("--quantas", type=int, default=7)
    b.add_argument("--min-min", type=int, default=30, help="duração mínima em minutos")
    b.add_argument("--gta6", action="store_true", help="aplica filtro estrito de GTA 6")
    b.add_argument("--br", action="store_true", help="prioriza streamers e lives brasileiras")
    b.add_argument("--semana", action="store_true", help="busca vídeos/lives desta semana")
    b.add_argument("--mes", action="store_true", help="busca vídeos/lives deste mês")
    b.add_argument("--todas-datas", action="store_true", help="não restringe por data")
    b.set_defaults(f=buscar)

    bx = sub.add_parser("baixar")
    bx.add_argument("links", nargs="+")
    bx.set_defaults(f=baixar_cmd)

    pr = sub.add_parser("processar")
    pr.add_argument("live")
    pr.add_argument("--modelo", default="base")
    pr.add_argument("--idioma", default=None)
    pr.set_defaults(f=processar_cmd)

    p = sub.add_parser("preparar")
    p.add_argument("links", nargs="+")
    p.add_argument("--modelo", default="base")
    p.add_argument("--idioma", default=None)
    p.set_defaults(f=preparar)

    e = sub.add_parser("escolher")
    e.add_argument("live")
    e.add_argument("--manter", type=int, default=3)
    e.add_argument("--minimo", type=int, default=15)
    e.add_argument("--maximo", type=int, default=90)
    e.set_defaults(f=escolher)

    f = sub.add_parser("fazer")
    f.add_argument("live")
    f.add_argument("--modelo", default="small")
    f.add_argument("--so-baixar", action="store_true", help="apenas baixa os trechos sem renderizar")
    f.add_argument("--so-capa", action="store_true", help="gera apenas as capas PNG separadas")
    f.add_argument("--cortes", nargs="+", type=int, help="índices dos cortes a processar (ex.: 1 2)")
    f.set_defaults(f=fazer)

    yt = sub.add_parser("youtube")
    yt.add_argument("live")
    yt.add_argument("--videos", nargs="+", type=int, help="índices de video_*.json (ex.: 1 2)")
    yt.add_argument("--so-baixar", action="store_true", help="apenas baixa os trechos sem renderizar")
    yt.add_argument("--so-thumb", action="store_true", help="gera apenas a thumbnail 1280x720")
    yt.set_defaults(f=youtube_cmd)

    pt = sub.add_parser("potencial")
    pt.add_argument("live", nargs="?", default=None, help="live específica ou todas")
    pt.set_defaults(f=potencial_cmd)

    sub.add_parser("status").set_defaults(f=status)

    a = ap.parse_args()
    if not a.cmd:
        ap.print_help()
        print("\n--- Status atual ---")
        ffmpeg_embutido()
        status(a)
        return
    if a.f is not instalar:
        ffmpeg_embutido()
    a.f(a)
    if a.cmd in ("processar", "preparar", "fazer", "youtube"):
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(0)


if __name__ == "__main__":
    main()

