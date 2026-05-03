# fire_pdf

Benchmark e pipeline de extração de PDFs técnicos para RAG, comparando:

1. **[pdf-inspector](https://github.com/firecrawl/pdf-inspector)** — biblioteca Rust da Firecrawl (rápida, heurística, sem ML)
2. **[MinerU](https://github.com/opendatalab/MinerU)** — pipeline ML com detecção de layout e OCR (Apache-2.0)

> Cenário alvo: ingest de livros técnicos e manuais de equipamento (VDR, ECDIS, AIS) em base RAG, com preservação de blocos de código, tabelas e reading order multicoluna.

---

## Veredito

- **Para ingest final em RAG → MinerU.** Preserva código em fences, tabelas HTML com rowspan/colspan, extrai imagens, e emite JSON estruturado (`_content_list.json`) pronto para chunking.
- **Para classificação rápida no caminho quente → pdf-inspector.** Classifica tipo de PDF e decide roteamento OCR em milissegundos.
- **Pipeline recomendado:** `detect-pdf` (~20ms) decide se vale extração ML; PDFs `text_based` simples vão pro `pdf2md`, PDFs complexos ou com código vão pro MinerU.

---

## Resultados do benchmark

### PDF de teste
`Agile Principles, Patterns, and Practices in C#` (Martin & Martin, 2006) — **944 páginas, 13 MB, `text_based`**, com código C# extenso, diálogos em 2 colunas, tabelas financeiras e listings de classes.

### Números

| Métrica | pdf-inspector (CPU) | MinerU (GPU RTX 3060 Ti 8GB) |
|---|---|---|
| Tempo total | **1.0 s** | 63 s |
| Tamanho markdown | 1.17 MB | 1.15 MB |
| Linhas | 12.859 | 20.633 |
| Headings detectados | 1.166 | 940 |
| Blocos de código (` ``` `) | **0** | **340** (`cs`) |
| Tabelas | 416 linhas MD (muitas falsas) | 14 `<table>` HTML estruturadas |
| Imagens extraídas | 0 | ~340 `.jpg` |
| Fórmulas LaTeX | não | sim (`-f` flag) |

### Qualidade por critério

| Critério | pdf-inspector | MinerU |
|---|---|---|
| Prosa | limpa | limpa |
| Código C# | colapsado em 1 linha, sem fences | preservado com quebras e fences `cs` |
| Frontmatter | palavras duplicadas (capa/TOC) | limpo |
| Cap. 6 (diálogo RCM/RSK) | fatiado em tabelas quebradas | diálogo em prosa |
| Tabelas financeiras | heurística erra | HTML com merged cells |
| Reading order multicoluna | ok na maioria | ok |

---

## Setup

### Pré-requisitos

- Windows 10/11 (testado em 10 Pro 19045)
- ~5 GB livres em disco (~500 MB Rust + ~3 GB MinerU)
- GPU NVIDIA com 8 GB+ VRAM **opcional** (acelera MinerU 60×+)
- **Windows Developer Mode habilitado** (obrigatório se for usar `-b vlm-auto-engine` ou qualquer backend VLM). O `huggingface_hub` baixa modelos via symlinks; sem Developer Mode, falha com `WinError 1314 — o cliente não tem o privilégio necessário`. Habilitar em Settings → Privacy & security → For developers, ou via PowerShell admin:
  ```powershell
  New-ItemProperty -Path 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\AppModelUnlock' -Name AllowDevelopmentWithoutDevLicense -PropertyType DWord -Value 1 -Force
  ```
  Backend `pipeline` não precisa disso.

### Instalação

**1. Rust toolchain** (para `pdf-inspector`)
```bash
winget install Rustlang.Rustup
rustup default stable
```

**2. uv** (gerenciador Python isolado, para MinerU)
```bash
winget install astral-sh.uv
```

**3. Clone `pdf-inspector` e compile**
```bash
cd fire_pdf
git clone https://github.com/firecrawl/pdf-inspector.git
cd pdf-inspector
cargo build --release
cd ..
```

**4. Venv Python 3.12 + MinerU**
```bash
uv venv --python 3.12 .venv-mineru
uv pip install -p .venv-mineru "mineru[core]"
```

**5. (Opcional) Torch com CUDA** (só se tiver GPU NVIDIA)
```bash
uv pip install -p .venv-mineru --reinstall --index-url https://download.pytorch.org/whl/cu128 torch torchvision
```
Verificar:
```bash
./.venv-mineru/Scripts/python.exe -c "import torch; print(torch.cuda.is_available(), torch.cuda.get_device_name(0))"
```

---

## Uso

### pdf-inspector (rápido, sem ML)

```bash
# Classificação + layout (~20 ms)
./pdf-inspector/target/release/detect-pdf.exe arquivo.pdf --analyze --json

# PDF → Markdown (~30-150 ms/página)
./pdf-inspector/target/release/pdf2md.exe arquivo.pdf --raw > saida.md

# JSON estruturado
./pdf-inspector/target/release/pdf2md.exe arquivo.pdf --json
```

### MinerU (ML, qualidade alta)

```bash
./.venv-mineru/Scripts/mineru.exe \
  -p arquivo.pdf \
  -o mineru_out \
  -b pipeline \
  -l en
```

Backends:
- `pipeline` — layout-model + PaddleOCR (rápido, roda em CPU ou GPU)
- `vlm-auto-engine` — VLM local (qualidade máxima, precisa GPU com muita VRAM)
- `hybrid-auto-engine` — combina ambos

Flags úteis:
- `-l en` / `-l latin` — idioma (default `ch`). Para PT-BR use `latin`. Ver seção [Processando PDFs em português](#processando-pdfs-em-português-pt-br).
- `-s N -e M` — intervalo de páginas
- `-f true` — parsing de fórmulas → LaTeX
- `-t true` — parsing de tabelas (default on)

### Processando PDFs em português (PT-BR)

A flag `-l/--lang` mapeia para os pacotes de OCR do PaddleOCR. **Não existe código `pt`/`pt_br`** — para português brasileiro use **`-l latin`** (cobre alfabetos latinos: PT/ES/FR/IT/etc.).

Códigos aceitos pelo backend `pipeline` (fonte: [doc oficial](https://opendatalab.github.io/MinerU/usage/cli_tools/)):
`ch, ch_server, ch_lite, en, korean, japan, chinese_cht, ta, te, ka, th, el, latin, arabic, east_slavic, cyrillic, devanagari`

```bash
# PDF text-based digital (caso comum)
./.venv-mineru/Scripts/mineru.exe -p arquivo.pdf -o mineru_out -b pipeline -l latin

# Forçar OCR (texto digital ruim, fontes embedded estranhas)
./.venv-mineru/Scripts/mineru.exe -p arquivo.pdf -o mineru_out -b pipeline -l latin -m ocr

# Qualidade máxima via VLM multilíngue (precisa VRAM)
./.venv-mineru/Scripts/mineru.exe -p arquivo.pdf -o mineru_out -b vlm-auto-engine
```

Notas (verificadas empiricamente em PDF PT-BR de 156 páginas, `text_based`):
- `-l` **só importa quando há OCR**. PDFs `text_based` extraem texto direto e a flag é praticamente ignorada.
- **Pipeline `-l latin` produziu acentos PT-BR perfeitos** (13.661 caracteres acentuados, zero U+FFFD): "reprodução", "autorização", "citações", "Enéias", "Comissão Teológica" — todos limpos. Em ~7 s.
- **VLM `vlm-auto-engine` produziu qualidade equivalente** (13.688 acentos, zero U+FFFD), mas levou **~5 minutos** (~40× mais lento). Estrutura marginalmente melhor (mais headings detectados), volume de texto quase idêntico (209 KB vs 212 KB).
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

---

## Pipeline de ingest RAG (recomendado)

```
PDF chega
  │
  ├─► detect-pdf (Rust, ~20 ms)
  │     ├─ text_based simples? → pdf2md → done
  │     └─ mixed/escaneado/complex? ↓
  │
  └─► MinerU (GPU, ~1 min/livro)
        └─ consumir _content_list.json
              ├─ text  → chunking por heading + tamanho
              ├─ table → embedding separado (preservar HTML)
              ├─ image → vision model / OCR complementar
              └─ equation → LaTeX como-está
```

---

## Relevância JRC

- **DSR / Service Reports escaneados** — pipeline híbrido identifica e roteia só o que precisa
- **Manuais VDR/ECDIS/AIS** — extração ML preserva tabelas de especificação e diagramas
- **Base RAG do agente técnico** — `_content_list.json` do MinerU fornece chunks prontos com metadados de página e tipo

---

## Estrutura do repo

```
fire_pdf/
├── README.md                    # este arquivo
├── CLAUDE.md                    # contexto p/ Claude Code (comandos, PT-BR, ambiente)
├── .gitignore
└── (NÃO COMITADOS — gerados localmente)
    ├── pdf-inspector/           # clone do repo upstream
    ├── .venv-mineru/            # venv Python
    ├── mineru_out/              # saída MinerU (contém conteúdo do PDF — copyright)
    ├── out_agile.md             # saída pdf-inspector
    ├── out_agile_mineru.md      # saída MinerU
    └── *.pdf                    # PDFs de teste (copyright)
```

PDFs e saídas extraídas **não são versionados** porque contêm material protegido por direitos autorais. Este repo é setup + documentação.

---

## Links

- pdf-inspector: https://github.com/firecrawl/pdf-inspector
- MinerU: https://github.com/opendatalab/MinerU
- Fire-PDF (blog de lançamento): https://firecrawl.dev/blog/fire-pdf-launch

## Licença

Este repositório (setup + documentação): MIT.
As ferramentas têm licenças próprias (pdf-inspector MIT, MinerU Apache-2.0).
