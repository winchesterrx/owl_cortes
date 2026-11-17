---
name: clipper
description: >-
  Transforma lives e vídeos longos (YouTube, Twitch ou Kick) em cortes verticais (1080x1920)
  prontos para Reels, Shorts e TikTok — com câmera do streamer em cima, conteúdo embaixo,
  título de gancho, legenda palavra por palavra e arquivo .txt com post, hashtags e créditos.
  Use quando o usuário pedir para cortar uma live/vídeo, buscar lives para cortar, instalar/verificar
  o clipper, ou enviar um link de live pedindo cortes.
---

# Clipper de Lives (Antigravity)

Você (o agente) cuida da **curadoria editorial**: ler os blocos da transcrição, identificar os melhores
momentos, dar notas e escrever título gancho + legenda do post. Todo o processamento pesado (download,
transcrição local, detecção de picos de áudio/chat, detecção de webcam e renderização com ffmpeg) é
executado pelos scripts em `scripts/` dentro desta skill.

Fale com o usuário em português simples e objetivo, avisando quando uma etapa demorada estiver rodando.

## Caminhos e Comando Base

- Script principal: `python ".agents/skills/clipper/scripts/clip.py" COMANDO`
- Cache pesado (venv, modelos, áudio/trabalho): `.clipper/` na raiz do workspace (ou `CLIPPER_HOME`)
- Cortes finais prontos (`.mp4` e `.txt`): `cortes/` na raiz do workspace (ou `CLIPPER_CORTES_DIR`)
- Vídeos longos para YouTube (`16:9` + thumb `1280×720` + `.txt`): `YOUTUBE-POTENCIAL/<streamer>/<live>/` (ou `CLIPPER_YOUTUBE_DIR`)

> [!IMPORTANT]
> No ambiente com sandbox, os comandos que acessam a internet (`instalar`, `buscar`, `baixar`,
> `preparar` sem `--so-processar`, e a etapa de download do `fazer`) exigem rede. Separe o download do
> processamento local quando útil (`baixar` -> `processar`, `fazer --so-baixar` -> `fazer`).

## 0. Instalar / Atualizar (`instalar`)

Execute:
```powershell
python ".agents/skills/clipper/scripts/clip.py" instalar
```
Ele cria `.clipper/ambiente`, instala dependências (`faster-whisper`, `opencv-python-headless`,
`numpy`, `yt-dlp[default]`, `certifi`, `static-ffmpeg`), verifica `ffmpeg`/`ffprobe`, baixa o
detector facial YuNet e pré-baixa os modelos Whisper `base` e `small`.

## 1. Buscar Lives no YouTube (`buscar`)

Quando o usuário pedir para encontrar lives sobre algum assunto/jogo:
```powershell
python ".agents/skills/clipper/scripts/clip.py" buscar "termo 1" "termo 2" --quantas 7
```
Flags úteis: `--br` (prioriza streamers brasileiros), `--gta6` (exclui falsos positivos de GTA 5 / RP) e `--todas-datas` (busca além de hoje).
Mostre título, canal, duração, views e link, e pergunte quais cortar (ou siga direto com as 3
primeiras se o usuário já pediu para cortar).

## 2. Cortar uma Live — Fluxo Completo

### 2.1 Baixar e Preparar
Para baixar áudio + chat (rede) e depois processar localmente (Whisper + análise de picos):
```powershell
python ".agents/skills/clipper/scripts/clip.py" baixar "LINK"
python ".agents/skills/clipper/scripts/clip.py" processar NOME-DA-LIVE
```
*(Ou rode `preparar "LINK"` direto. Se não for PT nem EN, passe `--idioma` ex.: `--idioma es`. Para
transcrição mais rápida, `--modelo tiny`.)*

Isso gera blocos de 12 minutos em `.clipper/trabalho/NOME-DA-LIVE/blocos/bloco_NN.txt`.

### 2.2 Escolher os Momentos (Sua Curadoria)
Leia **cada bloco** (`bloco_01.txt`, `bloco_02.txt`…) com `read_file` e grave os momentos em
`.clipper/trabalho/NOME-DA-LIVE/momentos/bloco_NN.json` com `write_file` (use `[]` se não houver
nada bom naquele bloco).

