# covenants_temp 基线假设 KB 核问（2026-11-18，协作A，应主策划 P1§13.2/交接⑯）

主策划横幅读取器（analysis/ocr_covenants.py）感知层达标，基线减法遇中期帧阻塞（rest OCR 间歇漏名→单条最近 rest 基线把永久层误算 temp，f758 莱塔尼亚11/不屈6）。拟用永久单调包络+KB 上限 sanity，固化前核三个假设。本笔记=取证回答 + KB v1.3 勘误落地。

## 0. 取证范围

- **S6 bonds.json**（E:/garrison-ai/data/repo_snapshot/act3autochess-v3_1/）：26 盟约 desc 全文 + bb 参数 + noStack/activeType/countMode/countsHand/layerMilestones/maxCount 全扫。
- **S6 effects.json**：34 条 effectType=BOND 的 continuedRound/counterType；layer 相关 effect key（bond_layer_added_reward_equip / bond_layer_gain_coin / bond_layer_char_garrison_bonus / bond_layer_shop_same_tier / skill_sell_char_bond_layer / use_equip_bond_layer）。
- **规则说明书.md** §2.2/§5.1-5.3；**KB md** §7.1-7.3/缺口表#7。
- **五局 curves 校准**（样本只作校准不作规则来源）：灵巧 223918 全序列、炎 200142 全序列、乌萨斯 205833 全序列（压缩平台）、远见 200142 尾段。

## 1. (a) 永久盟约层数是否单调只增？spendable（灵巧）是否例外？

**结论：永久层单调只增；灵巧不是例外——"spendable"系 OCR 误推断。**

规则侧（权威）：
- 26 盟约 desc 全扫，**无任何消耗层数机制**。"消耗"命中仅奇迹（刷新不消耗**资金**）、绝技（技力**消耗**−30%），皆非层数。
- 层数来源全是加法：部署叠层、里程碑（维多利亚每25/谢拉格每100/远见每10）、助力休整末+2/+4、策略（但书全盟约提升/三船卖干员叠等阶/华法琳战斗开始叠层）、装备（effects `use_equip_bond_layer`，eff_acarm124/eff_acgarm124）。
- KB md §7.3 既有两条支持失活不清零：**层数整局保留**（S3 贴士，B）+ **未激活攒层激活时补发里程碑**（S7 社区，C）。

样本校准互证：
- **灵巧 223918**：噪声过滤后严格单调 2→4→8→11→13→16→19→22→24→27→30→33→36→42→50→59→69→65→72→79→85→98→100→106→112→121→133→157→163→169→175→184。所有"下降"（80→8、11→1、65→5、85→5/35、157→57、175→75）都是 **x1 单帧 OCR 截断尖峰**（丢尾数字），非真实减少。
- **乌萨斯 205833 rest 平台**：2→14→21→30→39→49→61→80→109→150→204→251 严格增（每平台 x36-72 帧稳定）。
- → **parse_hud 注释"some are spendable (灵巧)"是误推断**（主策划 lane，建议随下次增量修注释；本报告不代改）。

**noStack 四名（新事实）**：调和/协防干员/独行/绝技 `noStack=true`（bonds.json），**无层数概念**。HUD 上这四名的数字语义≠层数（疑人数/阶徽章），**temp 减法应整体排除**，否则把人数当层数减出假 temp。

**未决 anomaly（诚实标注，C）**：炎 200142 R3 rest 8(x8 帧)→R5 rest 2(x20 帧) 是稳定平台下降，非截断。候选解释=名数错配（nearest-x 配对把邻名数字配给炎）或未知机制；规则书两条均不支持失活清零，暂按单调处理。**待局内取证**：卖炎干员至失活（<3 人）观察层数是否清零/隐藏。对包络影响：若炎 R3 的 8 是错配，包络会短暂高估永久 6 层（R5-R7），但因 temp 只算乌萨斯（见§3），对读取器实际输出无影响。

