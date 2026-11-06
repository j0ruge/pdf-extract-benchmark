# CLAUDE.md — pdf-extract-benchmark

Contexto para sessões do Claude Code neste repositório.

## O que é este repo

Setup do **MinerU** (OpenDataLab, ML, Apache-2.0) para extração de PDFs → Markdown estruturado pra ingest RAG. Sem código próprio — só wrapper Python, docs e benchmarks empíricos.

O repo nasceu como benchmark comparando MinerU vs `pdf-inspector` (Firecrawl/Rust). **MinerU venceu** (preserva código com fences, tabelas HTML, imagens, JSON estruturado pronto pra chunking) e virou o caminho único — comparação completa e números em [`BENCHMARK.md`](BENCHMARK.md).

Versão testada: **MinerU 4.1.7**. A 4.x quebrou a CLI da 3.x; a tabela de equivalências está em "Migração da 3.x" no [`README.md`](README.md).

## Ambiente

- Windows 10 Pro 19045, PowerShell (preferir; Bash via tool também funciona)
- GPU NVIDIA RTX 3060 Ti 8 GB
- Python 3.12 isolado em `.venv-mineru/` (uv), com `mineru[torch]` e `torch` CUDA (`+cu128`)
- **Ao atualizar o MinerU, não use `uv pip install -U`**: ele pode trocar o `torch` CUDA pela build de CPU do PyPI. Instale só `"mineru[torch]==<versão>"` e confira com `torch.cuda.is_available()`.
- Modelos em `~/.mineru/models` (`mineru-kit models download --tier basic`, ~0,85 GB). Os caches da 3.x em `~/.cache/huggingface` não são usados pela 4.x.
- **`hf_xet` instalado no venv** — sem ele o download dos modelos HF cai no HTTP single-stream lento (~500 kB/s, ~40 min para ~1 GB; log avisa `'hf_xet' package is not installed. Falling back to regular HTTP download`). Instalar com `uv pip install -p .venv-mineru hf_xet`.
- **Windows Developer Mode = ON** — era pré-requisito na 3.x para baixar modelos VLM (`WinError 1314`, por causa de symlinks). A 4.x grava arquivos comuns (zero symlinks no tier `basic`), mas isso não foi testado com o Developer Mode desligado nem com os modelos VLM. Foi habilitado neste setup via:
  ```powershell
  # PowerShell admin, executado uma vez
  New-ItemProperty -Path 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\AppModelUnlock' -Name AllowDevelopmentWithoutDevLicense -PropertyType DWord -Value 1 -Force
  ```
  O Claude Code roda sem privilégio admin neste ambiente — não tente alterar HKLM via shell normal, vai falhar com "Requested registry access is not allowed". Se uma sessão futura precisar desligar/religar, peça pro usuário fazer.
- **Via WSL:** a working tree é CRLF e o `git` do WSL mostra os 5 arquivos versionados como modificados. Use `git diff --ignore-cr-at-eol` e preserve o CRLF ao editar. Para rodar o venv, chame `./.venv-mineru/Scripts/python.exe` e `mineru-kit.exe`; caminhos absolutos passam por `wslpath -w`.

## Comandos canônicos

```powershell
# Entry point preferencial — wrapper Python cross-platform (não instala nada, assume o venv pronto)
python mineru-md.py arquivo.pdf

# Mesma coisa, especificando tier e OCR
python mineru-md.py arquivo.pdf --tier basic --ocr-mode auto

# MinerU CLI direto — pra debugging ou flags que o wrapper não expõe
./.venv-mineru/Scripts/mineru-kit.exe parse arquivo.pdf -o saida.md --tier basic --pages 1-5
```

⚠️ Armadilhas do CLI direto:
- `mineru-kit parse` **sem `--tier` usa `standard`** (VLM) em PDF/imagem. O wrapper sempre passa `basic`.
- Formatos nativos com um único arquivo **só aceitam `--tier flash`**; passar `basic` dá erro. Sem `--tier`, o kit escolhe `flash`. O wrapper omite `--tier` nesses casos.
- `-f markdown` grava só o `.md`, com as imagens embutidas em base64. `images/` e JSON só vêm com `-f zip`.
- `mineru parse` é outro comando: usa biblioteca e cache, e por padrão lê só as **10 primeiras páginas** do PDF.
- `mineru -p ...` não existe mais (`No such option: -p`).

## Tiers do MinerU

- `flash` — parser nativo, sem modelos. Único tier dos formatos nativos. Em PDF é rápido, mas perde estrutura: no CV de teste, perdeu a tabela e 8 títulos.
- `basic` — modelos pequenos (Torch, com GPU). **Default do wrapper**, equivale ao antigo `pipeline`.
- `standard` / `advanced` — modelos pequenos + VLM local (engine efetiva aqui: `llama-cpp`; ~2 GB a mais de modelos). **Não testados neste setup.**

## Processando PDFs em português (PT-BR)

