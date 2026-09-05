"""LLM CLIENT — provider abstraction for the REASON + PLAN steps.

Providers:
  simulated       deterministic rule-based reasoner over the case payload
                  (offline, reproducible — the regression baseline)
  openai_compat   any OpenAI-chat-compatible endpoint (OpenAI, Azure, vLLM,
                  DeepSeek, local llama.cpp server) via env configuration

The provider NEVER sees ground truth: the caller passes the agent-safe case
payload built by agent/prompts.py. Output must pass AgentPlanSchema validation
before anything executes (Section 10).
"""
from __future__ import annotations

import json
import random
import re
import time
from typing import Any

from ..settings import settings

# --------------------------------------------------------------------------- #
# structured output contract (Section 10)                                     #
# --------------------------------------------------------------------------- #

AGENT_PLAN_SCHEMA_KEYS = {
    "case_id": str,
    "diagnosis": dict,          # {root_cause, confidence, explanation}
    "evidence_selection": list,  # [{evidence_id, reason}]
    "recommended_action": str,
    "reason_for_action": str,
    "requires_approval": bool,
    "draft_content": str,
    "stop_reason": (str, type(None)),
    "escalate": bool,
}

ALLOWED_ACTIONS = {
    "DRAFT_DISPUTE", "CREATE_DISPUTE", "NOTIFY_GATEWAY", "FINANCE_REVIEW",
    "ESCALATE", "CLOSE_NO_ACTION", "CREATE_PAYMENT_LINK",
    "SEND_RECEIVABLE_REMINDER", "PREPARE_CHARGEBACK_PACKET", "SCHEDULE_RETRY",
}

DIAGNOSIS_KEYS = {"root_cause": str, "confidence": float, "explanation": str}


class LLMValidationError(Exception):
    """LLM output violated the structured contract."""


class LLMUnavailableError(Exception):
    """No provider reachable (strict mode → fail closed)."""


def validate_agent_plan(plan: dict) -> dict:
    """Strict structural validation before ANY execution (Section 11).

    Returns the cleaned plan or raises LLMValidationError. This function is
    deliberately boring and total: it does not trust the model.
    """
    if not isinstance(plan, dict):
        raise LLMValidationError("plan must be a JSON object")
    missing = [k for k in AGENT_PLAN_SCHEMA_KEYS if k not in plan]
    if missing:
        raise LLMValidationError(f"missing keys: {missing}")

    case_id = plan["case_id"]
    if not isinstance(case_id, str) or not re.fullmatch(r"CASE-\d{4}", case_id):
        raise LLMValidationError(f"bad case_id: {case_id!r}")

    diag = plan["diagnosis"]
    if not isinstance(diag, dict) or any(k not in diag for k in DIAGNOSIS_KEYS):
        raise LLMValidationError("diagnosis must contain root_cause/confidence/explanation")
    if not isinstance(diag["root_cause"], str) or not diag["root_cause"].strip():
        raise LLMValidationError("diagnosis.root_cause must be non-empty string")
    try:
        conf = float(diag["confidence"])
        if not 0.0 <= conf <= 1.0:
            raise ValueError
    except (TypeError, ValueError):
        raise LLMValidationError("diagnosis.confidence must be a number in [0,1]")
    diag["confidence"] = conf

    ev = plan["evidence_selection"]
    if not isinstance(ev, list):
        raise LLMValidationError("evidence_selection must be a list")
    for item in ev:
        if not isinstance(item, dict) or "evidence_id" not in item or "reason" not in item:
            raise LLMValidationError("evidence items must be {evidence_id, reason}")
        if not re.fullmatch(r"EVID-\d{5}", str(item["evidence_id"])):
            raise LLMValidationError(f"bad evidence_id: {item['evidence_id']!r}")
        item["evidence_id"] = str(item["evidence_id"])

    action = plan["recommended_action"]
    if action not in ALLOWED_ACTIONS:
        raise LLMValidationError(
            f"recommended_action {action!r} is not a registered action")

    for key, types in (("reason_for_action", str), ("draft_content", str)):
        if not isinstance(plan[key], types):
            raise LLMValidationError(f"{key} must be a string")

    ra = plan["requires_approval"]
    if not isinstance(ra, bool):
        raise LLMValidationError("requires_approval must be boolean")
    esc = plan["escalate"]
    if not isinstance(esc, bool):
        raise LLMValidationError("escalate must be boolean")
    sr = plan["stop_reason"]
    if sr is not None and not isinstance(sr, str):
        raise LLMValidationError("stop_reason must be string or null")

    # semantic cross-checks (invariants that keep the loop honest)
    if plan["escalate"] and action not in ("ESCALATE", "FINANCE_REVIEW", "CLOSE_NO_ACTION"):
        raise LLMValidationError("escalate=true requires ESCALATE/FINANCE_REVIEW/CLOSE_NO_ACTION")
    if action == "CLOSE_NO_ACTION" and plan["stop_reason"] in (None, ""):
        raise LLMValidationError("CLOSE_NO_ACTION requires stop_reason")
    if plan["requires_approval"] and action in ("DRAFT_DISPUTE",):
        raise LLMValidationError("DRAFT_DISPUTE is L1 — never requires approval")

    return plan