## 2. (b) rest 相位横幅是否≈永久？expires_at_round_end 语义？

**结论：rest 横幅=永久成立（样本 B 级），但 expires_at_round_end 引用错位。**

- **引用纠正**：KB 的 `expires_at_round_end: true` 在 **shop.reward_offer**（三合一晋升临时刷 3 名高 1 阶 0 费干员槽，购买 1 个即退出/回合末退出），**与盟约层数无关**。covenants 节无此键。主策划§13.2"KB expires_at_round_end → rest 横幅≈永久"的推理链需换锚点。
- **正确锚点=样本回合末清零（B 级）**：乌萨斯 205833 八个回合边界全部回落且 rest 平台稳定——
  R7 combat 峰63→R8 rest39(x36)；R8 峰110→R9 rest49(x72)；R9 峰150→R10 rest61(x70)；R10 峰120→R11 rest80(x65)；R11 峰142→R12 rest109(x65)；R12 峰239→R13 rest150(x56)；R13 峰308→R14 rest204(x46)；R14→R15 rest251。
  → 临时层回合末清零，rest 横幅=永久。**repo 无临时层到期字段**（continuedRound=-1 全 34 条 BOND 效果统一，非判别字段；counterType 全 NONE）→ 此结论是样本证实非 repo 明文，标 B。
- **助力时序陷阱**：助力 +2/+4 在**休整结束**才授予（bonds.json deputShip desc 明文"休整期结束时"）→ rest 早期帧=授予前、晚期帧=授予后。**单条最近 rest 基线可能取到授予前→低估永久→虚高 temp**；包络 max（≤i 所有 rest 行）自动覆盖授予后值，优于单条。
- **combat 横幅=永久+乌萨斯临时+战斗中永久增量**：炎 200142 combat 22→353 持续增长且**跨回合保留**（R13 combat277→R13 rest277 x109、R14 combat353→R14 rest353 x129）→ 战斗中部署叠的是**永久层**非临时。故 combat−包络 对乌萨斯=临时+战斗中永久增量，**略高估 temp**，诚实标注（战斗中部署越多高估越大）。
- **联防/领袖轮不叠层**（S2 帮助页 A，md §7.3）：205833 R14 领袖轮乌萨斯 combat 恒 204 互证 ✓。parse_hud  coop 门控已处理。

## 3. (c) 各盟约临时层上限？

**结论：无上限；KB"乌萨斯临时层上限4"=误读，已勘误（v1.3）；临时层仅乌萨斯有。**

- **repo 直取**：ursusShip bb `temp_bond_stack_cnt=2`、`temp_bond_stack_cnt[power]=4`；desc 明文"【乌萨斯】干员击倒其他单位时叠加的临时层数**提升至4层**"→ **4=6 人后每次击倒叠层数，非上限**。repo 无任何临时层上限字段（maxCount=null）。
- **样本证伪上限4**：205833 R13 combat 峰 308−永久 150=临时≈158 ≫4。
- **其余 25 盟约无临时层机制**：desc 全扫唯一"临时"命中=乌萨斯。易混项澄清：伊比利亚 max_stacks10=**敌方 DOT 叠层**、卡西米尔 cap(50+1L)%=**战斗 buff 上限**、萨尔贡 aspd_cap300=**buff 上限**——皆非盟约临时层。
- **对主策划 f758 论证的修正**：「乌萨斯上限4→temp 必小量→莱塔尼亚11 不可能 temp」前提错（无上限），但**结论更强成立**：莱塔尼亚/不屈**根本无临时层机制**→f758 莱塔尼亚11/不屈6 必为永久（rest 漏读），不是 temp。

## 4. 对读取器的设计建议（主策划 lane，建议非代改）

阻塞可直接化解——**非乌萨斯名本来就不该有 temp**：