Cada linha traz `[hh:mm:ss] fala` e pode incluir sinais auxiliares:
- `[ALTO +12dB]` — pico de volume do streamer (grito, susto, gargalhada, surto)
- `[CHAT 3.1x]` — aceleração no replay do chat do YouTube
- `(reação/sem fala)` — pico de áudio ou chat ocorrido em momento sem palavras transcritas

Marca sozinha não garante corte bom: confirme pelo contexto da fala.

**O que vale um corte:**
- Primeira reação forte a algo inesperado (revelação, surpresa, susto, bug)
- Descoberta curiosa, detalhe escondido ou jogada absurda
- Surto, raiva genuína, risada contagiante ou falha hilária
- Opinião forte/polêmica ou discussão que prende atenção
- História ou piada curta que fecha sozinha sem precisar de contexto anterior

**Descarte com rigor:**
- Trechos dependentes de contexto longo de minutos anteriores
- Inícios com enrolação ("é…", "então…", "voltando aqui…", "uh, so yeah")
- Leitura de donate/sub, propaganda, papo técnico sobre a live, pausa ou tela parada
- Fala confusa ou picotada demais para entender

**Nota de 0 a 100:**
- `90+`: altíssimo potencial viral (qualquer pessoa para de rolar o feed)
- `70–89`: corte sólido e compartilhável
- `< 60`: nem inclua no JSON (espere de 0 a 3 momentos por bloco; não force quantidade)

**Regra dos primeiros 3 segundos (Gancho Viral — OBRIGATÓRIO):**
- Os **primeiros 1 a 3 segundos** do corte precisam prender quem está rolando o feed imediatamente (pergunta forte, afirmação polêmica, surto, reação ou punchline).
- **NUNCA** comece o `inicio` com leitura de nome/valor de donate ("Fulano mandou R$ 20 e cobriu a taxa…"), saudações vazias ("Fala Dava, beleza?"), nem resto de frase anterior ("…para você.").
- Pule o preâmbulo: aponte o `inicio` direto para a frase-gancho (ou `0,5s–1s` antes dela, consultando os timestamps exatos de `transcricao.json` se precisar ajustar ao segundo certo sem cortar a primeira palavra).
- Depois de gerar o `.ass` ou antes de entregar, confira se as primeiras palavras da legenda começam direto no gancho.

**Duração:** ideal entre `20` e `60` segundos (limites técnicos: `15s` a `90s`). Termine logo após a conclusão/reação.

**Formato de `momentos/bloco_NN.json`:**
```json
[
  {
    "inicio": "01:12:03",
    "fim": "01:12:41",
    "nota": 88,
    "tipo": "primeira reação",
    "titulo": "ELE NÃO ACREDITOU NO QUE ACONTECEU",
    "porque": "reação imediata e engraçada; fecha sozinho sem contexto",
    "post": "A reação dele diz tudo nessa hora 😂 #cortes #live #gaming #clips"
  }
]
```

- `titulo`: gancho escrito em cima do vídeo. Curto (até ~45 caracteres), em MAIÚSCULAS, no idioma
  da live, sem entregar o desfecho. Use o nome/apelido do streamer quando somar apelo.
- `capa_texto` *(opcional)*: se quiser uma frase ainda mais curta/chamativa só para a thumbnail
  separada (`corte_NN_capa.png`), caso contrário usa `titulo`.
- `capa_tag` *(opcional)*: selo curto no topo da capa (ex.: `"DESABAFO"`, `"SURTO AO VIVO"`,
  `"POLÊMICA"`, `"REVELAÇÃO"`; padrão usa `tipo`).
- `post`: legenda pronta com 1–2 frases + 4 a 6 hashtags adequadas ao assunto/jogo/streamer da live.

### 2.3 Ranquear os Melhores (`escolher`)
```powershell
python ".agents/skills/clipper/scripts/clip.py" escolher NOME-DA-LIVE --manter 3
```
Junta todos os blocos, ordena por nota, remove sobreposições e mostra os selecionados.

