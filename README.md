# Economic Plan Rework — Reference

Target: Stellaris 4.4.4 vanilla. All values read directly from game files, not from memory.

---

## 0. Strategy assessment

The premise — *make the economy so strong the military doesn't matter* — is sound, and
has precedent: StarNet's AI became competitive with decent human players mostly through
economic and ship-design tuning, not through replacing fleet logic.

Two honest caveats before committing:

1. **It doesn't fix the piecemeal-attack problem, it funds it.** An AI that out-produces
   you 3:1 and still feeds fleets in one at a time produces a specific feel: you win every
   engagement and lose the war. Some players find that more frustrating than a fair fight.
2. **It is not a difficulty bonus.** Worth being clear, since this was raised earlier as a
   failure mode: a better economic *plan* is genuine competence. Granting free resources
   is not. Keep the mod on the first side of that line.

The strategy's real advantage: everything below is additive or defines-only. Almost none of
it requires overwriting a contested vanilla file.

---

## 1. How the system works

### Plan ladder

Six plans, selected by flat `ai_weight`, descending:

| Plan | File | Weight |
|---|---|---|
| `basic_economy_plan` | `01_base.txt` | 1000 |
| `intermediate_economy_plan` | `02_intermediate.txt` | 200 |
| `advanced_economy_plan` | `03_advanced.txt` | 50 |
| `mature_economy_plan` | `04_mature.txt` | 25 |
| `endgame_economy_plan` | `05_endgame.txt` | 10 |
| `beyond_endgame_economy_plan` | `06_beyond_endgame.txt` | 1 |

No top-level `potential` on any of them. **Inferred** (verify in-game): the AI takes the
highest-weight plan whose goals it has not yet fulfilled, so the descending weights act as
a progression ladder. If that's wrong, the whole selection model needs rethinking — check
this first.

### Goal types

```
income        = { ... }   # target surplus income per resource
focus         = { ... }   # raised priority until rhs surplus is reached
pops          = N         # EMPIRE-WIDE total pop target
empire_size   = 1.25      # max admin cap fraction
naval_cap     = N         # naval cap to aim for
```

### Subplan flavors

| Form | Behavior |
|---|---|
| `subplan` | Goals added if `potential` passes. Must be fulfilled. |
| `scaling = yes` | Re-added repeatedly while `potential` holds — the infinite climb. |
| `optional = yes` | **Does not gate scaling.** A soft wish; never blocks. |

Scaling subplans keep stacking until one fails its `potential`. Their `potential` almost
always contains a `has_monthly_income < @some_limit` clause — **those limits are the
ceilings on AI ambition.**

### Overwrite semantics (from `00_example.txt`)

Economic plans overwrite **additively**, unlike most databases:

- Add a plan entry with only a subplan → that subplan is appended
- Add a subplan whose name matches an existing one → **it replaces it**
- Non-subplan content (e.g. bare `income = {}`) usually overwrites
- Full replacement requires overwriting the *file*, not the entry

This is the most conflict-tolerant lever in the game. Use same-name subplan replacement for
surgical edits; never overwrite these files wholesale.

---

## 2. The chain from alloys to fleet power

Four stages. A gain at any stage is capped by the next one.

```
[1] alloy income        <- economic_plans  (scripted_variables)
[2] share spent on ships <- ai_budget
[3] naval capacity       <- plan naval_cap goal + tech/buildings
[4] alloys-per-power     <- component ai_weight + DESIGNER_* defines
```

### Stage 2 is the bottleneck — alloy expenditure share

Computed across all `common/ai_budget/*.txt`, resource `alloys`, type `expenditure`
(total weight 4.95):

| Category | Weight | Share |
|---|---|---|
| colonies | 1.30 | 26.3% |
| starbases | 0.80 | 16.2% |
| **ships** | **0.60** | **12.1%** |
| megastructures | 0.40 | 8.1% |
| megastructures_waystations | 0.40 | 8.1% |
| megastructures_arkships | 0.40 | 8.1% |
| ship_upgrades | 0.20 | 4.0% |
| megastructures_habitat | 0.20 | 4.0% |
| decisions | 0.20 | 4.0% |
| armies | 0.20 | 4.0% |
| deposit_blockers | 0.15 | 3.0% |
| planets | 0.10 | 2.0% |
| buffer | 0.00 | 0.0% |

