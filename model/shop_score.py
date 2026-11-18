"""Shop candidate scoring (plan §4), rule-based, no NN.

score = covenant gain x route weight + combat fit vs checklist gaps
      + economy (price vs budget, promotion potential) + pool availability.
Weights are heuristic initial values; calibrate.py fits them offline from
ratings+outcomes and emits a drift report for user review (never silent).
Core-starvation monitor: activated core route with few pool copies left ->
early warning to pivot (lesson from session 2: never drew the key 炎 core).

Extreme economy routes (奇迹/投资人) SUSPENDED per user decision 2026-11-18
("暂时先不考虑极端化玩法…推荐只推荐正常玩法"): no economy-route weight
amplification, no activation push, no 非常规 warning bucket. Temporary, not a
permanent delete -- KB game facts (covenant mechanics, mode pools) stay intact.

M1 trial-run refactor (user 2026-11-18, 炉石盒子 coherent-plan spec):
- same-name shop slots are MERGED into one candidate with count=N (fixes the
  duplicate 野鬃×2 rows); ``score_copy`` is the single scoring primitive used
  both for the first-copy evaluation (options/parts, calibrate-compatible) and
  for the planner's marginal copy-by-copy greedy (promotion-aware: the copy
  that reaches upgradeNum jumps in value).
"""

DEFAULT_W = {"cov": 1.0, "combat": 0.8, "econ": 0.5, "pool": 0.3, "promote": 0.6}

STARVATION_COPIES = 4   # provisional: remaining pool copies of a core route
# 极端经济路线标记盟约：不参与路线加权/激活推动/警示分桶（用户 2026-11-18，暂时）。
ECONOMY_BONDS = ("奇迹", "投资人")
# provisional quality bar at DEFAULT_W scale; planner co-calibrates it with the
# active weights (score scale shifts after calibrate --apply). 临时值, calibratable.
WORTH_BUY_MIN_SCORE = 4.0


def bond_counts(state, kb):
    """Operator counts per bond. Bench counts only for 远见/奇迹/投资人."""
    bench_mode = set(kb.rules["covenants"]["rules"]["bench_count_mode"])
    counts = {}
    for u in state.field_units:
        for b in (kb.operators.get(u.name, {}).get("bonds") or []):
            counts[b] = counts.get(b, 0) + 1
    for u in state.bench:
        for b in (kb.operators.get(u.name, {}).get("bonds") or []):
            if b in bench_mode:
                counts[b] = counts.get(b, 0) + 1
    return counts


def activate_threshold(bond, kb):
    cov = kb.rules["covenants"]
    if bond in cov["core"]:
        return cov["core_activate"]
    return cov["addon"].get(bond, {}).get("activate", 2)


def route_weights(state, kb, counts=None):
    """Commitment weight per bond: activated routes weigh more; near-threshold
    bonds get a push. Heuristic v0, replaced by calibrated weights later.
    ``counts`` overrides bond_counts(state) so the planner can re-weight with
    effective counts as buys are planned (activation push updates marginal)."""
    if counts is None:
        counts = bond_counts(state, kb)
    layers = state.covenants_rest
    w = {}
    for b in kb.core_names | kb.addon_names:
        if b in ECONOMY_BONDS:
            w[b] = 1.0  # extreme economy route suspended: flat, no amplification
            continue
        n = counts.get(b, 0)
        th = activate_threshold(b, kb)
        base = 1.0 + min(layers.get(b, 0), 100) / 50.0
        if n >= th:
            base *= 1.5            # already activated: deepen the route
        elif n == th - 1:
            base *= 1.3            # one copy from activation
        w[b] = base
    return w


def core_starvation(state, kb):
    """{bond: remaining copies} for activated core routes running dry."""
    counts = bond_counts(state, kb)
    out = {}
    for b in kb.core_names:
        if counts.get(b, 0) < activate_threshold(b, kb):
            continue
        left = 0
        for name, op in kb.operators.items():
            if b not in (op.get("bonds") or []):
                continue
            if not kb.operator_available(name, state.difficulty, state.banned_addons,
                                         state.core_group):
                continue
            left += (state.pool_remaining or {}).get(
                name, kb.rules["shop"]["pool_copies"][str(op["tier"])])
        if left <= STARVATION_COPIES:
            out[b] = left
    return out


def _combat_fit(name, state, kb, checks):
    op = kb.operators[name]
    st = op["stats"]
    fit = kb.power(st) / 1000.0
    reasons = []
    levels = {c["id"]: c["level"] for c in checks}
    if "FLY" in state.special_types and op.get("canHitFly") and levels.get("anti_air") in ("red", "yellow"):
        fit += 2.0
        reasons.append("补对空缺口")
    if op["profession"] == "MEDIC" and any(
            levels.get(f"resp_{t}") == "yellow" for t in ("DOT", "ELEMENT")):
        fit += 1.5
        reasons.append("补治疗应对特训")
    if levels.get("block") == "yellow" and st.get("blockCnt", 0) >= 2:
        fit += 0.8
        reasons.append("补阻挡")
    return fit, reasons


