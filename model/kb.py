"""Knowledge-base loader for 档1 (rules_kb.json v1.2 + operators.json).

Mode-aware pools are mandatory: low difficulty excludes 奇迹/灵巧/投资人 etc.,
so extreme economy routes are only viable on 规程5+ (KB bans.mode_pools).
Operator bans follow CHANGELOG §37.211 core-priority judgement (C+,
provisional until in-game verified) -- NOT the stale repo rule string.
All C/D numbers are provisional; callers must surface 「临时值」 in reasons.
"""
import json
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"

# difficulty band keys (bans.band_map) -> economy.upgrade_prices keys
_UPGRADE_KEY = {
    "solo_regulation_1_4": "solo_regulation_1_20",
    "solo_regulation_5_8": "solo_regulation_1_20",
    "solo_regulation_9_14": "solo_regulation_1_20",
    "solo_regulation_15_20": "solo_regulation_1_20",
    "solo_fast": "solo_fast",
    "coop_standard": "coop_standard",
    "coop_peril": "coop_peril_despair_ultimate",
    "coop_despair_ultimate": "coop_peril_despair_ultimate",
}


class KB:
    def __init__(self, data_dir=DATA):
        self.rules = json.loads((Path(data_dir) / "rules_kb.json").read_text(encoding="utf-8"))
        ops = json.loads((Path(data_dir) / "operators.json").read_text(encoding="utf-8"))
        self.operators = ops["operators"]
        self.ops_meta = ops["_meta"]
        self.core_names = set(self.rules["covenants"]["core"])
        self.addon_names = set(self.rules["covenants"]["addon"])

    # ---- mode / difficulty ----
    def pool(self, difficulty):
        """Return mode_pools.low / .high dict for a difficulty band key."""
        mp = self.rules["bans"]["mode_pools"]
        if difficulty in mp["low"]["modes"]:
            return mp["low"]
        return mp["high"]  # regulation 5-20, coop peril/despair/ultimate

    def mode_excluded(self, difficulty):
        p = self.pool(difficulty)
        return set(p["core_excluded"]) | set(p["addon_excluded"])

    def addon_pool(self, difficulty):
        p = self.pool(difficulty)
        members = p["addon_pool_members"]
        if isinstance(members, list):
            return list(members)
        return sorted(self.addon_names)

    # ---- operator availability (core-priority, §37.211 provisional) ----
    def banned_bonds(self, difficulty, banned_addons=(), core_group=None):
        banned = set(banned_addons) | self.mode_excluded(difficulty or "solo_regulation_5_8")
        if core_group:  # solo: unchosen core group acts as grey
            banned |= self.core_names - set(core_group)
        return banned

    def operator_available(self, name, difficulty, banned_addons=(), core_group=None):
        op = self.operators.get(name)
        if op is None:
            return False
        bonds = op.get("bonds") or []
        if not bonds:
            return True
        banned = self.banned_bonds(difficulty, banned_addons, core_group)
        cores = [b for b in bonds if b in self.core_names]
        if cores:  # core-priority: addon brightness irrelevant
            return any(b not in banned for b in cores)
        addons = [b for b in bonds if b in self.addon_names]
        if addons:
            return any(b not in banned for b in addons)
        return True

    # ---- economy (C, provisional) ----
    def income(self, round_no):
        return min(3 + round_no, self.rules["economy"]["income_cap"])

    def upgrade_price(self, difficulty, center_level):
        table = self.rules["economy"]["upgrade_prices"][_UPGRADE_KEY[difficulty]]
        idx = center_level - 1
        if 0 <= idx < len(table):
            return table[idx]
        return None  # max level or unknown

    def slots(self, difficulty, center_level):
        key = ("coop_standard" if difficulty == "coop_standard"
               else "regulation_and_coop_hard")
        table = self.rules["shop"]["slots_chess_by_level"][key]
        idx = min(max(center_level - 1, 0), len(table) - 1)
        return table[idx]

    def price(self, name):
        op = self.operators.get(name)
        return op["price"] if op else self.rules["economy"]["chess_price"].get(str(op and op["tier"]))

    # ---- shop odds (copyWeighted, D-assumed -> provisional) ----
    def pool_weight(self, difficulty, shop_level, banned_addons=(), core_group=None,
                    pool_remaining=None):
        """Per-tier total remaining copies of available operators <= shop_level.
        pool_remaining: optional {name: copies_left} card-counting override."""
        copies = self.rules["shop"]["pool_copies"]
        mult = self.rules["shop"]["coop_pool_multiplier"] if (difficulty or "").startswith("coop") else 1  # None guard
        weight = {}
        for name, op in self.operators.items():
            tier = op["tier"]
            if tier > shop_level:
                continue
            if not self.operator_available(name, difficulty, banned_addons, core_group):
                continue
            left = (pool_remaining or {}).get(name, copies[str(tier)] * mult)
            weight[tier] = weight.get(tier, 0) + left
        return weight

    def draw_prob(self, name, difficulty, shop_level, banned_addons=(), core_group=None,
                  pool_remaining=None):
        """P(a given empty slot shows this operator). Provisional D model."""
        op = self.operators.get(name)
        if op is None or not self.operator_available(name, difficulty, banned_addons, core_group):
            return 0.0
        weight = self.pool_weight(difficulty, shop_level, banned_addons, core_group, pool_remaining)
        total = sum(weight.values())
        if total <= 0:
            return 0.0
        copies = self.rules["shop"]["pool_copies"]
        mult = self.rules["shop"]["coop_pool_multiplier"] if (difficulty or "").startswith("coop") else 1  # None guard
        left = (pool_remaining or {}).get(name, copies[str(op["tier"])] * mult)
        return left / total

    # ---- covenant derived ----
    def mira_free_prob(self, layers, difficulty):
        """Free-refresh probability; None when 奇迹 not in this mode's pool."""
        if "奇迹" in self.mode_excluded(difficulty or ""):
            return None
        return min(18 + 0.25 * layers, 100) / 100.0

    @staticmethod
    def power(stats):
        return stats["atk"] * 5 + stats["maxHp"] + stats["def"] * 3 + stats["res"] * 3

    def lp(self, strategy):
        return self.rules["strategies_lp"].get(strategy)

    def provisional(self, section):
        return bool(self.rules.get(section, {}).get("provisional"))