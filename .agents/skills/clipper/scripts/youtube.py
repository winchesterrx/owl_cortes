"""Modo YouTube Longo (16:9): detecta potencial de contexto completo e gera vídeos 1080p + thumb 1280x720 em YOUTUBE-POTENCIAL/."""
from pathlib import Path

from capa import gerar_thumb_youtube
from comum import (
    YOUTUBE_POTENCIAL,
    hms,
    ler_json,
    pasta_da_live,
    pasta_youtube_da_live,
    rodar,
    segundos,
)
from cortar import _duracao, _garantir_trecho


def _janelas_quentes(pasta):
    """Encontra janelas contínuas (4–15 min) com alta concentração de picos de volume/chat."""
    volume = ler_json(pasta / "volume.json", []) or []
    chat = ler_json(pasta / "chat_picos.json", []) or []
    pontos = sorted({int(s) for s, _ in volume} | {int(c) for c, _ in chat})
    if len(pontos) < 3:
        return []
    grupos = []
    for p in pontos:
        if grupos and p - grupos[-1][1] <= 180:
            grupos[-1][1] = p
            grupos[-1][2] += 1
        else:
            grupos.append([p, p, 1])
    quentes = []
    for ini, fim, qtd in grupos:
        if qtd >= 4 or (fim - ini) >= 180:
            quentes.append({
                "inicio": hms(max(0, ini - 20)),
                "fim": hms(fim + 30),
                "picos": qtd,
                "span_s": fim - ini + 50,
            })
    quentes.sort(key=lambda x: (-x["picos"], -x["span_s"]))
    return quentes[:5]


def avaliar_potencial_youtube(pasta):
    """Avalia se a live/vídeo tem material para vídeo longo horizontal (16:9) no YouTube."""
    info = ler_json(pasta / "info.json", {})
    dur = float(info.get("duration") or 0)
    eh_live = bool(info.get("was_live")) or info.get("live_status") == "was_live"
    blocos_lidos = len([p for p in (pasta / "momentos").glob("bloco_*.json") if ler_json(p)])
    escolhidos = ler_json(pasta / "escolhidos.json", {}).get("cortes") or []
    roteiros = sorted((pasta / "youtube").glob("video_*.json")) if (pasta / "youtube").is_dir() else []

    canal = info.get("uploader") or info.get("channel") or "geral"
    destino = pasta_youtube_da_live(canal, pasta.name)
    prontos = sorted(destino.glob("video_*.mp4")) if destino.is_dir() else []
    quentes = _janelas_quentes(pasta)

    if dur < 1800 and not eh_live:
        nivel = "SO_SHORTS"
        tem_potencial = False
        motivo = f"vídeo editado curto ({hms(dur)}): evite reupload longo no YouTube; use apenas Shorts/TikTok ou compilado multi-streamer"
    elif dur >= 3600 or len(quentes) >= 2 or len(escolhidos) >= 4:
        nivel = "ALTO"
        tem_potencial = True
        motivo = (
            f"{'live' if eh_live else 'VOD'} longa ({hms(dur)}) com {len(quentes)} zona(s) densas de picos e "
            f"{len(escolhidos)} cortes virais — ótimo para vídeo completo de 8–15 min do começo ao fim do tema"
        )
    elif dur >= 1800:
        nivel = "MEDIO"
        tem_potencial = True
        motivo = f"VOD de {hms(dur)} com arcos de história completos possíveis (verifique se a edição preserva valor transformativo)"
    else:
        nivel = "AVALIAR"
        tem_potencial = False
        motivo = f"duração {hms(dur)}; só vale longo se juntar com outros streamers sobre o mesmo assunto"

    return {
        "tem_potencial": tem_potencial,
        "nivel": nivel,
        "motivo": motivo,
        "dur": dur,
        "eh_live": eh_live,
        "blocos_com_momentos": blocos_lidos,
        "escolhidos": len(escolhidos),
        "janelas_quentes": quentes,
        "roteiros": len(roteiros),
        "prontos": len(prontos),
        "destino": str(destino),
    }


def imprimir_aviso_youtube(pasta):
    """Exibe aviso claro no terminal quando a live merece vídeo longo em YOUTUBE-POTENCIAL/."""
    av = avaliar_potencial_youtube(pasta)
    if not av["tem_potencial"]:
        return av
    print(f"\n[AVISO YOUTUBE-POTENCIAL · {av['nivel']}] {pasta.name}")
    print(f"  Motivo : {av['motivo']}")
    if av["janelas_quentes"]:
        amostras = ", ".join(f"{j['inicio']}–{j['fim']} ({j['picos']} picos)" for j in av["janelas_quentes"][:3])
        print(f"  Zonas  : {amostras}")
    print(f"  Destino: {av['destino']}")
    print(f"  Próximo: se um Shorts render contexto completo (5–15 min), grave .clipper/trabalho/{pasta.name}/youtube/video_01.json e rode: clip.py youtube {pasta.name}")
    return av


