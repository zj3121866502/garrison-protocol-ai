"""M1 replay comparison report generator (协作A lane).

Spec: notes/20261118-协作B-B3-评分UX与回放对照报告spec.md §3.3, with A review
corrections C1-C3 / O1-O2 (notes/20261118-B3-spec评审.md). The report is material
for USER judgment of recommendation reasonableness -- NOT an acceptance harness
(plan §6 step 4). It presents evidence (recommendation vs clicks vs outcome) and
never declares the model right/wrong; corrections go back via ratings.correction.

Inputs (all existing fields, no schema redefinition):
  replay_recs.jsonl (replay.py)  per-round rec + input + user_clicks_in_round
  curves.jsonl (parse_hud)       life_incoming = damage PREVIEW (-M token)
  rounds.json (parse_hud)        life_start per round (canon), clicks, drops
  settlement.json                rounds_passed = round-count AUTHORITY (not curves max)
  meta.json (raw)                outcome_user / route_tag / difficulty_user / mode_tag
  ratings.jsonl (optional)       score / followed / correction / risk_flag
  covenants_temp.json (optional) 乌萨斯-only temp + envelope + flags (KB v1.3)

Honest grading (B3 §3.4): input=="HUD-only" rounds are degraded (no shop -> no buy
recs); input=="SHOP-NAME" rounds carry real buy recs but price/tier are KB-fallback
provisional and roster is unperceived (synergy reasons limited). Coarse alignment:
clicks are a COUNT, not action semantics -> report gives 点击活跃/清淡 + 结局好/差,
never a 跟随/偏离 verdict (followed stays user-self-rated until P1 click semantics).

Usage: python -m model.report <analysis_dir> [<analysis_dir> ...] --out reports/
"""
import argparse
import io
import json
from pathlib import Path

ACTION_SEMANTIC = {"buy": "效用分", "upgrade": "升本价", "refresh": "刷新EV", "freeze": "试探(0)"}
LEVEL_ICON = {"red": "红", "yellow": "黄", "green": "绿", "unknown": "未知"}


def _jsonl(p):
    p = Path(p)
    if not p.exists():
        return []
    return [json.loads(l) for l in io.open(p, encoding="utf-8") if l.strip()]


def _json(p, default=None):
    p = Path(p)
    if not p.exists():
        return default
    return json.loads(p.read_text(encoding="utf-8"))


def join_ratings(recs, ratings):
    """O1: exact rec_id first, fallback to {session}:r{round}: prefix.
    state_hash drifts when perception improves (P1) -> prefix keeps history joined."""
    by_id = {r["rec_id"]: r for r in ratings}
    by_prefix = {}
    for r in ratings:
        pref = r["rec_id"].rsplit(":", 1)[0]
        by_prefix.setdefault(pref, []).append(r)
    out = {}
    for rec in recs:
        if rec["rec_id"] in by_id:
            out[rec["round"]] = by_id[rec["rec_id"]]
        else:
            cand = by_prefix.get(f"{rec['session']}:r{rec['round']}", [])
            if cand:
                out[rec["round"]] = cand[-1]
    return out


def round_outcomes(curves, rounds):
    """C3: preview = life_incoming (-M, predicted); actual = cross-round life drop.
    life per round from rounds.json life_start (canon). actual[rn]=life[rn]-life[rn+1]."""
    life = {g["round"]: g.get("life_start") for g in rounds}
    preview = {}
    for r in curves:
        rn = r.get("round")
        if rn is not None and r.get("life_incoming") is not None:
            preview[rn] = max(preview.get(rn, 0), r["life_incoming"])
    rns = sorted(life)
    actual = {}
    for k, rn in enumerate(rns):
        if life[rn] is None:
            continue
        nxt = life[rns[k + 1]] if k + 1 < len(rns) else None
        if nxt is not None:
            actual[rn] = life[rn] - nxt
    return life, preview, actual


def _flag_mark(flags):
    marks = []
    if any("饥饿" in f for f in flags):
        marks.append("饥饿")
    if "临时值" in flags:
        marks.append("临时")
    return ("[" + "/".join(marks) + "]") if marks else ""


