"""TOOL REGISTRY — full contracts for every agent tool (Sections 13–16).

Each tool declares the complete 14-field contract (Section 14). The registry
fails closed: a tool absent from the registry cannot be dispatched, whatever
the LLM says. Action tools are idempotent via `case_id:action_type` keys and
route through the RecoverySimulator at rollout levels 1–2 (Section 16).
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable

from ..settings import settings, can_execute_actions, is_shadow_mode
from ..agent.policies import VALID_RISK_LEVELS, PolicyViolation
from ..services.repository import repo, now_iso, idempotency_idkey_safe


# --------------------------------------------------------------------------- #
# contract model (Section 14)                                                 #
# --------------------------------------------------------------------------- #

@dataclass
class ToolContract:
    tool_name: str
    description: str
    input_schema: dict
    output_schema: dict
    risk_level: str
    allowed_roles: list
    allowed_case_categories: list          # [] = all
    approval_requirement: str              # NEVER | POLICY | ALWAYS
    idempotency_rule: str
    side_effects: list[str]
    timeout_seconds: int
    retry_policy: dict
    failure_status: str
    verification_method: str
    audit_event: str
    handler: Callable[..., dict] | None = field(default=None, repr=False)

    def describe(self) -> dict:
        """Contract without the handler (safe to expose via API)."""
        return {k: getattr(self, k) for k in (
            "tool_name", "description", "input_schema", "output_schema",
            "risk_level", "allowed_roles", "allowed_case_categories",
            "approval_requirement", "idempotency_rule", "side_effects",
            "timeout_seconds", "retry_policy", "failure_status",
            "verification_method", "audit_event")}


# standard retry policies
RETRY_NONE = {"max_retries": 0}
RETRY_2 = {"max_retries": 2, "backoff_ms": [200, 800]}
RETRY_1 = {"max_retries": 1, "backoff_ms": [500]}


class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, ToolContract] = {}
        self._simulator = None

    # ---------------------------------------------------------------- setup
    def register(self, contract: ToolContract) -> None:
        if contract.risk_level not in VALID_RISK_LEVELS:
            raise ValueError(f"tool {contract.tool_name}: unknown risk level")
        self._tools[contract.tool_name] = contract

    def get(self, name: str) -> ToolContract:
        if name not in self._tools:
            raise PolicyViolation(f"tool {name} is not registered")
        return self._tools[name]

    def all_contracts(self) -> list[dict]:
        return [c.describe() for c in self._tools.values()]

    def set_simulator(self, sim) -> None:
        self._simulator = sim

    # ------------------------------------------------------------ dispatch
    def dispatch(self, name: str, params: dict, case: dict,
                 actor: str = "AGENT", approval_id: str = "") -> dict:
        """Execute a tool under its contract. Idempotent actions replay.

        Returns {"ok": bool, "result": {...}, "action_id": str?, "status": str}
        — never lets a raw exception reach the agent loop.
        """
        contract = self.get(name)

        # category gate
        if (contract.allowed_case_categories
                and case.get("category") not in contract.allowed_case_categories):
            return {"ok": False, "status": "DENIED_CATEGORY",
                    "error": f"tool not allowed for category {case.get('category')}"}

        # side-effect gate (rollout level)
        if contract.side_effects and not can_execute_actions() and not is_shadow_mode():
            if contract.risk_level in ("L2", "L3", "L4"):
                # level 1-3: no side effects at all (drafts are L1 artifacts, fine)
                if not name.startswith("DRAFT"):
                    return {"ok": False, "status": "BLOCKED_BY_ROLLOUT_LEVEL",
                            "error": f"side-effecting tool blocked at rollout level "
                                     f"{settings.rollout_level}"}

        # idempotency for side-effecting tools
        action_id = ""
        if contract.idempotency_rule.startswith("case_action"):
            key = f"{case['case_id']}:{name.split('_')[0].upper()}"
            existing = repo.find_action_by_key(idempotency_idkey_safe(key))
            if existing:
                return {"ok": True, "status": "EXISTING",
                        "result": _parse_json(existing.get("result_payload", "{}")),
                        "action_id": existing["action_id"], "replayed": True}

        # retry loop
        result, status, err = None, "", None
        max_r = contract.retry_policy.get("max_retries", 0)
        for attempt in range(max_r + 1):
            try:
                result = contract.handler(case, params) if contract.handler else {}
                status = "OK"
                break
            except ToolTimeoutError:
                err = "timeout"
                status = contract.failure_status
            except Exception as e:                       # noqa: BLE001 — contract
                err = str(e)
                status = contract.failure_status
            if attempt < max_r:
                time.sleep(contract.retry_policy.get("backoff_ms", [500] * (attempt + 1))[attempt] / 1000)
        if result is None and status == "OK":
            status, err = contract.failure_status, "no result"

        # record action row for side-effecting tools (audit trail in ops)
        if contract.side_effects:
            action_id = repo.next_id("recovery_actions", "ACT-", "action_id")
            row = {
                "action_id": action_id, "case_id": case["case_id"],
                "tool_id": name, "action_type": name.upper(),
                "actor": actor, "status": "EXECUTED" if status == "OK" else status,
                "risk_level": contract.risk_level,
                "input_payload": _dumps(params), "result_payload": _dumps(result or {}),
                "external_ref": (result or {}).get("external_reference", ""),
                "idempotency_key": idempotency_idkey_safe(
                    f"{case['case_id']}:{name.split('_')[0].upper()}"),
                "approval_id": approval_id,
                "amount": params.get("amount", ""),
                "executed_at": now_iso(),
            }
            repo.append("recovery_actions", row)

        return {"ok": status == "OK", "status": status,
                "result": result or {}, "action_id": action_id,
                "error": err or ""}


class ToolTimeoutError(Exception):
    pass


def _dumps(x) -> str:
    import json
    try:
        return json.dumps(x, default=str)
    except Exception:
        return "{}"


def _parse_json(s: str) -> dict:
    import json
    try:
        return json.loads(s) if s else {}
    except Exception:
        return {}


registry = ToolRegistry()
