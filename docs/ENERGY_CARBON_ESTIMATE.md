# Energy and carbon estimate

> Estimate of the energy, carbon and water consumed by the AI assistance
> (Claude Opus 4.8) used to build this project. **An order of magnitude, not a
> measurement.** The only hard datum is the token count; the whole conversion to
> energy relies on approximate public coefficients. The "intervals" below are
> **subjective plausibility ranges** (low = all assumptions low, high = all
> assumptions high), **not statistical confidence intervals**.

## 1. Basis: tokens consumed (main session)

| Category | Tokens | Role |
|---|---:|---|
| Output (generation) | 3,100,615 | text produced by the model — 1 full pass per token |
| Prefill (cache creation) | 9,250,953 | unique context processed once |
| Cache read | 663,556,457 | context re-read each turn (mostly KV memory reads) |
| Uncached input | 3,997 | negligible |

Sub-agents (two Fable reviews ≈ 201 K tokens, one Sonnet scan ≈ 72 K) are not
included: negligible next to the main session.

## 2. Assumptions (with ranges)

| Parameter | Low | Central | High | Rationale |
|---|---:|---:|---:|---|
| Output energy (J/token) | 0.30 | 0.80 | 2.0 | decoding = 1 forward pass/token, the most expensive |
| Prefill energy (J/token) | 0.05 | 0.15 | 0.50 | processed in parallel → cheaper per token |
| Cache-read energy (J/token) | 0.003 | 0.010 | 0.050 | mostly memory bandwidth (KV); **most uncertain item** |
| Datacenter PUE | 1.10 | 1.20 | 1.50 | cooling/power overhead |
| Carbon intensity (kg CO₂e/kWh) | 0.05 | 0.20 | 0.45 | from a very renewable grid to a carbon-heavy one |
| Water (L/kWh) | 0.2 | 1.5 | 5.0 | on-site cooling + electricity generation |

## 3. Results

| Quantity | Low | **Central** | High |
|---|---:|---:|---:|
| IT energy | 3.4 MJ | **10.5 MJ** | 44.0 MJ |
| **Electricity (with PUE)** | **~1.0 kWh** | **~3.5 kWh** | **~18.3 kWh** |
| **Carbon footprint** | **~0.05 kg** | **~0.70 kg CO₂e** | **~8.3 kg** |
| **Water** | **~0.2 L** | **~5.3 L** | **~92 L** |

### Where the energy goes (central split, IT kWh before PUE)

| Item | kWh | Share |
|---|---:|---:|
| Cache read | 1.84 | **63%** |
| Output | 0.69 | 24% |
| Prefill | 0.39 | 13% |
| Input | ~0 | ~0% |
| **IT total** | **2.92** | 100% |

**Cache-read dominates** by volume (663 M tokens) and therefore the uncertainty,
even at a low per-token cost: every generated token "reads" attention over the
whole cached context. **Output** remains the most expensive item *per token*.

## 4. Equivalences (central value ≈ 3.5 kWh)

- ≈ **290 smartphone charges**
- ≈ **2.7 days** of a refrigerator's consumption
- ≈ **21 km** in an electric car
- ≈ **32 kettles** of water brought to a boil
- ≈ a microwave oven (1 kW) running for **~3.5 h**

Central carbon ≈ **0.7 kg CO₂e**: roughly **~4 km** in a petrol car, or one meal
with meat.

## 5. Takeaways

- **Modest at household scale**: ~1 to 2 days of a fridge to have produced a
  complete software project (dual-route pipeline + validation + packaging +
  multilingual repository).
- **But the uncertainty is wide**: the plausible result spans from **~1 kWh to
  ~18 kWh** (more than an order of magnitude), dominated by the unknown real
  energy cost of long-context cache reads.
- These figures are an **order-of-magnitude frame** for transparency, not to be
  cited as an exact measurement.

## 6. Method and limits

- Tokens: extracted from the `usage` fields of the session transcript (same
  figures as the API cost estimate).
- Energy = Σ(category_tokens × J/token) → MJ → kWh (÷3.6) × PUE.
- Carbon = kWh × grid intensity; Water = kWh × water factor.
- **Not counted**: model training (amortized over billions of requests),
  hardware manufacturing, my workstation, the network.
- Anthropic does not publish per-token energy; the coefficients come from generic
  public LLM-inference analyses and vary widely with model, hardware and batching.

*Estimate produced 2026-07-23. Coefficients are adjustable — see section 2 to
recompute with other assumptions.*
