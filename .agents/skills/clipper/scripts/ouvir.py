"""Passos 1 e 2: baixa só o áudio da live, transcreve localmente e separa em blocos de 12 min.

Cada bloco vira um .txt com a fala e marcas de apoio:
  [ALTO +11dB]       o streamer ficou bem mais alto que o normal daquele trecho
  [CHAT 3.4x]        no replay do YouTube, o chat acelerou 3,4x em relação à vizinhança
  (reação/sem fala)  pico de áudio ou chat em trecho sem fala transcrita
"""
import json
import time
import wave

import numpy as np

from comum import (
    BLOCO_MIN,
    TRABALHO,
    carregar_audio_16k,
    carregar_whisper,
    gravar_json,
    hms,
    ler_json,
    rodar,
    rodar_captura,
    slug,
    ytdlp,
)


def baixar(url):
    """Baixa metadados, faixa de áudio e (no YouTube) o replay do chat ao vivo."""
    print(f"\n[1/4] Lendo a live: {url}")
    res = rodar_captura(ytdlp() + ["-J", "--no-playlist", "--no-warnings", url], check=True)
    meta = json.loads(res.stdout)
    nome = slug(f"{meta.get('uploader') or meta.get('channel') or 'live'}-{meta.get('title', '')}")
    pasta = TRABALHO / nome
    pasta.mkdir(parents=True, exist_ok=True)
    info = {
        k: meta.get(k)
        for k in (
            "id", "title", "uploader", "channel", "duration",
            "view_count", "webpage_url", "extractor_key", "was_live", "live_status",
        )
    }
    info["url"] = url
    gravar_json(pasta / "info.json", info)
    print(f"      {info['title']}  |  {info.get('uploader')}  |  {hms(info.get('duration') or 0)}")

    if not list(pasta.glob("audio.*")):
        print("      baixando só o áudio…")
        rodar(ytdlp() + [
            "-f", "ba/b", "-x", "--no-playlist", "--no-warnings",
            "-o", str(pasta / "audio.%(ext)s"), url,
        ])
    if (info.get("extractor_key") or "").lower().startswith("youtube") and not (pasta / "chat.feito").exists():
        print("      tentando o replay do chat (quando disponível no YouTube)…")
        try:
            rodar(ytdlp() + [
                "--skip-download", "--write-subs", "--sub-langs", "live_chat",
                "--no-warnings", "-o", str(pasta / "chat"), url,
            ], timeout=1200)
        except Exception as e:
            print(f"      sem replay de chat ({type(e).__name__})")
        (pasta / "chat.feito").write_text("ok", encoding="utf-8")
    print(f"      pasta da live: {pasta.name}")
    return pasta


def wav16k(pasta):
    """Extrai/converte o áudio baixado para WAV mono 16 kHz."""
    w = pasta / "audio16k.wav"
    if not w.exists():
        audio = next(p for p in pasta.glob("audio.*"))
        rodar(["ffmpeg", "-y", "-loglevel", "error", "-i", audio, "-ac", "1", "-ar", "16000", w])
    return w


def transcrever(pasta, modelo="base", idioma=None):
    """Transcreve a live inteira usando faster-whisper."""
    saida = pasta / "transcricao.json"
    if saida.exists():
        return ler_json(saida)
    w = wav16k(pasta)
    dur = (ler_json(pasta / "info.json", {}) or {}).get("duration") or 0
    print(f"\n[2/4] Transcrevendo a live localmente (modelo {modelo})…", flush=True)
    audio = carregar_audio_16k(w)
    m = carregar_whisper(modelo)
    segs, inf = m.transcribe(
        audio,
        language=idioma,
        vad_filter=True,
        beam_size=1,
        condition_on_previous_text=False,
    )
    out, t0, aviso = [], time.time(), 0
    for s in segs:
        out.append([round(s.start, 2), round(s.end, 2), s.text.strip()])
        if s.end - aviso > 300:
            aviso = s.end
            pct = f" ({100 * s.end / dur:.0f}%)" if dur else ""
            print(f"      {hms(s.end)}{pct} escutado em {time.time() - t0:.0f}s", flush=True)
    dados = {"idioma": inf.language, "segmentos": out}
    gravar_json(saida, dados)
    return dados


def picos_de_volume(pasta):
    """Detecta segundos de grito/pico de volume lendo o WAV em janelas para poupar RAM."""
    saida = pasta / "volume.json"
    if saida.exists():
        return ler_json(saida)
    rms_partes = []
    with wave.open(str(wav16k(pasta))) as f:
        sr = f.getframerate()
        while True:
            bruto = f.readframes(sr * 60)
            if not bruto:
                break
            a = np.frombuffer(bruto, dtype=np.int16).astype(np.float32)
            seg_bloco = len(a) // sr
            if seg_bloco == 0:
                break
            rms_partes.append(np.sqrt(np.mean(a[: seg_bloco * sr].reshape(seg_bloco, sr) ** 2, axis=1) + 1e-6))
    if not rms_partes:
        gravar_json(saida, [])
        return []
    rms = np.concatenate(rms_partes)
    seg = len(rms)
    db = 20 * np.log10(rms / 32768 + 1e-9)
    fala = db > np.percentile(db, 20)
    base = np.zeros_like(db)
    for i in range(0, seg, 60):
        j0, j1 = max(0, i - 150), min(seg, i + 150)
        janela = db[j0:j1][fala[j0:j1]]
        base[i:i + 60] = np.median(janela) if len(janela) else np.median(db)
    excesso = db - base
    corte = max(8.0, float(np.percentile(excesso, 98)))
    picos = [[int(i), round(float(excesso[i]), 1)] for i in np.where(excesso >= corte)[0]]
    gravar_json(saida, picos)
    return picos


