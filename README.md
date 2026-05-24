# pdf-extract-benchmark

Setup e uso do **[MinerU](https://github.com/opendatalab/MinerU)** para extração de PDFs → Markdown estruturado, com foco em ingest RAG (livros técnicos, manuais de equipamento, documentos em PT-BR).

> Este repo nasceu como benchmark entre `pdf-inspector` e MinerU. MinerU venceu e virou o único caminho ativo — comparação completa, números e decisão em [BENCHMARK.md](BENCHMARK.md).

---

## Setup

### Pré-requisitos

- Windows 10/11 **ou** Linux (o script wrapper roda em ambos)
- ~5 GB livres em disco (~3 GB MinerU + ~3 GB torch CUDA opcional)
- GPU NVIDIA com 8 GB+ VRAM **opcional** (acelera o backend `pipeline` ~60×)
- **Windows Developer Mode habilitado** — obrigatório apenas se for usar `-b vlm-auto-engine` ou qualquer backend VLM. O `huggingface_hub` baixa modelos via symlinks; sem Developer Mode, falha com `WinError 1314 — o cliente não tem o privilégio necessário`. Habilitar em Settings → Privacy & security → For developers, ou via PowerShell admin:

  ```powershell
  New-ItemProperty -Path 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\AppModelUnlock' -Name AllowDevelopmentWithoutDevLicense -PropertyType DWord -Value 1 -Force
  ```

  Backend `pipeline` (default) não precisa disso.

### Instalação

**Caminho rápido (recomendado):** instale o [`uv`](https://docs.astral.sh/uv/) e rode `python mineru-md.py <pdf>` — o script faz o bootstrap completo do venv + MinerU + torch CUDA na primeira execução.

```bash
# Windows
winget install astral-sh.uv

# Linux/macOS
curl -LsSf https://astral.sh/uv/install.sh | sh
```

**Caminho manual:**

```bash
# Venv Python 3.12 + MinerU
uv venv --python 3.12 .venv-mineru
uv pip install -p .venv-mineru "mineru[core]"

# (Opcional) Torch com CUDA — só se tiver GPU NVIDIA
uv pip install -p .venv-mineru --reinstall --index-url https://download.pytorch.org/whl/cu128 torch torchvision

# Verificar
./.venv-mineru/Scripts/python.exe -c "import torch; print(torch.cuda.is_available(), torch.cuda.get_device_name(0))"
```

---

## Uso

### Atalho: `./mineru-md.py` (recomendado)

Script Python cross-platform (Windows + Linux) que automatiza todo o fluxo: bootstrap do venv na primeira execução, contorno de `MAX_PATH` no Windows (copia o PDF para a raiz com nome curto), chamada do `mineru` com defaults sensatos e relatório do resultado. Só usa stdlib — roda com `python mineru-md.py …` ou `uv run mineru-md.py …`.

**Primeira execução em máquina nova:** o script detecta que `.venv-mineru/` ainda não existe e dispara o bootstrap automaticamente. Pré-requisito único é o [`uv`](https://docs.astral.sh/uv/) instalado.

O bootstrap então faz: `uv venv --python 3.12 .venv-mineru` → `uv pip install mineru[core]` → se `nvidia-smi` for encontrado, instala também `torch` com CUDA (pula com `--no-cuda`).

**Uso:**

```bash
# Caso mais simples
python mineru-md.py "G:\caminho\longo\com espaços\Livro.pdf"

# PDF em inglês (OCR mais preciso pra páginas escaneadas em EN)
python mineru-md.py arquivo.pdf --lang en

# Slug custom da saída (vira mineru_out/livro-frontend/...)
python mineru-md.py arquivo.pdf --name livro-frontend

# Qualidade máxima via VLM (~40× mais lento, precisa VRAM)
python mineru-md.py arquivo.pdf --backend vlm-auto-engine

# Manter a cópia local do PDF (default: remove após rodar)
python mineru-md.py arquivo.pdf --keep-pdf-copy

# Bootstrap já feito → pular verificação (falha cedo se faltar venv)
python mineru-md.py arquivo.pdf --skip-bootstrap
```

**Parâmetros:**

| Flag | Default | Descrição |
|---|---|---|
| `pdf` (posicional) | obrigatório | Caminho do PDF (relativo ou absoluto). |
| `--name` | derivado | Slug para pasta/arquivo de saída. Auto: lowercase + hífens, máx 50 chars. |
| `--lang` | `latin` | Código `-l` do MinerU. Afeta OCR (`latin` cobre PT-BR/EN/ES/FR/IT). |
| `--backend` | `pipeline` | `pipeline`, `vlm-auto-engine`, `hybrid-auto-engine`, etc. |
| `--out` | `mineru_out` | Pasta raiz da saída (relativa à raiz do projeto). |
| `--keep-pdf-copy` | off | Não remove a cópia local do PDF ao final. |
| `--no-cuda` | off | No bootstrap, não tenta instalar `torch+CUDA` mesmo se houver GPU. |
| `--skip-bootstrap` | off | Assume venv pronto; falha rápido se faltar. |

O script falha cedo com mensagem clara se: o PDF não existir, for stub de 0 bytes do Google Drive, `uv` não estiver no PATH no momento do bootstrap, ou se o binário do `mineru` não estiver no caminho esperado.

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
# PDF text-based digital (caso comum) — via wrapper, latin é o default
python mineru-md.py arquivo.pdf

# Forçar OCR (texto digital ruim, fontes embedded estranhas)
./.venv-mineru/Scripts/mineru.exe -p arquivo.pdf -o mineru_out -b pipeline -l latin -m ocr

# Qualidade máxima via VLM multilíngue (precisa VRAM)
python mineru-md.py arquivo.pdf --backend vlm-auto-engine
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

`_content_list.json` é o artefato de produção — cada bloco tem tipo (`text`, `table`, `image`, `equation`), página, e bbox. Use ele direto pra chunking inteligente em vez de re-parsear o `.md`.

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

- **DSR / Service Reports escaneados** — backend `pipeline -l latin -m ocr` extrai texto via PaddleOCR; `vlm-auto-engine` quando a qualidade do scan for ruim.
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
