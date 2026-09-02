# pdf-extract-benchmark

Setup e uso do **[MinerU](https://github.com/opendatalab/MinerU)** para extração de PDFs → Markdown estruturado, com foco em ingest RAG (livros técnicos, manuais de equipamento, documentos em PT-BR).

> Este repo nasceu como benchmark entre `pdf-inspector` e MinerU. MinerU venceu e virou o único caminho ativo — comparação completa, números e decisão em [BENCHMARK.md](BENCHMARK.md).

> Testado com **MinerU 3.4.4**. Além de PDF/imagem, aceita **office nativo** (pptx/docx/xlsx) sem LibreOffice.

---

## Setup

### Pré-requisitos

- Windows 10/11 **ou** Linux (o script wrapper roda em ambos)
- ~5 GB livres em disco (~3 GB MinerU + ~3 GB torch CUDA opcional)
- GPU NVIDIA com 8 GB+ VRAM **opcional** (acelera o backend `pipeline` ~60×)
- **`hf_xet`** — pacote que acelera o download dos modelos do Hugging Face (protocolo Xet: paralelo, em chunks, deduplicado). Sem ele, `huggingface_hub` cai no HTTP single-stream (~500 kB/s) e a **primeira execução** leva ~40 min só baixando ~1 GB de modelos (o log avisa `Xet Storage is enabled ... 'hf_xet' package is not installed. Falling back to regular HTTP download`). Os modelos ficam em cache após o primeiro download, então a lentidão é única por máquina. Já incluído no comando de instalação abaixo.
- **Windows Developer Mode habilitado** — obrigatório apenas se for usar um backend VLM (`-b vlm-engine`/`hybrid-engine`). O `huggingface_hub` baixa modelos via symlinks; sem Developer Mode, falha com `WinError 1314 — o cliente não tem o privilégio necessário`. Habilitar em Settings → Privacy & security → For developers, ou via PowerShell admin:

  ```powershell
  New-ItemProperty -Path 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\AppModelUnlock' -Name AllowDevelopmentWithoutDevLicense -PropertyType DWord -Value 1 -Force
  ```

  Backend `pipeline` (default) não precisa disso.

### Instalação

**1. Instale o [`uv`](https://docs.astral.sh/uv/):**

```bash
# Windows
winget install astral-sh.uv

# Linux/macOS
curl -LsSf https://astral.sh/uv/install.sh | sh
```

**2. Prepare o venv (passo único):** o `mineru-md.py` é um wrapper thin — ele **não** instala nada, só assume o venv pronto. Rode:

```bash
# Venv Python 3.12 + MinerU + hf_xet
uv venv --python 3.12 .venv-mineru
uv pip install -p .venv-mineru "mineru[core]" hf_xet

# (Opcional) Torch com CUDA — só se tiver GPU NVIDIA
uv pip install -p .venv-mineru --reinstall --index-url https://download.pytorch.org/whl/cu128 torch torchvision

# Verificar
./.venv-mineru/Scripts/python.exe -c "import torch; print(torch.cuda.is_available(), torch.cuda.get_device_name(0))"
```

---

## Uso

### Atalho: `./mineru-md.py` (recomendado)

Wrapper thin cross-platform (Windows + Linux): contorna o `MAX_PATH` no Windows (copia o PDF para a raiz com nome curto), chama o `mineru` com defaults sensatos e reporta o resultado. Só usa stdlib — roda com `python mineru-md.py …` ou `uv run mineru-md.py …`. **Pré-requisito:** o venv já preparado (ver [Instalação](#instalação)); o script falha cedo com instrução de preparo se faltar.

**Uso:**

```bash
# Caso mais simples
python mineru-md.py "G:\caminho\longo\com espaços\Livro.pdf"

# PDF em inglês (OCR mais preciso pra páginas escaneadas em EN)
python mineru-md.py arquivo.pdf --lang en

# Slug custom da saída (vira mineru_out/livro-frontend/...)
python mineru-md.py arquivo.pdf --name livro-frontend

# Slides / office (pptx, docx, xlsx) — parser nativo do MinerU 3.4.x
python mineru-md.py "apresentacao.pptx"

# Escaneado / muitos gráficos — hybrid com análise de imagem
python mineru-md.py arquivo.pdf --backend hybrid-engine --effort high

# Qualidade máxima via VLM local (~40× mais lento, precisa VRAM)
python mineru-md.py arquivo.pdf --backend vlm-engine

# Manter a cópia local (default: remove após rodar)
python mineru-md.py arquivo.pdf --keep-pdf-copy
```

**Parâmetros:**

| Flag | Default | Descrição |
|---|---|---|
| `arquivo` (posicional) | obrigatório | Caminho do documento: pdf, png/jpg, ou office (pptx/docx/xlsx). |
| `--name` | derivado | Slug para pasta/arquivo de saída. Auto: lowercase + hífens, máx 50 chars. |
| `--lang` | `latin` | Código `-l` do MinerU. Afeta **só OCR** (`latin`→`ch`, cobre PT-BR/EN/ES/FR/IT). |
| `--backend` | `pipeline` | `pipeline`, `vlm-engine`, `hybrid-engine`, `vlm-http-client`, `hybrid-http-client`. Ignorado p/ office. |
| `--effort` | — | `medium`/`high` para backends `hybrid-*` (`high` analisa imagem/gráfico). |
| `--out` | `mineru_out` | Pasta raiz da saída (relativa à raiz do projeto). |
| `--keep-pdf-copy` | off | Não remove a cópia local ao final. |

> As flags `--no-cuda` e `--skip-bootstrap` ainda são aceitas mas **ignoradas** — restos da versão com bootstrap automático, mantidas só por compatibilidade de interface.

O script falha cedo com mensagem clara se: o PDF não existir, for stub de 0 bytes do Google Drive, ou se o binário do `mineru` não estiver no caminho esperado (venv não preparado).

Ao final, imprime caminho absoluto do `.md`, tamanho, contagem de imagens (referenciadas + extraídas), e a posição da primeira ocorrência de `U+FFFD` — útil pra detectar problemas de encoding em PDFs PT-BR antes de enviar pro pipeline RAG.

### MinerU CLI direto

Útil pra debugging e flags avançadas que o wrapper não expõe.

```bash
./.venv-mineru/Scripts/mineru.exe \
  -p arquivo.pdf \
  -o mineru_out \
  -b pipeline \
  -l en
```

Backends (MinerU 3.4.x):

- `pipeline` — layout-model + PaddleOCR (rápido, roda em CPU ou GPU)
- `vlm-engine` — VLM local (qualidade máxima, precisa GPU com muita VRAM)
- `hybrid-engine` — pipeline + VLM (default do CLI; `--effort high` liga análise de imagem/gráfico)
- `vlm-http-client` / `hybrid-http-client` — chamam serviço remoto

> Arquivos office (pptx/docx/xlsx) usam o parser nativo do MinerU e **ignoram** `-b`; a saída cai em `office/`.

Flags úteis:

- `-l latin` — idioma (default `ch`). Para PT-BR use `latin` (alias → `ch`). Ver seção [Processando PDFs em português](#processando-pdfs-em-português-pt-br).
- `--effort medium|high` — só para backends `hybrid-*` (`high` analisa imagem/gráfico, mais lento)
- `-s N -e M` — intervalo de páginas
- `-f true` — parsing de fórmulas → LaTeX
- `-t true` — parsing de tabelas (default on)

### Processando PDFs em português (PT-BR)

A flag `-l/--lang` mapeia para os pacotes de OCR do PaddleOCR. **Não existe código `pt`/`pt_br`** — para português brasileiro use **`-l latin`** (cobre alfabetos latinos: PT/ES/FR/IT/etc.).

Canônicos no MinerU 3.4.x (`--help`): `ch, ch_server, korean, ta, te, ka, th, el, arabic, east_slavic, cyrillic, devanagari`. Os códigos `latin`, `en`, `japan`, `chinese_cht` continuam aceitos como **aliases → `ch`** (o modelo `ch` cobre Chinese/English/Japanese/Latin), então para PT-BR `latin` e `ch` dão o mesmo resultado. `ch_lite` foi removido no 3.4.x.

```bash
# PDF text-based digital (caso comum) — via wrapper, latin é o default
python mineru-md.py arquivo.pdf

# Forçar OCR (texto digital ruim, fontes embedded estranhas)
./.venv-mineru/Scripts/mineru.exe -p arquivo.pdf -o mineru_out -b pipeline -l latin -m ocr

# Qualidade máxima via VLM multilíngue (precisa VRAM)
python mineru-md.py arquivo.pdf --backend vlm-engine
```

Notas (verificadas empiricamente em PDF PT-BR de 156 páginas, `text_based`):

- `-l` **só importa quando há OCR**. PDFs `text_based` extraem texto direto e a flag é praticamente ignorada.
- **Pipeline `-l latin` produziu acentos PT-BR perfeitos** (13.661 caracteres acentuados, zero U+FFFD): "reprodução", "autorização", "citações", "Enéias", "Comissão Teológica" — todos limpos. Em ~7 s.
- **VLM `vlm-engine` produziu qualidade equivalente** (13.688 acentos, zero U+FFFD), mas levou **~5 minutos** (~40× mais lento). Estrutura marginalmente melhor (mais headings detectados), volume de texto quase idêntico (209 KB vs 212 KB).
- **Conclusão para PT-BR digital: use `pipeline -l latin`** — VLM não compensa o custo. VLM só faz diferença real em PDFs escaneados/imagem onde o pacote `latin` do PaddleOCR poderia falhar.
- VLM no Windows precisa de **Developer Mode habilitado** (ver [Pré-requisitos](#pré-requisitos)) — sem isso, o download do modelo HF quebra com `WinError 1314`.

### Saída do MinerU

```
mineru_out/<pdfname>/auto/
├── <pdfname>.md                  # Markdown final
├── <pdfname>_content_list.json   # ← USE ISSO PARA CHUNKING RAG (blocos tipados)
├── <pdfname>_middle.json         # Representação intermediária
├── <pdfname>_layout.pdf          # PDF com bounding boxes do layout (auditoria visual)
├── <pdfname>_span.pdf            # PDF com spans de texto
└── images/*.jpg                  # Figuras extraídas
```

`_content_list.json` é o artefato de produção — cada bloco tem tipo (`text`, `table`, `image`, `equation`), página, e bbox. Use ele direto pra chunking inteligente em vez de re-parsear o `.md`.

> **Office (pptx/docx/xlsx):** a saída fica em `mineru_out/<nome>/office/` (não `auto/`), com os mesmos `.md` + `_content_list.json` + `images/`. O wrapper detecta a subpasta automaticamente.

---

## Pipeline de ingest RAG

```
PDF chega
  │
  └─► python mineru-md.py <pdf>     (GPU ~1 min/livro)
        └─ consumir _content_list.json
              ├─ text  → chunking por heading + tamanho
              ├─ table → embedding separado (preservar HTML com rowspan/colspan)
              ├─ image → vision model / OCR complementar
              └─ equation → LaTeX como-está
```

---

## Relevância JRC

- **DSR / Service Reports escaneados** — backend `pipeline -l latin -m ocr` extrai texto via PaddleOCR; `hybrid-engine --effort high` ou `vlm-engine` quando a qualidade do scan for ruim.
- **Manuais VDR/ECDIS/AIS** — extração ML preserva tabelas de especificação, diagramas e código embarcado em fences.
- **Base RAG do agente técnico** — `_content_list.json` do MinerU fornece chunks prontos com metadados de página e tipo, sem heurística adicional.

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
    ├── .venv-mineru/            # venv Python (~3 GB)
    ├── mineru_out/              # saída MinerU (conteúdo extraído — copyright)
    └── *.pdf                    # PDFs de teste (copyright)
```

PDFs e saídas extraídas **não são versionados** porque contêm material protegido por direitos autorais. Este repo é setup + documentação.

---

## Links

- MinerU: <https://github.com/opendatalab/MinerU>
- Doc MinerU: <https://opendatalab.github.io/MinerU/>
- CLI completo: <https://opendatalab.github.io/MinerU/usage/cli_tools/>
- Parâmetros avançados: <https://opendatalab.github.io/MinerU/usage/advanced_cli_parameters/>

## Licença

Este repositório (setup + documentação): MIT.
MinerU tem licença própria (Apache-2.0).
