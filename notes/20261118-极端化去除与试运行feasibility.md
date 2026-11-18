# 极端化去除（调整a）+ 试运行 feasibility（调整b）（协作A lane，2026-11-18）

来源：主策划转用户直发两条调整（最高优先，已登记交接§0红线+§4⑳）。
- (a) 用户原话「暂时先不考虑极端化玩法的问题，把这一条从模型考虑里去除。这是我的锅，我一开始想太多了。推荐只推荐正常玩法。」→ 覆盖原红线「极端路线可以学+标注非常规」。**暂时非永久删**。归我 model/ 落实。
- (b) 用户原话「其他的我光看文字不太能准确判断，建议在模型试运行阶段反馈。」→ M1 验收载体改为试运行（用户手动局+模型实时正常玩法推荐+在场当场反馈）。**先协调不先建**，主策划拿我 feasibility 给用户方案拍板再分工。

## 1. 调整(a) 落实清单（全我 lane，审计接力：我改→主策划复核读回→我确认）

设计原则：**去除策略级极端路线放大与警示，保留状态正确的游戏机制与正常叠层跟随**。奇迹/投资人=极端经济路线标记盟约（KB implication 明写「极端经济路线仅规程5+可行」指这两名+灵巧；灵巧非经济路线，按正常 bond 保留）。

- **shop_score.py**：
  - 新增 `ECONOMY_BONDS=("奇迹","投资人")`；删 `ECONOMY_ROUTE_LAYERS=80` 常量。
  - `route_weights`：奇迹/投资人 → 平权 1.0（**去层数放大** base=1+min(L,100)/50 与激活×1.5/差1×1.3 推动）。其余盟约（莱塔尼亚/乌萨斯/炎/维多利亚/灵巧/远见…）正常叠层跟随**不动**。
  - `score_shop` covenant 循环：奇迹/投资人 → cov+=1.0 平权跳过（不出「差1激活/已激活继续叠层」理由、不出饥饿）；**删 C2「非常规路线，可能会失败」flag+reason 整块**。
- **planner.py**：刷新 EV **去掉奇迹免费刷新率项**（原 `free=mira_free_prob(...)`），只按目标卡命中率估值 `ev=(1-(1-hit)^slots)*3.0-1.0`；reason 不再含「奇迹免费率」。`kb.mira_free_prob` 函数保留作规则知识，不再消费。
- **report.py**：删 ⚠非常规 flag 标记 / 局尾「非常规路线警示回合」行 / 汇总表「非常规回合」列 / 223918 极端警示引导文案；新增极端化移出标注（extreme route_tag 局头注 + 汇总边界声明）；223918 引导改为「极端样本保留作数据+正常玩法重算+保命红线复盘」；232000 引导删「未触发非常规警示」子句。
- **未改（核实无极端逻辑）**：replay.py（grep 无极端/非常规；route_tag 仅 meta 数据标签，report 显示用，非行为驱动）/ advisor.py / calibrate.py / kb.py / rules_kb.json（**KB 游戏事实不动**：盟约机制/mode_pools/325阈值待核项均保留——去的是模型偏好不是游戏知识）。

## 2. 调整(a) 影响面（重跑三局 replay+report 读回核实，非验收清单）

- 覆盖不变：223918=9/12、232000=7/10、224824=9/14 SHOP-NAME；degraded 清单不变。
- **223918（极端样本，推荐按正常玩法重算）**：
  - R10 吉星 8.097[⚠非常规]（奇迹116层）→ **6.097[临时]（无显著协同，按战力补充）**，−2.0=去掉的奇迹放大；斥罪9.084 仍榜首（战力）。
  - R11 吉星 7.597[⚠非常规]榜首 → **吉星跌出 top3**，改 海沫6.972/温蒂6.63/寒檀6.401（正常战力卡）；**hard_veto[11] 保留**（low_life 红→保命，正常玩法不动）。
  - 局头加极端化移出注；局尾非常规行消失、红线[11]保留；R12 末轮「实际未知(预览−10)」保留。