def picos_do_chat(pasta):
    """Identifica picos de velocidade de mensagens no replay de chat do YouTube."""
    arq = next(iter(pasta.glob("chat*.live_chat.json")), None)
    if not arq:
        return []
    tempos = []
    for linha in arq.read_text(encoding="utf-8", errors="ignore").splitlines():
        try:
            ms = json.loads(linha)["replayChatItemAction"]["videoOffsetTimeMsec"]
            tempos.append(int(ms) / 1000)
        except (KeyError, ValueError, json.JSONDecodeError):
            continue
    if len(tempos) < 50:
        return []
    caixas = np.bincount((np.array(tempos) // 10).astype(int))
    picos = []
    for i, c in enumerate(caixas):
        viz = caixas[max(0, i - 30): i + 30]
        normal = max(1.0, float(np.median(viz)))
        if c >= 8 and c / normal >= 2.5:
            picos.append([i * 10, round(c / normal, 1)])
    return picos


def _agrupar_picos_soltos(tempos_vol, tempos_chat, vol_dict, chat_dict):
    """Agrupa picos próximos sem fala transcrita (gap <= 5s) em eventos únicos."""
    eventos = sorted(set(tempos_vol) | set(tempos_chat))
    grupos = []
    for t in eventos:
        v = vol_dict.get(t, 0)
        c = chat_dict.get(t, 0)
        if grupos and t - grupos[-1]["fim"] <= 5:
            grupos[-1]["fim"] = t
            grupos[-1]["alto"] = max(grupos[-1]["alto"], v)
            grupos[-1]["chat"] = max(grupos[-1]["chat"], c)
        else:
            grupos.append({"ini": t, "fim": t, "alto": v, "chat": c})
    return grupos


def _formatar_marca(alto, ch):
    marca = ""
    if alto:
        marca += f"  [ALTO +{alto:.0f}dB]"
    if ch:
        marca += f"  [CHAT {ch}x]"
    return marca


def blocos(pasta, trans, volume, chat):
    """Divide a transcrição em blocos de 12 min incluindo picos fora de fala."""
    pb = pasta / "blocos"
    pb.mkdir(exist_ok=True)
    (pasta / "momentos").mkdir(exist_ok=True)
    vol = dict((s, e) for s, e in volume)
    chat_dict = dict((c, r) for c, r in chat)
    segs = trans["segmentos"]

    vol_usados, chat_usados = set(), set()
    itens = []
    for s, e, t in segs:
        vs = [x for x in range(int(s), int(e) + 1) if x in vol]
        vol_usados.update(vs)
        alto = max((vol[x] for x in vs), default=0)

        cs = [c for c, _ in chat if s - 10 <= c <= e]
        chat_usados.update(cs)
        ch = max((chat_dict[c] for c in cs), default=0)
        itens.append((s, f"[{hms(s)}] {t}{_formatar_marca(alto, ch)}"))

    soltos_vol = [x for x in vol if x not in vol_usados]
    soltos_chat = [c for c in chat_dict if c not in chat_usados]
    for g in _agrupar_picos_soltos(soltos_vol, soltos_chat, vol, chat_dict):
        itens.append((g["ini"], f"[{hms(g['ini'])}] (reação/sem fala){_formatar_marca(g['alto'], g['chat'])}"))

    itens.sort(key=lambda x: x[0])
    fim = max((x[0] for x in itens), default=0)
    passo = BLOCO_MIN * 60
    n = 0
    for k, ini in enumerate(range(0, int(fim) + 1, passo), start=1):
        linhas = [txt for ts, txt in itens if ini <= ts < ini + passo]
        if not linhas:
            continue
        n += 1
        cab = (
            f"# BLOCO {k:02d} — de {hms(ini)} a {hms(ini + passo)}\n"
            f"# Escreva os momentos deste bloco em: momentos/bloco_{k:02d}.json\n\n"
        )
        (pb / f"bloco_{k:02d}.txt").write_text(cab + "\n".join(linhas) + "\n", encoding="utf-8")
    return n


def processar(pasta, modelo="base", idioma=None):
    """Executa transcrição local, detecção de picos e geração dos blocos."""
    trans = transcrever(pasta, modelo, idioma)
    print("\n[2/4] Marcando picos de volume e aceleração de chat…")
    volume = picos_de_volume(pasta)
    chat = picos_do_chat(pasta)
    n = blocos(pasta, trans, volume, chat)
    print(f"      {len(volume)} segundos de grito/surto, {len(chat)} picos de chat")
    print(f"\nPRONTO PRA ESCOLHER: {n} blocos em {pasta / 'blocos'}")
    print(f"Próximo: ler cada bloco e gravar {pasta / 'momentos'}/bloco_NN.json")
    return pasta


def preparar(url, modelo="base", idioma=None):
    """Baixa áudio/chat e processa tudo para curadoria."""
    pasta = baixar(url)
    return processar(pasta, modelo, idioma)