def fmt_options(options, gate=None):
    """O2: group by action type, label score semantics (not cross-comparable).
    ``gate`` (plan.gate) disambiguates empty options: a funds/red-line gate is
    NOT perception loss (M1 review item 1, report honesty)."""
    if not options:
        if gate == "hard_veto":
            return "（红线否决：只保命，不做经济动作）"
        if gate == "funds_zero":
            return "（资金闸门：资金为 0，无购买力）"
        if gate == "funds_unknown":
            return "（资金闸门：资金未感知，暂不推荐购买）"
        return "（无具体推荐：商店/阵容未感知，仅战斗清单+收入方向）"
    groups = {"buy": [], "upgrade": [], "refresh": [], "freeze": []}
    for o in options:
        kind = o["action"].split(":")[0]
        groups.setdefault(kind, []).append(o)
    lines = []
    for kind in ("buy", "upgrade", "refresh", "freeze"):
        os_ = groups.get(kind, [])
        if not os_:
            continue
        sem = ACTION_SEMANTIC.get(kind, kind)
        if kind == "buy":
            items = []
            for o in os_:
                reason = o["reasons"][0] if o.get("reasons") else ""
                items.append(f"{o['name']} {o['score']}{_flag_mark(o['flags'])}（{reason}）")
            lines.append(f"买[{sem}]：" + "；".join(items))
        elif kind == "freeze":
            names = "/".join(o["action"].split(":")[1] for o in os_)
            lines.append(f"冻[{sem}]：{names}（高价值买不起，试探）")
        else:
            o = os_[0]
            reason = o["reasons"][0] if o.get("reasons") else ""
            label = "升本" if kind == "upgrade" else "刷新"
            lines.append(f"{label}[{sem}]：{o['score']}（{reason}）{_flag_mark(o['flags'])}")
    return "<br>".join(lines)


def fmt_checks(checks, hard_veto):
    if not checks:
        return "（无清单）"
    s = " / ".join(f"{c['id']}:{LEVEL_ICON.get(c['level'], c['level'])}" for c in checks)
    return s + (" · **红线否决**" if hard_veto else " · veto否")


def difficulty_display(meta, band):
    if meta.get("difficulty_user") == "lowest":
        return "规程1–4（最低难度，用户实证）"
    if band and band.startswith("solo_regulation"):
        return "规程5+（高难池；具体等级未取证，对推荐无影响）"
    return band or "未取证"