**Doubling alloy income sends ~12% of the increase to the fleet.** Colonies and
megastructures (28.3% combined) absorb far more. Any income rework without a matching
budget rework mostly builds habitats.

Wartime modifier exists — `alloys_expenditure_ships` has `factor = 3` on recent war loss /
at war — pushing ships to roughly 30% during a war. Peacetime buildup is where the
shortfall accumulates.

### Stage 3 — naval cap is a hard gate

Several budget entries key off `used_naval_capacity_percent`, and they divert alloys
**away** from ships at cap:

- `ship_upgrades` ×2.5 when at capacity
- `starbases` ×2 when at fleet cap
- `megastructures` ×3 when at capacity

Correct behavior — but it means excess alloy income at naval cap turns into starbases and
megastructures, not fleet. The plan-side lever is the naval cap subplan:

```
subplan = {
    optional = yes            # <- does not gate scaling
    scaling  = yes
    set_name = "Naval Cap Scaling"
    potential = { used_naval_capacity_percent > 0.85  meets_basic_resource_thresholds = yes }
    naval_cap = 100
}
```

`optional = yes` means naval cap growth never blocks anything. Prime candidate for
same-name replacement.

### Budget mechanics note

`type = expenditure` and `type = upkeep` are separate budgets. Multiple entries may share a
category+resource pair (documented in the budget file headers), so **budget entries can be
added without overwriting vanilla ones** — the additive path applies here too.

---

## 3. Tuning surface

All 93 plan variables live in `common/scripted_variables/00_scripted_variables.txt`.

### Ladder targets

| Stage | alloys | research (ea.) | minerals | energy | unity | trade | pops |
|---|---|---|---|---|---|---|---|
| base | 20 | 35 | 25 | 10 | 20 | 10 | 10,000 |
| intermediate | 50 | 150 | 50 | 40 | 50 | 25 | 25,000 |
| advanced | 150 | 400 | 150 | 100 | 100 | 50 | 100,000 |
| mature | 200 | 1000 | 200 | 150 | 200 | 75 | 175,000 |
| endgame | — | — | 300 | 200 | — | — | — |
| beyond endgame | — | — | 500 | 300 | — | — | — |

Note the alloy target **stops climbing after mature (200)** while research continues to
1000 and `@economic_plan_late_research_target = 5000`. Late-game AI has no rising alloy
ambition at all. Strong candidate for the single highest-impact change.

### Scaling ceilings (where the climb stops)

| Variable | Value |
|---|---|
| `@economic_plan_scaling_alloy_limit` | 250 |
| `@economic_plan_scaling_alloy_bioship_limit` | 100 |
| `@economic_plan_advanced_scaling_alloy_limit` | 1500 |
| `@economic_plan_scaling_energy_limit` | 100 |
| `@economic_plan_scaling_minerals_limit` | 250 |
| `@economic_plan_scaling_research_base_limit` | 300 |
| `@economic_plan_intermediate_scaling_research_limit` | 1500 |
| `@economic_plan_mature_scaling_research_limit` | 2500 |
| `@economic_plan_advanced_scaling_research_limit` | 3500 |
| `@economic_plan_scaling_unity_limit` | 300 |
| `@economic_plan_scaling_trade_limit` | 100 |
| `@economic_plan_stockpile_threshold` | 2,500 |
| `@economic_plan_stockpile_threshold_high` | 25,000 |
| `@economic_plan_stockpile_threshold_very_high` | 35,000 |

### Scaling increments (size of each step)

