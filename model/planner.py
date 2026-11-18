"""Per-screen coherent operation planner (plan §4, M1 trial-run refactor).

User authoritative spec (2026-11-18, 炉石盒子 analogy): evaluate each visible
shop card's worth-buying -> worthy ones get an ORDERED purchase sequence within
the current funds budget -> if all below the worth-buying bar, recommend refresh
-> refresh is random, so NEVER pre-script post-refresh cards; re-evaluate on the
next rest screen. "One coherent plan per screen", not a cross-refresh script.

Hard floor: any red combat check vetoes ALL economy actions (保命优先); ratings
can never override a red check. Gate priority: hard_veto > funds_zero >
funds_unknown. Leftover funds are lost at round end -> spend-down (refresh as
the last step when nothing worth buying remains and EV>0).

Budget invariant: spent = upgrade(if do) + sum(buy cost) + refresh(if do) <= funds;
step order upgrade -> buys -> refresh(last). The worth-buying bar co-calibrates
with the active weights (score scale shifts after calibrate --apply).
"""

from .shop_score import (DEFAULT_W, WORTH_BUY_MIN_SCORE, bond_counts,
                         route_weights, core_starvation, score_copy)

REFRESH_TARGET_VALUE = 3.0  # provisional value of hitting a wanted card


def _worth_threshold(w):
    """Quality bar scaled to the active weight magnitude (co-calibrate). After
    calibrate --apply the score scale shifts; a fixed 4.0 would drift, so scale
    by sum(w)/sum(DEFAULT_W). Provisional, flagged 临时值 downstream."""
    base = sum(DEFAULT_W.values())
    cur = sum(w.values())
    return WORTH_BUY_MIN_SCORE * (cur / base if base else 1.0)


def _starved_routes(state, kb):
    return list(core_starvation(state, kb))


