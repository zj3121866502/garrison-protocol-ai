"""Structured game state for the 档1 advisor (plan §3).

Null / empty = not perceived yet -> scoring degrades, never guesses.
Offline replay builds State from curves.jsonl rows; realtime will build it
from HUD + shop OCR (P1). User-facing strings are Chinese; code/docs English.
"""
from dataclasses import dataclass, field, asdict
import hashlib
import json


@dataclass
class ShopSlot:
    name: str | None = None      # operator name (OCR); None = unreadable
    tier: int | None = None
    price: int | None = None
    frozen: bool = False
    sold: bool = False


@dataclass
class Unit:
    name: str
    tier: int | None = None
    level: int | None = None
    golden: bool = False         # 3-merge promoted form
    equips: list = field(default_factory=list)
    pos: str = "bench"           # field | bench


@dataclass
class State:
    session: str = ""
    t: float = 0.0
    round: int | None = None
    phase: str = "other"         # rest | combat | other
    mode_tag: str = "solo"       # solo | coop
    difficulty: str | None = None  # kb band key, e.g. solo_regulation_1_4 / coop_peril
    life: int | None = None
    incoming: int | None = None  # combat-end damage preview (-M)
    enemy_total: int | None = None
    funds: int | None = None
    center_level: int | None = None
    upgrade_price: int | None = None
    covenants_rest: dict = field(default_factory=dict)  # permanent layers (rest readings)
    covenants_temp: dict = field(default_factory=dict)  # banner temporary layers
    shop: list = field(default_factory=list)            # list[ShopSlot]
    bench: list = field(default_factory=list)           # list[Unit]
    field_units: list = field(default_factory=list)     # list[Unit]
    strategy: str | None = None
    special_types: list = field(default_factory=list)   # 本局特训 (briefing OCR)
    banned_addons: list = field(default_factory=list)   # greyed addon covenants
    core_group: list | None = None                      # chosen core group (solo)
    pool_remaining: dict | None = None                  # card-counting inference, optional

    def missing(self, *names):
        """Critical fields not perceived -> caller degrades related scoring."""
        return [n for n in names if getattr(self, n) in (None, [], {})]

    def state_hash(self):
        key = {k: getattr(self, k) for k in
               ("round", "phase", "life", "funds", "center_level", "covenants_rest",
                "banned_addons", "core_group", "difficulty", "mode_tag")}
        key["shop"] = [asdict(s) for s in self.shop]
        key["field"] = sorted(u.name for u in self.field_units)
        key["bench"] = sorted(u.name for u in self.bench)
        return hashlib.sha1(json.dumps(key, sort_keys=True, ensure_ascii=False)
                            .encode("utf-8")).hexdigest()[:12]

    @classmethod
    def from_curves_row(cls, row, session="", mode_tag="solo", difficulty=None):
        """Partial state from one curves.jsonl row (HUD-only, no shop/roster)."""
        return cls(session=session, t=row.get("t", 0.0), round=row.get("round"),
                   phase=row.get("phase", "other"), mode_tag=mode_tag,
                   difficulty=difficulty, life=row.get("life"),
                   incoming=row.get("life_incoming"), enemy_total=row.get("enemy_total"),
                   covenants_rest=dict(row.get("covenants") or {}))