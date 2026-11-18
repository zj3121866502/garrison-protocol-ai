"""Coverage combat checklist (plan §5) -- HARD FLOOR, ratings cannot override.

Wave composition is random per game (no fixed wave table), so checks are
capability-coverage based, never round-number memorization. v0 computes only
what perception supports; unknown mappings stay 'unknown' (yellow-info),
never fabricated red/green. Provisional thresholds are named constants and
flagged 「临时值」 until calibrated on 35/35 previews + life-drop curves.
"""

# provisional thresholds (C/D, calibrate offline later; ±20% sensitivity scan)
LOW_LIFE_RED = 10
LOW_LIFE_YELLOW = 20
FLY_DPS_SHARE_YELLOW = 0.25   # fly-hitter share of team ATK when FLY present
BLOCK_RATIO_YELLOW = 1 / 3    # total block vs enemy_total (ground share unknown)


def _chk(cid, level, msg, flags=()):
    return {"id": cid, "level": level, "msg": msg, "flags": list(flags)}


def check(state, kb):
    """Return list of checks. hard_veto() = any red."""
    out = []
    units = state.field_units
    ops = kb.operators

    # 1. lethal preview (A-level semantics: incoming = combat-end damage)
    if state.life is not None and state.incoming is not None:
        if state.incoming >= state.life:
            out.append(_chk("lethal", "red",
                            f"预计扣血 {state.incoming} ≥ 剩余生命 {state.life}，本回合可能致命"))
        else:
            out.append(_chk("lethal", "green",
                            f"预计扣血 {state.incoming} < 剩余生命 {state.life}"))
    elif state.life is not None:
        if state.life <= LOW_LIFE_RED:
            out.append(_chk("low_life", "red", f"生命 {state.life} ≤ {LOW_LIFE_RED}，容错极低"))
        elif state.life <= LOW_LIFE_YELLOW:
            out.append(_chk("low_life", "yellow", f"生命 {state.life} ≤ {LOW_LIFE_YELLOW}，注意容错"))
        else:
            out.append(_chk("low_life", "green", f"生命 {state.life}"))

    # 2. anti-air coverage vs known special types
    fly_ops = {n for n, o in ops.items() if o.get("canHitFly")}
    hitters = [u for u in units if u.name in fly_ops]
    if "FLY" in state.special_types:
        if units and not hitters:
            out.append(_chk("anti_air", "red", "本局含飞行特训，场上无可对空干员"))
        elif units:
            total_atk = sum((ops[u.name]["stats"]["atk"] for u in units if u.name in ops), 0)
            fly_atk = sum((ops[u.name]["stats"]["atk"] for u in hitters if u.name in ops), 0)
            share = fly_atk / total_atk if total_atk else 0.0
            if share < FLY_DPS_SHARE_YELLOW:
                out.append(_chk("anti_air", "yellow",
                                f"对空输出占比 {share:.0%} 偏低（阈值 {FLY_DPS_SHARE_YELLOW:.0%}）",
                                ["临时值"]))
            else:
                out.append(_chk("anti_air", "green", f"对空输出占比 {share:.0%}"))
        else:
            out.append(_chk("anti_air", "unknown", "本局含飞行特训，阵容未感知"))
    elif not state.special_types:
        out.append(_chk("anti_air", "unknown", "特训类型未感知（战前简报 OCR 未落地）"))
    else:
        out.append(_chk("anti_air", "green", "本局特训类型不含飞行"))

    # 3. block coverage (ground share unknown -> provisional ratio)
    if units and state.enemy_total:
        block = sum(ops[u.name]["stats"].get("blockCnt", 0) for u in units if u.name in ops)
        if block < state.enemy_total * BLOCK_RATIO_YELLOW:
            out.append(_chk("block", "yellow",
                            f"总阻挡 {block} vs 敌人总量 {state.enemy_total}（地面占比未知）",
                            ["临时值"]))
        else:
            out.append(_chk("block", "green", f"总阻挡 {block} vs 敌人总量 {state.enemy_total}"))

    # 4. DPS tier vs template strength P: enemy base stats not extracted yet.
    #    Report team power as info only; threshold stays unknown until calibrated.
    if units:
        power = sum(kb.power(ops[u.name]["stats"]) for u in units if u.name in ops)
        out.append(_chk("dps", "unknown",
                        f"阵容战力 {power}（DPS 档位阈值待用 35/35 预览+扣血曲线校准）",
                        ["临时值"]))

    # 5. special-type response: only verified mappings produce verdicts
    medics = [u for u in units if u.name in ops and ops[u.name]["profession"] == "MEDIC"]
    for st in state.special_types:
        if st in ("DOT", "ELEMENT"):
            if units and not medics:
                out.append(_chk(f"resp_{st}", "yellow", f"特训 {st}：场上无医疗干员"))
            elif units:
                out.append(_chk(f"resp_{st}", "green", f"特训 {st}：医疗 {len(medics)} 名"))
        elif st != "FLY":
            out.append(_chk(f"resp_{st}", "unknown", f"特训 {st} 的应对语义待核，不臆造结论"))
    return out


def hard_veto(checks):
    """Any red = hard floor breached. Spend-down risky actions must be blocked."""
    return any(c["level"] == "red" for c in checks)