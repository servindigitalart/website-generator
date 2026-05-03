#!/usr/bin/env python3
"""Railway-safe entrypoint. Handles PORT env var and captures startup errors."""
import os
import sys
import traceback

port = int(os.environ.get("PORT", 8006))
print(f"[start.py] Starting on port {port}", flush=True)
print(f"[start.py] Python {sys.version}", flush=True)
print(f"[start.py] PYTHONPATH: {os.environ.get('PYTHONPATH', 'not set')}", flush=True)

print("[start.py] Testing import of api.main...", flush=True)
try:
    import api.main
    print("[start.py] Import OK", flush=True)
except Exception as e:
    print(f"[start.py] FATAL IMPORT ERROR: {e}", flush=True)
    traceback.print_exc(file=sys.stdout)
    sys.stdout.flush()

print("[start.py] Launching uvicorn...", flush=True)
import uvicorn
uvicorn.run("api.main:app", host="0.0.0.0", port=port, log_level="info")
