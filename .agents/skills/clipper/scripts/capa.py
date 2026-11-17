"""Gerador de capas/thumbnails verticais (1080x1920) com frame real da live e texto chamativo."""
import os
from pathlib import Path

from comum import YUNET

L, A = 1080, 1920

_CORES_TAG = {
    "surto": ("#FF2E4C", "#FFFFFF"),
    "rage": ("#FF2E4C", "#FFFFFF"),
    "polêmica": ("#FF2E4C", "#FFFFFF"),
    "polemica": ("#FF2E4C", "#FFFFFF"),
    "opinião": ("#FF5A1F", "#FFFFFF"),
    "opiniao": ("#FF5A1F", "#FFFFFF"),
    "revelação": ("#00D4FF", "#0A0A0A"),
    "revelacao": ("#00D4FF", "#0A0A0A"),
    "bastidores": ("#FFD400", "#0A0A0A"),
    "desabafo": ("#FFD400", "#0A0A0A"),
}


def _fonte(nomes, tamanho):
    from PIL import ImageFont

    win_fonts = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
    linux_fonts = [
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
        Path("/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"),
    ]
    candidatos = []
    for nome in nomes:
        candidatos.append(win_fonts / nome)
        candidatos.append(Path(nome))
    candidatos.extend(linux_fonts)
    for c in candidatos:
        if c.exists():
            return ImageFont.truetype(str(c), tamanho)
    return ImageFont.load_default()


def _detector_yunet(largura, altura):
    import cv2

    if not YUNET.exists():
        return None
    return cv2.FaceDetectorYN.create("onnx", Path(YUNET).read_bytes(), b"", (largura, altura), 0.72)


def escolher_melhor_frame(video, amostras=16):
    """Seleciona o frame mais expressivo e nítido do clipe, priorizando boa detecção facial."""
    import cv2
    import numpy as np

    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        # Fallback com caminho relativo/ASCII caso OpenCV VideoCapture receba path especial
        cap = cv2.VideoCapture(os.path.relpath(video))
    W = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    H = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 1
    if W <= 0 or H <= 0:
        cap.release()
        raise RuntimeError(f"Não consegui ler frames de {video}")

    esc = 960 / W
    alt_esc = max(1, int(H * esc))
    det = _detector_yunet(960, alt_esc)

    melhor_com_rosto = None
    melhor_sem_rosto = None
    for k in range(amostras):
        pos = int(n * (0.08 + 0.84 * k / max(1, amostras - 1)))
        cap.set(cv2.CAP_PROP_POS_FRAMES, pos)
        ok, frame = cap.read()
        if not ok or frame is None:
            continue

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        nitidez_global = float(cv2.Laplacian(gray, cv2.CV_64F).var())
        if melhor_sem_rosto is None or nitidez_global > melhor_sem_rosto[0]:
            melhor_sem_rosto = (nitidez_global, frame, None)

        if det is None:
            continue
        _, rostos = det.detect(cv2.resize(frame, (960, alt_esc)))
        for r in rostos if rostos is not None else []:
            conf = float(r[14])
            if conf < 0.72:
                continue
            bx, by, bw, bh = [float(v / esc) for v in r[:4]]
            if bh < H * 0.05:
                continue
            x0, y0 = max(0, int(bx)), max(0, int(by))
            x1, y1 = min(W, int(bx + bw)), min(H, int(by + bh))
            roi = gray[y0:y1, x0:x1]
            nitidez_rosto = float(cv2.Laplacian(roi, cv2.CV_64F).var()) if roi.size else nitidez_global
            score = conf * (bh / H) * (1.0 + min(nitidez_rosto, 600.0) / 150.0)
            if melhor_com_rosto is None or score > melhor_com_rosto[0]:
                melhor_com_rosto = (score, frame, (bx, by, bw, bh))

    cap.release()
    escolhido = melhor_com_rosto or melhor_sem_rosto
    if escolhido is None:
        raise RuntimeError(f"Nenhum frame válido encontrado em {video}")
    return escolhido[1], escolhido[2]