A 4.x **não tem `--lang`/`-l`**: nem a CLI nem o SDK expõem o idioma do OCR, que usa por padrão o modelo `ch` (cobre Latin). É o mesmo modelo para o qual o `-l latin` da 3.4 já apontava, então nada muda para PT-BR. Idiomas fora desse modelo deixaram de ter seleção pela CLI.

Notas importantes (verificadas empiricamente na 4.1.7, comparando com a saída da 3.x dos mesmos PDFs, `--tier basic`):
- **Acentos PT-BR limpos, zero `U+FFFD`**: livro de 95 págs. (8.082 → 8.083 acentos, 1:22, ou 2:30 na 1ª execução), livro de 201 págs. com figuras e fórmulas (10.022 → 10.028, 2:22), documento de 19 págs. (1.212 → 1.217, 0:41), CV de 6 págs. (329 → 332, 0:24).
- **A saída é determinística**: duas execuções geraram `.md` idênticos byte a byte.
- A 4.x corrigiu palavras que a 3.x colava (`dosfilipenses` → `dos filipenses`).
- GPU confirmada em uso: 100% de utilização, pico de 2,7 GB de VRAM.
- **`--ocr-mode ocr` só foi testado em PDF digital de 1 página. Um scan real não foi testado na 4.x.**
- Na 3.x (PDF de 156 págs.), o VLM deu qualidade equivalente ao `pipeline`, mas ~40× mais lento. Para PT-BR digital, o VLM não compensou.
- ⚠️ **Cuidado ao diagnosticar acentos via console**: o Git Bash no Windows e o pipe do WSL para o Python do Windows renderizam UTF-8 PT-BR como `�` em alguns prints, mesmo quando os bytes do arquivo estão corretos. Sempre verifique com `grep -c $'\xef\xbf\xbd'` ou Python (`txt.count(chr(0xFFFD))`) antes de acusar a ferramenta. Aprendi errado uma vez nesta sessão.

```powershell
# Recomendado para PT-BR digital ou misto
python mineru-md.py arquivo.pdf

# Forçar OCR (texto ruim, fontes embedded estranhas)
python mineru-md.py arquivo.pdf --ocr-mode ocr

# Qualidade máxima via VLM (precisa VRAM e de: mineru-kit models download --tier standard)
python mineru-md.py arquivo.pdf --tier standard
```

## Formatos nativos (office, OpenDocument, HTML, MHTML, CSV, EPUB, OFD)

O MinerU parseia esses formatos **nativamente** (sem LibreOffice nem modelos) — basta `python mineru-md.py slides.pptx`. `--tier` e `--ocr-mode` não se aplicam. A lista exata está em `mineru/filetypes.py`, e o wrapper mantém um espelho dela (`TIERED_SUFFIXES` e `NATIVE_SUFFIXES`): ao atualizar o MinerU, confira se ainda bate.

Verificado na 4.1.7 (DOCX de 62 KB com 41 tabelas): 884 de 884 células e 61 de 61 títulos iguais ao original, 5 s. Limitação: JSON dentro de tabela de uma célula no Word sai como `<table>` HTML, não como bloco de código.

Verificado na 3.4.4 (PPTX PT-BR, slides text-based):
- ⚠️ Slides com texto "queimado" em imagem (bitmap) **não** são OCR-ados pelo parser nativo — nesse caso, exportar o PPTX para PDF e rodar `--ocr-mode ocr`.

## Saída do MinerU

```
mineru_out/<nome>/
├── <nome>.md                 # Markdown final
├── <nome>_content_list.json  # USE PARA CHUNKING RAG (blocos tipados)
├── structured_content.json   # Documento agrupado por página (formato novo da 4.x)
├── middle_json.json          # Representação intermediária
└── images/                   # Figuras extraídas
```

`<nome>_content_list.json` é o artefato de produção — cada bloco tem tipo (`text`, `table`, `image`, `equation`), página, e bbox (escala 0–1000). Tem as mesmas chaves da 3.x, mas o `mineru-kit` não o exporta: o wrapper o gera a partir do `middle_json.json` com `mineru.render.render_content_list`, usando o Python do venv.

`_layout.pdf`, `_span.pdf` e as subpastas `auto/`/`office/` só existem em saídas antigas da 3.x.

## Arquivos não versionados

`.gitignore` exclui — não tentar commitar:
- `.venv-mineru/` (~5 GB)
- `mineru_out/`, `mineru_out_v2/`, etc. (conteúdo extraído de PDFs com copyright)
- `*.pdf` (PDFs de teste com copyright)
- saídas `out_*.md`, `mineru_*_run.log`

## Fontes oficiais

- Doc MinerU: https://opendatalab.github.io/MinerU/
- CLI completo: https://opendatalab.github.io/MinerU/usage/cli_tools/
- Migração da 3.x para a 4.0: https://opendatalab.github.io/MinerU/reference/migration_4/
- Formatos de saída: https://opendatalab.github.io/MinerU/reference/output_files/
- Modelos e configuração: https://opendatalab.github.io/MinerU/usage/model_source/
