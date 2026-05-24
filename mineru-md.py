#!/usr/bin/env python3
"""
mineru-md.py — wrapper cross-platform para extrair markdown de um PDF via MinerU.

Faz tres coisas:

1. **Bootstrap** do venv local (.venv-mineru/) na primeira execucao: detecta `uv`,
   cria o venv, instala `mineru[core]`, e (se houver NVIDIA GPU) instala torch
   com suporte a CUDA. Tudo isso pode ser pulado com --skip-bootstrap.
2. **Workaround MAX_PATH** no Windows: copia o PDF para a raiz do projeto com um
   nome curto (slugificado) antes de chamar o mineru.
3. **Verificacao** da saida: imprime tamanho, contagem de imagens e se ha
   caracteres corrompidos (U+FFFD).

Roda em Windows e Linux. So usa stdlib — invoque com `python mineru-md.py …`
ou `uv run mineru-md.py …`.

Exemplos:
    python mineru-md.py "G:\\Drive\\Caminho Longo\\livro.pdf"
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


def run(cmd: list[str], **kwargs) -> int:
    printable = " ".join(str(c) for c in cmd)
    print(f"  $ {printable}")
    return subprocess.run(cmd, **kwargs).returncode


def ensure_uv() -> None:
    if shutil.which("uv"):
        return
    if sys.platform == "win32":
        hint = "winget install astral-sh.uv"
    else:
        hint = "curl -LsSf https://astral.sh/uv/install.sh | sh"
    die(f"'uv' nao encontrado no PATH. Instale com:\n    {hint}")


def bootstrap(skip_cuda: bool) -> None:
    bin_path = mineru_binary()
    if bin_path.exists():
        return

    print(f"[bootstrap] venv ausente — preparando em {VENV}")
    ensure_uv()

    if not VENV.exists():
        if run(["uv", "venv", "--python", "3.12", str(VENV)]) != 0:
            die("falha ao criar venv via uv")

    print("[bootstrap] instalando mineru[core] (pode demorar — ~3 GB)")
    if run(["uv", "pip", "install", "-p", str(VENV), "mineru[core]"]) != 0:
        die("falha ao instalar mineru[core]")

    if not skip_cuda and shutil.which("nvidia-smi"):
        print("[bootstrap] NVIDIA GPU detectada — instalando torch+CUDA")
        rc = run([
            "uv", "pip", "install", "-p", str(VENV), "--reinstall",
            "--index-url", "https://download.pytorch.org/whl/cu128",
            "torch", "torchvision",
        ])
        if rc != 0:
            print(
                "[bootstrap] AVISO: instalacao do torch CUDA falhou; "
                "MinerU vai rodar em CPU (muito mais lento). "
                "Reinstale manualmente conforme README, ou use --no-cuda."
            )

    if not bin_path.exists():
        die(f"bootstrap terminou mas {bin_path} nao existe — inspecione o venv")


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
        description="Extrai markdown de um PDF via MinerU (cross-platform).",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    ap.add_argument("pdf", help="caminho do PDF de origem (relativo ou absoluto)")
    ap.add_argument("--name", help="slug para a pasta/arquivo de saida (default: derivado do nome do PDF)")
    ap.add_argument("--lang", default="latin", choices=LANG_CHOICES,
                    help="codigo -l do MinerU (afeta OCR; 'latin' cobre PT-BR/EN/ES/FR/IT)")
    ap.add_argument("--backend", default="pipeline", choices=BACKEND_CHOICES,
                    help="backend do MinerU")
    ap.add_argument("--out", default="mineru_out",
                    help="pasta raiz de saida, relativa a raiz do projeto")
    ap.add_argument("--keep-pdf-copy", action="store_true",
                    help="nao remover a copia local do PDF apos a extracao")
    ap.add_argument("--no-cuda", action="store_true",
                    help="durante bootstrap, nao tentar instalar torch+CUDA mesmo se houver GPU")
    ap.add_argument("--skip-bootstrap", action="store_true",
                    help="assume venv pronto; falha rapido se nao estiver")
    args = ap.parse_args()

    # 1. Bootstrap
    if args.skip_bootstrap:
        bin_path = mineru_binary()
        if not bin_path.exists():
            die(f"{bin_path} nao existe — rode sem --skip-bootstrap, ou siga o Setup do README")
    else:
        bootstrap(skip_cuda=args.no_cuda)

    # 2. Resolve source PDF
    src = Path(args.pdf).expanduser()
    if not src.exists():
        die(f"PDF nao encontrado: {src}")
    src = src.resolve()
    if src.stat().st_size == 0:
        die(f"PDF '{src}' tem 0 bytes — e stub do Google Drive? "
            "Abra a pasta no Explorer pra forcar download.")

    # 3. Derive short name
    name = args.name or slugify(src.stem)
    local_pdf = ROOT / f"{name}.pdf"
    src_size = src.stat().st_size

    # 4. Copy locally if necessary
    copied = False
    if not local_pdf.exists() or local_pdf.stat().st_size != src_size:
        print(f"Copiando PDF -> {local_pdf}")
        shutil.copy2(src, local_pdf)
        copied = True
    else:
        print(f"Copia local ja existe: {local_pdf} (reutilizando)")

    # 5. Run mineru
    abs_out = (ROOT / args.out).resolve()
    abs_out.mkdir(parents=True, exist_ok=True)
    cmd = [
        str(mineru_binary()),
        "-p", str(local_pdf),
        "-o", str(abs_out),
        "-b", args.backend,
        "-l", args.lang,
    ]
    print(f"Rodando: {' '.join(cmd)}")
    t0 = time.monotonic()
    rc = subprocess.run(cmd, cwd=ROOT).returncode
    elapsed = time.monotonic() - t0
    print(f"Elapsed: {fmt_elapsed(elapsed)}")
    if rc != 0:
        die(f"mineru falhou com exit code {rc}", code=rc)

    # 6. Verify and report
    md_path = abs_out / name / "auto" / f"{name}.md"
    if not md_path.exists():
        die(f"markdown esperado nao foi gerado: {md_path}")

    raw = md_path.read_text(encoding="utf-8")
    bytes_ = md_path.stat().st_size
    images = raw.count("![")
    fffd_pos = raw.find("�")
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

    # 7. Cleanup
    if copied and not args.keep_pdf_copy:
        local_pdf.unlink()
        print(f"Copia local removida: {local_pdf}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
