# pdf-extract-benchmark

Setup e uso do **[MinerU](https://github.com/opendatalab/MinerU)** para extração de PDFs → Markdown estruturado, com foco em ingest RAG (livros técnicos, manuais de equipamento, documentos em PT-BR).

> Este repo nasceu como benchmark entre `pdf-inspector` e MinerU. MinerU venceu e virou o único caminho ativo — comparação completa, números e decisão em [BENCHMARK.md](BENCHMARK.md).

> Testado com **MinerU 4.1.7** no Windows. Além de PDF/imagem, aceita **formatos nativos** (office, OpenDocument, HTML, MHTML, CSV, EPUB, OFD) sem LibreOffice nem modelos. Vindo da 3.x? Veja [Migração da 3.x](#migração-da-3x).

---

## Setup

### Pré-requisitos

- Windows 10/11 **ou** Linux (o script wrapper roda em ambos)
- ~6 GB livres em disco (venv com torch CUDA ~5 GB + modelos do tier `basic` ~0,85 GB). Os tiers `standard`/`advanced` pedem ~2 GB a mais.
- GPU NVIDIA com 8 GB+ VRAM **opcional** (acelera o tier `basic`; na 3.x o ganho medido foi de ~60×)
- **`hf_xet`** — pacote que acelera o download dos modelos do Hugging Face (protocolo Xet: paralelo, em chunks, deduplicado). Sem ele, `huggingface_hub` cai no HTTP single-stream (~500 kB/s) e o download de ~1 GB de modelos leva ~40 min (o log avisa `Xet Storage is enabled ... 'hf_xet' package is not installed. Falling back to regular HTTP download`). Já incluído no comando de instalação abaixo.
- **Windows Developer Mode** — era obrigatório na 3.x para baixar modelos VLM (`WinError 1314`, por causa de symlinks). Na 4.x os modelos ficam em `~/.mineru/models` como arquivos comuns (zero symlinks no tier `basic`), então o requisito provavelmente caiu. Isso não foi testado com o Developer Mode desligado nem com os modelos VLM. Se o erro aparecer, habilite em Settings → Privacy & security → For developers, ou via PowerShell admin:

  ```powershell
  New-ItemProperty -Path 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\AppModelUnlock' -Name AllowDevelopmentWithoutDevLicense -PropertyType DWord -Value 1 -Force
  ```

### Instalação

**1. Instale o [`uv`](https://docs.astral.sh/uv/):**

```bash
# Windows
winget install astral-sh.uv

# Linux/macOS
curl -LsSf https://astral.sh/uv/install.sh | sh
```

**2. Prepare o venv e os modelos:** o `mineru-md.py` é um wrapper thin — ele **não** instala nada, só assume o venv pronto. Rode:

```bash
# Venv Python 3.12 + MinerU + hf_xet
uv venv --python 3.12 .venv-mineru
uv pip install -p .venv-mineru "mineru[torch]>=4.1,<5" hf_xet

# (Opcional) Torch com CUDA — só se tiver GPU NVIDIA
uv pip install -p .venv-mineru --reinstall --index-url https://download.pytorch.org/whl/cu128 torch torchvision

# Verificar
./.venv-mineru/Scripts/python.exe -c "import torch; print(torch.cuda.is_available(), torch.cuda.get_device_name(0))"

# Modelos do tier basic (~0,85 GB, em ~/.mineru/models). Formatos nativos e --tier flash não precisam deles.
./.venv-mineru/Scripts/mineru-kit.exe models download --tier basic
./.venv-mineru/Scripts/mineru-kit.exe models verify --tier basic
```

---

## Uso

### Atalho: `./mineru-md.py` (recomendado)

Wrapper thin cross-platform (Windows + Linux): contorna o `MAX_PATH` no Windows (copia o arquivo para a raiz com nome curto), chama o `mineru-kit parse` com defaults sensatos, gera o content list para RAG e reporta o resultado. Só usa stdlib — roda com `python mineru-md.py …` ou `uv run mineru-md.py …`. **Pré-requisito:** o venv já preparado (ver [Instalação](#instalação)); o script falha cedo com instrução de preparo se faltar.

**Uso:**

```bash
# Caso mais simples (tier basic)
python mineru-md.py "G:\caminho\longo\com espaços\Livro.pdf"

# Slug custom da saída (vira mineru_out/livro-frontend/...)
python mineru-md.py arquivo.pdf --name livro-frontend

# Slides / office / HTML / EPUB — parser nativo, sem modelos
python mineru-md.py "apresentacao.pptx"

# Forçar OCR (texto digital ruim, fontes embedded estranhas)
python mineru-md.py arquivo.pdf --ocr-mode ocr

# PDF digital simples, sem modelos (rápido, mas pode perder tabelas e títulos)
python mineru-md.py arquivo.pdf --tier flash

# Layout difícil — VLM local (antes: mineru-kit models download --tier standard)
python mineru-md.py arquivo.pdf --tier standard

# Manter a cópia local (default: remove após rodar)
python mineru-md.py arquivo.pdf --keep-pdf-copy
```

**Parâmetros:**

| Flag | Default | Descrição |
|---|---|---|
| `arquivo` (posicional) | obrigatório | Caminho do documento: PDF, imagem ou formato nativo. |
| `--name` | derivado | Slug para pasta/arquivo de saída. Auto: lowercase + hífens, máx 50 chars. |
| `--tier` | `basic` | `flash`, `basic`, `standard`, `advanced`. Só para PDF/imagem; formatos nativos sempre usam `flash`. |
| `--ocr-mode` | `auto` | `auto`, `txt`, `ocr`. Só para PDF/imagem. |
| `--out` | `mineru_out` | Pasta raiz da saída (relativa à raiz do projeto). |
| `--keep-pdf-copy` | off | Não remove a cópia local ao final. |

> As flags `--no-cuda` e `--skip-bootstrap` ainda são aceitas mas **ignoradas** — restos da versão com bootstrap automático, mantidas só por compatibilidade de interface.

O script falha cedo com mensagem clara se: o arquivo não existir, for stub de 0 bytes do Google Drive, tiver extensão não suportada, ou se o binário do `mineru-kit` não estiver no caminho esperado (venv não preparado). A cópia local é removida também quando o parse falha.

Ao final, imprime caminho absoluto do `.md` e do content list, tamanho, contagem de imagens (referenciadas + extraídas), e a posição da primeira ocorrência de `U+FFFD` — útil pra detectar problemas de encoding em PDFs PT-BR antes de enviar pro pipeline RAG.

### Tiers

| Tier | O que usa | Quando usar |
|---|---|---|
| `flash` | Parser nativo, sem modelos | PDF digital simples. No CV de teste (6 págs.), levou 5 s contra 24 s do `basic`, mas perdeu a tabela e 8 títulos. |
| `basic` | Modelos pequenos (Torch, com GPU) | **Default do wrapper.** Equivale ao antigo backend `pipeline`. |
| `standard` / `advanced` | Modelos pequenos + VLM local | Layouts difíceis. **Não testado neste setup.** |

### MinerU CLI direto

Útil pra debugging e flags avançadas que o wrapper não expõe.

```bash
# Só o Markdown, com intervalo de páginas
./.venv-mineru/Scripts/mineru-kit.exe parse arquivo.pdf -o saida.md --tier basic --pages 1-5,8

# Diretório inteiro: um zip por arquivo
./.venv-mineru/Scripts/mineru-kit.exe parse ./documentos -o ./saida --format zip --tier basic
```

- ⚠️ **Sempre passe `--tier` em PDF/imagem.** Sem ele, o `mineru-kit parse` usa `standard`, que roda o VLM.
- ⚠️ **Formatos nativos com um único arquivo só aceitam `--tier flash`.** Passar `--tier basic` dá erro; sem `--tier`, o kit escolhe `flash` sozinho.
- ⚠️ **`-f markdown` grava só o `.md`, com as imagens embutidas em base64**, o que pode inflar bastante o arquivo. Para ter `images/` e JSON, use `-f zip`.
- ⚠️ **`mineru parse` é outro comando:** usa biblioteca de documentos e cache, e por padrão lê só as **10 primeiras páginas** de um PDF (`--pages all` para tudo). Aqui usamos o `mineru-kit parse`, que lê tudo.

### Processando PDFs em português (PT-BR)

A 4.x **não tem mais `--lang`/`-l`**: nem a CLI nem o SDK expõem o idioma do OCR, que usa por padrão o modelo `ch` (cobre Chinese/English/Japanese/Latin). É o mesmo modelo para o qual o `-l latin` da 3.4 já apontava, então nada muda para PT-BR. Idiomas fora desse modelo (coreano, árabe, cirílico etc.) deixaram de ter seleção pela CLI.

Medições da 4.1.7 com `--tier basic`, comparando com a saída da 3.x dos mesmos PDFs:

| PDF PT-BR | Páginas | Tempo | Palavras 3.x → 4.x | Acentos 3.x → 4.x | `U+FFFD` |
|---|---|---|---|---|---|
| Livro de texto | 95 | 1:22 (2:30 na 1ª execução) | 39.813 → 39.824 | 8.082 → 8.083 | 0 |
| Livro com 198 figuras e fórmulas | 201 | 2:22 | 46.418 → 47.021 | 10.022 → 10.028 | 0 |
| Documento de texto | 19 | 0:41 | 7.478 → 7.504 | 1.212 → 1.217 | 0 |
| CV com tabela e imagem | 6 | 0:24 | 1.679 → 1.697 | 329 → 332 | 0 |

- A 4.x corrigiu palavras que a 3.x colava: `dosfilipenses` → `dos filipenses`, `longoprazo` → `longo prazo`. A diferença de palavras no livro com fórmulas vem sobretudo da notação LaTeX (`array` → `pmatrix`) e dos nomes de imagem, que entram na contagem.
- GPU confirmada em uso: 100% de utilização, pico de 2,7 GB de VRAM.
- `--ocr-mode ocr` foi testado num PDF digital de 1 página, com o mesmo número de acentos da 3.x. **Um scan real não foi testado na 4.x.**
- Os tempos não são comparáveis aos ~7 s para 156 páginas medidos na 3.x, que vieram de outro PDF.

Referência histórica da 3.x (PDF de 156 páginas com texto): o VLM deu qualidade equivalente ao `pipeline` (13.688 contra 13.661 acentos), mas ~40× mais lento. Para PT-BR digital, o VLM não compensou o custo.

### Saída do MinerU

```
mineru_out/<nome>/
├── <nome>.md                 # Markdown final
├── <nome>_content_list.json  # ← USE ISSO PARA CHUNKING RAG (blocos tipados)
├── structured_content.json   # Documento agrupado por página (formato novo da 4.x)
├── middle_json.json          # Representação intermediária
└── images/                   # Figuras extraídas (page_0_image_3.jpg)
```

`<nome>_content_list.json` é o artefato de produção — cada bloco tem tipo (`text`, `table`, `image`, `equation`), página, e bbox (escala 0–1000). Tem as mesmas chaves da 3.x, mas é gerado pelo wrapper: o `mineru-kit` não exporta esse formato. Use ele direto pra chunking inteligente em vez de re-parsear o `.md`.

Mudanças em relação à 3.x:

- Não há mais subpastas `auto/` e `office/`, e todo formato cai direto em `mineru_out/<nome>/`. Saídas antigas continuam onde estão.
- `_layout.pdf` e `_span.pdf` **não são mais gerados** — não há mais a auditoria visual por bounding boxes.
- O `middle_json.json` mudou de esquema: não dependa de campos antigos como `pdf_info` ou `_backend`.
- Imagens agora têm nome legível, não mais hash.
- Formatos nativos usam tipos extras no content list, como `list` e `index`.

### Migração da 3.x

| MinerU 3.x | MinerU 4.x |
|---|---|
| `mineru -p arq.pdf -o saida -b pipeline -l latin` | `mineru-kit parse arq.pdf -o saida.md --tier basic` |
| `mineru-md.py --backend pipeline` | `mineru-md.py --tier basic` (default) |
| `--backend vlm-engine`/`hybrid-engine`, `--effort` | `--tier standard`/`advanced` (sem equivalência exata) |
| `--lang`/`-l` | Removido |
| `-m ocr` | `--ocr-mode ocr` |
| `-s N -e M` | `--pages N-M` (só no CLI direto) |
| `mineru[core]` | `mineru[torch]` |
| `~/mineru.json` | `~/.mineru/config.yaml` |
| `~/.cache/huggingface` (PDF-Extract-Kit, MinerU2.5) | `~/.mineru/models` (modelos novos; os antigos não são reaproveitados) |

Para atualizar um venv existente, **não use `-U`**: ele pode trocar o `torch` CUDA pela build de CPU do PyPI. Instale só a versão do MinerU e baixe os modelos novos:

```bash
uv pip install -p .venv-mineru "mineru[torch]==4.1.7"
./.venv-mineru/Scripts/mineru-kit.exe models download --tier basic
```

---

## Pipeline de ingest RAG

```
PDF chega
  │
  └─► python mineru-md.py <pdf>     (GPU: ~1,5–2,5 min para 100–200 páginas)
        └─ consumir <nome>_content_list.json
              ├─ text  → chunking por heading + tamanho
              ├─ table → embedding separado (preservar HTML com rowspan/colspan)
              ├─ image → vision model / OCR complementar
              └─ equation → LaTeX como-está
```

---

## Relevância JRC

- **DSR / Service Reports escaneados** — `--ocr-mode ocr` extrai texto via OCR; `--tier standard` quando a qualidade do scan for ruim (nenhum dos dois caminhos foi testado com um scan real na 4.x).
- **Manuais VDR/ECDIS/AIS** — extração ML preserva tabelas de especificação, diagramas e código embarcado em fences.
- **Base RAG do agente técnico** — `<nome>_content_list.json` fornece chunks prontos com metadados de página e tipo, sem heurística adicional.

---

## Estrutura do repo

```
pdf-extract-benchmark/
├── README.md                    # este arquivo (setup + uso atual)
├── BENCHMARK.md                 # comparação histórica pdf-inspector vs MinerU
├── CLAUDE.md                    # contexto p/ Claude Code (comandos, PT-BR, ambiente)
├── mineru-md.py                 # wrapper cross-platform (Win+Linux)
├── .gitignore
└── (NÃO COMITADOS — gerados localmente)
    ├── .venv-mineru/            # venv Python (~5 GB)
    ├── mineru_out/              # saída MinerU (conteúdo extraído — copyright)
    └── *.pdf                    # PDFs de teste (copyright)
```

PDFs e saídas extraídas **não são versionados** porque contêm material protegido por direitos autorais. Este repo é setup + documentação.

---

## Links

- MinerU: <https://github.com/opendatalab/MinerU>
- Doc MinerU: <https://opendatalab.github.io/MinerU/>
- CLI completo: <https://opendatalab.github.io/MinerU/usage/cli_tools/>
- Migração da 3.x para a 4.0: <https://opendatalab.github.io/MinerU/reference/migration_4/>
- Formatos de saída: <https://opendatalab.github.io/MinerU/reference/output_files/>
- Modelos e configuração: <https://opendatalab.github.io/MinerU/usage/model_source/>

## Licença

Este repositório (setup + documentação): MIT.
MinerU tem licença própria (Apache-2.0).