def session_report(analysis_dir, band):
    analysis_dir = Path(analysis_dir)
    session = analysis_dir.name
    raw = analysis_dir.parent.parent / "raw" / session
    meta = _json(raw / "meta.json", {})
    settle = _json(analysis_dir / "settlement.json", {})
    recs = _jsonl(analysis_dir / "replay_recs.jsonl")
    curves = _jsonl(analysis_dir / "curves.jsonl")
    rounds = _json(analysis_dir / "rounds.json", [])
    ratings = _jsonl(Path(__file__).resolve().parent.parent / "data" / "feedback" / "ratings.jsonl")
    ratings += _jsonl(analysis_dir.parent.parent / "feedback" / "ratings.jsonl")
    ratings += _jsonl(analysis_dir / "ratings.jsonl")
    cov_temp = _json(analysis_dir / "covenants_temp.json", [])
    rated = join_ratings(recs, ratings)
    life, preview, actual = round_outcomes(curves, rounds)

    n_total = len(recs)
    n_shop = sum(1 for r in recs if r["input"] == "SHOP-NAME")
    n_degraded = sum(1 for r in recs if r["input"] == "HUD-only")
    degraded_rns = [r["round"] for r in recs if r["input"] == "HUD-only"]
    rounds_passed = settle.get("rounds_passed")
    outcome = meta.get("outcome_user") or settle.get("outcome") or "unknown"
    rns = sorted(life)
    initial_life = life[rns[0]] if rns else None
    final_life = life[rns[-1]] if rns else None
    total_drop = (initial_life - final_life) if (initial_life is not None and final_life is not None) else None

    L = []
    L.append(f"# 回放对照报告 · {session}\n")
    L.append("> 本报告供你判「模型这步建议合不合理」，不是自动验收。读完把纠正写回评分（ratings.correction）。"
             "报告只呈现证据，不宣布模型对/错。\n")
    L.append("## 局头\n")
    L.append(f"- 模式：{meta.get('mode_tag', 'solo')}（单机） · 难度：{difficulty_display(meta, band)}")
    L.append(f"- 路线标签：{meta.get('route_tag', '未打')} · 最终结局：**{outcome}**"
             + (f"（结算核实：{meta.get('outcome_verified')}）" if meta.get("outcome_verified") else ""))
    L.append(f"- 通过回合数：**{rounds_passed}**（结算页权威，非曲线最大回合）")
    L.append(f"- 生命：{initial_life} → {final_life} · 总扣血：{total_drop}")
    L.append(f"- 对齐粒度：**卡名级粗对齐**（SHOP-NAME {n_shop}/{n_total} 回合有真实购买推荐；"
             f"price/tier 用规则库兜底=临时值；阵容未感知→协同理由受限）")
    L.append(f"- degraded 回合（HUD-only，无商店→无购买推荐）：{n_degraded}/{n_total}"
             + (f" = {degraded_rns}" if degraded_rns else ""))
    if meta.get("user_note"):
        L.append(f"- 用户原话：{meta['user_note']}")
    if meta.get("route_tag") == "extreme":
        L.append("- 注：极端样本保留作数据；极端化玩法已按用户决策移出模型考虑（2026-11-18，暂时），"
                 "本局推荐只产正常玩法、不再出极端路线加权/非常规警示。")
    L.append("")

    L.append("## 逐回合对照总表\n")
    L.append("点击=计数（粗对齐，**不判跟随/偏离**）；结局=预览−M / 实际跨回合扣血（C3 双呈现，背离即信号）。\n")
    L.append("| 回合 | 推荐(top，按类型分组) | 战斗清单 | 点击 | 预览/实际扣血 | 评分 | 对照标记 |")
    L.append("|---|---|---|---|---|---|---|")
    for rec in recs:
        rn = rec["round"]
        clicks = rec.get("user_clicks_in_round")
        pv = preview.get(rn)
        ac = actual.get(rn)
        outcome_cell = f"−{pv if pv is not None else '?'} / {ac if ac is not None else '?'}"
        rt = rated.get(rn)
        score_cell = (f"{rt['score']}/10 {rt.get('followed', '')}" if rt else "（未评）")
        act_mark = "活跃" if (clicks or 0) >= 30 else "清淡"
        if ac is None:
            end_mark = "实际未知" + (f"(预览−{pv})" if pv else "")
        elif ac > 0:
            end_mark = "结局差(扣血)"
        else:
            end_mark = "结局好(零扣)"
        mark = f"点击{act_mark} · {end_mark}"
        if rec["input"] == "HUD-only":
            mark += " · degraded"
        opt_cell = fmt_options(rec["options"], (rec.get("plan") or {}).get("gate")).replace("|", "/")
        chk_cell = fmt_checks(rec["checks"], rec["hard_veto"]).replace("|", "/")
        L.append(f"| R{rn} | {opt_cell} | {chk_cell} | {clicks} | {outcome_cell} | {score_cell} | {mark} |")
    L.append("")

    L.append("## 局尾小结\n")
    red_rns = [r["round"] for r in recs if r["hard_veto"]]
    L.append(f"- 红线否决回合（hard_veto，只保命不做经济）：{red_rns or '无'}")
    L.append(f"- degraded 回合清单（数据不足，仅供参考，不作模型对错结论）：{degraded_rns or '无'}")
    L.append(f"- 点击量级：总 {sum(r.get('user_clicks_in_round') or 0 for r in recs)} 次"
             "（粗对齐：点击数≠动作语义，不能断言买没买推荐干员）")
    L.append("")

    if cov_temp:
        L.append("## 盟约临时层（covenants_temp，KB v1.3 仅乌萨斯）\n")
        L.append("> 消费约束：temp 仅乌萨斯（略高估，含战斗中永久增量）；其余名 banner>包络=永久增量或基线漏读"
                 "（perm_increment_or_baseline_miss，**非 temp**）；noStack 四名（调和/协防干员/独行/绝技）不显层数；"
                 "qc_rest_temp_nonzero=True=基线漏读警报。\n")
        for c in cov_temp:
            temp = c.get("covenants_temp") or {}
            flags = c.get("flags") or {}
            qc = c.get("qc_rest_temp_nonzero")
            line = f"- f{c['frame']}({c.get('phase')})：乌萨斯temp={temp or '{}'}"
            if flags:
                line += f" · flags={flags}"
            if qc:
                line += " · **QC警报:rest临时层非零=基线漏读**"
            L.append(line)
        L.append("")

    L.append("## 感知边界（诚实分级，影响你判读）\n")
    L.append("- **已感知**：回合/相位/生命/伤害预览/敌人总量/盟约永久层（HUD）+ 商店卡名/盟约标签/金币（OCR 增量1）。")
    L.append("- **未感知（降级）**：商店 price/tier（用规则库兜底，标临时值）；调度中心等级（升本建议降级）；"
             "阵容 field/bench（协同理由受限、核心饥饿警告不触发）；战前特训类型（对空检查全=未知）；点击→动作语义（不判跟随/偏离）。")
    L.append("- 这些缺口属 P1 增强 backlog，不阻塞 M1；细对齐（逐动作对照+followed 自动建议）等 P1 落地。")
    L.append("")
    return "\n".join(L), {
        "session": session, "outcome": outcome, "rounds_passed": rounds_passed,
        "total_drop": total_drop, "n_total": n_total, "n_shop": n_shop,
        "n_degraded": n_degraded, "red_rns": red_rns,
        "route_tag": meta.get("route_tag"), "user_note": meta.get("user_note"),
    }


