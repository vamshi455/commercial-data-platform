"""Unit tests for the collections agent's pure logic (off-cluster)."""
from __future__ import annotations

import importlib.util
import os

_HERE = os.path.dirname(os.path.abspath(__file__))
_AGENT = os.path.abspath(os.path.join(
    _HERE, os.pardir, os.pardir, "agents", "collections", "agent.py"))
_spec = importlib.util.spec_from_file_location("collections_agent", _AGENT)
agent = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(agent)


def _acct(**kw):
    base = dict(account_id="A1", account_name="X", risk_tier="High",
                ar_balance=50000.0, oldest_invoice_days=45, open_invoice_count=2,
                account_health="Healthy")
    base.update(kw)
    return base


def test_is_actionable_true_for_high_risk_overdue():
    assert agent.is_actionable(_acct()) is True


def test_is_actionable_false_below_thresholds():
    assert agent.is_actionable(_acct(oldest_invoice_days=10)) is False   # not overdue enough
    assert agent.is_actionable(_acct(ar_balance=100.0)) is False          # too small
    assert agent.is_actionable(_acct(risk_tier="Low")) is False           # tier excluded


def test_priority_p1_high_value_or_critical():
    assert agent.priority_for(_acct(ar_balance=150000.0)) == "P1"
    assert agent.priority_for(_acct(account_health="Critical")) == "P1"


def test_priority_p2_and_p3():
    assert agent.priority_for(_acct(ar_balance=20000.0)) == "P2"          # High tier
    assert agent.priority_for(_acct(risk_tier="Medium", oldest_invoice_days=65)) == "P2"  # overdue
    assert agent.priority_for(_acct(risk_tier="Medium", oldest_invoice_days=40)) == "P3"


def test_action_type_escalation_for_p1():
    assert agent.recommend_action_type(_acct(ar_balance=150000.0)) == "csm_escalation"
    assert agent.recommend_action_type(_acct(ar_balance=20000.0)) == "dunning_email"


def test_detect_actionable_filters_and_orders():
    accts = [_acct(account_id="big", ar_balance=200000.0),          # P1
             _acct(account_id="mid", ar_balance=20000.0),           # P2
             _acct(account_id="low", risk_tier="Low")]              # excluded
    out = agent.detect_actionable(accts)
    ids = [a["account_id"] for a in out]
    assert ids == ["big", "mid"]                                    # low excluded, P1 first
    assert out[0]["priority"] == "P1" and "signal" in out[0]


def test_signal_is_human_readable():
    s = agent.signal_for(_acct(ar_balance=128500.0, oldest_invoice_days=47))
    assert "High risk" in s and "47d overdue" in s and "$128,500" in s


def test_action_id_stable_and_scoped():
    a = agent.action_id("A1", "run7")
    assert a == agent.action_id("A1", "run7")          # deterministic
    assert a != agent.action_id("A1", "run8")          # per-run


def test_parse_llm_json_lenient():
    ok = agent.parse_llm_json('prefix {"diagnosis":"d","draft":"e"} suffix')
    assert ok == {"diagnosis": "d", "draft": "e"}
    fallback = agent.parse_llm_json("no json here")
    assert fallback["diagnosis"] == "(no diagnosis)" and fallback["draft"] == "no json here"