- **224824（正常通关）**：R7 **黑键7.934 仍榜首**=用户真实核心（莱塔尼亚正常 bond 放大保留）→ 正常叠层跟随不受影响。全文无奇迹/非常规。
- **232000（正常失败）**：推荐稳定（云迹/斯卡蒂等不变，灵巧按正常 bond）；无奇迹/非常规文本。
- **planner 改动为潜伏态**：三局 center_level 全未感知→刷新/升本本就降级，mira 项去除在这三局报告**无可观察差异**；只在 center_level 被感知时（试运行/P1）生效。诚实标注。
- py_compile 三文件 OK；model/ 残留「非常规」字样仅在注释/标注文本，无活动逻辑；ECONOMY_ROUTE_LAYERS 全删；mira_free_prob 仅 kb.py 定义无消费方。

## 3. 调整(b) 试运行 feasibility（只评估，未建任何代码）

**问1：model 能否接受单帧/单回合 state 实时输入→即时推荐？**
- **就绪**。`advisor.advise(state, kb, weights=None, top_k=3, log_path=None)` 是纯单步函数：吃一个 State→返回 rec bundle，无批量依赖。replay 只是离线批驱动（从 curves 行造 State）。KB() 启动加载一次即可常驻。
- 延迟：纯 Python 打分（~5 商店槽×算子 KB），毫秒级；KB json 加载一次性。实时单步在 model 层**零缺口**。
- 唯一集成点=**State 组装**（感知侧，主策划 lane）：把最新 HUD parse + shop OCR 填进 State（`State.from_curves_row` 已有 curves→State 路径可复用/参照）。model 作为库被调用：`from model.advisor import advise; from model.state import State; from model.kb import KB`。
- advise 可实时 append recs.jsonl（log_path 默认 data/feedback/recs.jsonl）；ratings 由 GUI 写。反馈环 schema 已冻结可直接用。

**问2：advisor_gui.py 雏形/最简休整期决策窗口工作量风险？**
- **无雏形**：ui/ 目录尚不存在（原计划「等 P1 后做」）。
- GUI 工具：**venv 自带 tkinter 8.6**（stdlib 零新依赖）；PyQt5/PySide6 未装。最简窗口用 tkinter 即可，不引新依赖。
- 最简可用形态（休整期决策助手窗口）：角落小型 always-on-top 窗口（不遮游戏、零注入纯显示）→ 读最新推荐（latest.json 或 recs.jsonl tail）→ 显示 top 购买推荐+战斗清单红黄绿+保命红线+理由；~1-2s 轮询刷新或手动刷新按钮；每回合 1–10 评分按钮+可选纠正文本+followed 自评 → append ratings.jsonl（B3 评分UX：实时≤1/回合）。
- 工作量估：GUI 本体 ~200–300 行 tkinter，我 lane，约半天量级（数小时 agent 工）。
- 风险（低-中）：①窗口抢游戏焦点→缓解：小型 topmost、不自动聚焦、纯显示；②感知节奏/延迟→主策划 lane；③休整相位判定准度→phase 来自 HUD。

**问3：倾向哪种试运行形态最省？**
- **倾向 A 休整期决策助手**（推荐）：决策主战场、休整~70s 决策窗对 OCR+打分延迟宽裕（帧~1fps+OCR~1-2s/帧+advise 毫秒→休整开始~3-5s 内出推荐）、实时压力最小、最贴合用户「试运行阶段反馈」。
- B 全程实时 overlay（战斗+休整）：复杂度高、战斗相位无商店只清单、收益低，不推荐现在做。
- C 交互式回放复盘（局后逐回合点选）：更省但**事后**——用户明确要「试运行阶段」当场反馈，C 单独不满足；可作日后补充非现在。

**关键架构建议（供主策划方案，省基础设施）：复用被动录制做实时帧源（tail 模式），不新建采集/零注入。**
- 用户照常双击 bat 被动录制（recorder 持续写帧~1fps）→ 一个 watcher 对最新休整帧跑 parse_hud+ocr_shop（**现有离线 OCR 算法不动，只是按最新帧按需调用**，非新算法）→ 组装 State → 调 model.advise → 写 latest.json+recs.jsonl → GUI 读显。
- 守住红线：录制只用户启动、大号被动零注入、bot 永不联机。试运行=用户手动单机局+被动录制+助手只读显示。
- 分工契约：**主策划 lane**=实时感知 tail（帧 watcher+单帧 parse_hud/ocr_shop 编排+State 组装+调 advise+写 latest.json）；**我 lane**=model 单步（已就绪）+ advisor_gui.py（显示+反馈采集）。接口=State→advise→latest.json/recs.jsonl→GUI。
- 最大未知=主策划 lane 的实时感知编排（ocr_shop 现每次覆盖 shop.json 的批处理需改单帧按需读；scene gate clean 判定已有）。model+GUI 侧风险低。

