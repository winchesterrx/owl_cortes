"""Passos 3 e 4: seleciona os melhores momentos, acha a câmera e monta os vídeos verticais."""
import os
import sys
from pathlib import Path

from capa import gerar_capa
from comum import (
    CORTES,
    YUNET,
    carregar_audio_16k,
    carregar_whisper,
    gravar_json,
    hms,
    ler_json,
    rodar,
    rodar_captura,
    segundos,
    ytdlp,
)

L, A = 1080, 1920          # vídeo vertical
CAM_H = 768                # faixa da câmera em cima
JOGO_H = A - CAM_H         # faixa do conteúdo embaixo
FORMATO = "bv*[height<=1080][vcodec^=avc1]+ba[ext=m4a]/bv*[height<=1080]+ba/b[height<=1080]/b"


def escolher(pasta, manter=3, minimo=15, maximo=90):
    """Junta momentos de todos os blocos, remove sobreposições e escolhe os melhores."""
    todos, ruins = [], []
    for arq in sorted((pasta / "momentos").glob("bloco_*.json")):
        dados = ler_json(arq)
        if dados is None:
            ruins.append(arq.name)
            continue
        lista = dados if isinstance(dados, list) else dados.get("momentos", [])
        for m in lista:
            try:
                s, e = segundos(m["inicio"]), segundos(m["fim"])
                m.update(_s=s, _e=e, nota=float(m.get("nota", 0)), _bloco=arq.stem)
                if e - s < minimo:
                    m["_e"] = s + minimo
                if e - s > maximo:
                    m["_e"] = s + maximo
                todos.append(m)
            except (KeyError, ValueError, TypeError):
                ruins.append(f"{arq.name}: {str(m)[:60]}")
    if ruins:
        print("ATENÇÃO, não consegui ler:", *ruins, sep="\n  ")
    todos.sort(key=lambda m: -m["nota"])
    escolhidos = []
    for m in todos:
        if any(m["_s"] < o["_e"] and o["_s"] < m["_e"] for o in escolhidos):
            continue
        escolhidos.append(m)
        if len(escolhidos) >= manter:
            break
    escolhidos.sort(key=lambda m: m["_s"])
    gravar_json(pasta / "escolhidos.json", {"possiveis": len(todos), "cortes": escolhidos})
    print(f"\nAchados {len(todos)} momentos possíveis; mantidos os {len(escolhidos)} melhores:")
    for i, m in enumerate(escolhidos, 1):
        print(f"  {i}. [{hms(m['_s'])}–{hms(m['_e'])}] nota {m['nota']:.0f}  {m.get('titulo', '')}")
    return escolhidos


def _caminho_ascii(caminho):
    """Retorna caminho relativo ou curto ASCII quando possível (evita erro do OpenCV ONNX com acentos)."""
    p = Path(caminho)
    try:
        rel = os.path.relpath(p)
        if rel.isascii() and len(rel) < len(str(p)):
            return rel
    except ValueError:
        pass
    if str(p).isascii():
        return str(p)
    if os.name == "nt":
        import ctypes
        buf = ctypes.create_unicode_buffer(1024)
        if ctypes.windll.kernel32.GetShortPathNameW(str(p), buf, len(buf)) and buf.value.isascii():
            return buf.value
    return str(p)


def achar_camera(video):
    """Procura a webcam do streamer em 14 quadros e devolve a mediana do rosto dominante."""
    import cv2
    import numpy as np

    cap = cv2.VideoCapture(_caminho_ascii(video))
    W = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    H = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 1
    if W <= 0 or H <= 0:
        cap.release()
        return W, H, None
    esc = 960 / W
    alt_esc = max(1, int(H * esc))
    det = cv2.FaceDetectorYN.create(_caminho_ascii(YUNET), "", (960, alt_esc), 0.75)
    caixas = []
    for k in range(14):
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(n * (k + 0.5) / 14))
        ok, q = cap.read()
        if not ok:
            continue
        _, rostos = det.detect(cv2.resize(q, (960, alt_esc)))
        for r in rostos if rostos is not None else []:
            if r[14] >= 0.75 and r[3] / esc > H * 0.05:
                caixas.append([v / esc for v in r[:4]])
    cap.release()
    if len(caixas) < 3:
        return W, H, None
    c = np.array(caixas)
    centros = c[:, :2] + c[:, 2:] / 2
    med = np.median(centros, axis=0)
    perto = c[np.linalg.norm(centros - med, axis=1) < W * 0.08]
    if len(perto) < 3:
        return W, H, None
    return W, H, np.median(perto, axis=0)