# --------------------------------------------------------------------------- #
# simulated provider — deterministic reasoner (regression baseline)           #
# --------------------------------------------------------------------------- #

ROOT_CAUSE_TEMPLATES = {
    "SETTLEMENT_MISMATCH": "settlement credited below the contractual expected amount "
                           "(rate card MDR + GST on MDR + refund economics)",
    "FEE_DISCREPANCY": "gateway fee charged above the negotiated rate card beyond tolerance",
    "REFUND_ECONOMICS": "MDR fee not returned pro-rata on a processed refund",
    "PAYMENT_MISMATCH": "captured payment amount deviates from the order value",
    "GST_ITC_REVIEW": "input tax credit mismatch requiring finance review",
}


def _simulated_reason(case: dict) -> dict:
    cat = case.get("category", "SETTLEMENT_MISMATCH")
    evidence = case.get("evidence", [])
    variance = case.get("variance") or case.get("potential_leakage") or 0
    try:
        variance_f = float(variance)
    except (TypeError, ValueError):
        variance_f = 0.0

    sel = [{"evidence_id": e["evidence_id"],
            "reason": f"primary proof of the {cat.lower().replace('_', ' ')} variance"}
            for e in evidence[:3]] or [{"evidence_id": "EVID-00000", "reason": "none bound"}]

    deadline_state = case.get("deadline_state") or "OPEN"
    if deadline_state == "CLOSED":
        return {
            "case_id": case["case_id"],
            "diagnosis": {"root_cause": ROOT_CAUSE_TEMPLATES.get(cat, "unknown"),
                          "confidence": 0.75,
                          "explanation": "case deadline closed before action; "
                                         "escalating for human decision"},
            "evidence_selection": sel,
            "recommended_action": "ESCALATE",
            "reason_for_action": "deadline closed — automatic action no longer permissible",
            "requires_approval": False,
            "draft_content": "",
            "stop_reason": "deadline closed",
            "escalate": True,
        }

    allowed = case.get("allowed_actions", [])
    if "DRAFT_DISPUTE" in allowed:
        action, reason = "DRAFT_DISPUTE", ("draft the gateway dispute with bound evidence; "
                                            "submission goes through the approval gate")
    elif "CREATE_DISPUTE" in allowed:
        action, reason = "CREATE_DISPUTE", "no draft tool in policy; direct dispute creation"
    elif "NOTIFY_GATEWAY" in allowed:
        action, reason = "NOTIFY_GATEWAY", "notify the gateway support desk with the evidence pack"
    elif allowed:
        action, reason = allowed[0], "fallback to first policy-allowed action"
    else:
        action, reason = "ESCALATE", "no action allowed by policy"

    draft = ""
    if action == "DRAFT_DISPUTE":
        draft = (f"Subject: Settlement discrepancy on {case.get('order_id')} — "
                 f"₹{variance_f:.2f}\n\n"
                 f"Order {case.get('order_id')} (payment {case.get('payment_id')}) settled "
                 f"₹{case.get('actual_settlement', 0)} against contractual expectation "
                 f"₹{case.get('expected_settlement', 0)} after rate-card MDR and GST. "
                 f"We request reversal of the unexplained difference of ₹{variance_f:.2f}.")
    return {
        "case_id": case["case_id"],
        "diagnosis": {"root_cause": ROOT_CAUSE_TEMPLATES.get(cat, "unknown"),
                      "confidence": 0.9 if variance_f > 2 else 0.7,
                      "explanation": (f"{ROOT_CAUSE_TEMPLATES.get(cat, 'unknown')}; variance "
                                      f"₹{variance_f:.2f} exceeds tolerance and is unexplained "
                                      "by any documented adjustment")},
        "evidence_selection": sel,
        "recommended_action": action,
        "reason_for_action": reason,
        "requires_approval": action in ("CREATE_DISPUTE", "CREATE_PAYMENT_LINK"),
        "draft_content": draft,
        "stop_reason": None,
        "escalate": False,
    }


