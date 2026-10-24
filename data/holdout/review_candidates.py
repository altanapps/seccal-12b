#!/usr/bin/env python3
"""Blind local re-labeling: only goal/tool/input enter the model request.

Run through eval/run_matrix.py --review-input so its server lifecycle, memory
watchdog and shared lock also cover this job. Outputs are independent judgments,
not accepted labels. Candidate hypotheses are deliberately not included.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT / "eval"))
from run_eval import messages_for, query, parse_verdict  # noqa: E402


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--input",type=Path,required=True)
    ap.add_argument("--output",type=Path,required=True)
    ap.add_argument("--url",required=True)
    ap.add_argument("--max-tokens",type=int,default=96)
    ap.add_argument("--structured",action="store_true")
    args=ap.parse_args()
    rows=[json.loads(line) for line in args.input.read_text().splitlines() if line.strip()]
    args.output.parent.mkdir(parents=True,exist_ok=True)
    done={}
    if args.output.exists():
        done={r["id"]:r for r in (json.loads(line) for line in args.output.read_text().splitlines() if line.strip())}
    source_hash=hashlib.sha256(args.input.read_bytes()).hexdigest()
    for result in done.values():
        if result.get("candidate_sha256")!=source_hash:raise ValueError("input changed since partial review; choose a new output")
    if any(r["judge_action"] in ("ERROR","PARSE_ERROR") for r in done.values()):
        done={key:r for key,r in done.items() if r["judge_action"] not in ("ERROR","PARSE_ERROR")}
        temporary=args.output.with_suffix(".tmp")
        temporary.write_text("".join(json.dumps(r,ensure_ascii=False)+"\n" for r in done.values()))
        temporary.replace(args.output)
    with args.output.open("a") as handle:
        for i,row in enumerate(rows,1):
            if row["id"] in done:continue
            blind={k:row[k] for k in ("user_goal","tool_name","tool_input")}
            try:
                text,latency,details=query(args.url,messages_for(blind,"policy"),90,args.max_tokens,args.structured)
                action,category=parse_verdict(text)
                result={"id":row["id"],"judge_action":action,"judge_category":category,
                        "raw_final":text,"latency_s":round(latency,3),"candidate_sha256":source_hash,**details}
            except (OSError,ValueError,KeyError,IndexError,TypeError) as error:
                result={"id":row["id"],"judge_action":"ERROR","judge_category":"ERROR",
                        "error":str(error),"candidate_sha256":source_hash}
            handle.write(json.dumps(result,ensure_ascii=False)+"\n");handle.flush()
            if i%25==0:print(f"blind reviewed {i}/{len(rows)}",flush=True)
            if result["judge_action"] in ("ERROR","PARSE_ERROR"):
                raise RuntimeError(f"review failed on {row['id']}; stop rather than treating errors as labels")
    print(f"wrote {len(rows)} blind judgments; no candidates auto-accepted")


if __name__=="__main__":main()