def _par(v):
    return int(v) // 2 * 2


def filtro(W, H, rosto):
    """Monta o filter_complex do ffmpeg (split cam+jogo ou centralizado com fundo blur)."""
    if rosto is None:
        return (
            "[0:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=30:3[bg];"
            "[0:v]scale=1080:-2[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2,setsar=1,format=yuv420p,ass=legenda.ass[v]"
        )
    fx, fy, fw, fh = rosto
    cw = min(W, max(fw * 3.2, 200))
    ch = cw * CAM_H / L
    if ch > H:
        ch, cw = H, H * L / CAM_H
    cx = min(max(fx + fw / 2 - cw / 2, 0), W - cw)
    cy = min(max(fy + fh * 0.65 - ch / 2, 0), H - ch)
    gw = min(W, H * L / JOGO_H)
    gx = (W - gw) / 2
    return (
        f"[0:v]crop={_par(cw)}:{_par(ch)}:{_par(cx)}:{_par(cy)},scale={L}:{CAM_H},setsar=1[cam];"
        f"[0:v]crop={_par(gw)}:{_par(H)}:{_par(gx)}:0,scale={L}:{JOGO_H},setsar=1[jogo];"
        "[cam][jogo]vstack=inputs=2,format=yuv420p,ass=legenda.ass[v]"
    )


def _ass_tempo(t):
    t = max(0.0, t)
    return f"{int(t // 3600)}:{int(t % 3600 // 60):02d}:{t % 60:05.2f}"


def _limpo(txt):
    return txt.replace("{", "(").replace("}", ")").replace("\\", "/").strip()


def palavras_do_trecho(video, idioma, modelo="small"):
    """Extrai timestamps palavra por palavra do trecho recortado."""
    audio = carregar_audio_16k(video)
    m = carregar_whisper(modelo)
    segs, _ = m.transcribe(
        audio,
        language=idioma,
        word_timestamps=True,
        vad_filter=True,
        condition_on_previous_text=False,
    )
    return [(w.start, w.end, w.word.strip()) for s in segs for w in (s.words or []) if w.word.strip()]


def escrever_ass(caminho, titulo, palavras, dur, com_camera):
    """Gera o arquivo de legenda .ass com título gancho e destaque palavra por palavra."""
    fonte = "DejaVu Sans" if sys.platform.startswith("linux") else "Arial"
    y_titulo = CAM_H if com_camera else 520
    y_leg = CAM_H + int(JOGO_H * 0.62) if com_camera else 1480
    linhas = [
        "[Script Info]",
        "ScriptType: v4.00+",
        f"PlayResX: {L}",
        f"PlayResY: {A}",
        "WrapStyle: 0",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, "
        "Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, "
        "MarginL, MarginR, MarginV, Encoding",
        f"Style: Gancho,{fonte},58,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,1,0,0,0,100,100,0,0,3,18,0,5,60,60,0,1",
        f"Style: Leg,{fonte},84,&H00FFFFFF,&H00FFFFFF,&H00000000,&H64000000,1,0,0,0,100,100,0,0,1,7,3,5,40,40,0,1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
        f"Dialogue: 1,{_ass_tempo(0)},{_ass_tempo(dur)},Gancho,,0,0,0,,{{\\pos(540,{y_titulo})}}{_limpo(titulo).upper()}",
    ]
    grupos = [palavras[i:i + 3] for i in range(0, len(palavras), 3)]
    for g, grupo in enumerate(grupos):
        prox = grupos[g + 1][0][0] if g + 1 < len(grupos) else dur
        for k, (s, e, _) in enumerate(grupo):
            fim = grupo[k + 1][0] if k + 1 < len(grupo) else (prox if prox - e < 0.6 else e + 0.25)
            txt = " ".join(
                ("{\\c&H00E5FF&}" if j == k else "{\\c&HFFFFFF&}") + _limpo(w).upper()
                for j, (_, _, w) in enumerate(grupo)
            )
            linhas.append(f"Dialogue: 0,{_ass_tempo(s)},{_ass_tempo(fim)},Leg,,0,0,0,,{{\\pos(540,{y_leg})}}{txt}")
    Path(caminho).write_text("\n".join(linhas) + "\n", encoding="utf-8")


