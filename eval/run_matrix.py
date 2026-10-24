#!/usr/bin/env python3
"""Run downloaded baselines one at a time with reproducible llama.cpp settings.

  python3 eval/run_matrix.py --wave initial
  python3 eval/run_matrix.py --models qwen3-4b --prompt-mode policy

Validation is the selection set. Request --split test explicitly only after
choosing finalists. This script starts its own server on loopback port 8091,
never changes an existing server, and stops its child server after each model.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import fcntl
import ctypes
import json
import hashlib
import shutil
import socket
import subprocess
import sys
import threading
import time
import platform
import os
import urllib.error
import urllib.request
from pathlib import Path

from download_models import ROOT, digest, load_models, model_path, select


@contextmanager
def sweep_lock(root=ROOT):
    """Prevent two matrix invocations (even on different ports) loading models."""
    directory = root / "eval/out"
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / ".model-sweep.lock").open("a+") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("another seccal sweep is active; wait for it to finish before loading another model") from None
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def wait_ready(process, url, timeout):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"llama-server exited with {process.returncode}; see server log")
        try:
            with urllib.request.urlopen(url + "/health", timeout=2) as response:
                if response.status == 200:
                    return
        except (urllib.error.URLError, TimeoutError, OSError):
            pass
        time.sleep(0.5)
    raise TimeoutError("server readiness deadline exceeded")


class RUsageInfoV0(ctypes.Structure):
    _fields_ = [("uuid", ctypes.c_uint8 * 16)] + [
        (name, ctypes.c_uint64) for name in (
            "user_time", "system_time", "pkg_idle_wkups", "interrupt_wkups", "pageins",
            "wired_size", "resident_size", "phys_footprint", "proc_start_abstime", "proc_exit_abstime")]


def process_memory(pid):
    """macOS ledger footprint includes memory not represented by plain RSS."""
    if platform.system() == "Darwin":
        lib = ctypes.CDLL("/usr/lib/libproc.dylib", use_errno=True)
        data = RUsageInfoV0()
        if lib.proc_pid_rusage(pid, 0, ctypes.byref(data)):
            raise OSError(ctypes.get_errno(), "proc_pid_rusage failed")
        return data.resident_size, data.phys_footprint
    result = subprocess.run(["ps", "-o", "rss=", "-p", str(pid)], capture_output=True, text=True, check=True, timeout=3)
    return int(result.stdout.strip()) * 1024, None


def measure_memory(process, stop, sample, cap_gb):
    # Reserve 2 GB for allocation bursts between samples. This is an early-stop
    # watchdog, not a kernel-enforced physical-memory quota.
    threshold = max(0.1, cap_gb - 2) * 1e9
    while not stop.wait(0.1):
        try:
            rss, footprint = process_memory(process.pid)
            sample["peak_sampled_process_rss_gb"] = max(sample.get("peak_sampled_process_rss_gb", 0), rss / 1e9)
            if footprint is not None:
                sample["peak_sampled_phys_footprint_gb"] = max(sample.get("peak_sampled_phys_footprint_gb", 0), footprint / 1e9)
            if max(rss, footprint or 0) >= threshold:
                sample["memory_abort"] = f"early-stop threshold {threshold / 1e9:.1f} GB reached for {cap_gb:.1f} GB cap"
                process.terminate()
                return
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            if process.poll() is not None:
                return
            sample["memory_abort"] = f"memory telemetry unavailable: {type(error).__name__}"
            process.terminate()
            return


def run_one(model, args, server, version):
    reasoning = args.track == "reasoning"
    if not reasoning and (model.get("thinking") != "off" or model["wave"] == "specialist"):
        raise ValueError("this model needs a separate native-schema/reasoning evaluation adapter; the direct matrix is not a fair benchmark")
    if model["fit_48gb"] == "no":
        raise ValueError("model does not fit the catalog memory budget")
    if model["estimated_runtime_gb"][1] > args.max_runtime_gb:
        raise ValueError("model exceeds configured estimated runtime memory budget")
    artifacts = model.get("artifacts", [])
    if not artifacts:
        raise ValueError("no pinned artifact: resolve/download one first")
    deadline = time.monotonic() + args.wait_downloads
    while not all(model_path(model, a).exists() for a in artifacts):
        if time.monotonic() >= deadline:
            raise FileNotFoundError("artifact is not downloaded and verified yet")
        time.sleep(2)
    for artifact in artifacts:
        path = model_path(model, artifact)
        if path.stat().st_size != artifact["bytes"] or digest(path) != artifact["sha256"]:
            raise ValueError(f"artifact failed integrity verification: {path.name}")
    review_hash=hashlib.sha256(args.review_input.read_bytes()).hexdigest()[:12] if args.review_input else None
    suffix = ("-reasoning" if reasoning else "") + (f"-blind-review-{review_hash}" if review_hash else "")
    name = f"base-{model['id']}-{model['quantization'].lower()}-{args.split}-{args.prompt_mode}{suffix}"
    out = ROOT / "eval/out"
    out.mkdir(parents=True, exist_ok=True)
    summary_path = out / f"{name}.summary.json"
    if summary_path.exists() and not args.rerun:
        previous = json.loads(summary_path.read_text())
        if previous["metrics"]["error_rate"]["hits"] == 0:
            print(f"skip completed {name}; use --rerun to repeat", flush=True)
            return
    log_path = out / f"{name}.server.log"
    metadata_path = out / f"{name}.runtime.json"
    command = [server, "-m", str(model_path(model, artifacts[0])), "--jinja", "--temp", "0",
               "--host", "127.0.0.1", "--port", str(args.port), "-c", str(args.ctx),
               "-np", "1", "-ngl", "99", "--flash-attn", "on", "--no-webui",
               "--reasoning", "on" if reasoning else "off"]
    if reasoning:
        command += ["--reasoning-effort", "low", "--reasoning-budget", str(args.reasoning_budget)]
    else:
        command += ["--grammar-file", str(ROOT / "serve/seccal.gbnf")]
    if (model.get("total_parameters_b_approx") or 0) >= 20:
        command += ["--batch-size","256","--ubatch-size","128"]
    metadata = {"model_id": model["id"], "source_model": model["source_model"],
                "gguf_repo": model["gguf_repo"], "gguf_revision": model["gguf_revision"],
                "artifacts": artifacts, "llama_server_version": version, "server_command": command,
                "context_tokens": args.ctx, "server_slots": 1, "thinking": "on" if reasoning else "off",
                "track": args.track, "reasoning_budget": args.reasoning_budget if reasoning else 0}
    metadata_path.write_text(json.dumps(metadata, indent=2) + "\n")
    print(f"starting {name}", flush=True)
    # Probe telemetry before loading a model; inability to monitor is a blocker.
    process_memory(os.getpid())
    stop, sample = threading.Event(), {}
    with log_path.open("w") as log:
        process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT, cwd=ROOT)
        monitor = threading.Thread(target=measure_memory, args=(process, stop, sample, args.max_runtime_gb), daemon=True)
        monitor.start()
        try:
            wait_ready(process, f"http://127.0.0.1:{args.port}", args.startup_timeout)
            eval_command = [
                sys.executable, "-u", str(ROOT / "eval/run_eval.py"), "--name", name,
                "--split", args.split, "--url", f"http://127.0.0.1:{args.port}",
                "--concurrency", "1", "--warmup", "2", "--max-tokens", str(1024 if reasoning else 96),
                "--timeout", str(args.request_timeout), "--prompt-mode", args.prompt_mode,
                "--metadata", str(metadata_path),
            ]
            if reasoning:
                eval_command += ["--structured"]
            if args.eval_input:
                eval_command += ["--input",str(args.eval_input.resolve())]
            if args.review_input:
                eval_command=[sys.executable,"-u",str(ROOT / "data/holdout/review_candidates.py"),
                    "--input",str(args.review_input.resolve()),"--output",str((args.review_output_dir or ROOT / "data/holdout/reviews") / f"{model['id']}.jsonl"),
                    "--url",f"http://127.0.0.1:{args.port}","--max-tokens",str(1024 if reasoning else 96)]
                if reasoning:eval_command += ["--structured"]
            result = subprocess.run(eval_command, cwd=ROOT)
            if result.returncode:
                raise RuntimeError("evaluation had errors; artifacts preserved")
            if sample.get("memory_abort"):
                raise RuntimeError(sample["memory_abort"])
        finally:
            stop.set()
            monitor.join(timeout=4)
            process.terminate()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            metadata.update(sample)
            metadata["max_runtime_gb"] = args.max_runtime_gb
            metadata["memory_abort_threshold_gb"] = args.max_runtime_gb - 2
            metadata["memory_note"] = "RSS and macOS physical footprint sampled every 0.1s. Early-stop watchdog reserves 2GB for bursts; not a kernel physical-memory quota or total system measurement."
            metadata_path.write_text(json.dumps(metadata, indent=2) + "\n")
            if summary_path.exists():
                summary = json.loads(summary_path.read_text())
                summary["provenance"] = metadata
                summary_path.write_text(json.dumps(summary, indent=2) + "\n")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--models", nargs="+")
    ap.add_argument("--wave")
    ap.add_argument("--split", choices=["val", "test", "holdout"], default="val")
    ap.add_argument("--eval-input",type=Path,help="explicit frozen evaluation input")
    ap.add_argument("--prompt-mode", choices=["original", "policy"], default="original")
    ap.add_argument("--ctx", type=int, default=4096)
    ap.add_argument("--port", type=int, default=8091)
    ap.add_argument("--max-runtime-gb", type=float, default=24, help="estimated model/runtime cap; default leaves about half the RAM for normal work")
    ap.add_argument("--startup-timeout", type=float, default=180)
    ap.add_argument("--request-timeout", type=float, default=60)
    ap.add_argument("--wait-downloads", type=float, default=0, help="seconds per model to wait for downloader")
    ap.add_argument("--rerun", action="store_true")
    ap.add_argument("--track", choices=["direct", "reasoning"], default="direct")
    ap.add_argument("--reasoning-budget", type=int, default=256)
    ap.add_argument("--review-input",type=Path,help="blind-review a candidate set instead of scoring validation")
    ap.add_argument("--review-output-dir",type=Path,help="separate review output for a different candidate version or supplement")
    args = ap.parse_args()
    if args.track == "reasoning" and args.prompt_mode != "policy":
        ap.error("the specialist reasoning track requires --prompt-mode policy")
    if args.review_input and args.prompt_mode != "policy":
        ap.error("blind review requires --prompt-mode policy")
    if args.split=="holdout" and not args.eval_input:
        ap.error("holdout scoring requires --eval-input; candidate review uses --review-input instead")
    chosen = select(load_models(), args.models, args.wave)
    if not chosen:
        ap.error("empty model selection")
    server = shutil.which("llama-server")
    if not server:
        ap.error("llama-server is not installed")
    with socket.socket() as sock:
        # Closed HTTP connections may leave TIME_WAIT after the server exits.
        # Match llama-server's reuse behavior; an active listener still fails.
        sock.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
        try:
            sock.bind(("127.0.0.1", args.port))
        except OSError:
            ap.error(f"port {args.port} is occupied; choose another --port")
    version = subprocess.run([server, "--version"], capture_output=True, text=True, check=True).stderr.strip()
    failures, skipped = [], []
    try:
        with sweep_lock():
            for model in chosen:
                if model.get("direct_eval_compatible") is False:
                    skipped.append({"model_id": model["id"], "reason": model["direct_eval_blocker"]})
                    print(f"SKIP {model['id']}: separate protocol adapter required (see catalog)", flush=True)
                    continue
                try:
                    run_one(model, args, server, version)
                except (OSError, RuntimeError, ValueError, TimeoutError) as error:
                    failure = {"model_id": model["id"], "error": str(error)}
                    failures.append(failure)
                    print(f"FAILED {model['id']}: {error}", flush=True)
    except RuntimeError as error:
        ap.error(str(error))
    print(json.dumps({"selected": len(chosen), "skipped": skipped, "failures": failures}), flush=True)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
