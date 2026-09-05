"""RECOVERY SIMULATOR — Phase 9 simulation mode (Section 16).

Deterministic outcome engine for side-effecting tools at rollout levels 1–2.
Scenario per case is seeded from the case_id hash so reruns are reproducible,
and the outcome set can be forced per case for tests:

    success | failure | timeout | duplicate | already_resolved | partial | none

Verification tools query the simulator state, so the FULL loop
(action → verification → audit → KPI) is exercisable without any external API.
"""
from __future__ import annotations

import hashlib
import json
import random
from typing import Any

from ..settings import settings
from ..services.repository import repo, now_iso

SCENARIOS = ["success", "failure", "timeout", "duplicate",
             "already_resolved", "partial", "none"]


class RecoverySimulator:
    def __init__(self):
        # dispute_id → state
        self._disputes: dict[str, dict] = {}
        # case_id → forced scenario (tests)
        self._forced: dict[str, str] = {}

    def force(self, case_id: str, scenario: str) -> None:
        if scenario not in SCENARIOS + ["success"]:
            raise ValueError(f"unknown scenario {scenario}")
        self._forced[case_id] = scenario

    def clear_forced(self) -> None:
        self._forced.clear()

    # ------------------------------------------------------------- helpers
    def _seeded(self, case: dict) -> random.Random:
        h = hashlib.sha256((case["case_id"] + settings.llm_model).encode()).hexdigest()
        return random.Random(int(h[:16], 16))

    def _scenario(self, case: dict) -> str:
        if case["case_id"] in self._forced:
            return self._forced[case["case_id"]]
        rng = self._seeded(case)
        roll = rng.random()
        if roll < 0.55:
            return "success"
        if roll < 0.75:
            return "partial"
        if roll < 0.85:
            return "none"
        if roll < 0.90:
            return "failure"
        if roll < 0.95:
            return "already_resolved"
        if roll < 0.98:
            return "duplicate"
        return "timeout"

    # ------------------------------------------------------- action outcomes
    def create_dispute(self, case: dict, params: dict) -> dict:
        scenario = self._scenario(case)
        amount = float(params.get("amount") or case.get("potential_recovery")
                       or case.get("potential_leakage") or 0)
        dispute_id = f"DIS-{case['case_id']}"

        if scenario in ("duplicate",):
            # a previous dispute exists — replay-safe response
            if dispute_id in self._disputes:
                return {"external_reference": dispute_id, "dispute_id": dispute_id,
                        "status": "DUPLICATE", "submitted_at": now_iso(),
                        "simulated": True}
        if scenario == "already_resolved":
            return {"external_reference": dispute_id, "dispute_id": dispute_id,
                    "status": "ALREADY_RESOLVED", "submitted_at": now_iso(),
                    "simulated": True}

        state = {"dispute_id": dispute_id, "amount": amount, "scenario": scenario,
                 "status": "SUBMITTED", "submitted_at": now_iso(),
                 "recovered": 0.0, "mode": ""}
        self._disputes[dispute_id] = state

        if scenario == "timeout":
            # the action row records the timeout; verification later sees nothing
            state["status"] = "TIMEOUT"
            return {"external_reference": dispute_id, "dispute_id": dispute_id,
                    "status": "SUBMIT_TIMEOUT", "submitted_at": now_iso(),
                    "simulated": True}

        if scenario == "failure":
            state["status"] = "REJECTED"
            return {"external_reference": dispute_id, "dispute_id": dispute_id,
                    "status": "SUBMIT_FAILED", "submitted_at": now_iso(),
                    "simulated": True, "error": "gateway rejected dispute payload"}

        state["status"] = "SUBMITTED"
        return {"external_reference": dispute_id, "dispute_id": dispute_id,
                "status": "SUBMITTED", "submitted_at": now_iso(),
                "simulated": True}

    def notify_gateway(self, case: dict, params: dict) -> dict:
        return {"ticket_id": f"TIC-{case['case_id']}", "status": "SENT",
                "simulated": True}

    def create_finance_review(self, case: dict, params: dict) -> dict:
        return {"review_id": f"REV-{case['case_id']}", "status": "OPENED",
                "simulated": True}

    def create_payment_link(self, case: dict, params: dict) -> dict:
        link_id = "PL-" + hashlib.sha256(
            f"{case['case_id']}:{params.get('amount')}".encode()).hexdigest()[:12]
        return {"link_id": link_id, "url": f"https://rzp.io/i/{link_id}",
                "amount": params.get("amount"), "simulated": True}

    def send_receivable_reminder(self, case: dict, params: dict) -> dict:
        return {"reminder_id": f"REM-{case['case_id']}", "status": "SENT",
                "simulated": True}

    def prepare_chargeback_packet(self, case: dict, params: dict) -> dict:
        return {"packet_id": f"CBP-{case['case_id']}", "status": "DRAFTED",
                "simulated": True}

    def schedule_retry(self, case: dict, params: dict) -> dict:
        return {"retry_id": f"RTY-{case['case_id']}", "status": "SCHEDULED",
                "simulated": True}

    def escalate(self, case: dict, params: dict) -> dict:
        return {"escalation_id": f"ESC-{case['case_id']}", "status": "ESCALATED",
                "simulated": True}

    def close_no_action(self, case: dict, params: dict) -> dict:
        return {"status": "CLOSED_NO_ACTION",
                "reason": params.get("reason", "not recoverable"),
                "simulated": True}

    # -------------------------------------------------- verification outcomes
    def resolve_dispute(self, dispute_id: str) -> dict:
        """Simulated downstream resolution, queried by verification tools."""
        st = self._disputes.get(dispute_id)
        if not st:
            return {"status": "NOT_FOUND", "recovered": 0.0, "mode": ""}
        if st["status"] == "TIMEOUT":
            return {"status": "TIMEOUT", "recovered": 0.0, "mode": ""}
        if st["status"] == "REJECTED":
            return {"status": "REJECTED", "recovered": 0.0, "mode": ""}
        scenario = st["scenario"]
        if scenario == "success":
            st.update(recovered=st["amount"], mode="FULL")
            return {"status": "RESOLVED", "recovered": st["amount"], "mode": "FULL"}
        if scenario == "partial":
            rec = round(st["amount"] * 0.6, 2)
            st.update(recovered=rec, mode="PARTIAL")
            return {"status": "RESOLVED", "recovered": rec, "mode": "PARTIAL"}
        # none / already_resolved → nothing more arrives
        return {"status": "PENDING", "recovered": 0.0, "mode": ""}


# single simulator instance for the process
simulator = RecoverySimulator()
