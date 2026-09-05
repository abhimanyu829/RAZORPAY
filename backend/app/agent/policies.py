"""POLICY ENGINE — everything the LLM must not decide (Section 11/21/27/28/44).

The pipeline:
  LLM PLAN → SCHEMA VALIDATION → CASE POLICY VALIDATION → ALLOWED ACTION
  CHECK → RISK CHECK → APPROVAL CHECK → EXECUTION

This module is the gate between the model's recommendation and the tool
registry. It fails CLOSED: anything not explicitly allowed is denied.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# --------------------------------------------------------------------------- #
# action metadata (mirrors cfg.recovery_policies + ops.agent_tools)           #
# --------------------------------------------------------------------------- #

RISK_LEVELS = {
    # read/analysis (L0 covers both; risk_level strings stay L0)
    "GET_ORDER": "L0", "GET_PAYMENT": "L0", "GET_REFUND": "L0", "GET_FEE": "L0",
    "GET_SETTLEMENT": "L0", "GET_BANK_TRANSACTION": "L0", "GET_INVOICE": "L0",
    "GET_CASE_HISTORY": "L0", "GET_RATE_CARD": "L0",
    "CALCULATE_FEE": "L0", "CALCULATE_VARIANCE": "L0", "CHECK_CONTRACT": "L0",
    "CHECK_DEADLINE": "L0", "CHECK_DUPLICATE_CLAIM": "L0",
    "CHECK_EVIDENCE_COMPLETENESS": "L0",
    "CHECK_DISPUTE_STATUS": "L0", "CHECK_SETTLEMENT": "L0",
    "CHECK_BANK_CREDIT": "L0", "CHECK_PAYMENT_STATUS": "L0", "CHECK_RECOVERY": "L0",
    # drafts (reversible artifacts)
    "DRAFT_DISPUTE": "L1",
    # reversible side effects
    "NOTIFY_GATEWAY": "L2", "FINANCE_REVIEW": "L2", "ESCALATE": "L2",
    "CLOSE_NO_ACTION": "L2", "SCHEDULE_RETRY": "L2",
    "SEND_RECEIVABLE_REMINDER": "L2",
    # financial
    "CREATE_DISPUTE": "L3", "CREATE_PAYMENT_LINK": "L3",
    # legal/tax (reserved)
    "PREPARE_CHARGEBACK_PACKET": "L4",
}

# validation set: the only legal risk strings
VALID_RISK_LEVELS = {"L0", "L1", "L2", "L3", "L4"}

L3_ACTIONS = {"CREATE_DISPUTE", "CREATE_PAYMENT_LINK"}
L4_ACTIONS = {"PREPARE_CHARGEBACK_PACKET"}

# policy caps: category → auto-approve-below amount (₹) for L2 actions
AUTO_APPROVE_BELOW = {
    "FEE_DISCREPANCY": 250.0,
    "SETTLEMENT_MISMATCH": 500.0,
    "REFUND_ECONOMICS": 250.0,
    "PAYMENT_MISMATCH": 250.0,
    "GST_ITC_REVIEW": 0.0,
}

# always-escalate threshold regardless of category
ESCALATION_FLOOR = 5000.0

# actions with external financial exposure that counts toward the run cap
FINANCIAL_EXPOSURE_ACTIONS = {"CREATE_DISPUTE", "CREATE_PAYMENT_LINK",
                              "PREPARE_CHARGEBACK_PACKET"}


class PolicyViolation(Exception):
    """LLM plan denied by policy. Never retried blindly — recorded + escalated."""

    def __init__(self, reason: str, escalate: bool = True):
        super().__init__(reason)
        self.reason = reason
        self.escalate = escalate


@dataclass
class PolicyDecision:
    allowed: bool
    action: str
    risk_level: str
    approval_required: bool
    auto_approved: bool
    reasons: list[str] = field(default_factory=list)
    exposure_amount: float = 0.0


class PolicyEngine:
    """Stateless gate; all inputs explicit so every decision is auditable."""

    def __init__(self, max_actions_per_run: int = 1,
                 max_financial_exposure: float = 5000.0):
        self.max_actions_per_run = max_actions_per_run
        self.max_financial_exposure = max_financial_exposure

    # ---------------------------------------------------------------- gates
    def validate_plan(self, plan: dict, case: dict,
                      actions_this_run: int = 0,
                      exposure_this_run: float = 0.0) -> PolicyDecision:
        """Full LLM-plan → execution gate. Raises PolicyViolation on deny."""
        action = plan["recommended_action"]

        # 1) allowed-action check (case policy)
        allowed_list = (case.get("allowed_actions") or "").split("|") \
            if isinstance(case.get("allowed_actions"), str) else (case.get("allowed_actions") or [])
        if action not in allowed_list:
            raise PolicyViolation(
                f"action {action} not in case allowed_actions {allowed_list}")

        # 2) risk check
        risk = RISK_LEVELS.get(action)
        if risk is None:
            raise PolicyViolation(f"action {action} has no registered risk level")

        # 3) L4 tax/legal: always human, and never autonomous in MVP
        if action in L4_ACTIONS:
            return PolicyDecision(False, action, risk, True, False,
                                  ["L4 actions require human approval — denied autonomously"])

        # 4) one-primary-action rule (Section 28)
        if action in FINANCIAL_EXPOSURE_ACTIONS and actions_this_run >= self.max_actions_per_run:
            raise PolicyViolation(
                f"run already executed {actions_this_run} primary action(s); "
                f"limit {self.max_actions_per_run}")

        # 5) financial exposure cap (Section 27)
        if action in FINANCIAL_EXPOSURE_ACTIONS:
            amount = _to_float(case.get("potential_recovery")
                               or case.get("potential_leakage"))
            if exposure_this_run + amount > self.max_financial_exposure:
                raise PolicyViolation(
                    f"financial exposure cap exceeded: {exposure_this_run + amount:.2f} "
                    f"> {self.max_financial_exposure:.2f}")

        # 6) approval requirement (Section 29) — decided ONLY here
        approval_required, auto, reasons = self._approval(action, risk, case)

        d = PolicyDecision(True, action, risk, approval_required, auto, reasons)
        d.exposure_amount = (_to_float(case.get("potential_recovery")
                                       or case.get("potential_leakage"))
                             if action in FINANCIAL_EXPOSURE_ACTIONS else 0.0)
        return d

    def _approval(self, action: str, risk: str, case: dict) -> tuple[bool, bool, list]:
        amount = _to_float(case.get("potential_recovery") or case.get("potential_leakage"))
        category = case.get("category", "")
        reasons = []
        if risk == "L3":
            return True, False, [f"L3 financial action — human approval always"]
        if action == "ESCALATE" and amount > ESCALATION_FLOOR:
            reasons.append(f"amount {amount:.2f} > escalation floor {ESCALATION_FLOOR:.2f}")
            return True, False, reasons
        if risk == "L2":
            cap = AUTO_APPROVE_BELOW.get(category, 0.0)
            if amount > cap:
                reasons.append(f"L2 amount {amount:.2f} > auto-approve cap {cap:.2f} for {category}")
                return True, False, reasons
            reasons.append(f"L2 auto-approved below cap ({cap:.2f})")
            return False, True, reasons
        reasons.append(f"{risk} action — automatic")
        return False, True, reasons

    # ------------------------------------------------------ injection defence
    @staticmethod
    def scrub_untrusted_text(plan: dict) -> dict:
        """Section 44: the LLM output is itself untrusted at the boundary.
        Strip instruction-like content from fields that may echo evidence text.
        The plan validator + policy gate remain the real defense; this scrub
        keeps echoed instructions from even reaching dispute drafts."""
        import re
        injection_pat = re.compile(
            r"(ignore (all )?(previous|prior) instructions|disregard (the )?rules|"
            r"call create_dispute immediately|without approval|transfer the disputed amount)",
            re.IGNORECASE)

        def clean(value):
            if isinstance(value, str):
                return injection_pat.sub("[injected content removed]", value)
            if isinstance(value, list):
                return [clean(v) for v in value]
            if isinstance(value, dict):
                return {k: clean(v) for k, v in value.items()}
            return value

        return clean(plan)


def _to_float(x) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


def _selftest() -> None:                                  # pragma: no cover
    pe = PolicyEngine(max_actions_per_run=1, max_financial_exposure=5000)
    case = {"allowed_actions": "DRAFT_DISPUTE|CREATE_DISPUTE|ESCALATE",
            "category": "SETTLEMENT_MISMATCH", "potential_leakage": 250.0,
            "potential_recovery": 250.0}
    ok = pe.validate_plan({"recommended_action": "CREATE_DISPUTE"}, case)
    assert ok.allowed and ok.approval_required and ok.risk_level == "L3"
    try:
        pe.validate_plan({"recommended_action": "CREATE_PAYMENT_LINK"}, case)
        raise AssertionError("should have denied")
    except PolicyViolation as e:
        assert "not in" in str(e)
    # exposure cap
    big = dict(case, potential_leakage=9000.0, potential_recovery=9000.0)
    try:
        pe.validate_plan({"recommended_action": "CREATE_DISPUTE"}, big)
        raise AssertionError("should have denied by exposure")
    except PolicyViolation as e:
        assert "exposure" in str(e)
    print("policy selftest OK")


if __name__ == "__main__":
    _selftest()
