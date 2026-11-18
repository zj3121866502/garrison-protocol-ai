"""Advisor aggregation + feedback logging (plan §2, feedback-loop note).

v0 = solo only (coop recommendations deferred: teammate panel semantics +
countdown overlay red line). Emits recs.jsonl per the agreed schema:
{session, t, round, rec_id, state_hash, options:[{action, score, reasons,
flags, parts, count}], top_k, plan, checks, plan_notes, hard_veto}. ``plan`` is
the additive per-screen coherent operation plan (steps/refresh/upgrade/freeze/
budget/gate/notes, M1 trial-run refactor); ``options`` keeps merged ×N buy
candidates + parts so calibrate/report stay backward-compatible. ratings.jsonl
is written later by the GUI / replay review. Hard floor: red checks veto economy
actions (planner) and are surfaced on the recommendation; user ratings can never
override a red check.
"""
import json
import time
from pathlib import Path

from . import combat_check, shop_score, planner

FEEDBACK_DIR = Path(__file__).resolve().parent.parent / "data" / "feedback"
WEIGHTS_PATH = Path(__file__).resolve().parent / "weights.json"


def _load_weights():
    """Calibrated weights, only present after user-reviewed calibrate --apply."""
    if WEIGHTS_PATH.exists():
        return json.loads(WEIGHTS_PATH.read_text(encoding="utf-8"))
    return None


def advise(state, kb, weights=None, top_k=3, log_path=None):
    """Return recommendation bundle, or None when gated (coop / no round)."""
    if state.mode_tag == "coop":
        return None  # v0 solo-only gate
    if state.round is None:
        return None
    if weights is None:
        weights = _load_weights()
    checks = combat_check.check(state, kb)
    buys = shop_score.score_shop(state, kb, weights, checks)
    plan = planner.plan(state, kb, checks, buys, weights)
    gate = plan.get("gate")
    options = []
    # gate↔options consistency (M1 review item 1): when a gate suppresses buys,
    # options carries NO buy entries -- otherwise report.fmt_options would show
    # gated buys and its empty-options text would misattribute the funds gate as
    # "商店/阵容未感知". Gate reason lives in plan_notes + plan.gate; calibrate
    # naturally skips gated rounds (no buy parts).
    if not gate:
        for o in buys[:top_k]:
            options.append({"action": f"buy:{o['name']}", "name": o["name"],
                            "count": o.get("count", 1),
                            "score": o["score"], "reasons": o["reasons"],
                            "flags": o["flags"], "parts": o["parts"]})
        if plan.get("upgrade") and plan["upgrade"]["do"]:
            options.append({"action": "upgrade", "score": plan["upgrade"]["price"],
                            "reasons": [plan["upgrade"]["reason"]],
                            "flags": plan["upgrade"]["flags"]})
        if plan.get("refresh") and plan["refresh"]["do"]:
            options.append({"action": "refresh", "score": plan["refresh"]["ev"],
                            "reasons": [plan["refresh"]["reason"]],
                            "flags": plan["refresh"]["flags"]})
        for n in plan.get("freeze", []):
            options.append({"action": f"freeze:{n}", "score": 0,
                            "reasons": ["高价值候选，资金够再买"], "flags": ["试探"]})
    options.sort(key=lambda o: -(o["score"] or 0))
    rec = {"session": state.session, "t": state.t, "round": state.round,
           "rec_id": f"{state.session}:r{state.round}:{state.state_hash()}",
           "state_hash": state.state_hash(),
           "options": options[:top_k], "top_k": top_k,
           "plan": plan,
           "checks": checks, "plan_notes": plan["notes"],
           "hard_veto": combat_check.hard_veto(checks)}
    if log_path is not False:
        p = Path(log_path) if log_path else FEEDBACK_DIR / "recs.jsonl"
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return rec