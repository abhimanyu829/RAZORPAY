"""Application settings — rollout levels, LLM provider, feature flags.

Rollout levels (Section 48):
  1 synthetic only (simulated tools, no external calls)
  2 synthetic + sandbox connectors
  3 live external read-only
  4 live agent recommendation (SHADOW: record proposal, no side effects)
  5 approved recovery execution
  6 limited autonomous actions
  7 production bounded autonomy

Environment overrides via env vars (REVENUEGUARD_*). Defaults are safe: level 1.
"""
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def business_now() -> datetime:
    """The authoritative clock for SLA/deadline decisions.

    Defaults to the synthetic universe's frozen EVAL_NOW so dev/eval runs are
    deterministic; REVENUEGUARD_BUSINESS_NOW overrides (production sets it to
    real UTC, which it equals anyway once live data flows).
    """
    val = os.environ.get("REVENUEGUARD_BUSINESS_NOW", "")
    if val:
        try:
            return datetime.fromisoformat(val.replace("Z", "+00:00"))
        except ValueError:
            pass
    for cand in (ROOT / "generators" / "config.py",):
        if cand.exists():
            import re
            m = re.search(r'EVAL_NOW\s*=\s*"([^"]+)"', cand.read_text(encoding="utf-8"))
            if m:
                return datetime.fromisoformat(m.group(1).replace("Z", "+00:00"))
    return datetime.now(timezone.utc)


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


@dataclass
class Settings:
    # ---- rollout / safety ----
    rollout_level: int = _int("REVENUEGUARD_ROLLOUT_LEVEL", 1)
    # ---- agent boundaries (Section 27) ----
    max_agent_steps: int = _int("REVENUEGUARD_MAX_AGENT_STEPS", 12)
    max_tool_retries: int = _int("REVENUEGUARD_MAX_TOOL_RETRIES", 2)
    max_actions_per_run: int = _int("REVENUEGUARD_MAX_ACTIONS_PER_RUN", 1)
    max_execution_seconds: int = _int("REVENUEGUARD_MAX_EXECUTION_SECONDS", 120)
    max_financial_exposure: float = float(os.environ.get("REVENUEGUARD_MAX_FINANCIAL_EXPOSURE", "5000"))

    # ---- LLM ----
    llm_provider: str = os.environ.get("REVENUEGUARD_LLM_PROVIDER", "simulated")   # simulated|openai_compat
    llm_base_url: str = os.environ.get("REVENUEGUARD_LLM_BASE_URL", "")
    llm_api_key: str = os.environ.get("REVENUEGUARD_LLM_API_KEY", "")
    llm_model: str = os.environ.get("REVENUEGUARD_LLM_MODEL", "gpt-4o-mini")
    llm_timeout_seconds: int = _int("REVENUEGUARD_LLM_TIMEOUT_SECONDS", 30)
    llm_max_retries: int = _int("REVENUEGUARD_LLM_MAX_RETRIES", 2)
    # strict mode: fail closed when a real LLM is configured but unavailable
    llm_strict: bool = os.environ.get("REVENUEGUARD_LLM_STRICT", "0") == "1"

    # ---- database ----
    # '' → CSV-backed adapter (works offline today); postgres DSN → Supabase
    database_url: str = os.environ.get("REVENUEGUARD_DATABASE_URL", "")

    # ---- paths ----
    data_raw: Path = field(default_factory=lambda: ROOT / "data" / "raw")
    data_staging: Path = field(default_factory=lambda: ROOT / "data" / "staging")
    data_runtime: Path = field(default_factory=lambda: ROOT / "data" / "runtime")
    data_exports: Path = field(default_factory=lambda: ROOT / "data" / "exports")

    # ---- api ----
    api_host: str = os.environ.get("REVENUEGUARD_API_HOST", "127.0.0.1")
    api_port: int = _int("REVENUEGUARD_API_PORT", 8010)
    api_keys: dict = field(default_factory=lambda: {
        # dev-mode API keys → roles (Supabase Auth replaces these in production)
        "rg-admin-key": "admin",
        "rg-finance-key": "finance_lead",
        "rg-analyst-key": "analyst",
        "rg-agent-key": "agent",
        "rg-evaluator-key": "evaluator",
    })

    # ---- connectors ----
    razorpay_key_id: str = os.environ.get("RAZORPAY_KEY_ID", "")
    razorpay_key_secret: str = os.environ.get("RAZORPAY_KEY_SECRET", "")
    shopify_domain: str = os.environ.get("SHOPIFY_DOMAIN", "")
    shopify_access_token: str = os.environ.get("SHOPIFY_ACCESS_TOKEN", "")
    webhook_secrets: dict = field(default_factory=lambda: {
        "razorpay": os.environ.get("RAZORPAY_WEBHOOK_SECRET", "dev-secret-razorpay"),
        "shopify": os.environ.get("SHOPIFY_WEBHOOK_SECRET", "dev-secret-shopify"),
    })


settings = Settings()
settings.data_runtime.mkdir(parents=True, exist_ok=True)


def can_execute_actions() -> bool:
    """Side-effecting tools only run from rollout level 5+."""
    return settings.rollout_level >= 5


def is_shadow_mode() -> bool:
    return settings.rollout_level == 4
