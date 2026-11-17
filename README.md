# OWL CORTES — Máquina de Cortes (Shorts + YouTube 16:9)

Workspace e skill `clipper` para transformar lives e VODs longos (YouTube, Twitch e Kick) em:

1. **Cortes verticais (`cortes/<streamer-live>/`)** prontos para Shorts, Reels e TikTok:
   - Vídeo `1080x1920` (webcam em cima + conteúdo embaixo, legenda sincronizada palavra por palavra)
   - Capa PNG separada (`corte_XX_capa.png`) com detecção facial para nunca tampar o rosto
   - Roteiro de postagem (`corte_XX.txt`) com título, gancho, hashtags e créditos

2. **Vídeos longos completos (`YOUTUBE-POTENCIAL/<streamer>/<live>/`)** para YouTube `16:9`:
   - Sinais automáticos (`[AVISO YOUTUBE-POTENCIAL]`) sempre que uma live/VOD longa tem arco temático completo (`8–15+ min`)
   - Vídeo `1920x1080` (`h264` + `aac`), thumbnail horizontal `1280x720` (`video_XX_thumb.png`) e arquivo `.txt` com título principal, variações A/B, capítulos `00:00`, Short relacionado para linkar no YouTube Studio, tags e créditos

## Estrutura do repositório

- `.agents/skills/clipper/` — Skill completa (`SKILL.md` + scripts Python: `clip.py`, `ouvir.py`, `cortar.py`, `capa.py`, `youtube.py`, `comum.py`)
- `cortes/` — Cortes verticais `1080x1920`, capas e textos prontos para publicação
- `YOUTUBE-POTENCIAL/` — Vídeos longos `16:9`, thumbnails `1280x720` e roteiros/capítulos por streamer e live
- `.vscode/` & `pyrefly.toml` — Configuração do interpretador Python local

> **Nota sobre arquivos locais:** A pasta `.clipper/` (ambiente Python, modelos Whisper/YuNet e downloads brutos das lives) fica ignorada pelo `.gitignore` por conter arquivos temporários de vários GB. Vídeo(s) acima de 100 MB em `YOUTUBE-POTENCIAL/` usam Git LFS (`.gitattributes`).

## Comandos principais

```powershell
.clipper\ambiente\Scripts\python.exe .agents\skills\clipper\scripts\clip.py status
.clipper\ambiente\Scripts\python.exe .agents\skills\clipper\scripts\clip.py potencial
.clipper\ambiente\Scripts\python.exe -u .agents\skills\clipper\scripts\clip.py fazer <live>
.clipper\ambiente\Scripts\python.exe -u .agents\skills\clipper\scripts\clip.py youtube <live>
```