| Variable | Value |
|---|---|
| `@economic_plan_scaling_alloy_target` | 10 |
| `@economic_plan_advanced_scaling_alloy_target` | 100 |
| `@economic_plan_scaling_research_target` | 10 |
| `@economic_plan_late_scaling_research_target` | 500 |
| `@economic_plan_scaling_pops_target` | 10,000 |
| `@economic_plan_scaling_unity_target` | 8 |
| `@economic_plan_scaling_trade_target` | 5 |
| `@economic_plan_rare_resource_target` | 1 |
| `@economic_plan_scaling_rare_resource_target` | 0.20 |

---

## 4. Known defects to fix along the way

### Pop growth on new colonies

Three independent causes:

1. `pops` is an **empire-wide total**. The plan language cannot express "this colony needs
   growth infrastructure."
2. Both pop subplans (`"Base Pops"`, `"Scaling Pops"`) are `optional = yes` — they never
   gate anything.
3. **Across all 100 designations in `common/colony_types/00_colony_types.txt`,
   `ai_building_set_affinity` never once references pop growth or assembly.** Full key
   distribution: industrial 28, government 17, foundry 14, unity 13, trade 13, society 12,
   research 12, physics 12, factory 12, engineering 12, base 9, farming 8, hydroponics 7,
   generator 7, generator_automation 6, farming_automation 6, mining 5, mining_automation 4,
   fortress 4, entertainment 2, bio_trophy 2. There are 28 buildings with
   `category = pop_assembly` and no designation expresses any desire for them.

**Open question — resolve before writing:** the namespace for `ai_building_set_affinity`
keys is unidentified. They do not match building `category` values (`foundry`, `factory`,
`farming`, `generator`, `mining` are not categories), and there is no `building_sets`
folder. Verify the valid key set or an added affinity will silently no-op.

### Planet specialization

Four compounding brakes:

| Cause | Location | Value |
|---|---|---|
| Weak plan-alignment signal | defines | `AI_DESIGNATION_RESOURCES_IN_ECONOMIC_PLAN_BONUS = 1.25` |
| Long change cooldown | defines | `AI_DESIGNATION_COOLDOWN = 360` |
| Incumbency bonus | `00_colony_types.txt` | `@stickiness = 10`, `@stickiness_low = 5` added via `weight_modifier` when `has_designation` matches self |
| **Flat plans** | economic_plans | base plan requests alloys + 3 research + unity + trade + minerals + energy simultaneously |

The fourth is upstream of the rest. If every resource is wanted equally, no designation is
better aligned than any other and the 1.25 bonus has nothing to bite on. **The AI is not
failing to specialize planets — it has no specialization to express.** `focus` is the tool
for this ("increased prio until surplus income of rhs value is reached").

---

## 5. Proposed order of operations

Each step gated before the next. Rationale: earliest steps are cheapest to revert and
validate the loop.

1. **Sharpen the plans with `focus`.** Fixes flatness, which is upstream of specialization.
   Additive via same-name subplan replacement. No file overwrites.
2. **Raise late-game alloy ambition.** Alloy target stalls at 200 from mature onward while
   research climbs to 5000. Variable edits only.
3. **Rebalance alloy expenditure share.** Move ships from 12% upward. Budget entries are
   additive — prefer adding a weighted entry over overwriting.
4. **Un-`optional` the naval cap subplan.** Otherwise steps 2–3 hit the stage-3 gate.
5. **Designation affinity for pop growth** — *blocked on the namespace question above.*
6. **Designation stickiness / cooldown / alignment bonus** — only after step 1, since flat
   plans may be the whole cause.

### Gate for every step

- Loads with clean `error.log` (Stellaris fails silently; this is the only automated signal)
- AI solvent at year 2250, no runaway deficits
- Observer check: does at least one AI planet change designation after year 2230?

---

## 6. Open questions requiring observer play

1. Does plan selection actually work as a fulfilled-then-advance ladder? (§1)
2. What namespace do `ai_building_set_affinity` keys come from? (§4)
3. Does any AI planet designation ever change after the first ~30 years?
4. Where does surplus alloy income actually go at naval cap — measured, not inferred?