def _preparar_segmentos(pasta, rdir, trechos):
    """Baixa/recorta e calcula duração exata de cada bloco que compõe o vídeo longo."""
    info_padrao = ler_json(pasta / "info.json", {})
    segs = []
    for k, tr in enumerate(trechos, 1):
        live_ref = tr.get("live")
        fpasta = pasta_da_live(live_ref) if live_ref else pasta
        finfo = ler_json(fpasta / "info.json", info_padrao)
        s = segundos(tr["inicio"])
        e = segundos(tr["fim"])
        if e <= s:
            raise ValueError(f"Trecho {k} inválido ({tr.get('inicio')}–{tr.get('fim')})")
        sdir = rdir / f"seg_{k:02d}"
        sdir.mkdir(parents=True, exist_ok=True)
        mp4 = _garantir_trecho(fpasta, sdir, finfo["url"], s, e)
        segs.append({
            "indice": k,
            "arquivo": mp4,
            "capitulo": tr.get("capitulo") or f"Parte {k}",
            "s": s,
            "e": e,
            "canal": finfo.get("uploader") or finfo.get("channel") or "",
            "titulo_live": finfo.get("title") or fpasta.name,
            "url": finfo.get("webpage_url") or finfo.get("url") or "",
        })
    return segs


def _render_horizontal(segs, saida):
    """Concatena e padroniza segmentos em 1920x1080 (16:9), 30fps e áudio 48kHz stereo."""
    cmd = ["ffmpeg", "-y", "-loglevel", "error"]
    for seg in segs:
        cmd += ["-i", str(seg["arquivo"].resolve())]
    n = len(segs)
    if n == 1:
        vf = "scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=30,format=yuv420p"
        cmd += ["-vf", vf, "-af", "aresample=48000,aformat=channel_layouts=stereo"]
    else:
        partes = []
        concat_in = []
        for i in range(n):
            partes.append(
                f"[{i}:v]scale=1920:1080:force_original_aspect_ratio=decrease,"
                f"pad=1920:1080:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=30,format=yuv420p[v{i}];"
                f"[{i}:a]aresample=48000,aformat=channel_layouts=stereo[a{i}]"
            )
            concat_in.append(f"[v{i}][a{i}]")
        fc = ";".join(partes) + ";" + "".join(concat_in) + f"concat=n={n}:v=1:a=1[v][a]"
        cmd += ["-filter_complex", fc, "-map", "[v]", "-map", "[a]"]
    cmd += [
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
        "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart",
        str(Path(saida).resolve()),
    ]
    rodar(cmd)


def _formatar_cap(seg):
    seg = max(0, int(seg))
    return f"{seg // 3600}:{seg % 3600 // 60:02d}:{seg % 60:02d}" if seg >= 3600 else f"{seg // 60:02d}:{seg % 60:02d}"


def _montar_txt(roteiro, segs, duracoes, destino_pasta):
    """Cria arquivo .txt completo para upload no YouTube (títulos A/B, descrição, capítulos, tags e créditos)."""
    titulo = roteiro.get("titulo", "").strip()
    ab = [t.strip() for t in (roteiro.get("titulos_ab") or []) if t.strip()]
    desc = (roteiro.get("descricao") or "").strip()
    tags = [t.strip().lstrip("#") for t in (roteiro.get("tags") or []) if t.strip()]
    short_rel = (roteiro.get("short_relacionado") or "").strip()

    t_acum = 0.0
    caps = []
    fontes = []
    vistos = set()
    for seg, d in zip(segs, duracoes):
        caps.append(f"{_formatar_cap(t_acum)} - {seg['capitulo']}")
        t_acum += d
        chave = seg["url"] or seg["canal"]
        if chave and chave not in vistos:
            vistos.add(chave)
            fontes.append(f"- {seg['canal']} ({seg['titulo_live']}): {seg['url']}")

    linhas = [f"TÍTULO PRINCIPAL:\n{titulo}"]
    if ab:
        linhas.append("VARIAÇÕES DE TÍTULO (TESTE A/B):\n" + "\n".join(f"- {t}" for t in ab))
    if short_rel:
        linhas.append(f"SHORT RELACIONADO (linkar no YouTube Studio):\n{short_rel}")
    linhas.append("DESCRIÇÃO PARA O YOUTUBE:\n" + desc)
    if caps:
        linhas.append("CAPÍTULOS:\n" + "\n".join(caps))
    if fontes:
        linhas.append("CRÉDITOS / LIVE ORIGINAL:\n" + "\n".join(fontes))
    if tags:
        hashtags = " ".join("#" + t.replace(" ", "") for t in tags[:6])
        linhas.append(f"HASHTAGS:\n{hashtags}\n\nTAGS:\n{', '.join(tags)}")
    linhas.append(f"PASTA DESTINO:\n{destino_pasta}")
    return "\n\n---\n\n".join(linhas) + "\n"