### 2.4 Montar os Vídeos e Capas (`fazer`)
Se quiser separar rede de renderização local:
```powershell
python ".agents/skills/clipper/scripts/clip.py" fazer NOME-DA-LIVE --so-baixar
python ".agents/skills/clipper/scripts/clip.py" fazer NOME-DA-LIVE
```
*(Para gerar/refazer apenas as capas separadas sem re-renderizar o vídeo: adicione `--so-capa`.)*
Ou rode direto `fazer NOME-DA-LIVE`. Ele baixa apenas os trechos necessários, localiza a webcam do
streamer (ou aplica fundo desfocado caso não haja câmera), gera **capa/thumbnail vertical separada**
com o melhor frame real da live, legenda palavra por palavra e salva:
- `cortes/NOME-DA-LIVE/corte_01.mp4`
- `cortes/NOME-DA-LIVE/corte_01_capa.png` (thumbnail vertical 1080×1920 pronta para Shorts/Reels/TikTok)
- `cortes/NOME-DA-LIVE/corte_01.txt` (título + post + crédito com link original)

Informe os caminhos finais ao usuário.

## 3. Modo YOUTUBE-POTENCIAL (Contexto Completo 16:9 para YouTube)

Mantenha o fluxo normal de Shorts/TikTok (`cortes/`) intacto. **Dentro dessa mesma curadoria**, fique atento ao que pode virar vídeo completo (`5 a 15+ min`) para o YouTube e **avise o usuário** (`[AVISO YOUTUBE-POTENCIAL]`):

- **Quando gerar:**
  - Quando um tema de um Short viral tiver **história/conversa completa do começo ao fim** na live (ex.: uma saga inteira de GTA RP, uma partida completa ou um debate longo de 6–15 minutos sem cortes bruscos) — **priorizando lives longas (1h+)** ou compilados multi-streamer para evitar reupload de vídeo curto já editado.
- **Onde gravar o roteiro:**
  - `.clipper/trabalho/NOME-DA-LIVE/youtube/video_01.json`:
```json
{
  "streamer": "Nome do Canal",
  "titulo": "TÍTULO FORTE DE ALTO CTR PARA YOUTUBE",
  "titulos_ab": ["VARIAÇÃO A", "VARIAÇÃO B"],
  "thumb_texto": "TEXTO CURTO NA THUMB",
  "thumb_tag": "CONTEXTO COMPLETO",
  "short_relacionado": "cortes/NOME-DA-LIVE/corte_01.mp4",
  "descricao": "Resumo atrativo do que acontece do começo ao fim...",
  "tags": ["gta 6", "cortes"],
  "trechos": [
    {
      "inicio": "00:25:15",
      "fim": "00:35:31",
      "capitulo": "A negociação completa"
    }
  ]
}
```
  *(Opcional: um item em `trechos` pode incluir `"live": "OUTRA-LIVE"` para compilados multi-streamer.)*
- **Comandos:**
  - `python ".agents/skills/clipper/scripts/clip.py" potencial [NOME-DA-LIVE]` — audita o potencial YouTube das lives
  - `python ".agents/skills/clipper/scripts/clip.py" youtube NOME-DA-LIVE [--so-baixar] [--so-thumb]` — gera em `YOUTUBE-POTENCIAL/<streamer>/<live>/`:
    - `video_01.mp4` (`1920×1080`, `16:9` widescreen)
    - `video_01_thumb.png` (`1280×720` thumbnail horizontal com destaque facial)
    - `video_01.txt` (títulos A/B, descrição com capítulos `00:00`, tags, short relacionado e créditos)

## Dicas e Solução de Problemas
- Use `python ".agents/skills/clipper/scripts/clip.py" status` para checar o progresso de cada live.
- Tudo é retomável por etapa: nada já processado é refeito sem necessidade.
- Para trocar um momento depois de rodar `escolher`: edite `momentos/bloco_NN.json` e rode
  `escolher` e `fazer` de novo (o cache do trecho verifica timestamps e só baixa novamente se o
  intervalo mudar).
- Respeite as regras de uso de cada criador e mantenha os créditos do arquivo `.txt`.

