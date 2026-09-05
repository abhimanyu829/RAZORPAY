"""Audit chain integrity validator (Section 61 cron job).

Validates the per-case hash chain: every entry's prev_hash must equal the
previous entry's entry_hash for that case (GENESIS for the first), and each
entry_hash must recompute from its fields.

Usage:
  python scripts/validate_audit_chain.py                 # dev CSV ledger
  python scripts/validate_audit_chain.py --alert-if-broken   # cron mode: exit 1
"""
from __future__ import annotations

import csv
import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main(alert: bool = False) -> int:
    p = ROOT / "data" / "runtime" / "audit_ledger.csv"
    if not p.exists():
        print("audit ledger empty — nothing to validate")
        return 0
    rows = list(csv.DictReader(open(p, encoding="utf-8")))
    prev: dict[str, str] = {}
    broken_links: list[str] = []
    broken_hashes: list[str] = []
    for r in rows:
        expect = prev.get(r["case_id"], "GENESIS")
        if r["prev_hash"] != expect:
            broken_links.append(f"{r['audit_id']}({r['case_id']})")
        recomputed = hashlib.sha256(
            (str(r.get("prev_hash")) + str(r.get("audit_id"))
             + str(r.get("event_type")) + str(r.get("amount") or ""))
            .encode()).hexdigest()[:16]
        if recomputed != r.get("entry_hash"):
            broken_hashes.append(r["audit_id"])
        prev[r["case_id"]] = r["entry_hash"]
    print(f"audit chain: {len(rows)} entries, "
          f"{len(broken_links)} broken links, "
          f"{len(broken_hashes)} broken hashes")
    if broken_links:
        print("BROKEN LINKS:", broken_links[:10])
    if broken_hashes:
        print("BROKEN HASHES:", broken_hashes[:10])
    ok = not broken_links and not broken_hashes
    if not ok and alert:
        print("ALERT: audit chain failure — freeze agent actions")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(alert="--alert-if-broken" in sys.argv))
