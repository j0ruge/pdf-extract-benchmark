#!/usr/bin/env python3
"""
mineru-md.py — wrapper thin para extrair markdown de um documento via MinerU 4.x.

Aceita PDF, imagem e formatos nativos (office, OpenDocument, HTML, MHTML, CSV,
EPUB, OFD). Os formatos nativos sao parseados sem modelos nem LibreOffice.

Delega para `mineru-kit parse`, do .venv-mineru (Python 3.12). Assume que o venv
e os modelos ja foram preparados (ver README).

Funcionalidades:
1. Copia o arquivo para a raiz do projeto com nome curto (slug), preservando a
   extensao (o MinerU roteia o parser pelo sufixo), para evitar caminhos longos
   no Windows.
2. Invoca o `mineru-kit parse --format zip` (unico formato do kit que traz
   imagens e JSON estruturado) e extrai o resultado em <out>/<slug>/.
3. Gera <slug>_content_list.json, no mesmo esquema da 3.x, para chunking RAG.
4. Verifica a saida gerada: tamanho, contagem de imagens, caracteres U+FFFD.
5. Remove a copia local ao final, mesmo em falha (a menos que --keep-pdf-copy).

Exemplos:
    python mineru-md.py livro.pdf
    python mineru-md.py slides.pptx
    python mineru-md.py escaneado.pdf --ocr-mode ocr
    python mineru-md.py complexo.pdf --tier standard
    python mineru-md.py arquivo.pdf --name livro-frontend --keep-pdf-copy
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV = ROOT / ".venv-mineru"

# O default do kit e "standard" (VLM). O wrapper mantem o caminho rapido com
# modelos pequenos, equivalente ao antigo backend `pipeline`.
TIER_CHOICES = ["flash", "basic", "standard", "advanced"]
OCR_MODE_CHOICES = ["auto", "txt", "ocr"]

# Espelho de mineru/filetypes.py (TIERED_PARSE_EXTENSIONS e
# FLASH_ONLY_PARSE_EXTENSIONS) no MinerU 4.1.7. O wrapper so usa stdlib, entao
# nao importa de la. Formatos nativos rejeitam --tier != flash; sem --tier, o kit
# escolhe flash sozinho.
TIERED_SUFFIXES = {
    ".pdf", ".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tiff", ".jp2",
}
NATIVE_SUFFIXES = {
    ".doc", ".docx", ".ppt", ".pptx", ".xls", ".xlsx", ".rtf",
    ".odt", ".ods", ".odp", ".html", ".htm", ".shtml", ".mhtml", ".mht",
    ".csv", ".tsv", ".epub", ".ofd",
}
SUPPORTED_SUFFIXES = TIERED_SUFFIXES | NATIVE_SUFFIXES

# O kit nao exporta o content list, so o SDK, que precisa do Python do venv.
CONTENT_LIST_SCRIPT = """\
import json, sys
from pathlib import Path
from mineru.render import render_content_list
from mineru.types import MiddleJson
middle = MiddleJson.model_validate_json(Path(sys.argv[1]).read_text(encoding="utf-8"))
items = render_content_list(middle)
Path(sys.argv[2]).write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
"""


def mineru_binary() -> Path:
    if sys.platform == "win32":
        return VENV / "Scripts" / "mineru-kit.exe"
    return VENV / "bin" / "mineru-kit"


def venv_python() -> Path:
    if sys.platform == "win32":
        return VENV / "Scripts" / "python.exe"
    return VENV / "bin" / "python"


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
        description="Extrai markdown de um documento via MinerU 4.x (thin wrapper).",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    ap.add_argument("pdf", metavar="arquivo",
                    help="caminho do arquivo de origem (pdf, imagem ou formato nativo)")
    ap.add_argument("--name",
                    help="slug para a pasta/arquivo de saida (default: derivado do nome do arquivo)")
    ap.add_argument("--tier", default="basic", choices=TIER_CHOICES,
                    help="qualidade para PDF/imagem (formatos nativos sempre usam flash)")
    ap.add_argument("--ocr-mode", default="auto", choices=OCR_MODE_CHOICES,
                    help="estrategia de OCR para PDF/imagem")
    ap.add_argument("--out", default="mineru_out",
                    help="pasta raiz de saida, relativa a raiz do projeto")
    ap.add_argument("--keep-pdf-copy", action="store_true",
                    help="nao remover a copia local do arquivo apos a extracao")
    # Mantidos para compatibilidade de interface — ignorados (venv já pronto)
    ap.add_argument("--no-cuda", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--skip-bootstrap", action="store_true", help=argparse.SUPPRESS)
    args = ap.parse_args()

    # --- Verifica venv pronto ------------------------------------------------
    bin_path = mineru_binary()
    if not bin_path.exists():
        die(
            f"MinerU 4.x nao encontrado em {bin_path}\n\n"
            "Prepare o venv manualmente com:\n"
            f"    uv pip install -p {VENV} \"mineru[torch]>=4.1,<5\" hf_xet\n"
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

    # --- Roda mineru-kit ------------------------------------------------------
    out_dir = (ROOT / args.out / name).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    zip_path = out_dir / f"{name}.zip"
    cmd = [
        str(bin_path), "parse", str(local_file),
        "-o", str(zip_path),
        "-f", "zip",
    ]
    if suffix in TIERED_SUFFIXES:
        cmd += ["--tier", args.tier, "--ocr-mode", args.ocr_mode]

    print(f"Rodando: {' '.join(cmd)}")
    t0 = time.monotonic()
    try:
        rc = subprocess.run(cmd, cwd=ROOT).returncode
    finally:
        if copied and not args.keep_pdf_copy:
            local_file.unlink(missing_ok=True)
            print(f"Copia local removida: {local_file}")
    elapsed = time.monotonic() - t0
    print(f"Elapsed: {fmt_elapsed(elapsed)}")
    if rc != 0:
        die(f"mineru-kit falhou com exit code {rc}", code=rc)

    # --- Extrai o pacote ------------------------------------------------------
    # O zip traz markdown.md, middle_json.json, structured_content.json, images/
    # e, quando existe, model_output.json. Os links do .md sao relativos, entao
    # renomear o arquivo nao os quebra.
    if not zip_path.exists():
        die(f"pacote esperado nao foi gerado: {zip_path}")
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(out_dir)
    zip_path.unlink()

    md_path = out_dir / f"{name}.md"
    extracted_md = out_dir / "markdown.md"
    if not extracted_md.exists():
        die(f"markdown esperado nao foi gerado: {extracted_md}")
    extracted_md.replace(md_path)

    content_list_path = out_dir / f"{name}_content_list.json"
    rc = subprocess.run([
        str(venv_python()), "-c", CONTENT_LIST_SCRIPT,
        str(out_dir / "middle_json.json"), str(content_list_path),
    ], cwd=ROOT).returncode
    if rc != 0:
        die(f"falha ao gerar o content list; o markdown foi salvo em {md_path}", code=rc)

    # --- Verifica e reporta ---------------------------------------------------
    raw = md_path.read_text(encoding="utf-8")
    bytes_ = md_path.stat().st_size
    images = raw.count("![")
    fffd_pos = raw.find("\ufffd")
    img_dir = out_dir / "images"
    img_count = sum(1 for _ in img_dir.iterdir()) if img_dir.exists() else 0
    fffd_msg = "limpo" if fffd_pos == -1 else f"QUEBRADO (primeiro U+FFFD em pos {fffd_pos})"

    print()
    print("==== Resultado ====")
    print(f"Markdown:     {md_path}")
    print(f"Content list: {content_list_path}")
    print(f"Tamanho:      {bytes_} bytes ({bytes_/1024/1024:.2f} MB)")
    print(f"Imagens ref:  {images} embutidas no .md")
    print(f"Imagens dir:  {img_count} arquivos em images/")
    print(f"U+FFFD:       {fffd_msg}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
