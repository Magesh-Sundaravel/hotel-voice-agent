#!/usr/bin/env python3
"""Stop hook: if Python files changed, run tests before Claude says it's done."""
import json
import subprocess
import sys

data = json.load(sys.stdin)
if data.get("stop_hook_active"):  # already retried once; don't loop forever
    sys.exit(0)

changed = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True).stdout
if ".py" not in changed:
    sys.exit(0)

r = subprocess.run(["uv", "run", "pytest", "-q", "-x"], capture_output=True, text=True)
if r.returncode not in (0, 5):  # 5 = no tests collected yet
    print(r.stdout[-3000:], file=sys.stderr)
    sys.exit(2)
