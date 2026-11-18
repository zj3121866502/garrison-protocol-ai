"""Rest-phase decision assistant GUI (协作A lane, 形态A 试运行验收载体).

tkinter 8.6 stdlib, ZERO new dependencies. A small corner always-on-top window
that does NOT auto-focus and does not overlay/block the game (display only,
zero input injection). It reads data/feedback/latest.json (the watcher writes
it atomically: tmp -> rename) and shows the model's NORMAL-PLAY buy recommendations
+ combat checklist (red/yellow/green) + 保命 hard-veto + plan notes + round context.

Feedback loop (B3 frozen schema): user sets difficulty once (dropdown -> config.json,
the watcher reads it to assemble State), and rates each round 1-10 + optional text
correction + followed self-rating -> appended to ratings.jsonl (<=1 per round).
calibrate.py consumes recs.jsonl + ratings.jsonl offline (>=20 samples to --apply).

This is the user trial-run feedback vehicle, NOT an acceptance harness: the user
plays a manual solo game with passive recording on, watches the recommendations,
and judges them in situ. Extreme gameplay is out of the model (user 2026-11-18);
only normal play is recommended.

Launch: python ui/advisor_gui.py  (or ui/run_gui.bat). Paths are resolved relative
to this file, so cwd does not matter. Code/docs English, user-facing strings Chinese.
"""
import json
import tkinter as tk
from tkinter import ttk
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parent.parent
FEEDBACK = ROOT / "data" / "feedback"
LATEST = FEEDBACK / "latest.json"
CONFIG = FEEDBACK / "config.json"
RATINGS = FEEDBACK / "ratings.jsonl"
POLL_MS = 1500

# difficulty dropdown: kb band keys (kb._UPGRADE_KEY / bans.band_map), solo only
# (试运行 = 用户手动单机局; coop recommendations are gated off in v0).
DIFFICULTIES = [
    ("规程1–4（最低）", "solo_regulation_1_4"),
    ("规程5–8", "solo_regulation_5_8"),
    ("规程9–14", "solo_regulation_9_14"),
    ("规程15–20", "solo_regulation_15_20"),
    ("极速模拟", "solo_fast"),
]
LEVEL_TEXT = {"red": "红", "yellow": "黄", "green": "绿", "unknown": "未知"}
LEVEL_COLOR = {"red": "#cc3333", "yellow": "#cc9900", "green": "#33aa33", "unknown": "#888888"}


def read_json(path):
    """Tolerate missing / partial files (watcher may not have written yet)."""
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None