def fazer_youtube(pasta, video_ids=None, so_baixar=False, so_thumb=False):
    """Monta os vídeos longos (16:9), thumbnails 1280x720 e .txt em YOUTUBE-POTENCIAL/<streamer>/<live>/."""
    yt_dir = pasta / "youtube"
    roteiros = sorted(yt_dir.glob("video_*.json")) if yt_dir.is_dir() else []
    if not roteiros:
        raise SystemExit(
            f"Nenhum roteiro YouTube encontrado em {yt_dir}.\n"
            f"Crie ex.: {yt_dir / 'video_01.json'} antes de rodar: clip.py youtube {pasta.name}"
        )

    info = ler_json(pasta / "info.json", {})
    canal_padrao = info.get("uploader") or info.get("channel") or "geral"
    filtro = set(video_ids) if video_ids else None
    feitos = []

    for idx, r_path in enumerate(roteiros, 1):
        if filtro and idx not in filtro:
            continue
        roteiro = ler_json(r_path)
        if not roteiro or not roteiro.get("trechos"):
            print(f"Pulando {r_path.name}: sem 'trechos' válidos.")
            continue

        streamer = roteiro.get("streamer") or canal_padrao
        destino = pasta_youtube_da_live(streamer, roteiro.get("pasta_saida") or pasta.name)
        destino.mkdir(parents=True, exist_ok=True)
        rdir = yt_dir / r_path.stem
        rdir.mkdir(parents=True, exist_ok=True)

        print(f"\n[YOUTUBE-POTENCIAL {idx}/{len(roteiros)}] {roteiro.get('titulo', r_path.stem)}")
        segs = _preparar_segmentos(pasta, rdir, roteiro["trechos"])
        if so_baixar:
            continue

        capa_idx = max(0, min(len(segs) - 1, int(roteiro.get("capa_trecho", 0))))
        thumb_saida = destino / f"video_{idx:02d}_thumb.png"
        print("      gerando thumbnail horizontal 1280x720…")
        gerar_thumb_youtube(
            segs[capa_idx]["arquivo"],
            thumb_saida,
            titulo=roteiro.get("thumb_texto") or roteiro.get("titulo", ""),
            tag=roteiro.get("thumb_tag") or "COMPLETO DA LIVE",
            canal=streamer,
        )
        print(f"      THUMB PRONTA: {thumb_saida}")
        if so_thumb:
            feitos.append(thumb_saida)
            continue

        duracoes = [_duracao(s["arquivo"]) for s in segs]
        saida = destino / f"video_{idx:02d}.mp4"
        print(f"      renderizando vídeo 16:9 (1920x1080) com {len(segs)} bloco(s) ({hms(sum(duracoes))})…")
        _render_horizontal(segs, saida)

        txt_saida = destino / f"video_{idx:02d}.txt"
        txt_saida.write_text(_montar_txt(roteiro, segs, duracoes, destino), encoding="utf-8")
        feitos.append(saida)
        print(f"      VÍDEO PRONTO: {saida}")

    if so_baixar:
        print(f"\nSegmentos baixados em {yt_dir}. Rode agora sem --so-baixar para montar o vídeo YouTube.")
        return []
    print(f"\n{len(feitos)} entrega(s) salva(s) em {YOUTUBE_POTENCIAL}")
    return feitos


def potencial_cmd(live=None):
    """Lista o potencial YouTube (vídeo longo 16:9) das lives já processadas no workspace."""
    from comum import TRABALHO

    alvos = [pasta_da_live(live)] if live else sorted(p for p in TRABALHO.glob("*") if p.is_dir()) if TRABALHO.exists() else []
    if not alvos:
        print("Nenhuma live encontrada ainda.")
        return
    print(f"Pasta de saída configurada: {YOUTUBE_POTENCIAL}\n")
    for p in alvos:
        av = avaliar_potencial_youtube(p)
        tag = f"[{av['nivel']}]"
        print(f"- {p.name}  {tag}")
        print(f"  {av['motivo']}")
        print(f"  Roteiros: {av['roteiros']} | Prontos em YOUTUBE-POTENCIAL: {av['prontos']} | Pasta: {av['destino']}")
        if av["janelas_quentes"]:
            amostras = ", ".join(f"{j['inicio']}–{j['fim']} ({j['picos']}p)" for j in av["janelas_quentes"][:3])
            print(f"  Zonas quentes: {amostras}")

