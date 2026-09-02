#!/usr/bin/env python3
"""
mineru-md.py — wrapper thin para extrair markdown de um documento via MinerU.

Aceita PDF, imagem (png/jpg) e office (pptx/docx/xlsx). No MinerU 3.4.x os
arquivos office sao parseados nativamente (sem LibreOffice) e a saida cai na
subpasta `office/` em vez de `auto/` — o wrapper detecta e reporta corretamente.

Delega para o CLI do MinerU instalado em .venv-mineru/bin/mineru (Python 3.12).
Assume que o venv já foi preparado (setup manual ou primeira execução de
`uv pip install -p .venv-mineru "mineru[core]"`).

Funcionalidades:
1. Copia o arquivo para a raiz do projeto com nome curto (slug), preservando a
   extensao (o MinerU roteia o parser pelo sufixo), para evitar caminhos longos
   no Windows.
2. Invoca o mineru CLI com os parâmetros fornecidos.
3. Verifica a saída gerada: tamanho, contagem de imagens, caracteres U+FFFD.
4. Remove a cópia local ao final (a menos que --keep-pdf-copy).

Exemplos:
    python mineru-md.py livro.pdf
    python mineru-md.py slides.pptx
    python mineru-md.py escaneado.pdf --backend hybrid-engine --effort high
    python mineru-md.py arquivo.pdf --name livro-frontend --keep-pdf-copy
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV = ROOT / ".venv-mineru"

# MinerU 3.4.x: canonicos (PUBLIC_OCR_LANGUAGES) + aliases que mapeiam p/ 'ch'.
# 'latin'/'en'/'japan'/'chinese_cht' sao aliases -> 'ch' (o modelo 'ch' cobre
# Chinese/English/Japanese/Latin). 'ch_lite' foi removido no 3.4.x.
LANG_CHOICES = [
    "ch", "ch_server", "en", "japan", "chinese_cht", "latin",
    "korean", "ta", "te", "ka", "th", "el",
    "arabic", "east_slavic", "cyrillic", "devanagari",
]

BACKEND_CHOICES = [
    "pipeline", "vlm-engine", "hybrid-engine",
    "vlm-http-client", "hybrid-http-client",
]

EFFORT_CHOICES = ["medium", "high"]

# Sufixos "office": MinerU 3.4.x parseia nativamente (sem LibreOffice) e grava
# a saida na subpasta "office/" em vez de "auto/".
OFFICE_SUFFIXES = {".docx", ".pptx", ".xlsx"}
SUPPORTED_SUFFIXES = {".pdf", ".png", ".jpg", ".jpeg"} | OFFICE_SUFFIXES


def mineru_binary() -> Path:
    if sys.platform == "win32":
        return VENV / "Scripts" / "mineru.exe"
    return VENV / "bin" / "mineru"


def die(msg: str, code: int = 1) -> None:
    print(f"ERRO: {msg}", file=sys.stderr)
    sys.exit(code)


def slugify(name: str, maxlen: int = 50) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    if len(slug) > maxlen:
        slug = slug[:maxlen].rstrip("-")
    return slug or "pdf"


def fmt_elapsed(seconds: float) -> str:
    s = int(seconds)
    return f"{s // 3600:02d}:{(s % 3600) // 60:02d}:{s % 60:02d}"


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Extrai markdown de um PDF via MinerU (thin wrapper).",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    ap.add_argument("pdf", metavar="arquivo",
                    help="caminho do arquivo de origem (pdf/png/jpg/docx/pptx/xlsx)")
    ap.add_argument("--name",
                    help="slug para a pasta/arquivo de saida (default: derivado do nome do arquivo)")
    ap.add_argument("--lang", default="latin", choices=LANG_CHOICES,
                    help="codigo -l do MinerU ('latin' -> alias p/ 'ch', cobre PT-BR/EN/ES/FR/IT)")
    ap.add_argument("--backend", default="pipeline", choices=BACKEND_CHOICES,
                    help="backend do MinerU (ignorado para office: pptx/docx/xlsx)")
    ap.add_argument("--effort", default=None, choices=EFFORT_CHOICES,
                    help="esforco do backend hybrid-* (high analisa imagem/grafico; so p/ hybrid-*)")
    ap.add_argument("--out", default="mineru_out",
                    help="pasta raiz de saida, relativa a raiz do projeto")
    ap.add_argument("--keep-pdf-copy", action="store_true",
                    help="nao remover a copia local do PDF apos a extracao")
    # Mantidos para compatibilidade de interface — ignorados (venv já pronto)
    ap.add_argument("--no-cuda", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--skip-bootstrap", action="store_true", help=argparse.SUPPRESS)
    args = ap.parse_args()

    # --- Verifica venv pronto ------------------------------------------------
    bin_path = mineru_binary()
    if not bin_path.exists():
        die(
            f"MinerU nao encontrado em {bin_path}\n\n"
            "Prepare o venv manualmente com:\n"
            f"    uv pip install -p {VENV} \"mineru[core]\" hf_xet\n"
            "Ou execute o setup do README."
        )

    # --- Resolve arquivo fonte ------------------------------------------------
    src = Path(args.pdf).expanduser()
    if not src.exists():
        die(f"arquivo nao encontrado: {src}")
    src = src.resolve()
    if src.stat().st_size == 0:
        die(f"arquivo '{src}' tem 0 bytes.")
    suffix = src.suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        die(f"extensao nao suportada: '{suffix}' "
            f"(suportadas: {', '.join(sorted(SUPPORTED_SUFFIXES))})")
    is_office = suffix in OFFICE_SUFFIXES

    # --- Deriva short name & copia localmente ---------------------------------
    # Preserva o sufixo real: o MinerU roteia o parser pela extensao do arquivo.
    name = args.name or slugify(src.stem)
    local_file = ROOT / f"{name}{suffix}"
    src_size = src.stat().st_size

    copied = False
    if not local_file.exists() or local_file.stat().st_size != src_size:
        print(f"Copiando arquivo -> {local_file}")
        shutil.copy2(src, local_file)
        copied = True
    else:
        print(f"Copia local ja existe: {local_file} (reutilizando)")

    # --- Roda mineru ----------------------------------------------------------
    abs_out = (ROOT / args.out).resolve()
    abs_out.mkdir(parents=True, exist_ok=True)
    cmd = [
        str(bin_path),
        "-p", str(local_file),
        "-o", str(abs_out),
        "-b", args.backend,
    ]
    if args.lang:
        cmd += ["-l", args.lang]
    if args.effort and args.backend.startswith("hybrid"):
        cmd += ["--effort", args.effort]

    print(f"Rodando: {' '.join(cmd)}")
    t0 = time.monotonic()
    rc = subprocess.run(cmd, cwd=ROOT).returncode
    elapsed = time.monotonic() - t0
    print(f"Elapsed: {fmt_elapsed(elapsed)}")
    if rc != 0:
        die(f"mineru falhou com exit code {rc}", code=rc)

    # --- Verifica e reporta ---------------------------------------------------
    # Office (pptx/docx/xlsx) grava em "office/"; PDF/imagem grava em "auto/".
    subdir = "office" if is_office else "auto"
    md_path = abs_out / name / subdir / f"{name}.md"
    if not md_path.exists():
        # Fallback: estrutura sem subpasta
        md_path = abs_out / name / f"{name}.md"
    if not md_path.exists():
        die(f"markdown esperado nao foi gerado: {md_path}")

    raw = md_path.read_text(encoding="utf-8")
    bytes_ = md_path.stat().st_size
    images = raw.count("![")
    fffd_pos = raw.find("\ufffd")
    img_dir = abs_out / name / subdir / "images"
    img_count = sum(1 for _ in img_dir.iterdir()) if img_dir.exists() else 0
    fffd_msg = "limpo" if fffd_pos == -1 else f"QUEBRADO (primeiro U+FFFD em pos {fffd_pos})"

    print()
    print("==== Resultado ====")
    print(f"Markdown:     {md_path}")
    print(f"Tamanho:      {bytes_} bytes ({bytes_/1024/1024:.2f} MB)")
    print(f"Imagens ref:  {images} embutidas no .md")
    print(f"Imagens dir:  {img_count} arquivos em images/")
    print(f"U+FFFD:       {fffd_msg}")

    # --- Cleanup ----------------------------------------------------------------
    if copied and not args.keep_pdf_copy:
        local_file.unlink()
        print(f"Copia local removida: {local_file}")

    return 0


if __name__ == "__main__":
    sys.exit(main())