### 3.1 difficulty=None 降级路径取证（主策划问，probe 复现非纸面）

- **就绪部分**：combat_check 不读 difficulty；kb.operator_available/banned_bonds 有 `difficulty or "solo_regulation_5_8"` 默认兜底（None→高难池）；kb.pool(None)→high（None 不在 low.modes）。**HUD-only（shop 空+center_level=None）+difficulty=None → advise 正常降级不崩**（probe options=0 OK）。
- **真实崩溃缺口**：`kb.pool_weight` L106 `mult = ... if difficulty.startswith("coop") else 1` 对 None 抛 `AttributeError: 'NoneType' object has no attribute 'startswith'`。经 draw_prob 被 score_shop（每个可用商店槽必调 L155）+ planner.refresh 调用 → **SHOP-NAME（有商店）+difficulty=None 必崩**（probe 复现：HUD-only OK / SHOP+None AttributeError / SHOP+band OK / pool_weight(None,1) 直崩）。这正是试运行休整期决策窗场景（有商店）。
- **次要缺口**：planner upgrade 分支 `if center_level is not None and state.difficulty:` 对 None 静默跳过（center_level 感知时也无降级 note），非崩溃。
- **最小修复（我 lane，1-2 行）**：pool_weight L106 改 `(difficulty or "").startswith("coop")`（或 None→默认 band）；顺带 planner upgrade None 补降级 note。
- **实务影响（给主策划方案选项准确依据）**：GUI 让用户设 difficulty（下拉 band key）→ difficulty 永不为 None → **现码零改动可用**；选 null 降级 → 需先修这 1 行守卫。
- 按「先不建码」纪律本轮未改；建议作 (b) 开工第一步（用户拍板后），或主策划授权现在预修（纯 robustness 非新功能）。

## 4. 边界与待办

- (a) 已落实+重生成报告读回核实，等主策划复核读回→我确认闭环。**不出验收清单（用户自测）**。
- (b) feasibility 阶段未建码；**形态A 已拍板+主策划绿光分工后已落地，见 §5**（本节 §3/§3.1 为当时评估记录，状态以 §5 为准）。阶段边界纪律仍生效：试运行是 M1 验收载体，建成→用户验收即止，不续 backlog。
- 报告 M1 验收措辞（「读完判读得对推荐靠谱」）待 (b) 形态定后可能需跟进微调（验收载体改试运行）；本轮只动极端化相关，未 preempt 改验收框架。
- 223918 极端样本保留作数据（局真实发生）；模型不从它学极端推荐、不再出极端警示。KB 325阈值待核项保留（游戏事实，极端标注用途已暂停）。

## 5. 形态A 落地（主策划绿光分工后，我 lane 已建，2026-11-18）

形态拍板闭环：用户两侧 AskUserQuestion 均跳过→按「跳过=推荐默认」=**A 休整期决策助手**（主策划/我同倾向）。主策划 delegated 绿光+接口契约，并行建：他=实时感知 watcher，我=model 单步（已就绪）+ advisor_gui.py。

### 5.1 difficulty=None 守卫已修（§3.1 缺口闭合，我 lane）
- `kb.py` L106（pool_weight）+ L129（draw_prob）：`difficulty.startswith("coop")` → `(difficulty or "").startswith("coop")`（allow_multiple 两处同改）。L136 mira_free_prob `mode_excluded(difficulty or "")` 亦守卫（该函数已不被 planner 消费，纯 robustness）。
- `planner.py` L43-44：upgrade 分支补 `elif state.difficulty is None: notes.append("难度未设置，升本建议降级（GUI 设难度）")`。
- 效果：SHOP-NAME+difficulty=None 不再崩，降级到高难池+降级 note；GUI 必选下拉为主路径（difficulty 永不为 None），守卫为启动早期/未设 config 的兜底。py_compile kb/planner/report/shop_score/advisor_gui 全 OK。

