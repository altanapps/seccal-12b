#!/usr/bin/env python3
"""Build a self-contained Colab notebook per model preset, with a verifiable bundle.

Usage:
  python3 train/make_colab_notebook.py [--model qwen3-4b] [--out train/seccal_colab_qwen3-4b.ipynb]
  python3 train/make_colab_notebook.py --check [--model ...] [--out ...]   # verify committed notebook

The notebook embeds train/sft_unsloth.py and the rendered data/sft/train.jsonl +
val.jsonl as a base64 zip, so Colab needs no clone and no uploads. Integrity:
- the zip is reproducible (fixed entry timestamps, writestr), so a local rebuild
  diffs cleanly against the committed notebook;
- a SHA-256 manifest of every member is rendered as a readable dict in the
  extraction cell and asserted before extractall, so a notebook whose blob was
  tampered with fails before anything runs;
- `--check` decodes the committed notebook and fails if any member differs from
  the tracked sources. Run it in review for any change touching a notebook.
Re-run this after any change to the training script or the dataset
(run data/synth/render_sft.py first).
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import re
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "train"))
from sft_unsloth import PRESETS  # noqa: E402  (pure data; sft_unsloth has no import side effects)

FILES = {
    "train/sft_unsloth.py": ROOT / "train" / "sft_unsloth.py",
    "data/sft/train.jsonl": ROOT / "data" / "sft" / "train.jsonl",
    "data/sft/val.jsonl": ROOT / "data" / "sft" / "val.jsonl",
}
B64_RE = re.compile(r"BUNDLE_B64 = '''([A-Za-z0-9+/=]+)'''")


def bundle() -> tuple[str, dict, dict]:
    buf = io.BytesIO()
    sizes, hashes = {}, {}
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for arc, p in FILES.items():
            if not p.exists():
                raise SystemExit(f"missing {p}; run data/synth/render_sft.py first")
            data = p.read_bytes()
            zi = zipfile.ZipInfo(arc, date_time=(1980, 1, 1, 0, 0, 0))  # reproducible
            zi.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(zi, data)
            sizes[arc] = len(data)
            hashes[arc] = hashlib.sha256(data).hexdigest()
    return base64.b64encode(buf.getvalue()).decode(), sizes, hashes


def bundle_members(nb_path: Path) -> dict[str, bytes]:
    nb = json.loads(nb_path.read_text())
    for c in nb["cells"]:
        src = c["source"] if isinstance(c["source"], str) else "".join(c["source"])
        m = B64_RE.search(src)
        if m:
            z = zipfile.ZipFile(io.BytesIO(base64.b64decode(m.group(1))))
            return {zi.filename: z.read(zi) for zi in z.infolist()}
    raise SystemExit(f"{nb_path}: no BUNDLE_B64 cell")


def check(nb_path: Path) -> int:
    members = bundle_members(nb_path)
    bad = [a for a, p in FILES.items() if members.get(a) != p.read_bytes()]
    extra = sorted(set(members) - set(FILES))
    if bad or extra:
        print(f"MISMATCH in {nb_path.name}: members differing from tracked sources: {bad}; unexpected members: {extra}")
        return 1
    print(f"OK: {nb_path.name} bundle matches tracked sources ({len(members)} members)")
    return 0


def md(text: str) -> dict:
    return {"cell_type": "markdown", "metadata": {}, "source": text}


def code(text: str) -> dict:
    return {"cell_type": "code", "metadata": {}, "execution_count": None, "outputs": [], "source": text}


def build(preset: str, out: Path) -> None:
    b64, sizes, hashes = bundle()
    cfg = PRESETS[preset]
    n_train = sum(1 for _ in open(FILES["data/sft/train.jsonl"]))
    n_val = sum(1 for _ in open(FILES["data/sft/val.jsonl"]))
    outdir = f"out/seccal-{preset}"
    cells = [
        md(
            f"# seccal: fine-tune `{cfg['model']}` (preset `{preset}`)\n\n"
            "**Before running:** `Runtime → Change runtime type → T4 GPU` (free tier is enough).\n\n"
            f"Then `Runtime → Run all`. Embedded: training script + {n_train} train / {n_val} val rows, "
            "with a SHA-256 manifest that is checked before anything is extracted. Nothing else to upload. "
            "Output GGUFs are copied to your Google Drive at `MyDrive/seccal-12b/` (one Drive authorization prompt). "
            "Roughly 10–25 minutes on a T4 including installs."
        ),
        code(
            "import torch, subprocess\n"
            "assert torch.cuda.is_available(), 'No GPU. Runtime → Change runtime type → T4 GPU, then Run all again.'\n"
            "print(torch.cuda.get_device_name(0))\n"
            "print(subprocess.run(['nvidia-smi', '--query-gpu=memory.total', '--format=csv,noheader'], capture_output=True, text=True).stdout.strip())"
        ),
        md("## 1. Verify and unpack the embedded training script and data\n\n"
           "`EXPECTED` is the SHA-256 of each bundled file as generated from the repository's tracked sources. "
           "If any member differs, the cell stops before extracting anything."),
        code(
            "import base64, io, zipfile, os, hashlib\n"
            f"EXPECTED = {json.dumps(hashes, indent=1)}\n"
            f"BUNDLE_B64 = '''{b64}'''\n"
            "z = zipfile.ZipFile(io.BytesIO(base64.b64decode(BUNDLE_B64)))\n"
            "assert set(z.namelist()) == set(EXPECTED), f'unexpected bundle members: {z.namelist()}'\n"
            "for n in z.namelist():\n"
            "    h = hashlib.sha256(z.read(n)).hexdigest()\n"
            "    assert h == EXPECTED[n], f'bundle member {n} does not match the manifest ({h} != {EXPECTED[n]})'\n"
            "z.extractall('/content/seccal')\n"
            "os.chdir('/content/seccal')\n"
            "for n in z.namelist(): print('verified', n, os.path.getsize(n), 'bytes')"
        ),
        md("## 2. Install the training stack (a few minutes)"),
        code(
            "%pip install -q -U unsloth \"trl>=0.15\" datasets transformers\n"
            "import unsloth, trl, transformers\n"
            "print('unsloth', unsloth.__version__, '| trl', trl.__version__, '| transformers', transformers.__version__)"
        ),
        md("## 3. (Optional) Hugging Face token\n\n"
           "Only needed if the base model download asks for one (none of the presets are gated). Add a Colab secret named `HF_TOKEN` "
           "and this cell will pick it up; otherwise it is skipped."),
        code(
            "import os\n"
            "try:\n"
            "    from google.colab import userdata\n"
            "    os.environ['HF_TOKEN'] = userdata.get('HF_TOKEN')\n"
            "    print('HF_TOKEN set from Colab secrets')\n"
            "except Exception:\n"
            "    print('no HF_TOKEN secret; continuing without one')"
        ),
        md(f"## 4. Train (`--model {preset}`), then export Q4_K_M and Q8_0 GGUFs\n\n"
           "If a 16-bit LoRA runs out of memory on the T4 (possible on 4B presets), add `--load-in-4bit`."),
        code(
            f"!python train/sft_unsloth.py --model {preset} --train data/sft/train.jsonl --val data/sft/val.jsonl --out {outdir} --epochs 3\n"
            f"!find {outdir} -name '*.gguf' -exec ls -la {{}} \\;"
        ),
        md("## 5. Save the GGUFs to Google Drive\n\n"
           "Approve the Drive prompt. Files land in `MyDrive/seccal-12b/`. Then on your Mac, copy them into the repo's `models/` folder "
           f"as `models/seccal_{preset}_Q4_K_M.gguf` and `models/seccal_{preset}_Q8_0.gguf`."),
        code(
            "from google.colab import drive\n"
            "import shutil, glob, os\n"
            "drive.mount('/content/drive')\n"
            "dst = '/content/drive/MyDrive/seccal-12b'\n"
            "os.makedirs(dst, exist_ok=True)\n"
            f"ggufs = glob.glob('{outdir}/**/*.gguf', recursive=True)\n"
            f"assert ggufs, 'no .gguf files found under {outdir}; check the training cell output'\n"
            "for f in ggufs:\n"
            "    shutil.copy(f, dst)\n"
            "    print('copied', os.path.basename(f), round(os.path.getsize(f)/1e6), 'MB')\n"
            f"shutil.copy('{outdir}/train_stats.json', dst)\n"
            "print('done ->', dst)"
        ),
        md("### Fallback: direct browser download"),
        code(
            "from google.colab import files\n"
            "import glob\n"
            f"ggufs = glob.glob('{outdir}/**/*.gguf', recursive=True)\n"
            f"assert ggufs, 'no .gguf files found under {outdir}'\n"
            "for f in ggufs:\n"
            "    print(f); files.download(f)"
        ),
    ]
    nb = {
        "cells": cells,
        "metadata": {
            "accelerator": "GPU",
            "colab": {"provenance": [], "gpuType": "T4"},
            "kernelspec": {"display_name": "Python 3", "name": "python3"},
            "language_info": {"name": "python"},
        },
        "nbformat": 4,
        "nbformat_minor": 0,
    }
    out.write_text(json.dumps(nb, indent=1))
    print(f"wrote {out} ({out.stat().st_size // 1024} KB); preset {preset}; embedded {sizes}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="lfm2.5-1.2b", choices=sorted(PRESETS))
    ap.add_argument("--out", default=None, help="default: train/seccal_colab.ipynb for lfm2.5-1.2b, else train/seccal_colab_<preset>.ipynb")
    ap.add_argument("--check", action="store_true", help="verify the committed notebook's bundle against tracked sources")
    args = ap.parse_args()
    out = Path(args.out) if args.out else (
        ROOT / "train" / ("seccal_colab.ipynb" if args.model == "lfm2.5-1.2b" else f"seccal_colab_{args.model}.ipynb"))
    if args.check:
        return check(out)
    build(args.model, out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