# --------------------------------------------------------------------------- #
# provider interface                                                          #
# --------------------------------------------------------------------------- #

class LLMClient:
    def __init__(self, provider: str | None = None):
        self.provider = provider or settings.llm_provider

    # -- public entry point --------------------------------------------------
    def reason_and_plan(self, case_payload: dict) -> dict:
        """Call the configured provider, validate output, bounded retry."""
        last_error: Exception | None = None
        attempts = settings.llm_max_retries + 1
        for attempt in range(attempts):
            try:
                raw = (self._call_simulated(case_payload) if self.provider == "simulated"
                       else self._call_openai_compat(case_payload))
                return validate_agent_plan(raw)
            except LLMValidationError as e:
                last_error = e
                # structural errors are deterministic to repeat → retry can help
                # only when a real model is behind the endpoint
                if self.provider == "simulated":
                    raise
            except LLMUnavailableError:
                raise
            except Exception as e:                      # transport / HTTP errors
                last_error = e
                if attempt < attempts - 1:
                    time.sleep(min(2 ** attempt, 5))     # bounded backoff
        if settings.llm_strict:
            raise LLMUnavailableError(f"LLM unavailable after {attempts} attempts: {last_error}")
        # non-strict: fall back to the deterministic reasoner, flagged
        plan = _simulated_reason(case_payload)
        plan["_fallback"] = True
        return validate_agent_plan(plan)

    # -- simulated -----------------------------------------------------------
    def _call_simulated(self, case_payload: dict) -> dict:
        return _simulated_reason(case_payload)

    # -- openai-compatible ---------------------------------------------------
    def _call_openai_compat(self, case_payload: dict) -> dict:
        import httpx
        if not (settings.llm_base_url and settings.llm_api_key):
            raise LLMUnavailableError("openai_compat provider configured without base_url/api_key")
        url = settings.llm_base_url.rstrip("/") + "/chat/completions"
        headers = {"Authorization": f"Bearer {settings.llm_api_key}",
                   "Content-Type": "application/json"}
        body = {
            "model": settings.llm_model,
            "messages": case_payload["_messages"],     # built by prompts.py
            "response_format": {"type": "json_object"},
            "temperature": 0.1,
        }
        try:
            resp = httpx.post(url, json=body, headers=headers,
                              timeout=settings.llm_timeout_seconds)
            resp.raise_for_status()
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
            return json.loads(content)
        except httpx.TimeoutException as e:
            raise LLMUnavailableError(f"LLM timeout: {e}") from e
        except (KeyError, ValueError) as e:
            raise LLMValidationError(f"unparsable LLM response: {e}") from e


# module-level instance
llm = LLMClient()


def _selftest() -> None:                                  # pragma: no cover
    sample = {"case_id": "CASE-0001", "category": "SETTLEMENT_MISMATCH",
              "evidence": [{"evidence_id": "EVID-00001"}],
              "allowed_actions": ["DRAFT_DISPUTE", "CREATE_DISPUTE"],
              "variance": 250.0, "potential_leakage": 250.0,
              "order_id": "ORD-1001", "payment_id": "PAY-1001",
              "expected_settlement": 9764.0, "actual_settlement": 9514.0,
              "deadline_state": "OPEN"}
    plan = llm.reason_and_plan(sample)
    assert plan["recommended_action"] == "DRAFT_DISPUTE"
    print("LLM selftest OK:", plan["recommended_action"])


if __name__ == "__main__":
    _selftest()