### 5.2 advisor_gui.py 已建（ui/，tkinter 8.6 零新依赖，~288 行）
- 角落小型 always-on-top + `-toolwindow`（不进任务栏/alt-tab，try/except 容错）；460x700，minsize 420x600；**纯显示零注入**，不自动聚焦、不遮游戏决策。
- 读 `data/feedback/latest.json`（watcher 原子写 tmp→rename），~1.5s 轮询 + 手动刷新按钮；签名 `(rec_id, ctx.updated_at, ctx.frame)` 变化才重渲染（省闪烁）。read_json 容忍缺失/半截/JSON 错→None。
- 显示：局面 ctx（回合/相位/帧/生命/预览扣血/金币/难度/商店5槽/盟约永久层）+ top 购买推荐（名/分/flags/理由）+ 冻/升本/刷新 + 战斗清单红黄绿未知着色 + plan_notes + **hard_veto 红条「红线否决：只保命，不做经济动作」**。rec=null→「暂无推荐」+禁用评分（coop/round=None 门控诚实呈现）。
- 反馈采集（B3 冻结 schema）：难度下拉（5 solo band key）→原子写 `config.json{difficulty}`（watcher 读它组装 State）；每回合评分 Spinbox 1–10（默认7）+ followed 自评 Checkbutton + 纠正 Entry → append `ratings.jsonl`，`risk_flag=bool(hard_veto)`（保命红线回合单独分桶学校准风险偏好，calibrate 已支持）；`_rated` 集按 rec_id 去重≤1/回合，已评禁用。
- 路径全相对 `__file__`（cwd 无关）；不 import model（解耦，只读 json）→GUI 可独立跑。界面中文，存盘值/键英文。
- 启动：`python ui/advisor_gui.py` 或 **`ui/run_gui.bat`**（纯 ASCII+CRLF 已字节核实：894 bytes/29 CRLF/0 lone LF/0 non-ascii；用 `%~dp0advisor_gui.py` 避中文字面量，venv python.exe 控制台可见英文状态+错误不闪退，pause 收尾）。

### 5.3 接口契约（与主策划一致，GUI 消费侧确认）
- `latest.json` = `{rec: <advise 返回全 bundle 或 null>, state_ctx: {funds, life, life_incoming, difficulty, shop_names:[5槽], covenants_rest, frame, round, phase, updated_at}}`，路径 `data/feedback/latest.json`，watcher 原子写。
- **rec=null 约定**：latest.json 恒有 state_ctx+updated_at；rec 可为 null（coop/round=None 门控或商店未感知）→GUI 显示局面+「暂无推荐」+禁用评分，不崩。
- GUI 写 `config.json{difficulty}`（band key）+ `ratings.jsonl`（rec_id/session/round/score/followed/correction/risk_flag/t）。calibrate 离线消费 recs.jsonl+ratings.jsonl（≥20 才 --apply）。
- 联调：先用录好的 224824 走 replay 式（watcher 顺序喂录制帧→latest.json→GUI 读），再用户实时局。等主策划 watcher 建成 relay。

### 5.4 边界
- 我 lane 已建+py_compile 绿；**未自建 smoke/验收 harness**（用户自测纪律），未启动 GUI 窗口（不扰用户机）。行为正确性以用户试运行实测为准。
- 不碰主策划 lane（watcher/感知/State 组装/交接.md）。建成→用户试运行验收即止（§0.1），不续 backlog（P1 增强/B2 等挂起）。

### 5.5 接口联调核对（主策划 watcher 落地后，2026-11-18）

主策划 analysis/live_advisor.py watcher 落地（tail 被动录制最新帧→ocr_frame+parse_row+read_shop_frame→State.from_curves_row+复用我 replay._apply_shop→KB()+advise→原子写 latest.json；round 携带+盟约包络+去抖键(round,shop_names,funds)+config.difficulty 读取+OCR 常驻+容错；--once replay 式联调 log recs_once.jsonl 与真实 recs.jsonl 分离）。我核对接口：