def _recortar_card(img_pil, rosto):
    """Recorta o sujeito/momento principal com realce fotográfico para compor o cartão Hero."""
    from PIL import ImageEnhance

    W, H = img_pil.size
    if rosto is not None:
        fx, fy, fw, fh = rosto
        cw = min(W, max(fw * 3.8, 520))
        ch = cw * 0.76
        if ch > H:
            ch = H
            cw = min(W, ch / 0.76)
        cx = min(max(fx + fw / 2 - cw / 2, 0), W - cw)
        cy = min(max(fy + fh * 0.48 - ch / 2, 0), H - ch)
        card = img_pil.crop((int(cx), int(cy), int(cx + cw), int(cy + ch)))
        card = card.resize((940, 714), img_pil.Resampling.LANCZOS if hasattr(img_pil, "Resampling") else 1)
    else:
        card = img_pil.resize((940, int(940 * H / W)), 1)
        if card.height > 620:
            top = (card.height - 620) // 2
            card = card.crop((0, top, 940, top + 620))

    card = ImageEnhance.Contrast(card).enhance(1.12)
    card = ImageEnhance.Color(card).enhance(1.15)
    card = ImageEnhance.Sharpness(card).enhance(1.22)
    return card


def _fundo_dramatico(img_pil, rosto):
    """Cria fundo vertical desfocado, vibrante e com vinheta escura para destacar texto e cartão."""
    from PIL import Image, ImageDraw, ImageEnhance, ImageFilter

    W, H = img_pil.size
    escala = max(L / W, A / H)
    nw, nh = int(W * escala), int(H * escala)
    bg = img_pil.resize((nw, nh), Image.Resampling.LANCZOS)
    if rosto is not None:
        foco_x = (rosto[0] + rosto[2] / 2) * escala
        left = int(min(max(foco_x - L / 2, 0), max(0, nw - L)))
    else:
        left = max(0, (nw - L) // 2)
    top = max(0, (nh - A) // 2)
    bg = bg.crop((left, top, left + L, top + A))
    bg = bg.filter(ImageFilter.GaussianBlur(radius=18))
    bg = ImageEnhance.Color(bg).enhance(1.25)
    bg = ImageEnhance.Brightness(bg).enhance(0.45)

    grad = Image.new("RGBA", (L, A), (0, 0, 0, 0))
    draw = ImageDraw.Draw(grad)
    for y in range(A):
        if y < 320:
            alpha = int(150 * (1 - y / 320))
        elif y > 820:
            t = min(1.0, (y - 820) / (A - 820))
            alpha = int(215 * (t ** 0.75))
        else:
            alpha = 35
        draw.line([(0, y), (L, y)], fill=(8, 8, 12, alpha))
    return Image.alpha_composite(bg.convert("RGBA"), grad)


def _colar_card_estilizado(canvas, card, x, y, cor_borda):
    """Aplica cantos arredondados, sombra projetada e borda vibrante ao cartão Hero."""
    from PIL import Image, ImageDraw, ImageFilter

    cw, ch = card.size
    raio = 34
    mascara = Image.new("L", (cw, ch), 0)
    ImageDraw.Draw(mascara).rounded_rectangle([(0, 0), (cw - 1, ch - 1)], radius=raio, fill=255)

    sombra = Image.new("RGBA", (cw + 80, ch + 80), (0, 0, 0, 0))
    ImageDraw.Draw(sombra).rounded_rectangle([(40, 40), (cw + 39, ch + 39)], radius=raio, fill=(0, 0, 0, 200))
    sombra = sombra.filter(ImageFilter.GaussianBlur(radius=22))
    canvas.alpha_composite(sombra, (x - 40, y - 30))

    card_rgba = card.convert("RGBA")
    card_rgba.putalpha(mascara)
    canvas.alpha_composite(card_rgba, (x, y))

    overlay_borda = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    ImageDraw.Draw(overlay_borda).rounded_rectangle(
        [(x - 3, y - 3), (x + cw + 2, y + ch + 2)],
        radius=raio + 2,
        outline=cor_borda,
        width=7,
    )
    canvas.alpha_composite(overlay_borda)


def _quebrar_texto(draw, texto, fonte, max_largura):
    """Divide o texto em linhas balanceadas respeitando `max_largura`."""
    palavras = texto.strip().upper().split()
    if not palavras:
        return []
    linhas, atual = [], []
    for p in palavras:
        teste = " ".join([*atual, p])
        bbox = draw.textbbox((0, 0), teste, font=fonte, stroke_width=8)
        if atual and (bbox[2] - bbox[0]) > max_largura:
            linhas.append(" ".join(atual))
            atual = [p]
        else:
            atual.append(p)
    if atual:
        linhas.append(" ".join(atual))
    return linhas


def _escolher_cor_tag(tag):
    t = (tag or "").strip().lower()
    for chave, cores in _CORES_TAG.items():
        if chave in t:
            return cores
    return ("#FFD400", "#0A0A0A")


def _desenhar_badge(canvas, texto, y_centro, cor_fundo, cor_txt, x_centro=None, tam_fonte=38):
    from PIL import Image, ImageDraw, ImageFilter

    txt = (texto or "MOMENTO DA LIVE").strip().upper()
    xc = L // 2 if x_centro is None else x_centro
    fonte = _fonte(["segoeuib.ttf", "arialbd.ttf"], tam_fonte)
    tmp = ImageDraw.Draw(canvas)
    bbox = tmp.textbbox((0, 0), txt, font=fonte)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    pad_x, pad_y = int(tam_fonte * 0.95), int(tam_fonte * 0.45)
    bw, bh = tw + pad_x * 2, th + pad_y * 2
    bx, by = max(16, min(canvas.width - bw - 16, int(xc - bw // 2))), int(y_centro - bh // 2)

    sombra = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    ImageDraw.Draw(sombra).rounded_rectangle([(bx, by + 6), (bx + bw, by + bh + 6)], radius=bh // 2, fill=(0, 0, 0, 170))
    sombra = sombra.filter(ImageFilter.GaussianBlur(radius=10))
    canvas.alpha_composite(sombra)

    camada = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(camada)
    d.rounded_rectangle([(bx, by), (bx + bw, by + bh)], radius=bh // 2, fill=cor_fundo)
    d.text((bx + bw // 2, by + bh // 2), txt, font=fonte, fill=cor_txt, anchor="mm")
    canvas.alpha_composite(camada)
    return bh


def _desenhar_titulo_area(canvas, titulo, x_centro, y_inicio, y_limite, max_w, tam_max=126, tam_min=68, max_linhas=4):
    """Desenha texto gancho gigante com contorno preto, sombra e destaque alternado em amarelo."""
    from PIL import Image, ImageDraw

    draw = ImageDraw.Draw(canvas)
    altura_disp = max(60, y_limite - y_inicio)
    fonte = None
    linhas = []
    for tam in range(tam_max, tam_min - 1, -6):
        f = _fonte(["impact.ttf", "arialbd.ttf", "bahnschrift.ttf"], tam)
        ls = _quebrar_texto(draw, titulo, f, max_w)
        if not ls:
            return
        if len(ls) > max_linhas:
            continue
        entrelinha = int(tam * 1.15)
        if len(ls) * entrelinha <= altura_disp:
            fonte, linhas = f, ls
            break
    if fonte is None:
        fonte = _fonte(["impact.ttf", "arialbd.ttf"], tam_min)
        linhas = _quebrar_texto(draw, titulo, fonte, max_w)[:max_linhas]

    entrelinha = int(fonte.size * 1.14)
    total_h = len(linhas) * entrelinha
    y = y_inicio + max(0, (altura_disp - total_h) // 2)

    camada = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(camada)
    for idx, linha in enumerate(linhas):
        cor = "#FFE600" if (len(linhas) == 1 or idx == len(linhas) - 1 or idx % 2 == 1) else "#FFFFFF"
        if len(linhas) == 3 and idx == 1:
            cor = "#FFE600"
        if len(linhas) == 3 and idx == 2:
            cor = "#FFFFFF"
        cy = y + idx * entrelinha + entrelinha // 2
        d.text((x_centro + 6, cy + 8), linha, font=fonte, fill=(0, 0, 0, 220), anchor="mm", stroke_width=9, stroke_fill=(0, 0, 0, 220))
        d.text((x_centro, cy), linha, font=fonte, fill=cor, anchor="mm", stroke_width=8, stroke_fill="#000000")
    canvas.alpha_composite(camada)


def _desenhar_titulo(canvas, titulo, y_inicio, y_limite):
    """Desenha o texto gancho centralizado na capa vertical 1080x1920."""
    _desenhar_titulo_area(canvas, titulo, L // 2, y_inicio, y_limite, 930)


def _desenhar_rodape(canvas, canal):
    from PIL import Image, ImageDraw

    if not canal:
        return
    txt = f"{canal.strip().upper()}  •  CORTE"
    fonte = _fonte(["segoeuib.ttf", "arialbd.ttf"], 30)
    camada = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(camada)
    d.text((L // 2 + 2, 1612), txt, font=fonte, fill=(0, 0, 0, 180), anchor="mm")
    d.text((L // 2, 1610), txt, font=fonte, fill=(235, 235, 240, 210), anchor="mm")
    canvas.alpha_composite(camada)


def gerar_capa(video, saida, titulo, tag="MOMENTO DA LIVE", canal=""):
    """Gera a capa vertical 1080x1920 em `saida` usando o melhor frame real de `video`."""
    import cv2
    from PIL import Image

    frame_bgr, rosto = escolher_melhor_frame(video)
    img_rgb = Image.fromarray(cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB))

    cor_tag, cor_txt_tag = _escolher_cor_tag(tag)
    canvas = _fundo_dramatico(img_rgb, rosto)
    card = _recortar_card(img_rgb, rosto)
    card_x = (L - card.width) // 2
    card_y = 240
    _colar_card_estilizado(canvas, card, card_x, card_y, cor_tag)
    _desenhar_badge(canvas, tag, card_y, cor_tag, cor_txt_tag)
    _desenhar_titulo(canvas, titulo, card_y + card.height + 34, 1555)
    _desenhar_rodape(canvas, canal)

    Path(saida).parent.mkdir(parents=True, exist_ok=True)
    canvas.convert("RGB").save(str(saida), format="PNG", optimize=True)
    return Path(saida)


def gerar_thumb_youtube(video, saida, titulo, tag="CORTE COMPLETO", canal=""):
    """Gera thumbnail horizontal 1280x720 (16:9) com rosto em destaque e texto fora do rosto."""
    import cv2
    from PIL import Image, ImageDraw, ImageEnhance

    YT_W, YT_H = 1280, 720
    frame_bgr, rosto = escolher_melhor_frame(video, amostras=20)
    img_rgb = Image.fromarray(cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB))

    W, H = img_rgb.size
    escala = max(YT_W / W, YT_H / H)
    nw, nh = int(W * escala), int(H * escala)
    base = img_rgb.resize((nw, nh), Image.Resampling.LANCZOS)
    left = max(0, (nw - YT_W) // 2)
    top = max(0, (nh - YT_H) // 2)
    base = base.crop((left, top, left + YT_W, top + YT_H))
    base = ImageEnhance.Contrast(base).enhance(1.14)
    base = ImageEnhance.Color(base).enhance(1.18)
    base = ImageEnhance.Sharpness(base).enhance(1.22)
    canvas = base.convert("RGBA")

    cx_rosto = None
    if rosto is not None:
        cx_rosto = (rosto[0] + rosto[2] / 2) * escala - left

    grad = Image.new("RGBA", (YT_W, YT_H), (0, 0, 0, 0))
    draw_g = ImageDraw.Draw(grad)
    cor_tag, cor_txt_tag = _escolher_cor_tag(tag)

    if cx_rosto is not None and cx_rosto < YT_W * 0.44:
        # Rosto à esquerda -> texto na direita
        for x in range(YT_W):
            t = max(0.0, min(1.0, (x - 420) / (YT_W - 420)))
            draw_g.line([(x, 0), (x, YT_H)], fill=(8, 8, 12, int(220 * (t ** 0.8))))
        area = (925, 185, 650, 620)
    elif cx_rosto is not None and cx_rosto > YT_W * 0.56:
        # Rosto à direita -> texto na esquerda
        for x in range(YT_W):
            t = max(0.0, min(1.0, (860 - x) / 860))
            draw_g.line([(x, 0), (x, YT_H)], fill=(8, 8, 12, int(220 * (t ** 0.8))))
        area = (355, 185, 650, 620)
    else:
        # Rosto centralizado ou tela cheia -> faixa dramática na parte inferior
        for y in range(YT_H):
            t = max(0.0, min(1.0, (y - 260) / (YT_H - 260)))
            draw_g.line([(0, y), (YT_W, y)], fill=(8, 8, 12, int(230 * (t ** 0.78))))
        area = (YT_W // 2, 370, 1140, 685)

    canvas = Image.alpha_composite(canvas, grad)
    x_centro, y_ini, max_w, y_fim = area
    _desenhar_badge(canvas, tag, y_ini - 48, cor_tag, cor_txt_tag, x_centro=x_centro, tam_fonte=30)
    _desenhar_titulo_area(canvas, titulo, x_centro, y_ini, y_fim, max_w, tam_max=98, tam_min=52, max_linhas=3)

    if canal:
        f_ch = _fonte(["segoeuib.ttf", "arialbd.ttf"], 26)
        cam = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        d = ImageDraw.Draw(cam)
        d.text((YT_W - 28, 32), canal.strip().upper(), font=f_ch, fill=(255, 255, 255, 220), anchor="ra", stroke_width=4, stroke_fill=(0, 0, 0, 200))
        canvas.alpha_composite(cam)

    # Borda sutil cinematográfica 16:9 para destacar no feed claro ou escuro do YouTube
    borda = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    ImageDraw.Draw(borda).rectangle([(0, 0), (YT_W - 1, YT_H - 1)], outline=cor_tag, width=8)
    canvas.alpha_composite(borda)

    Path(saida).parent.mkdir(parents=True, exist_ok=True)
    canvas.convert("RGB").save(str(saida), format="PNG", optimize=True)
    return Path(saida)