def summary_report(metas):
    L = []
    L.append("# M1 三局回放对照 · 汇总\n")
    L.append("> 档1 v0 结案边界交付。三局单机旧样本，卡名级粗对齐。供你判推荐合理性 → 纠正写 ratings → 喂 calibrate。\n")
    L.append("## 三局结局对照\n")
    L.append("| 局 | 路线 | 结局 | 通过回合 | 总扣血 | 有推荐回合 | degraded | 红线回合 |")
    L.append("|---|---|---|---|---|---|---|---|")
    for m in metas:
        L.append(f"| {m['session']} | {m['route_tag']} | {m['outcome']} | {m['rounds_passed']} | "
                 f"{m['total_drop']} | {m['n_shop']}/{m['n_total']} | {m['n_degraded']} | "
                 f"{m['red_rns'] or '无'} |")
    L.append("")
    L.append("## 跨局 recurring 盲点\n")
    L.append("- **对空检查三局全=未知**：战前特训类型未感知（简报 OCR 未落地）→ 模型无法判对空缺口。"
             "这是感知缺口，不是模型判错；P1 战前简报 OCR 落地后消失。")
    L.append("- **协同理由偏薄**：阵容未感知→ bond_counts 空→ 多数推荐理由=「无显著协同，按战力补充」，"
             "叠层路线权重已在分数里体现但理由文本未显。P1 肖像/阵容感知落地后细化。")
    L.append("- **核心饥饿警告未触发**：需阵容感知到已激活核心才判池干；232000 炎路线「发牌员不给余」的饥饿"
             "目前只能靠你复盘指出，模型暂看不见。")
    L.append("")
    L.append("## 评分分布\n")
    L.append("- 暂无 ratings（你尚未评分）。复盘后逐回合 1–10 + 可选纠正写回，calibrate 离线拟合（≥20 样本才 --apply）。")
    L.append("")
    L.append("## 值得你复盘的推荐（引导，不替你下结论）\n")
    for m in metas:
        if m["outcome"] == "failed" and m.get("route_tag") == "extreme":
            red = f"，红线保命回合 {m['red_rns']}" if m["red_rns"] else ""
            L.append(f"- **{m['session']}**（极端路线失败，样本保留作数据）：极端化已按用户决策移出模型考虑，"
                     f"本局推荐已按正常玩法重算（总扣血 {m['total_drop']}{red}）。"
                     "回看扣血段——正常玩法推荐与保命红线是否贴合你当时的处境？值得你文字纠正。")
        elif m["outcome"] == "failed":
            L.append(f"- **{m['session']}**（失败）：{m.get('user_note') or ''} "
                     "失败原因（如核心饥饿）当前感知看不见，值得你文字纠正补盲点。")
        if m["outcome"] == "won":
            L.append(f"- **{m['session']}**（通关）：对照模型推荐与你实际操作（点击量级），"
                     "看叠层路线推荐是否贴合你的真实 build；零扣血回合的推荐可作为正向样本。")
    L.append("")
    L.append("## 边界声明\n")
    L.append("- 极端化玩法已按用户决策移出模型考虑（2026-11-18，暂时非永久）：模型只产正常玩法推荐，"
             "不再出极端路线加权/激活推动/非常规警示；极端样本（223918）保留作数据，KB 规则事实不动。")
    L.append("- 粗对齐：点击数≠动作语义，报告不给「跟随/偏离」判定；followed 由你复盘自评。")
    L.append("- price/tier=规则库临时值；阵容/特训/点击语义未感知。细对齐等 P1（backlog，不阻塞 M1）。")
    L.append("- 本报告非验收 harness；M1 验收=你读完判「读得对、推荐靠谱」并给纠正。")
    L.append("")
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("analysis_dirs", nargs="+")
    ap.add_argument("--bands", default="", help="comma-separated band keys aligned to dirs")
    ap.add_argument("--out", default="reports")
    args = ap.parse_args()
    bands = args.bands.split(",") if args.bands else []
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    metas = []
    for k, ad in enumerate(args.analysis_dirs):
        band = bands[k] if k < len(bands) else None
        text, meta = session_report(ad, band)
        fp = out / f"{meta['session']}.md"
        fp.write_text(text, encoding="utf-8")
        metas.append(meta)
        print(f"[report] {meta['session']}: {meta['n_shop']}/{meta['n_total']} shop rounds -> {fp}")
    sp = out / "M1-三局汇总.md"
    sp.write_text(summary_report(metas), encoding="utf-8")
    print(f"[report] summary -> {sp}")


if __name__ == "__main__":
    main()