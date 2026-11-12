#!/usr/bin/env python3
"""Per-OS automated verification; actual USB/audio permission tests are separate."""
import argparse
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
from datetime import datetime, timezone

ROOT=Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser();p.add_argument("--output",type=Path);a=p.parse_args()
env=dict(os.environ,QT_QPA_PLATFORM="offscreen")
results=[]
with tempfile.TemporaryDirectory(prefix="remotehub-check-") as tmp:
    for label,cmd in [
        ("regression",[sys.executable,"-m","pytest","-q"]),
        ("ui_smoke",[sys.executable,"-m","remotehub","--smoke","--config-dir",tmp]),
    ]:
        r=subprocess.run(cmd,cwd=ROOT,env=env,capture_output=True,text=True)
        print(label,r.returncode);print(r.stdout);print(r.stderr,file=sys.stderr)
        results.append({"check":label,"exit_code":r.returncode,"output":r.stdout[-6000:],"stderr":r.stderr[-3000:]})
report={"platform":platform.platform(),"python":sys.version,"time":datetime.now(timezone.utc).isoformat(),"results":results,"hardware_tested":False}
if a.output:
    a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(report,ensure_ascii=False,indent=2))
raise SystemExit(0 if all(x["exit_code"]==0 for x in results) else 1)
