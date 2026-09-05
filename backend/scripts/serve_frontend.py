"""Frontend serve + API smoke check.

Serves frontend/index.html and validates the API surface the dashboard needs.
Run:  python backend/scripts/serve_frontend.py
"""
import json
import sys
import urllib.request
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "frontend"
API = "http://127.0.0.1:8010"


def check_api() -> list[str]:
    ok = []
    key = {"X-API-Key": "rg-admin-key"}
    for path in ("/health", "/api/v1/dashboard/summary", "/api/v1/cases?limit=3",
                 "/api/v1/cases/CASE-0004", "/api/v1/cases/CASE-0004/timeline",
                 "/api/v1/recovery/kpis", "/api/v1/agent/tools"):
        try:
            req = urllib.request.Request(API + path, headers=key)
            urllib.request.urlopen(req, timeout=10)
            ok.append(f"OK   {path}")
        except Exception as e:
            ok.append(f"FAIL {path}: {e}")
    return ok


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(FRONTEND), **kw)

    def log_message(self, fmt, *args):
        pass


if __name__ == "__main__":
    if "--check" in sys.argv:
        print("\n".join(check_api()))
        sys.exit(0 if all(l.startswith("OK") for l in check_api()) else 1)
    print("API check:")
    results = check_api()
    print("\n".join(results))
    print("\nServing frontend at http://127.0.0.1:8020  (Ctrl+C to stop)")
    HTTPServer(("127.0.0.1", 8020), Handler).serve_forever()
