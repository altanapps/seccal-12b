#!/usr/bin/env python3
"""Download pinned GGUF artifacts from model_catalog.json; no model code executes.

  python3 eval/download_models.py --wave initial
  python3 eval/download_models.py --models qwen3-4b qwen3.5-4b

Downloads resume through .part files and are promoted only after size and SHA-256
verification. Model weights and receipts stay under the gitignored models/ tree.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "eval/model_catalog.json"


def load_models(path=CATALOG):
    return json.loads(Path(path).read_text())["models"]


def select(models, ids=None, wave=None):
    if ids:
        missing = set(ids) - {m["id"] for m in models}
        if missing:
            raise ValueError(f"unknown models: {sorted(missing)}")
        return [m for m in models if m["id"] in ids]
    if wave:
        return [m for m in models if m["wave"] == wave]
    raise ValueError("select --models or --wave explicitly")


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(8 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def model_path(model, artifact):
    name = Path(artifact["file"]).name
    if not re.fullmatch(r"[a-z0-9][a-z0-9.-]*", model["id"]) or not name.endswith(".gguf"):
        raise ValueError("invalid local model path")
    return ROOT / "models/base" / model["id"] / name


def download(model, artifact):
    target = model_path(model, artifact)
    target.parent.mkdir(parents=True, exist_ok=True)
    size, sha = artifact["bytes"], artifact["sha256"]
    revision = model["gguf_revision"]
    if not re.fullmatch(r"[0-9a-f]{40}", revision) or not re.fullmatch(r"[0-9a-f]{64}", sha):
        raise ValueError("download requires pinned revision and SHA-256")
    if target.exists():
        if target.stat().st_size == size and digest(target) == sha:
            print(f"verified cached {model['id']}: {target.name}", flush=True)
            return
        raise ValueError(f"existing artifact failed integrity check: {target}")
    part = target.with_suffix(target.suffix + ".part")
    url = f"https://huggingface.co/{model['gguf_repo']}/resolve/{revision}/{quote(artifact['file'], safe='/')}"
    for attempt in range(4):
        try:
            offset = part.stat().st_size if part.exists() else 0
            if offset > size:
                raise ValueError(f"oversized partial download: {part}")
            if offset < size:
                headers = {"User-Agent": "seccal-base-eval/1.0"}
                if offset:
                    headers["Range"] = f"bytes={offset}-"
                request = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(request, timeout=60) as response:
                    if offset and response.status != 206:
                        offset = 0  # server ignored Range: replace, never append twice
                    if response.status == 206:
                        expected = f"bytes {offset}-"
                        if not response.headers.get("Content-Range", "").startswith(expected):
                            raise ValueError("unexpected Content-Range")
                    print(f"downloading {model['id']}: {offset / 1e9:.2f}/{size / 1e9:.2f} GB", flush=True)
                    last = time.monotonic()
                    with part.open("ab" if offset else "wb") as f:
                        while block := response.read(4 * 1024 * 1024):
                            offset += len(block)
                            if offset > size:
                                raise ValueError("response exceeds expected artifact size")
                            f.write(block)
                            if time.monotonic() - last >= 30:
                                print(f"  {model['id']}: {offset / size:.0%}", flush=True)
                                last = time.monotonic()
            if part.stat().st_size != size:
                raise OSError("incomplete response; rerun to resume")
            if digest(part) != sha:
                raise ValueError(f"SHA-256 mismatch: {part}; inspect/remove partial before retry")
            os.replace(part, target)
            target.with_suffix(".receipt.json").write_text(json.dumps({
                "model_id": model["id"], "repo": model["gguf_repo"], "revision": revision,
                **artifact, "verified_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }, indent=2) + "\n")
            print(f"downloaded and verified {model['id']}: {size / 1e9:.2f} GB", flush=True)
            return
        except (OSError, TimeoutError) as error:
            if attempt == 3:
                raise
            print(f"retry {model['id']}: {type(error).__name__}", flush=True)
            time.sleep(2 ** attempt)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--models", nargs="+")
    ap.add_argument("--wave")
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--max-gb", type=float, default=25, help="maximum selected artifact bytes (decimal GB)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    chosen = select(load_models(), args.models, args.wave)
    if not chosen or any(not m.get("artifacts") for m in chosen):
        ap.error("every selected model must have a pinned GGUF artifact")
    jobs = [(m, a) for m in chosen for a in m["artifacts"]]
    total = sum(a["bytes"] for _, a in jobs)
    if total > args.max_gb * 1e9:
        ap.error(f"selection is {total / 1e9:.2f} GB, above --max-gb {args.max_gb}")
    if shutil.disk_usage(ROOT).free < total + 10 * 1e9:
        ap.error("insufficient disk headroom")
    print(f"{len(chosen)} models, {total / 1e9:.2f} GB selected", flush=True)
    if args.dry_run:
        for m, a in jobs:
            print(m["id"], a["file"], a["bytes"])
        return
    with ThreadPoolExecutor(max_workers=max(1, min(args.workers, 4))) as pool:
        futures = [pool.submit(download, m, a) for m, a in jobs]
        for future in futures:
            future.result()


if __name__ == "__main__":
    main()
