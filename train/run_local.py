#!/usr/bin/env python3
"""Run an isolated MLX QLoRA pilot using the same lock and memory guard as eval.

  .venv-mlx/bin/python train/run_local.py --model qwen3-4b --pilot

Pilots perform eight microbatches (one optimizer update), not a completed model.
Omit --pilot for the prepared 1200-microbatch recipe after pilot validation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "eval"))
from run_matrix import sweep_lock, measure_memory, process_memory  # noqa: E402


def tokenizer_options(model):
    if model == "qwen3-4b":
        template=ROOT / "train/tokenizer_templates/qwen3-4b.jinja"
        source=json.loads(template.with_suffix(".source.json").read_text())
        text=template.read_text()
        if hashlib.sha256(text.encode()).hexdigest()!=source["template_sha256"]:
            raise ValueError("publisher tokenizer template integrity check failed")
        return {"chat_template":text}
    return {"fix_mistral_regex":True}


def preflight(config):
    from transformers import AutoTokenizer
    from mlx_lm.tuner.datasets import ChatDataset
    from mlx_lm.utils import _get_classes
    model_path=ROOT / config["model"]
    if not (model_path / "seccal-source.json").exists():
        raise ValueError("pinned snapshot download has not completed")
    source=json.loads((model_path / "seccal-source.json").read_text())
    _get_classes(json.loads((model_path / "config.json").read_text()))
    name=model_path.name
    options=tokenizer_options(name)
    tokenizer=AutoTokenizer.from_pretrained(model_path,trust_remote_code=False,**options)
    result={"source":source,"splits":{},"tokenizer_options":list(options)}
    if "chat_template" in options:
        result["publisher_chat_template_sha256"]=hashlib.sha256(options["chat_template"].encode()).hexdigest()
    for split in ("train", "valid"):
        path=ROOT / config["data"] / f"{split}.jsonl"
        records=[json.loads(line) for line in path.read_text().splitlines() if line.strip()]
        dataset=ChatDataset(records,tokenizer,mask_prompt=True)
        lengths, completions=[],[]
        for record in records:
            tokens,offset=dataset.process(record)
            prompt=tokenizer.apply_chat_template(record["messages"][:-1],add_generation_prompt=True,return_dict=False)
            if tokens[:offset]!=prompt:
                raise ValueError(f"{record['id']}: native template prefix changes at assistant boundary")
            if offset>=len(tokens) or len(tokens)>config["max_seq_length"]:
                raise ValueError(f"{record['id']}: empty assistant loss or truncation ({len(tokens)} tokens)")
            target=record["messages"][-1]["content"]
            decoded=tokenizer.decode(tokens[offset:],skip_special_tokens=True)
            if target not in decoded or "<think>" in decoded or "</think>" in decoded:
                raise ValueError(f"{record['id']}: verdict not wholly inside supervised tokens")
            lengths.append(len(tokens));completions.append(len(tokens)-offset)
        result["splits"][split]={"rows":len(records),"max_tokens":max(lengths),
            "min_completion_tokens":min(completions),"sha256":hashlib.sha256(path.read_bytes()).hexdigest()}
    if (ROOT / config["data"] / "test.jsonl").exists():
        raise ValueError("test examples must not be in this training directory")
    return result


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--model",choices=["qwen3-4b","ministral3-3b"],required=True)
    ap.add_argument("--pilot",action="store_true")
    ap.add_argument("--check-only",action="store_true")
    ap.add_argument("--output-dir",type=Path,help="new run directory; existing run outputs are never overwritten")
    ap.add_argument("--recipe",type=Path,help="explicit experimental recipe; default is the model's policy recipe")
    ap.add_argument("--worker",type=Path,help=argparse.SUPPRESS)
    args=ap.parse_args()
    os.chdir(ROOT)
    if args.worker:
        import mlx.core as mx
        mx.set_memory_limit(20_000_000_000)
        mx.set_cache_limit(500_000_000)
        import importlib
        lora=importlib.import_module("mlx_lm.lora")
        original_load=lora.load
        def load_with_native_tokenizer(*positional,**kwargs):
            kwargs["tokenizer_config"]={**kwargs.get("tokenizer_config",{}),**tokenizer_options(args.model)}
            return original_load(*positional,**kwargs)
        lora.load=load_with_native_tokenizer
        sys.argv=["mlx_lm.lora","--config",str(args.worker)]
        lora.main()
        return 0
    recipe=args.recipe.resolve() if args.recipe else ROOT / "train/recipes" / f"{args.model}-policy.json"
    config=json.loads(recipe.read_text())
    evidence=preflight(config)
    print(json.dumps(evidence,indent=2),flush=True)
    if args.check_only:return 0
    if args.pilot:
        config.update(iters=8,steps_per_report=1,steps_per_eval=8,val_batches=2,save_every=8)
        config["adapter_path"] += "-pilot"
    if args.output_dir:
        config["adapter_path"] = str(args.output_dir)
    output=ROOT / config["adapter_path"]
    if output.exists() and any(output.iterdir()):
        raise FileExistsError(f"preserving existing run at {output}; choose a new --output-dir")
    output.mkdir(parents=True,exist_ok=True)
    effective=output / "run-config.json"
    effective.write_text(json.dumps(config,indent=2)+"\n")
    evidence.update({"pilot":args.pilot,"effective_config_sha256":hashlib.sha256(effective.read_bytes()).hexdigest(),
        "max_runtime_gb":24,"memory_abort_threshold_gb":22,"mlx_allocator_guideline_gb":20,
        "microbatches":config["iters"],"optimizer_updates":config["iters"]//config["grad_accumulation_steps"]})
    process_memory(os.getpid())
    stop,sample=threading.Event(),{}
    with sweep_lock(), (output / "train.log").open("w") as log:
        process=subprocess.Popen([sys.executable,str(Path(__file__).resolve()),"--model",args.model,"--worker",str(effective)],stdout=log,stderr=subprocess.STDOUT,cwd=ROOT)
        monitor=threading.Thread(target=measure_memory,args=(process,stop,sample,24),daemon=True)
        monitor.start()
        try:
            code=process.wait()
        finally:
            stop.set();monitor.join(timeout=4)
            if process.poll() is None:process.terminate();process.wait(timeout=15)
        evidence.update(sample)
        evidence["exit_code"]=code
        evidence["status"]="completed pilot" if args.pilot and code==0 else "completed training" if code==0 else "failed"
        (output / "evidence.json").write_text(json.dumps(evidence,indent=2)+"\n")
    if code or sample.get("memory_abort"):
        raise RuntimeError(f"training failed; inspect {output / 'train.log'}")
    print(f"{evidence['status']}; evidence: {output / 'evidence.json'}")
    return 0


if __name__=="__main__":
    raise SystemExit(main())