- **阻塞性路径分歧（他 lane，已报告+确切改法，我不改他文件）**：watcher `feedback = data/"feedback"`（L198，data=E:/garrison-ai/data）→ **E:/garrison-ai/data/feedback**；我 GUI（L28-32）+ advisor.FEEDBACK_DIR（advisor.py L16）+ calibrate ROOT（calibrate.py L20/L72-73）三者均 __file__-相对项目 = **D:/Qroot/卫戍协议AI/data/feedback**。磁盘核实：E: 有他 latest.json+recs_once.jsonl，D:/data/feedback 不存在。后果：GUI 读 D: 看不到 E: latest.json（卡「等待」）/ config.json GUI 写 D: 他读 E: 难度传不到 / recs.jsonl 他写 E: calibrate 读 D: join 失败。**建议 canonical=项目 D:**（advisor/calibrate __file__-相对可移植锚点已冻结，GUI 已对齐，4 组件 3 锚 D: 只 watcher 锚 E:；raw 大帧留 E:，feedback 小 json 随 model 放 D:）。**确切改法（他 lane 1 行）：live_advisor.py L198 `feedback = data / "feedback"` → `feedback = ROOT / "data" / "feedback"`**（ROOT 他 L28 已定义=项目根；L197 raw 不动；下游 recs_path L91/load_difficulty L62/latest.json L145 自动跟随）。备选 GUI+calibrate+advisor 全改 E: 不推荐（我 lane 3 文件 churn+硬编机器专属 E: 进 model 破坏可移植性）。
- **latest.json schema GUI 可消费=确认**（读他 E: 样本）：rec 全量+state_ctx 吻合，buy:折桠8.45/忍冬6.811/风丸6.242 渲染正常（flags[临时值,试探]/理由），checks low_life绿+anti_air unknown，plan_notes 2 条，hard_veto=false，「折」→折桠 tags 归一化✓装备卡→null✓。**样本 state_ctx 缺 round 键系旧版生成**（样本 mtime15:41 < 代码15:49），当前代码 L141 已写 round=eff_round → 当前 watcher 输出含 round。
- **我 GUI  robustness 小修（我 lane）**：ctx_var round 兜底（ctx.round→rec.round→'?'）+ life/funds None→'?'、life_incoming None→'未感知'（不显示字面 None）；py_compile 绿。
- **_apply_shop 只读复用确认**：他 L119 `_apply_shop(state, shop_rec, self.kb)` 与我 replay.py L80 签名匹配，未改我文件。
- **难度键名清单已回他**（5 solo band key，GUI 下拉→config.json{difficulty}，他 load_difficulty 读传 State）；difficulty=None 守卫已修与他实测吻合，mode pool 过滤偏（kb.mode_excluded("")）→ GUI 必填正确 band key 主路径。
- **状态**：报告已发主策划（supervise），**等他改 L198 路径→relay 联调**（--once 喂 224824→latest.json D:→GUI 读显+config/ratings 写 D:）。路径对齐前联调卡「等待 latest.json」=先决条件。他修完我复核（审计接力）。不续 backlog，建成→用户试运行验收即止§0.1。

### 5.6 难度键名权威核对 + 交叉旧信降噪（2026-11-18）

主策划又发一信「(a)结案收讫+difficulty 守卫核实已修+索取难度 band key 清单（所有键含 coop+中文名）」。**系交叉旧信**（写于 07:43:48 他处理我更早 difficulty 取证信那轮，早于他处理我 GUI 建成三确认信②〔已含 5 solo 键+coop 门控说明〕+我路径报告④〔亦含键名〕）→所问均已覆，按降噪协议**零回执不重复发**（防乒乓）。他当前 running turn 正在处理我②（含键名清单），queued(1)=我路径报告。

