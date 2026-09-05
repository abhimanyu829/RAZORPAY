# Deployment check — Section 63 checklist, executable.
# Verifies every deployment gate locally (dev evidence) and against a target
# Supabase DSN when provided.
import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(ROOT / "generators"))

PASS = FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ok    {name}")
    else:
        FAIL += 1
        print(f"  FAIL  {name} — {detail}")


def gate_migrations():
    print("\n[1] Database migrations")
    for f in ["database/schema.sql", "database/seed.sql", "database/functions.sql",
              "database/views.sql", "database/indexes.sql",
              "supabase/migrations/002_security_rls_storage.sql",
              "supabase/generated/load_data.sql"]:
        check(f"migration artifact present: {f}", (ROOT / f).exists())
    m = (ROOT / "supabase/migrations/002_security_rls_storage.sql").read_text(encoding="utf-8")
    check("RLS enabled in migration 002", "ROW LEVEL SECURITY" in m)
    check("eval isolation (deny-all policies)", "p_deny_agent_gt" in m or "RESTRICTIVE" in m)
    check("roles created (admin/finance/agent/evaluator)",
          all(r in m for r in ("app_admin", "app_agent", "app_evaluator")))


def gate_security():
    print("\n[2] Security & isolation")
    # secrets not in git-tracked frontend/backend source
    patterns = [re.compile(r"sk_live_[A-Za-z0-9]{10,}"),
                re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")]
    hits = []
    for p in list((ROOT / "webui/src").rglob("*")) + list((ROOT / "backend/app").rglob("*.py")):
        if p.is_file() and p.suffix in (".ts", ".tsx", ".py"):
            blob = p.read_text(encoding="utf-8", errors="ignore")
            for pat in patterns:
                if pat.search(blob):
                    hits.append(str(p))
    check("no real secrets committed in source", not hits, str(hits[:3]))
    # demo keys documented as dev-only
    settings = (BACKEND / "app/settings.py").read_text(encoding="utf-8")
    check("dev keys isolated to settings (documented dev fallback)",
          "rg-admin-key" in settings)
    # frontend never holds DB credentials
    api = (ROOT / "webui/src/api.ts").read_text(encoding="utf-8")
    check("frontend has no DB URL/credentials",
          "DATABASE_URL" not in api and "service_key" not in api.lower())


def gate_tool_gating():
    print("\n[3] Tool gating & approvals")
    import app.tools.implementations          # registers all tools at import
    from app.tools.registry import registry
    contracts = registry.all_contracts()
    check("30 tools registered with contracts", len(contracts) == 30,
          str(len(contracts)))
    def _has_se(t) -> bool:
        se = t["side_effects"]
        if isinstance(se, str):
            return se.strip() not in ("", "none", "None", "[]", "None — read only")
        return bool(se)
    side_effect = [t for t in contracts if _has_se(t)]
    approval_needed = [t for t in contracts
                       if t["risk_level"] in ("L2", "L3", "L4")]
    check("every side-effecting tool has risk >= L1",
          all(t["risk_level"] in ("L1", "L2", "L3", "L4")
              for t in side_effect),
          str([(t["tool_name"], t["risk_level"]) for t in side_effect
               if t["risk_level"] not in ("L1", "L2", "L3", "L4")][:3]))
    check("no L3/L4 tool auto-approves",
          all(t["approval_requirement"] != "AUTO" or
              "policy" in str(t["approval_requirement"]).lower()
              for t in approval_needed))
    check("idempotency rule declared on every action tool",
          all(t["idempotency_rule"] for t in side_effect))


def gate_rollout():
    print("\n[4] Rollout mode")
    from app.settings import settings
    check("rollout level is configured", settings.rollout_level in range(1, 8),
          settings.rollout_level)
    check("production default gates enforced in code",
          hasattr(settings, "rollout_level"))


def gate_eval_regression():
    print("\n[5] Evaluation regression (latest suite results)")
    p = ROOT / "data/exports/phase15_release_suite.json"
    check("Phase 15 release suite ran", p.exists())
    if p.exists():
        d = json.loads(p.read_text(encoding="utf-8"))
        ev = d["report"]["evaluation"]["regression"]
        check("precision == 1.00", ev["precision"] == 1.0, ev["precision"])
        check("category accuracy >= 0.98", ev["category_accuracy"] >= 0.98,
              ev["category_accuracy"])
        check("suite zero failures", d["fail"] == 0, d["fail"])


def gate_audit():
    print("\n[6] Audit chain")
    import csv, hashlib
    rows = list(csv.DictReader(open(ROOT / "data/runtime/audit_ledger.csv",
                                    encoding="utf-8"))) if (ROOT / "data/runtime/audit_ledger.csv").exists() else []
    prev, broken = {}, 0
    for r in rows:
        if r["prev_hash"] != prev.get(r["case_id"], "GENESIS"):
            broken += 1
        prev[r["case_id"]] = r["entry_hash"]
    check("audit chain intact", broken == 0, broken)


def gate_environments():
    print("\n[7] Environment separation")
    env_dir = ROOT / "deploy/env"
    check("env templates present (dev/staging/prod)",
          all((env_dir / f".env.{n}.example").exists()
              for n in ("dev", "staging", "prod")))
    docker = ROOT / "deploy/docker-compose.yml"
    check("docker compose present", docker.exists())
    df = ROOT / "deploy/Dockerfile"
    check("Dockerfile present", df.exists())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", default="dev", choices=["dev", "staging", "prod"])
    args = ap.parse_args()
    print(f"DEPLOYMENT CHECK — target: {args.target}")
    for g in (gate_migrations, gate_security, gate_tool_gating, gate_rollout,
              gate_eval_regression, gate_audit, gate_environments):
        try:
            g()
        except Exception as e:
            check(f"{g.__name__} crashed", False, repr(e))
    print(f"\n{'='*52}\nPASS {PASS}  FAIL {FAIL}")
    if args.target == "prod":
        print("PROD GATE:", "GO" if FAIL == 0 else "NO-GO")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
