#!/usr/bin/env python3
"""Build train/seccal_colab.ipynb: a single self-contained Colab notebook.

Usage: python3 train/make_colab_notebook.py

The notebook embeds (as a base64 zip) train/sft_unsloth.py and the rendered
data/sft/train.jsonl + val.jsonl, so nothing has to be cloned or uploaded in
Colab beyond the notebook itself. Re-run this after any change to the
training script or the dataset (run data/synth/render_sft.py first).
"""
from __future__ import annotations

import base64
import io
import json
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FILES = {
    "train/sft_unsloth.py": ROOT / "train" / "sft_unsloth.py",
    "data/sft/train.jsonl": ROOT / "data" / "sft" / "train.jsonl",
    "data/sft/val.jsonl": ROOT / "data" / "sft" / "val.jsonl",
}
OUT = ROOT / "train" / "seccal_colab.ipynb"


def bundle_b64() -> tuple[str, dict]:
    buf = io.BytesIO()
    sizes = {}
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for arc, p in FILES.items():
            if not p.exists():
                raise SystemExit(f"missing {p}; run data/synth/render_sft.py first")
            z.write(p, arc)
            sizes[arc] = p.stat().st_size
    return base64.b64encode(buf.getvalue()).decode(), sizes


def md(text: str) -> dict:
    return {"cell_type": "markdown", "metadata": {}, "source": text}


def code(text: str) -> dict:
    return {"cell_type": "code", "metadata": {}, "execution_count": None, "outputs": [], "source": text}


def main() -> None:
    b64, sizes = bundle_b64()
    n_train = sum(1 for _ in open(FILES["data/sft/train.jsonl"]))
    n_val = sum(1 for _ in open(FILES["data/sft/val.jsonl"]))

    cells = [
        md(
            "# seccal-12b: fine-tune LFM2.5-1.2B-Instruct\n\n"
            "**Before running:** `Runtime → Change runtime type → T4 GPU` (free tier is enough).\n\n"
            f"Then `Runtime → Run all`. Embedded: training script + {n_train} train / {n_val} val rows. "
            "Nothing else to upload. Output GGUFs are copied to your Google Drive at "
            "`MyDrive/seccal-12b/` (you will get one Drive authorization prompt). "
            "Total time on a T4 is roughly 10–20 minutes including installs."
        ),
        code(
            "import torch, subprocess\n"
            "assert torch.cuda.is_available(), 'No GPU. Runtime → Change runtime type → T4 GPU, then Run all again.'\n"
            "print(torch.cuda.get_device_name(0))\n"
            "print(subprocess.run(['nvidia-smi', '--query-gpu=memory.total', '--format=csv,noheader'], capture_output=True, text=True).stdout.strip())"
        ),
        md("## 1. Unpack the embedded training script and data"),
        code(
            "import base64, io, zipfile, os\n"
            f"BUNDLE_B64 = '''{b64}'''\n"
            "z = zipfile.ZipFile(io.BytesIO(base64.b64decode(BUNDLE_B64)))\n"
            "z.extractall('/content/seccal')\n"
            "os.chdir('/content/seccal')\n"
            "for n in z.namelist(): print(n, os.path.getsize(n), 'bytes')"
        ),
        md("## 2. Install the training stack (a few minutes)"),
        code(
            "%pip install -q -U unsloth \"trl>=0.15\" datasets transformers\n"
            "import unsloth, trl, transformers\n"
            "print('unsloth', unsloth.__version__, '| trl', trl.__version__, '| transformers', transformers.__version__)"
        ),
        md(
            "## 3. (Optional) Hugging Face token\n\n"
            "Only needed if the base model download asks for one. Add a Colab secret named `HF_TOKEN` "
            "(key icon in the left sidebar) and this cell will pick it up; otherwise it is skipped."
        ),
        code(
            "import os\n"
            "try:\n"
            "    from google.colab import userdata\n"
            "    os.environ['HF_TOKEN'] = userdata.get('HF_TOKEN')\n"
            "    print('HF_TOKEN set from Colab secrets')\n"
            "except Exception:\n"
            "    print('no HF_TOKEN secret; continuing without one')"
        ),
        md("## 4. Train, then export Q4_K_M and Q8_0 GGUFs"),
        code(
            "!python train/sft_unsloth.py --train data/sft/train.jsonl --val data/sft/val.jsonl --out out/seccal-12b --epochs 3\n"
            "# Unsloth writes the merged HF model to gguf/ and the quantized files to gguf_gguf/ (version-dependent).\n"
            "!ls -la out/seccal-12b/gguf/ out/seccal-12b/gguf_gguf/ 2>/dev/null; find out/seccal-12b -name '*.gguf' -exec ls -la {} \\;"
        ),
        md(
            "## 5. Save the GGUFs to Google Drive\n\n"
            "Approve the Drive prompt. Files land in `MyDrive/seccal-12b/`. "
            "Then on your Mac, copy them into the repo's `models/` folder."
        ),
        code(
            "from google.colab import drive\n"
            "import shutil, glob, os\n"
            "drive.mount('/content/drive')\n"
            "dst = '/content/drive/MyDrive/seccal-12b'\n"
            "os.makedirs(dst, exist_ok=True)\n"
            "ggufs = glob.glob('out/seccal-12b/**/*.gguf', recursive=True)\n"
            "assert ggufs, 'no .gguf files found under out/seccal-12b; check the training cell output'\n"
            "for f in ggufs:\n"
            "    shutil.copy(f, dst)\n"
            "    print('copied', os.path.basename(f), round(os.path.getsize(f)/1e6), 'MB')\n"
            "shutil.copy('out/seccal-12b/train_stats.json', dst)\n"
            "print('done ->', dst)"
        ),
        md(
            "### Fallback: direct browser download\n\n"
            "If Drive is not an option, run this instead (two downloads, ~0.7 GB and ~1.3 GB)."
        ),
        code(
            "from google.colab import files\n"
            "import glob\n"
            "ggufs = glob.glob('out/seccal-12b/**/*.gguf', recursive=True)\n"
            "assert ggufs, 'no .gguf files found under out/seccal-12b'\n"
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
    OUT.write_text(json.dumps(nb, indent=1))
    print(f"wrote {OUT} ({OUT.stat().st_size // 1024} KB); embedded {sizes}")


if __name__ == "__main__":
    main()