**借机权威核对我 GUI 难度键 vs kb（我 lane，确认无 bug）**：
- kb.py `_UPGRADE_KEY`（L15-24）全 8 键：solo_regulation_1_4/5_8/9_14/15_20（均→upgrade_prices.solo_regulation_1_20）、solo_fast（→solo_fast）、coop_standard（→coop_standard）、coop_peril/coop_despair_ultimate（→coop_peril_despair_ultimate）。
- rules_kb.json `bans.band_map`（L79-80）7 键：solo_regulation_1_4=FUNNY/5_8=NORMAL/9_14=HARD/15_20=ABYSS；coop_standard=FUNNY/coop_peril=NORMAL·HARD/coop_despair_ultimate=HARD·ABYSS。**solo_fast 不在 band_map 但在 _UPGRADE_KEY+mode_pools.low.modes**（valid 键，极速）。
- `mode_pools.low.modes`（L84）=["solo_regulation_1_4","coop_standard","solo_fast"]→低难池（排除核心阿戈尔/卡西米尔+附加灵巧/奇迹/投资人/突袭/独行/绝技）；其余→high（26 盟约全量）。kb.pool(difficulty)：in low.modes→low else high。
- **我 GUI DIFFICULTIES 5 solo 键逐一吻合 kb**（solo_regulation_1_4→low、5_8/9_14/15_20→high、solo_fast→low），中文名「规程1–4（最低）/规程5–8/规程9–14/规程15–20/极速模拟」准确。**GUI 下拉 solo-only 正确**（试运行=v0 solo 门控，coop advise→None，coop 键不入下拉）。
- 主策划举例「coop_绝境」非真键（权威=coop_despair_ultimate）；coop 三键真名=coop_standard/coop_peril/coop_despair_ultimate（备查，试运行不用，未发他免噪）。
- 他 correctness 注（difficulty=None→banned_bonds L57 默认 solo_regulation_5_8 高难池→低难局误过滤）=同意，我 GUI 已「未设置（必填）」红标+ctx「难度 未设」双提示，必填为主路径，守卫仅防崩兜底。无需再加冗余警示（守边界不精修）。
- **结论**：GUI 难度键无 bug，键名清单已在②覆盖他索取，交叉旧信零回执。仍等他改 L198 路径→relay 联调。

### 5.7 路径修复复核 PASS + 联调绿光（主策划联调就绪信号后，2026-11-18）

主策划发「联调就绪信号」（watcher 适配嵌套契约+结构核验 PASS+start_trial.bat 建成，索我确认 (a) 渲染 (b) 难度键）。**我按实际磁盘+代码核实（非信文本），审计接力闭环**：

- **路径修复复核 PASS**：他 live_advisor.py **L204 已改 `feedback = ROOT / "data" / "feedback"`**（带注释 credit「A review 2026-11-18」，L199 raw 留 E:）=我 §5.5 报的确切改法。磁盘核实 **D:/Qroot/卫戍协议AI/data/feedback/latest.json 已存在**（309B，mtime16:00）。程序核实 `GUI FEEDBACK == watcher feedback == D:\Qroot\卫戍协议AI\data\feedback`（co-located=True）。四件套 latest/config/recs/ratings 全 co-locate D:，calibrate join 通。**§5.5 阻塞解除，我 GUI 零改动消费**。（我报→他修→我核 PASS，闭环。）
- **(a) GUI 渲染两分支确认**：rec=null 分支用当前 D: latest.json（rec:null+state_ctx frame457/round3/life26/funds=null/shop_names=[]/covenants{不屈:4,精准:4}）→局面+「暂无推荐」+禁评分+无红条✓；has-rec 分支用他 recs_once.jsonl f457 r5 bundle（buy:折桠8.45/忍冬6.811/风丸6.242+checks low_life绿/anti_air未知+plan_notes2+hard_veto false）→买名/分/flags/理由+清单着色+notes+R5 评分启用✓。消费口径 rec=data.get('rec')/state_ctx含round/sig=(rec_id,updated_at,frame)/if not rec→暂无推荐 逐字段匹配。
- **(b) 难度 5 solo 键+中文名就位**（§5.6 已核 vs kb 吻合），写 config.json{difficulty} 他 load_difficulty 读传 State 键名一致。
- **start_trial.bat 复核 PASS**（他 lane，我读核）：项目根，ASCII+CRLF 字节核 1766B/47CRLF/0non-ascii（与他 47/47 一致）；PY=E:venv+exist 检查+ROOT=%~dp0+WATCHER/GUI 路径✓；`start /min` 后台 watcher+前台 GUI✓；提醒先开录制✓零注入/bot 永不联机/手动单机✓pause✓。
- **诚实注（非阻塞，他信文本 stale）**：他信①写路径 E:、②称当前样本 f2185 round14，但实际代码 L204=D:、当前 D: latest.json=f457 round3 life26 rec=null（非 f2185）。实现正确，我按磁盘+代码核非信文本；已建议他交接/docs 路径/样本引用顺手更新。E: 旧 latest.json+recs_once.jsonl（15:50）=修路径前遗留，不干扰（GUI 读 D:），清/留他 lane 自定（不push删）。
- **绿光已发主策划**（supervise）：GUI 就绪+路径对齐+结构联调 PASS→他 relay 用户开实时单机局试运行验收。**我不自启 GUI 窗口（用户自测纪律）**。建成→用户验收即止§0.1 不续 backlog。用户试运行报 GUI 显示/反馈问题我随时修（我 lane）。
- **M1 验收载体就绪**：用户双击 start_trial.bat（先开录制）→watcher tail 最新休整帧→OCR→State→advise→latest.json(D:)→GUI 显示正常玩法推荐+战斗清单+保命红线→用户当场判+难度下拉+每回合评分→ratings.jsonl(D:)→calibrate 离线。**等用户实时局试运行验收=档1 v0 结案边界**。