1. **covenants_temp 只对乌萨斯计算**（唯一临时层盟约）。其余盟约 banner>包络 的差=战斗中永久增量或基线漏读→**更新包络/标 absent_from_rest，不产 temp**。f758 类中期帧不再"虚高 temp"而是"修基线"。
2. **noStack 四名（调和/协防干员/独行/绝技）整体排除**出 temp 减法（无层数概念）。
3. **基线=≤i 所有 rest 行逐名包络 max**（永久单调→包络合法），优于单条最近 rest（助力授予前陷阱+OCR 漏名）。包络本身对 OCR 截断尖峰免疫（max 取稳定平台）。
4. **乌萨斯 temp=combat 横幅−包络**，clamp≥0，诚实标注"含战斗中永久增量，略高估"；rest 帧 temp 应≈0（可作 QC 不变量：rest 帧算出大 temp=基线漏读信号）。
5. 炎 anomaly 未决前，包络对非乌萨斯名只用于"修基线"不用于产 temp→anomaly 不影响输出。

## 5. KB v1.3 落地清单（我 lane，已改）

- `data/rules_kb.json`：乌萨斯 m6 勘误（per-kill 4 非上限）；covenants.rules 新增 6 键（temp_layers_only/temp_layers_note/no_stack_bonds/no_stack_note/permanent_monotonic/rest_end_grant_timing）；_meta version 1.3。JSON 校验 OK。
- `notes/20261117-规则知识库-v1.md`：标题 v1.3 + v1.3 勘误头；§7.1 乌萨斯行修；§7.3 新增 4 条（临时层唯一性/noStack 四名/永久单调/助力时序）；缺口表#7 修。
- **QMind 再同步**：KB md/json 升 v1.3 → 加入 B4 再同步批次（赛季库 KB 源 2292e289 现 v1.2）。

## 6. 报主策划他 lane 项（报告不代改）

- parse_hud 注释"some are spendable (灵巧)"系 OCR 截断误推断，建议修注释（灵巧永久单调）。
- P1方案§13.2/交接⑯"KB 证伪（乌萨斯临时层上限4，temp 必小量）"引用宜随 v1.3 勘误更新为"临时层仅乌萨斯有、无上限；莱塔尼亚/不屈无临时层机制→f758 必为永久漏读"。
- ocr_covenants.py 当前对所有名产 temp（L82）+absent 标记——建议按§4 收窄到乌萨斯，中期帧阻塞即解。

## 7. 未决/待局内（不催用户，随 P1 管线顺带）

- 炎 200142 R3→R5 平台下降 anomaly：卖炎干员失活取证（层数清零/隐藏/保留）。
- 临时层到期 repo 无字段：回合末清零目前 B 级样本，局内一回合 combat 峰→rest 直读可升 A。
- noStack 四名 HUD 数字语义（人数/阶）：局内一帧面板核。

## 8. 实现复核（2026-11-18，主策划按§4 建议重构 ocr_covenants.py 后交复核）= **PASS**

取证非纸面：读重构代码 + 从 raw curves 独立重算 9 帧 envelope/temp/flags 逐帧比对 + coop own 过滤计数核实 + 零消费方 grep。

### 8.1 声称 vs 实际（7 项重构点全核实）

| 声称 | 代码定位 | 核实 |
|---|---|---|
| temp 只算乌萨斯 | L45 TEMP_BOND="乌萨斯"，L119-121 仅该名额产 temp | ✓ |
| noStack 四名排除 | L46 NO_STACK={调和,协防干员,独行,绝技}，L116-118 标 no_stack_excluded skip | ✓ |
| 基线=逐名包络 max(≤i own-rest) | L81-90 envelope_at；L103-104 rest 过滤 phase==rest & covenants & gate∈(None,own) | ✓ |
| 乌萨斯 temp clamp≥0+诚实标 | L121 max(0,v−env)；L129-130 temp_note | ✓ |
| 其余名 banner>包络 标 perm_increment_or_baseline_miss 不产 temp | L122-124 | ✓ |
| rest 帧 temp≈0 QC 不变量 | L126 qc_rest_temp_nonzero=(phase==rest & temp[乌萨斯]>0) | ✓ |
| coop 包络只 own 态 rest | L103-104 gate 过滤排除 spectate/jd/leader/hidden | ✓ |

