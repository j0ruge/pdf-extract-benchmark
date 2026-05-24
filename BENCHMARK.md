# Benchmark histórico: pdf-inspector vs MinerU

> Esta análise comparou **pdf-inspector** (Firecrawl) e **MinerU** (OpenDataLab) como extratores de PDF→Markdown para o pipeline de ingest RAG. **MinerU venceu** e virou o único caminho ativo do repo — setup e uso atuais estão no [README.md](README.md). Este documento existe pra registrar a comparação, os números medidos e a decisão.

---

## Ferramentas comparadas

1. **[pdf-inspector](https://github.com/firecrawl/pdf-inspector)** — biblioteca Rust da Firecrawl (rápida, heurística, sem ML)
2. **[MinerU](https://github.com/opendatalab/MinerU)** — pipeline ML com detecção de layout e OCR (Apache-2.0)

> Cenário alvo: ingest de livros técnicos e manuais de equipamento (VDR, ECDIS, AIS) em base RAG, com preservação de blocos de código, tabelas e reading order multicoluna.

---

## Veredito

- **Para ingest final em RAG → MinerU.** Preserva código em fences, tabelas HTML com rowspan/colspan, extrai imagens, e emite JSON estruturado (`_content_list.json`) pronto para chunking.
- **Para classificação rápida no caminho quente → pdf-inspector.** Classifica tipo de PDF e decide roteamento OCR em milissegundos.
- **Pipeline originalmente proposto:** `detect-pdf` (~20ms) decide se vale extração ML; PDFs `text_based` simples vão pro `pdf2md`, PDFs complexos ou com código vão pro MinerU.

> Na prática, o repo acabou só usando MinerU. O ganho de roteamento rápido do pdf-inspector não compensou a manutenção de duas stacks — a perda de qualidade no caminho rápido era grande demais pra base RAG. Mantemos a opção documentada aqui pra referência.

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

## Por que MinerU venceu

1. **Código em fences** — pdf-inspector colapsava listings C# em uma linha sem marcação; MinerU preserva quebras de linha e marca como ```` ```cs ````. Pra RAG técnico, isso é a diferença entre chunk utilizável e chunk lixo.
2. **Tabelas estruturadas** — pdf-inspector emite linhas Markdown achatadas e frequentemente falsas; MinerU emite `<table>` HTML com `rowspan`/`colspan` corretos.
3. **`_content_list.json` pronto pra chunking** — cada bloco tem tipo (`text`, `table`, `image`, `equation`), página e bbox. Não precisa parsear o markdown de volta pra chunkar inteligentemente.
4. **Frontmatter limpo** — pdf-inspector duplicava palavras de capa/TOC; MinerU lida com isso via layout-model.
5. **PT-BR sem corrupção** — testado em PDF de 156 páginas: pipeline `-l latin` produz acentos perfeitos, zero `U+FFFD`.
6. **Reproduzibilidade bit-a-bit** — mesma execução produz SHA-256 idêntico do `.md` e dos JSONs estruturados.

Custo: ~60× mais lento que pdf-inspector em wall-clock, mas continua dentro de **~1 min/livro** com GPU NVIDIA — aceitável pra ingest em batch.

---

## Setup do pdf-inspector (histórico)

Necessário só pra reproduzir o benchmark. **Não é mais parte do fluxo ativo do repo.**

### Pré-requisitos extras

- Rust toolchain estável
- ~500 MB livres em disco pro clone + build do pdf-inspector

### Instalação

```bash
# 1. Rust
winget install Rustlang.Rustup
rustup default stable

# 2. Clone + build do pdf-inspector
git clone https://github.com/firecrawl/pdf-inspector.git
cd pdf-inspector
cargo build --release
cd ..
```

### Uso

```bash
# Classificação + layout (~20 ms)
./pdf-inspector/target/release/detect-pdf.exe arquivo.pdf --analyze --json

# PDF → Markdown (~30-150 ms/página)
./pdf-inspector/target/release/pdf2md.exe arquivo.pdf --raw > saida.md

# JSON estruturado
./pdf-inspector/target/release/pdf2md.exe arquivo.pdf --json
```

---

## Pipeline de ingest RAG (proposta original com 2 ferramentas)

Arquitetura proposta na época do benchmark — substituída por **MinerU direto** na stack atual (ver [README.md](README.md)).

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

## Links

- pdf-inspector: <https://github.com/firecrawl/pdf-inspector>
- MinerU: <https://github.com/opendatalab/MinerU>
- Fire-PDF (blog de lançamento da pdf-inspector): <https://firecrawl.dev/blog/fire-pdf-launch>
