# CLAUDE.md — pdf-extract-benchmark

Contexto para sessões do Claude Code neste repositório.

## O que é este repo

Setup do **MinerU** (OpenDataLab, ML, Apache-2.0) para extração de PDFs → Markdown estruturado pra ingest RAG. Sem código próprio — só wrapper Python, docs e benchmarks empíricos.

O repo nasceu como benchmark comparando MinerU vs `pdf-inspector` (Firecrawl/Rust). **MinerU venceu** (preserva código com fences, tabelas HTML, imagens, JSON estruturado pronto pra chunking) e virou o caminho único — comparação completa e números em [`BENCHMARK.md`](BENCHMARK.md).

## Ambiente

- Windows 10 Pro 19045, PowerShell (preferir; Bash via tool também funciona)
- GPU NVIDIA RTX 3060 Ti 8 GB (acelera MinerU ~60×)
- Python 3.12 isolado em `.venv-mineru/` (uv)
- **`hf_xet` instalado no venv** — sem ele o download inicial dos modelos HF cai no HTTP single-stream lento (~500 kB/s, ~40 min para ~1 GB; log avisa `'hf_xet' package is not installed. Falling back to regular HTTP download`). Com ele usa o protocolo Xet (paralelo, em chunks). Instalar com `uv pip install -p .venv-mineru hf_xet`. Modelos ficam em cache após o 1º download.
- **Windows Developer Mode = ON** (pré-requisito p/ qualquer backend VLM). Sem isso, `huggingface_hub` quebra ao baixar modelos com `WinError 1314` porque tenta criar symlinks. Foi habilitado neste setup via:
  ```powershell
  # PowerShell admin, executado uma vez
  New-ItemProperty -Path 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\AppModelUnlock' -Name AllowDevelopmentWithoutDevLicense -PropertyType DWord -Value 1 -Force
  ```
  O Claude Code roda sem privilégio admin neste ambiente — não tente alterar HKLM via shell normal, vai falhar com "Requested registry access is not allowed". Se uma sessão futura precisar desligar/religar, peça pro usuário fazer.

## Comandos canônicos

```powershell
# Entry point preferencial — wrapper Python cross-platform com bootstrap automático
python mineru-md.py arquivo.pdf

# Mesma coisa, especificando lang/backend
python mineru-md.py arquivo.pdf --lang latin --backend pipeline

# MinerU CLI direto — pra debugging ou flags que o wrapper não expõe
./.venv-mineru/Scripts/mineru.exe -p arquivo.pdf -o mineru_out -b pipeline -l en
```

## Processando PDFs em português (PT-BR)

A flag `-l/--lang` do MinerU mapeia para os pacotes de OCR do PaddleOCR. **Não existe código `pt` ou `pt_br`.** Para português brasileiro use **`-l latin`** (cobre todos os alfabetos latinos: PT/ES/FR/IT/etc.).

Códigos aceitos pelo backend `pipeline`:
`ch, ch_server, ch_lite, en, korean, japan, chinese_cht, ta, te, ka, th, el, latin, arabic, east_slavic, cyrillic, devanagari`

Notas importantes (verificadas empiricamente em PDF PT-BR de 156 páginas, `text_based`):
- `-l` **só afeta OCR**. PDFs `text_based` extraem texto direto e a flag é praticamente ignorada.
- **`pipeline -l latin` produziu acentos PT-BR perfeitos**: 13.661 chars acentuados, **zero `U+FFFD`**. "reprodução", "autorização", "Enéias", "Comissão Teológica" — todos limpos. ~7 s no GPU.
- **`vlm-auto-engine` produziu qualidade equivalente** (13.688 acentos, zero quebrados), mas em **~5 min** (~40× mais lento). Volume e cobertura de texto quase idênticos (209 KB pipeline vs 212 KB VLM).
- **Recomendação para PT-BR digital: pipeline `-l latin`.** VLM só vale a pena para PDFs escaneados/imagem onde o pacote `latin` do PaddleOCR poderia falhar — não testado neste setup.
- ⚠️ **Cuidado ao diagnosticar acentos via console**: o Git Bash no Windows renderiza UTF-8 PT-BR como `�` em alguns prints, mesmo quando os bytes do arquivo estão corretos. Sempre verifique com `grep -c $'\xef\xbf\xbd'` ou Python (`txt.count(chr(0xFFFD))`) antes de acusar a ferramenta. Aprendi errado uma vez nesta sessão.
- Para usar VLM, **Windows Developer Mode é obrigatório** (ver "Ambiente"). Sem isso, download do modelo `MinerU2.5-Pro-2604-1.2B` quebra com `WinError 1314`.

```powershell
# Recomendado para PT-BR digital ou misto
./.venv-mineru/Scripts/mineru.exe -p arquivo.pdf -o mineru_out -b pipeline -l latin

# Forçar OCR (texto ruim, fontes embedded estranhas)
./.venv-mineru/Scripts/mineru.exe -p arquivo.pdf -o mineru_out -b pipeline -l latin -m ocr

# Qualidade máxima via VLM (precisa VRAM)
./.venv-mineru/Scripts/mineru.exe -p arquivo.pdf -o mineru_out -b vlm-auto-engine
```

## Backends do MinerU (default mudou)

- `pipeline` — layout-model + PaddleOCR. Rápido em GPU, bom default.
- `hybrid-auto-engine` — **default atual**. Combina pipeline + VLM.
- `hybrid-http-client`, `vlm-http-client` — chamam serviço remoto.
- `vlm-auto-engine` — VLM local, qualidade máxima, alto consumo de VRAM.

## Saída do MinerU

```
mineru_out/<pdfname>/auto/
├── <pdfname>.md                  # Markdown final
├── <pdfname>_content_list.json   # USE PARA CHUNKING RAG (blocos tipados)
├── <pdfname>_middle.json         # Representação intermediária
├── <pdfname>_layout.pdf          # Auditoria visual (bounding boxes)
├── <pdfname>_span.pdf            # Spans de texto
└── images/*.jpg                  # Figuras extraídas
```

`_content_list.json` é o artefato de produção — cada bloco tem tipo (`text`, `table`, `image`, `equation`), página, e bbox.

## Arquivos não versionados

`.gitignore` exclui — não tentar commitar:
- `.venv-mineru/` (~3 GB)
- `mineru_out/`, `mineru_out_v2/`, etc. (conteúdo extraído de PDFs com copyright)
- `*.pdf` (PDFs de teste com copyright)
- saídas `out_*.md`, `mineru_*_run.log`

## Fontes oficiais

- Doc MinerU: https://opendatalab.github.io/MinerU/
- CLI completo: https://opendatalab.github.io/MinerU/usage/cli_tools/
- Parâmetros avançados: https://opendatalab.github.io/MinerU/usage/advanced_cli_parameters/