def plan(state, kb, checks, shop_candidates, weights=None):
    """Build the per-screen coherent plan. ``shop_candidates`` = merged buy
    candidates from shop_score.score_shop (name/count/price/score/parts/strategic).
    Returns dict with steps/budget/gate + upgrade/refresh/freeze/notes."""
    out = {"income": None, "upgrade": None, "refresh": None, "freeze": [],
           "notes": [], "flags": ["试探"], "steps": [], "budget": None, "gate": None}
    if state.round is None:
        out["notes"].append("回合未感知，规划降级")
        return out
    income = kb.income(state.round)
    out["income"] = income
    if kb.provisional("economy"):
        out["flags"].append("临时值")
    funds = state.funds
    veto = any(c["level"] == "red" for c in checks)
    w = dict(DEFAULT_W, **(weights or {}))
    refresh_price = kb.rules["economy"].get("refresh_price", 1)

    # ---- gate priority: hard_veto(red) > funds_zero > funds_unknown ----
    if veto:
        out["gate"] = "hard_veto"
    elif funds == 0:
        out["gate"] = "funds_zero"
    elif funds is None:
        out["gate"] = "funds_unknown"
    if out["gate"]:
        # suppress ALL economy actions; options buy entries removed by advisor
        if out["gate"] == "hard_veto":
            out["notes"].append("红线状态：只保命，不做经济动作")
        elif out["gate"] == "funds_zero":
            out["notes"].append("资金为 0，无购买力，不推荐购买")
        else:
            out["notes"].append("资金未感知，暂不推荐购买（无法核实买得起）")
        out["budget"] = {"funds": funds, "spent": 0, "remaining": funds}
        return out

    budget = funds
    spent = 0
    steps = []

    # ---- upgrade-first: unlock better shop before buying (provisional v0) ----
    if state.center_level is not None and state.difficulty:
        price = kb.upgrade_price(state.difficulty, state.center_level)
        if price is not None:
            slots_now = kb.slots(state.difficulty, state.center_level)
            slots_next = kb.slots(state.difficulty, state.center_level + 1)
            gain = (slots_next - slots_now) * 1.5 + state.center_level * 0.5
            do = funds >= price and gain >= price / 2.0
            reason = (f"升本 {state.center_level}→{state.center_level + 1}："
                      f"槽位 {slots_now}→{slots_next}，费用 {price}")
            if funds < price:
                reason += "；资金不足"
            out["upgrade"] = {"do": do, "price": price, "reason": reason,
                              "flags": ["临时值"]}
            if do:
                steps.append({"op": "upgrade", "name": None, "count": 1,
                              "cost": price, "score": price, "reasons": [reason]})
                budget -= price
                spent += price
    elif state.center_level is None:
        out["notes"].append("调度中心等级未感知，升本建议降级")
    elif state.difficulty is None:
        out["notes"].append("难度未设置，升本建议降级（GUI 设难度）")

    # ---- greedy coherent buys: marginal value within budget ----
    counts = bond_counts(state, kb)
    owned = {}
    for u in state.field_units + state.bench:
        owned[u.name] = owned.get(u.name, 0) + 1
    starving = core_starvation(state, kb)
    remaining = {c["name"]: c["count"] for c in shop_candidates}
    cand_price = {c["name"]: c["price"] for c in shop_candidates}
    threshold = _worth_threshold(w)
    counts_eff = dict(counts)
    owned_eff = dict(owned)
    while True:
        rw_eff = route_weights(state, kb, counts_eff)
        best, best_score = None, None
        for c in shop_candidates:
            name = c["name"]
            if remaining.get(name, 0) <= 0:
                continue
            price = cand_price[name]
            if price > budget:
                continue
            sc = score_copy(name, state, kb, w, checks, counts_eff, owned_eff,
                            rw_eff, starving, budget, price=price)
            if sc["score"] < threshold and not sc["strategic"]:
                continue  # below worth-buying bar and not strategic -> skip
            if best_score is None or sc["score"] > best_score:
                best, best_score = (name, price, sc), sc["score"]
        if best is None:
            break
        name, price, sc = best
        if steps and steps[-1]["op"] == "buy" and steps[-1]["name"] == name:
            steps[-1]["count"] += 1
            steps[-1]["cost"] += price
            steps[-1]["reasons"] = sc["reasons"]   # latest marginal reason
        else:
            steps.append({"op": "buy", "name": name, "count": 1, "cost": price,
                          "score": sc["score"], "reasons": sc["reasons"]})
        budget -= price
        spent += price
        owned_eff[name] = owned_eff.get(name, 0) + 1
        for b in kb.operators[name].get("bonds") or []:
            counts_eff[b] = counts_eff.get(b, 0) + 1
        remaining[name] -= 1

    # ---- refresh as spend-down LAST step (random reroll, never pre-scripted) ----
    # post-greedy no affordable worthy card remains; refresh only if EV>0 and
    # budget covers it (guards early-game/low-funds mindless refresh spam).
    if state.center_level is not None:
        wanted = [c["name"] for c in shop_candidates[:3]]
        wanted += [n for n, op in kb.operators.items()
                   if any(b in op.get("bonds", []) for b in _starved_routes(state, kb))]
        hit = 0.0
        for n in set(wanted):
            p = kb.draw_prob(n, state.difficulty, state.center_level,
                             state.banned_addons, state.core_group, state.pool_remaining)
            hit = 1 - (1 - hit) * (1 - p)
        slots = kb.slots(state.difficulty, state.center_level)
        ev = (1 - (1 - hit) ** slots) * REFRESH_TARGET_VALUE - 1.0
        do = ev > 0 and budget >= refresh_price
        reason = f"刷新 EV≈{ev:.2f}（目标命中率 {hit:.0%}）"
        if budget < refresh_price:
            reason += "；剩余资金不足刷新"
        elif ev <= 0:
            reason += "；EV 偏低暂不刷新"
        out["refresh"] = {"do": do, "ev": round(ev, 3), "reason": reason,
                          "flags": ["临时值"]}
        if do:
            steps.append({"op": "refresh", "name": None, "count": 1,
                          "cost": refresh_price, "score": round(ev, 3),
                          "reasons": [reason]})
            budget -= refresh_price
            spent += refresh_price
    else:
        out["notes"].append("调度中心等级未感知，刷新建议降级")
        out["refresh"] = {"do": False, "ev": None,
                          "reason": "调度中心等级未感知，刷新降级", "flags": []}

    # ---- freeze high-value unaffordable candidates (keep for next screen) ----
    for c in shop_candidates:
        if (remaining.get(c["name"], 0) > 0 and cand_price[c["name"]] > budget
                and c["score"] >= threshold):
            out["freeze"].append(c["name"])
    if out["freeze"]:
        out["notes"].append("冻结高价值但买不起的候选（休整开始有一次免费自动刷新）")

    # ---- spend-down honesty: leftover funds lost at round end ----
    if budget > 0:
        out["notes"].append(f"回合末资金清零：剩余 {budget} 将损失（无更多值得买，刷新未触发）")
    if not steps:
        out["notes"].append("本屏无值得买的卡（全低于阈值或买不起）")

    out["steps"] = steps
    out["budget"] = {"funds": funds, "spent": spent, "remaining": budget}
    return out