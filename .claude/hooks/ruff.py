#!/usr/bin/env python3
"""PostToolUse hook: format + lint any Python file Claude edits."""
import json
import subprocess
import sys

path = json.load(sys.stdin).get("tool_input", {}).get("file_path", "")
if not path.endswith(".py"):
    sys.exit(0)

subprocess.run(["uv", "run", "ruff", "format", path], capture_output=True)
r = subprocess.run(["uv", "run", "ruff", "check", "--fix", path], capture_output=True, text=True)
if r.returncode != 0:
    print(r.stdout, file=sys.stderr)
    sys.exit(2)