def tem_video(arq):
    """Verifica rapidamente se o arquivo possui fluxo de vídeo válido (>10 pacotes)."""
    r = rodar_captura([
        "ffprobe", "-v", "error", "-select_streams", "v:0",
        "-read_intervals", "%+#15", "-count_packets",
        "-show_entries", "stream=nb_read_packets", "-of", "csv=p=0", str(arq),
    ])
    out = r.stdout.strip()
    return out.isdigit() and int(out) > 10


def _recortar_local(inteiro, s, e, destino):
    rodar([
        "ffmpeg", "-y", "-loglevel", "error", "-ss", f"{s:.2f}", "-i", inteiro,
        "-t", f"{e - s:.2f}", "-c:v", "libx264", "-preset", "veryfast", "-crf", "16",
        "-c:a", "aac", "-b:a", "192k", destino,
    ])


def baixar_trecho(pasta, url, s, e, destino):
    """Recorta do vídeo inteiro já baixado, tenta corte remoto (60s timeout) ou baixa o vídeo 1x."""
    inteiro = next(iter(pasta.glob("video_inteiro.*")), None)
    if inteiro and tem_video(inteiro):
        print("      recortando trecho do vídeo local…")
        _recortar_local(inteiro, s, e, destino)
        return

    print("      baixando só esse pedaço do vídeo…")
    try:
        rodar(ytdlp() + [
            "-f", FORMATO, "--no-playlist", "--no-warnings", "-q",
            "--download-sections", f"*{s:.2f}-{e:.2f}",
            "--force-keyframes-at-cuts", "--merge-output-format", "mp4",
            "-o", str(destino), url,
        ], timeout=60)
    except Exception:
        pass
    if destino.exists() and tem_video(destino):
        return
    destino.unlink(missing_ok=True)
    print("      esse site não liberou corte remoto: baixando vídeo inteiro uma vez (até 1080p)…")
    rodar(ytdlp() + [
        "-f", FORMATO, "--no-playlist", "--no-warnings", "--merge-output-format", "mp4",
        "-o", str(pasta / "video_inteiro.%(ext)s"), url,
    ])
    inteiro = next(iter(pasta.glob("video_inteiro.*")))
    _recortar_local(inteiro, s, e, destino)


def _garantir_trecho(pasta, tdir, url, s, e):
    """Garante que `trecho.mp4` corresponda exatamente ao intervalo [s, e] atual."""
    trecho = tdir / "trecho.mp4"
    tmeta = tdir / "trecho.json"
    alvo = {"s": round(s, 2), "e": round(e, 2), "url": url}
    cache_ok = trecho.exists() and ler_json(tmeta) == alvo and tem_video(trecho)
    if not cache_ok:
        trecho.unlink(missing_ok=True)
        baixar_trecho(pasta, url, s, e, trecho)
        gravar_json(tmeta, alvo)
    return trecho


def _duracao(trecho):
    r = rodar_captura(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(trecho)])
    txt = r.stdout.strip()
    if r.returncode != 0 or not txt:
        raise RuntimeError(f"Não consegui ler a duração de {trecho}: {r.stderr.strip()}")
    return float(txt)