parse_hud 注释修正核实（L300-304）：「permanent covenant layers monotonic non-decreasing (KB v1.3)…灵巧 is NOT spendable—prior 'spendable' note was a misinference…noStack four HUD digit != layer」✓。§13.3/交接⑰ 登记与代码/消息一致 ✓。

### 8.2 独立重算（从 curves 复刻 envelope_at，用他 banner OCR 作输入，比对 envelope/temp/flags）

**9/9 帧三项全匹配**（env_match=temp_match=flags_match=True）：
- 224824 f457/f470/f758/f761/f2185：temp={} 全对；f758/f761 莱塔尼亚11/不屈6 → perm_increment_or_baseline_miss（中期阻塞化解 ✓）；f2185 大三 258/166/67=包络闭环 ✓。
- 205833 f212/f785/f2403/f2457：f785/f2403 rest temp=0（QC ✓）；f212 combat temp=18；f2457 combat temp=150（300−env150）；不屈 f2457 24>env8 诚实标 ✓。
- 交叉吻合：他 f2457 temp150（帧值300）vs 我§1 引用 R13 峰 308−150=158——同回合不同帧，一致 ✓。

### 8.3 coop own 过滤计数核实

205833 rest 行按 gate={None(own):467, leader:96, hidden:83}→过滤排除 179 条 gated rest，own-rest=467 ✓（jd99/spectate 属 combat 相位不在 rest 子集）。224824 solo rest 全 None=881 ✓。

### 8.4 零消费方 + schema

covenants_temp.json 全仓库 grep=仅生产者 ocr_covenants.py + 文档/笔记引用；model/state.py L46 有 covenants_temp **字段**但无任何代码从该文件加载（replay/advisor 不读）→**零消费方维持**。schema 演进（旧 rest/rest_source_i/absent_from_rest → 新 envelope/flags/phase/temp_note/qc）对零消费方 artifact 自由。注：他标"additive"措辞略宽（实为零消费方 artifact 的字段替换），非阻塞。

### 8.5 非阻塞注记（4 条）

1. **早期包络=0**：f212 乌萨斯 temp=18=banner（首条 own-rest 乌萨斯在 i335>212，之前无基线）→temp 含永久≈2 全归 temp。temp_note 文案覆盖"战斗中永久增量"但未覆盖"尚无基线"。早期帧轻微高估，诚实标即可。
2. **hidden own-rest 保守排除**：205833 hidden rest83（R15 own 永久乌萨斯251 可读）被排除→hidden 回合 combat 帧会用 R14 env204 而非 251→temp 高估+47。对未来联机 hidden 归属不确定是稳健保守；若 hidden 确认 own 态可喂包络。当前验证帧不含 R15 combat 无实际影响。
3. **temp_note  cosmetic**：temp={乌萨斯:0} 的 rest 帧也带"combat temp slight overestimate"文案（L129 条件=temp 非空含 0 值）。建议 gate 于 phase==combat & temp>0。纯措辞。
4. **schema "additive" 措辞**：见§8.4，零消费方下自由演进，PASS 不受影响。

### 8.6 model/ 兼容 + 未来消费约束

State.covenants_temp 字段不读此文件→零适配。未来 replay/报告生成器消费 covenants_temp.json 时：读 envelope+covenants_temp(仅乌萨斯)+flags；**perm_increment_or_baseline_miss 当基线修复信号非 temp**；no_stack_excluded 四名不呈现层数；乌萨斯 temp 标"略高估"；rest 帧 qc_rest_temp_nonzero=True 当基线漏读告警。