### 5.8 路径修复正式复核 PASS（主策划审计接力复核请求，2026-11-18）

主策划发正式「路径分歧已修请复核」信（我报→他修→我复核闭环）。他独立 grep 核实四组件锚 D: 唯他写 E:→改 L208（=我推荐一行）→显式 --session 224824 solo --once 重跑→清 E: 孤儿→加 coop WARNING 诊断。**我按实际磁盘+代码程序复核（非信文本）**：

- **(a) co-locate 程序核实 ALL_CO_LOCATED_D=True**：GUI/advisor/calibrate/watcher 四锚全等 `D:\Qroot\卫戍协议AI\data\feedback`（watcher L208 `feedback=ROOT/"data"/"feedback"`，raw L203 留 E:）+ report.py 项目 data/feedback ratings 锚 present=True。磁盘 D: feedback={latest.json 1998B, recs_once.jsonl 3768B}（mtime16:02），**E: feedback=[]（孤儿已清）**。四件套全 D: calibrate join 通。**PASS**。
- **(b) GUI 有 rec 渲染分支核 OK**（读实际 D: latest.json）：f457/round5/life40/funds9/shop[null,忍冬,风丸,伺夜,折桠]/covenants{迅捷11}/rec=buy:折桠8.45/忍冬6.811/风丸6.242（flags[临时值,试探]/理由「无显著协同按战力补充」/parts）+checks low_life绿「生命40」/anti_air未知+plan_notes2+hard_veto=false。逐字段：局面栏+三买推荐+清单着色+notes+无红条+R5 评分启用。rec=null 分支 §5.7 已验。**两分支 PASS**。他信文本这次与磁盘一致（§5.7 stale 已正）。
- **E: 清理复核 OK**：E: feedback 空，删的是他自有临时孤儿（latest/recs_once），我 lane 文件全 D: 未触，范围正确（他 lane 临时产物，非我数据）。
- **coop WARNING 诊断复核 OK**：run_live L173-176 `if mode_tag=="coop": print WARNING`（bot 永不联机→全 null，先开单机录制再重启），最小不改选择逻辑（§0.1）。**latest_session mtime-pick 边界 reconciled**：§5.7 我读的 D: rec=null 样本（f457 round3 life26 covenants{不屈:4,精准:4}）=他无 --session 挑到 coop 200142（mtime 被管线触碰最新）被 advise gate 的产物；现显式 --session 224824 solo→has-rec f457 round5 life40。live 试运行用户新开单机录制=最新 mtime→solo picked 无此问题。
- **诚实注（非阻塞）**：当前 has-rec 样本 difficulty=null（--once 未设 config）→GUI「难度未设」+推荐用 kb None→solo_regulation_5_8 高难池默认；224824 实为最低难（solo_regulation_1_4 低难池）→样本推荐是高难池口径非该局真实低难过滤。**验渲染 OK 但非难度校准推荐**；实时试运行用户设正确 difficulty→config→准确池。印证必填重要性。
- **正式复核 PASS 已发主策划（supervise）→他 relay 用户实时单机局试运行验收**。审计接力闭环（我报路径分歧→他修 L208→我程序复核 PASS）。我不自启 GUI（用户自测）。建成→用户验收即止§0.1 不续 backlog。**剩余挂起：用户实时局试运行验收（=档1 v0 结案）/P1 后 replay+报告批次/B 修订版 spec 抽查/A6 若触及 schema**。