def fazer(pasta, modelo_legenda="small", so_baixar=False, cortes_ids=None, so_capa=False):
    """Baixa trechos e renderiza os cortes verticais, capas PNG separadas e .txt em `cortes/`."""
    info = ler_json(pasta / "info.json", {})
    escolhidos = ler_json(pasta / "escolhidos.json", {}).get("cortes")
    if not escolhidos:
        raise SystemExit("Nenhum corte escolhido ainda. Rode antes: clip.py escolher " + pasta.name)
    idioma = ler_json(pasta / "transcricao.json", {}).get("idioma")
    canal = info.get("uploader") or info.get("channel") or ""
    destino = CORTES / pasta.name
    destino.mkdir(parents=True, exist_ok=True)
    filtro_ids = set(cortes_ids) if cortes_ids else None
    feitos = []
    for i, m in enumerate(escolhidos, 1):
        if filtro_ids and i not in filtro_ids:
            continue
        s, e = m["_s"], m["_e"]
        print(f"\n[4/4] Corte {i}/{len(escolhidos)}: {m.get('titulo', '')}  ({hms(s)}–{hms(e)})")
        tdir = pasta / f"corte_{i:02d}"
        tdir.mkdir(exist_ok=True)
        trecho = _garantir_trecho(pasta, tdir, info["url"], s, e)
        if so_baixar:
            continue

        capa_saida = destino / f"corte_{i:02d}_capa.png"
        print("      gerando capa/thumbnail vertical…")
        gerar_capa(
            trecho,
            capa_saida,
            titulo=m.get("capa_texto") or m.get("titulo", ""),
            tag=m.get("capa_tag") or m.get("tipo", "MOMENTO DA LIVE"),
            canal=canal,
        )
        print(f"      CAPA PRONTA: {capa_saida}")
        if so_capa:
            feitos.append(capa_saida)
            continue

        dur = _duracao(trecho)
        print("      procurando a câmera do streamer…")
        W, H, rosto = achar_camera(trecho)
        print("      câmera achada" if rosto is not None else "      sem câmera: jogo inteiro com fundo desfocado")
        print("      legenda palavra por palavra…")
        palavras = palavras_do_trecho(trecho, idioma, modelo_legenda)
        escrever_ass(tdir / "legenda.ass", m.get("titulo", ""), palavras, dur, rosto is not None)
        saida = destino / f"corte_{i:02d}.mp4"
        rodar([
            "ffmpeg", "-y", "-loglevel", "error", "-i", "trecho.mp4",
            "-filter_complex", filtro(W, H, rosto), "-map", "[v]", "-map", "0:a?",
            "-c:v", "libx264", "-preset", "medium", "-crf", "19", "-r", "30",
            "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart",
            str(saida.resolve()),
        ], cwd=tdir)
        post = (
            f"{m.get('titulo', '')}\n\n{m.get('post', '').strip()}\n\n"
            f"Crédito (TikTok/Reels - use @): {canal}\n"
            f"Link original (Shorts/Referência): {info.get('webpage_url') or info['url']}\n"
        )
        saida.with_suffix(".txt").write_text(post, encoding="utf-8")
        feitos.append(saida)
        print(f"      PRONTO: {saida}")
    if so_baixar:
        print(f"\nTrechos prontos em {pasta}. Rode agora sem --so-baixar para montar os vídeos.")
        return []
    if not filtro_ids and not so_capa:
        for sobra in destino.glob("corte_*.mp4"):
            num = int(sobra.stem.split("_")[1]) if "_" in sobra.stem and sobra.stem.split("_")[1].isdigit() else 0
            if num > len(escolhidos):
                sobra.unlink(missing_ok=True)
                sobra.with_suffix(".txt").unlink(missing_ok=True)
                (destino / f"corte_{num:02d}_capa.png").unlink(missing_ok=True)
    print(f"\n{len(feitos)} {'capas prontas' if so_capa else 'cortes prontos pra postar'} em {destino}")
    return feitos

