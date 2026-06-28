#!/usr/bin/env python3
"""
mineru-md.py — wrapper thin para extrair markdown de um PDF via MinerU.

Delega para o CLI do MinerU instalado em .venv-mineru/bin/mineru (Python 3.12).
Assume que o venv já foi preparado (setup manual ou primeira execução de
`uv pip install -p .venv-mineru "mineru[core]"`).

Funcionalidades:
1. Copia o PDF para a raiz do projeto com nome curto (slug) para evitar
   caminhos longos no Windows.
2. Invoca o mineru CLI com os parâmetros fornecidos.
3. Verifica a saída gerada: tamanho, contagem de imagens, caracteres U+FFFD.
4. Remove a cópia local do PDF ao final (a menos que --keep-pdf-copy).

Exemplos:
    python mineru-md.py livro.pdf
    python mineru-md.py arquivo.pdf --lang en --backend vlm-auto-engine
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

LANG_CHOICES = [
    "ch", "ch_server", "ch_lite", "en", "korean", "japan", "chinese_cht",
    "ta", "te", "ka", "th", "el", "latin", "arabic", "east_slavic",
    "cyrillic", "devanagari",
]

BACKEND_CHOICES = [
    "pipeline", "vlm-auto-engine", "hybrid-auto-engine",
    "vlm-http-client", "hybrid-http-client",
]


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
    ap.add_argument("pdf", help="caminho do PDF de origem (relativo ou absoluto)")
    ap.add_argument("--name",
                    help="slug para a pasta/arquivo de saida (default: derivado do nome do PDF)")
    ap.add_argument("--lang", default="latin", choices=LANG_CHOICES,
                    help="codigo -l do MinerU ('latin' cobre PT-BR/EN/ES/FR/IT)")
    ap.add_argument("--backend", default="pipeline", choices=BACKEND_CHOICES,
                    help="backend do MinerU")
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

    # --- Resolve PDF fonte ----------------------------------------------------
    src = Path(args.pdf).expanduser()
    if not src.exists():
        die(f"PDF nao encontrado: {src}")
    src = src.resolve()
    if src.stat().st_size == 0:
        die(f"PDF '{src}' tem 0 bytes.")

    # --- Deriva short name & copia localmente ---------------------------------
    name = args.name or slugify(src.stem)
    local_pdf = ROOT / f"{name}.pdf"
    src_size = src.stat().st_size

    copied = False
    if not local_pdf.exists() or local_pdf.stat().st_size != src_size:
        print(f"Copiando PDF -> {local_pdf}")
        shutil.copy2(src, local_pdf)
        copied = True
    else:
        print(f"Copia local ja existe: {local_pdf} (reutilizando)")

    # --- Roda mineru ----------------------------------------------------------
    abs_out = (ROOT / args.out).resolve()
    abs_out.mkdir(parents=True, exist_ok=True)
    cmd = [
        str(bin_path),
        "-p", str(local_pdf),
        "-o", str(abs_out),
        "-b", args.backend,
    ]
    if args.lang:
        cmd += ["-l", args.lang]

    print(f"Rodando: {' '.join(cmd)}")
    t0 = time.monotonic()
    rc = subprocess.run(cmd, cwd=ROOT).returncode
    elapsed = time.monotonic() - t0
    print(f"Elapsed: {fmt_elapsed(elapsed)}")
    if rc != 0:
        die(f"mineru falhou com exit code {rc}", code=rc)

    # --- Verifica e reporta ---------------------------------------------------
    md_path = abs_out / name / "auto" / f"{name}.md"
    if not md_path.exists():
        # Tenta fallback: estrutura sem subpasta
        md_path = abs_out / name / f"{name}.md"
    if not md_path.exists():
        die(f"markdown esperado nao foi gerado: {md_path}")

    raw = md_path.read_text(encoding="utf-8")
    bytes_ = md_path.stat().st_size
    images = raw.count("![")
    fffd_pos = raw.find("\ufffd")
    img_dir = abs_out / name / "auto" / "images"
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
        local_pdf.unlink()
        print(f"Copia local removida: {local_pdf}")

    return 0


if __name__ == "__main__":
    sys.exit(main())