def _promote_value(op, have, kb):
    """Promotion part for buying one more copy given ``have`` already owned.
    Returns (promote, reason, completes) -- completes=True when this copy hits
    upgradeNum (买入即晋升, strategic override)."""
    need = op.get("upgradeNum", 3)
    if have >= need - 1:
        gpower = kb.power(op["golden"]["stats"]) - kb.power(op["stats"])
        return gpower / 1000.0, f"买入即晋升（{have}+1→{need}）", True
    if have > 0:
        return 0.3 * have, f"已有 {have} 份，晋升进度 {have}/{need}", False
    return 0.0, None, False


def _covenant_gain(op, counts, rw, starving, kb):
    """Covenant part for one copy given effective bond ``counts``.
    Returns (cov, reasons, flags, core_activation) -- core_activation=True when
    this copy crosses a CORE bond's activate threshold (差1激活核心, strategic)."""
    cov = 0.0
    reasons, flags = [], []
    core_activation = False
    for b in op.get("bonds") or []:
        if b in ECONOMY_BONDS:
            cov += 1.0  # flat: no extreme-route push (user 2026-11-18)
            continue
        n = counts.get(b, 0)
        th = activate_threshold(b, kb)
        gain = rw.get(b, 1.0)
        if n + 1 == th:
            gain += 2.0
            reasons.append(f"{b} 差1激活")
            if b in kb.core_names:
                core_activation = True
        elif n >= th:
            reasons.append(f"{b} 已激活，继续叠层")
        cov += gain
        if b in starving:
            flags.append("核心卡饥饿")
            reasons.append(f"{b} 路线池内仅剩 {starving[b]} 份，考虑早转线")
    return cov, reasons, flags, core_activation


def score_copy(name, state, kb, w, checks, counts, owned, rw, starving, funds,
               price=None):
    """Score buying ONE copy of ``name`` under effective counts/owned/funds.

    Single scoring primitive shared by score_shop (first-copy evaluation) and
    planner's marginal greedy. ``strategic`` marks copy that completes promotion
    or crosses a core activation -> worth buying regardless of the quality bar.
    """
    op = kb.operators[name]
    if price is None:
        price = op["price"]
    reasons, flags = [], ["试探"]
    cov, cov_reasons, cov_flags, core_act = _covenant_gain(op, counts, rw, starving, kb)
    reasons.extend(cov_reasons)
    flags.extend(cov_flags)
    fit, fit_reasons = _combat_fit(name, state, kb, checks)
    reasons.extend(fit_reasons)
    econ = 0.0
    if funds is not None:
        econ += 1.0 if price <= funds else -1.0
    promote, promote_reason, completes = _promote_value(op, owned.get(name, 0), kb)
    if promote_reason:
        reasons.append(promote_reason)
    pool = kb.draw_prob(name, state.difficulty, state.center_level or 1,
                        state.banned_addons, state.core_group, state.pool_remaining) * 10
    if kb.provisional("shop") or kb.provisional("economy"):
        flags.append("临时值")
    score = (w["cov"] * cov + w["combat"] * fit + w["econ"] * econ
             + w["pool"] * pool + w["promote"] * promote)
    return {"score": round(score, 3),
            "parts": {"cov": round(cov, 2), "combat": round(fit, 2), "econ": econ,
                      "pool": round(pool, 2), "promote": round(promote, 2)},
            "reasons": reasons or ["无显著协同，按战力补充"],
            "flags": sorted(set(flags)),
            "strategic": bool(completes or core_act),
            "price": price, "need": op.get("upgradeNum", 3)}


def score_shop(state, kb, weights=None, checks=()):
    """Score visible unsold shop slots, MERGED by name (count=N). Returns sorted
    candidate dicts (first-copy evaluation, parts kept for calibrate). Empty when
    shop not perceived -> advisor degrades. The planner re-scores marginally."""
    w = dict(DEFAULT_W, **(weights or {}))
    counts = bond_counts(state, kb)
    rw = route_weights(state, kb, counts)
    starving = core_starvation(state, kb)
    owned = {}
    for u in state.field_units + state.bench:
        owned[u.name] = owned.get(u.name, 0) + 1
    # group unsold, available, known slots by name -> one candidate with count=N
    groups = {}
    for slot in state.shop:
        if slot.sold or not slot.name or slot.name not in kb.operators:
            continue
        name = slot.name
        if not kb.operator_available(name, state.difficulty, state.banned_addons,
                                     state.core_group):
            continue
        price = slot.price if slot.price is not None else kb.operators[name]["price"]
        g = groups.setdefault(name, {"count": 0, "price": price})
        g["count"] += 1
    out = []
    for name, g in groups.items():
        sc = score_copy(name, state, kb, w, checks, counts, owned, rw, starving,
                        state.funds, price=g["price"])
        out.append({"action": "buy", "name": name, "count": g["count"],
                    "score": sc["score"], "reasons": sc["reasons"],
                    "flags": sc["flags"], "parts": sc["parts"],
                    "price": g["price"], "need": sc["need"],
                    "strategic": sc["strategic"]})
    out.sort(key=lambda o: -o["score"])
    return out