class AssistantGUI:
    def __init__(self, root):
        self.root = root
        self._current = None      # latest rec dict (or None)
        self._last_sig = None     # change signature to avoid needless re-render
        self._rated = set()       # rec_ids already rated (<=1 per round)
        root.title("卫戍协议 · 休整决策助手")
        root.attributes("-topmost", True)
        try:
            root.attributes("-toolwindow", True)  # keep out of taskbar / alt-tab
        except tk.TclError:
            pass
        root.geometry("460x700+40+40")
        root.minsize(420, 600)
        self._build()
        self._load_config()
        self._poll()

    # ---- layout ----
    def _build(self):
        pad = {"padx": 8, "pady": 3}
        top = ttk.Frame(self.root)
        top.pack(fill="x", **pad)
        ttk.Label(top, text="难度（开局设一次）：").pack(side="left")
        self.diff_box = ttk.Combobox(top, state="readonly", width=18,
                                     values=[l for l, _ in DIFFICULTIES])
        self.diff_box.pack(side="left")
        self.diff_box.bind("<<ComboboxSelected>>", self._on_diff)
        self.diff_status = tk.StringVar(value="未设置（必填）")
        self.diff_status_lbl = ttk.Label(top, textvariable=self.diff_status, foreground="#cc3333")
        self.diff_status_lbl.pack(side="left", padx=6)

        self.ctx_var = tk.StringVar(value="等待 latest.json …")
        ctx = ttk.LabelFrame(self.root, text="局面")
        ctx.pack(fill="x", **pad)
        ttk.Label(ctx, textvariable=self.ctx_var, justify="left", anchor="w").pack(fill="x", padx=6, pady=4)

        self.veto_var = tk.StringVar(value="")
        self.veto_lbl = tk.Label(self.root, textvariable=self.veto_var, bg="#cc3333",
                                 fg="white", font=("", 10, "bold"), anchor="w")
        self.veto_lbl.pack(fill="x", padx=8)

        body = ttk.LabelFrame(self.root, text="模型推荐（只产正常玩法）")
        body.pack(fill="both", expand=True, **pad)
        self.txt = tk.Text(body, height=16, wrap="word", state="disabled",
                           font=("Consolas", 10), bg="#1e1e1e", fg="#dddddd")
        self.txt.pack(fill="both", expand=True, padx=4, pady=4)
        self.txt.tag_configure("buy", foreground="#7fd0ff", font=("Consolas", 10, "bold"))
        self.txt.tag_configure("act", foreground="#ffd479")
        self.txt.tag_configure("reason", foreground="#aaaaaa")
        self.txt.tag_configure("head", foreground="#ffffff", font=("Consolas", 10, "bold"))
        self.txt.tag_configure("note", foreground="#9cdcfe")
        self.txt.tag_configure("dim", foreground="#777777")
        for lv, col in LEVEL_COLOR.items():
            self.txt.tag_configure(lv, foreground=col)

        rate = ttk.LabelFrame(self.root, text="本回合反馈（≤1 次/回合）")
        rate.pack(fill="x", **pad)
        self.round_lbl = ttk.Label(rate, text="本回合评分 R?")
        self.round_lbl.grid(row=0, column=0, columnspan=4, sticky="w", padx=6, pady=2)
        ttk.Label(rate, text="评分").grid(row=1, column=0, sticky="w", padx=6)
        self.score_var = tk.StringVar(value="7")
        self.score_box = ttk.Spinbox(rate, from_=1, to=10, width=4, textvariable=self.score_var)
        self.score_box.grid(row=1, column=1, sticky="w")
        self.followed_var = tk.BooleanVar(value=False)
        self.followed_chk = ttk.Checkbutton(rate, text="跟随了推荐", variable=self.followed_var)
        self.followed_chk.grid(row=1, column=2, columnspan=2, sticky="w", padx=6)
        ttk.Label(rate, text="纠正").grid(row=2, column=0, sticky="w", padx=6)
        self.corr_var = tk.StringVar()
        self.corr_entry = ttk.Entry(rate, textvariable=self.corr_var)
        self.corr_entry.grid(row=2, column=1, columnspan=3, sticky="we", padx=6, pady=2)
        self.rate_btn = ttk.Button(rate, text="提交评分", command=self._submit)
        self.rate_btn.grid(row=3, column=0, columnspan=2, sticky="w", padx=6, pady=3)
        self.rate_status = tk.StringVar(value="")
        ttk.Label(rate, textvariable=self.rate_status).grid(row=3, column=2, columnspan=2, sticky="w")
        rate.columnconfigure(3, weight=1)

        bottom = ttk.Frame(self.root)
        bottom.pack(fill="x", **pad)
        ttk.Button(bottom, text="手动刷新", command=self._poll_once).pack(side="left")
        self.status = tk.StringVar(value="启动中 …")
        ttk.Label(bottom, textvariable=self.status, foreground="#888888").pack(side="left", padx=8)
        self._set_rating_enabled(False)

    # ---- difficulty config ----
    def _load_config(self):
        cfg = read_json(CONFIG) or {}
        key = cfg.get("difficulty")
        for label, k in DIFFICULTIES:
            if k == key:
                self.diff_box.set(label)
                self.diff_status.set(f"已设 {key}")
                self.diff_status_lbl.configure(foreground="#33aa33")
                break

    def _on_diff(self, event=None):
        label = self.diff_box.get()
        key = next((k for l, k in DIFFICULTIES if l == label), None)
        if not key:
            return
        FEEDBACK.mkdir(parents=True, exist_ok=True)
        tmp = CONFIG.with_suffix(".tmp")
        tmp.write_text(json.dumps({"difficulty": key}, ensure_ascii=False), encoding="utf-8")
        tmp.replace(CONFIG)
        self.diff_status.set(f"已设 {key}（watcher 读取）")
        self.diff_status_lbl.configure(foreground="#33aa33")

    # ---- latest.json polling ----
    def _read_latest(self):
        return read_json(LATEST)

    def _poll_once(self):
        data = self._read_latest()
        if data is None:
            self.status.set("等待 latest.json（watcher 尚未写入？）")
            return
        ctx = data.get("state_ctx") or {}
        rec = data.get("rec")
        sig = ((rec or {}).get("rec_id"), ctx.get("updated_at"), ctx.get("frame"))
        if sig != self._last_sig:
            self._last_sig = sig
            self._render(data)
        self.status.set(f"轮询中 · 更新 {ctx.get('updated_at', '?')}")

    def _poll(self):
        self._poll_once()
        self.root.after(POLL_MS, self._poll)

    # ---- rendering ----
    def _render(self, data):
        rec = data.get("rec")
        ctx = data.get("state_ctx") or {}
        self._current = rec
        shop = ctx.get("shop_names") or []
        rnd = ctx.get("round") or (rec or {}).get("round") or "?"
        life = ctx.get("life")
        inc = ctx.get("life_incoming")
        funds = ctx.get("funds")
        self.ctx_var.set(
            f"回合 R{rnd} · {ctx.get('phase') or '?'} · 帧 f{ctx.get('frame', '?')}\n"
            f"生命 {'?' if life is None else life} · 预览扣血 {'未感知' if inc is None else inc}"
            f" · 金币 {'?' if funds is None else funds}\n"
            f"难度 {ctx.get('difficulty') or '未设'}\n"
            f"商店 {' / '.join(n or '?' for n in shop) if shop else '未感知'}\n"
            f"盟约永久层 {ctx.get('covenants_rest') or {}}"
        )
        self.txt.configure(state="normal")
        self.txt.delete("1.0", "end")
        if not rec:
            self.txt.insert("end", "（暂无推荐：等待回合/商店感知，或 coop 门控）\n", "dim")
            self.veto_var.set("")
            self.veto_lbl.configure(bg="#1e1e1e")
            self._set_rating_enabled(False)
            self.round_lbl.configure(text="本回合评分 R?")
        else:
            plan = rec.get("plan")
            if bool(ctx.get("stale")):
                self.txt.insert("end", "（上一休整屏建议 · 切屏/战斗中，界面变后重评）\n", "dim")
            if plan:
                self._render_plan(plan)
            else:
                self._render_options(rec.get("options") or [])
            checks = rec.get("checks") or []
            if checks:
                self.txt.insert("end", "\n战斗清单：\n", "head")
                for c in checks:
                    lv = c.get("level", "unknown")
                    self.txt.insert("end", f"  {c.get('id')}:{LEVEL_TEXT.get(lv, lv)} — {c.get('msg', '')}\n", lv)
            notes = (plan.get("notes") if plan else rec.get("plan_notes")) or []
            for n in notes:
                self.txt.insert("end", f"· {n}\n", "note")
            if rec.get("hard_veto"):
                self.veto_var.set("  红线否决：只保命，不做经济动作")
                self.veto_lbl.configure(bg="#cc3333")
            else:
                self.veto_var.set("")
                self.veto_lbl.configure(bg="#1e1e1e")
            self.round_lbl.configure(text=f"本回合评分 R{rec.get('round')}")
            if rec.get("rec_id") in self._rated:
                self._set_rating_enabled(False)
                self.rate_status.set("本回合已评")
            else:
                self._set_rating_enabled(True)
                self.rate_status.set("")
        self.txt.configure(state="disabled")
        self.txt.see("1.0")

    def _render_plan(self, plan):
        """Per-screen coherent operation plan (M1 trial-run refactor): ordered
        steps within budget + gate + refresh/upgrade decisions + freeze."""
        gate = plan.get("gate")
        if gate:
            gate_text = {"hard_veto": "红线否决：只保命，不做经济动作",
                         "funds_zero": "资金为 0，无购买力，不推荐购买",
                         "funds_unknown": "资金未感知，暂不推荐购买（无法核实买得起）"}.get(gate, gate)
            self.txt.insert("end", f"⊘ {gate_text}\n", "act")
        steps = plan.get("steps") or []
        if steps:
            self.txt.insert("end", "连贯操作计划（按顺序执行）：\n", "head")
            for idx, s in enumerate(steps, 1):
                op = s.get("op")
                reason = (s.get("reasons") or [""])[0]
                if op == "buy":
                    self.txt.insert("end", f"{idx}. 买 {s.get('name')} ×{s.get('count', 1)} — 花费 {s.get('cost')}\n", "buy")
                elif op == "upgrade":
                    self.txt.insert("end", f"{idx}. 升本 — 花费 {s.get('cost')}\n", "act")
                elif op == "refresh":
                    self.txt.insert("end", f"{idx}. 刷新 — 花费 {s.get('cost')}\n", "act")
                else:
                    self.txt.insert("end", f"{idx}. {op} — 花费 {s.get('cost')}\n", "act")
                if reason:
                    self.txt.insert("end", f"    {reason}\n", "reason")
            b = plan.get("budget") or {}
            f, sp, rem = b.get("funds"), b.get("spent"), b.get("remaining")
            self.txt.insert("end", f"预算：资金 {'?' if f is None else f} → 花费 {sp} → 剩 {'?' if rem is None else rem}\n", "note")
        elif not gate:
            self.txt.insert("end", "（本屏无值得买的卡：全低于阈值或买不起）\n", "dim")
        rf = plan.get("refresh")
        if rf and not rf.get("do") and rf.get("reason"):
            self.txt.insert("end", f"刷新：{rf['reason']}\n", "reason")
        up = plan.get("upgrade")
        if up and not up.get("do") and up.get("reason"):
            self.txt.insert("end", f"升本：{up['reason']}\n", "reason")
        fr = plan.get("freeze") or []
        if fr:
            self.txt.insert("end", f"冻结候选：{'/'.join(fr)}（高价值买不起，试探）\n", "act")

    def _render_options(self, opts):
        """Fallback for older recs without a coherent plan (merged ×N buys)."""
        if not opts:
            self.txt.insert("end", "（本回合无具体购买推荐：商店未感知或战斗相位）\n", "dim")
        for o in opts:
            kind = (o.get("action") or "").split(":")[0]
            reason = (o.get("reasons") or [""])[0]
            if kind == "buy":
                flags = "/".join(o.get("flags") or [])
                cnt = o.get("count", 1)
                nm = o.get("name") + (f" ×{cnt}" if cnt and cnt > 1 else "")
                self.txt.insert("end", f"买 {nm}  {o.get('score')}  [{flags}]\n", "buy")
                self.txt.insert("end", f"    {reason}\n", "reason")
            elif kind == "freeze":
                self.txt.insert("end", f"冻 {o['action'].split(':')[1]}（高价值买不起，试探）\n", "act")
            elif kind in ("upgrade", "refresh"):
                label = "升本" if kind == "upgrade" else "刷新"
                self.txt.insert("end", f"{label}  {o.get('score')}  — {reason}\n", "act")

    def _set_rating_enabled(self, on):
        state = "normal" if on else "disabled"
        self.score_box.configure(state=state)
        self.corr_entry.configure(state=state)
        self.rate_btn.configure(state=state)
        self.followed_chk.configure(state=state)

    # ---- rating submit ----
    def _submit(self):
        rec = self._current
        if not rec:
            return
        rid = rec.get("rec_id")
        if not rid or rid in self._rated:
            return
        try:
            score = max(1, min(10, int(self.score_var.get())))
        except (TypeError, ValueError):
            score = 7
        entry = {
            "rec_id": rid, "session": rec.get("session"), "round": rec.get("round"),
            "score": score, "followed": bool(self.followed_var.get()),
            "correction": self.corr_var.get().strip(),
            "risk_flag": bool(rec.get("hard_veto")),  # 保命红线回合单独分桶（学校准风险偏好）
            "t": datetime.now().isoformat(timespec="seconds"),
        }
        FEEDBACK.mkdir(parents=True, exist_ok=True)
        with open(RATINGS, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        self._rated.add(rid)
        self._set_rating_enabled(False)
        self.rate_status.set(f"已记录 R{rec.get('round')} {score}/10 ✓")
        self.corr_var.set("")


def main():
    FEEDBACK.mkdir(parents=True, exist_ok=True)
    root = tk.Tk()
    AssistantGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()