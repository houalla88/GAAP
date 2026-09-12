<div align="center">

# GAAP

**G**overnance · **A**rbitrage · **A**udit · **P**rice

*Price can be tested like anything else. It cannot be decided like anything else.*

[![Tests](https://img.shields.io/badge/tests-162%20passing-09806c)](tests/)
[![Python](https://img.shields.io/badge/python-3.11%2B-09806c)](pyproject.toml)
[![Dependencies](https://img.shields.io/badge/engine-stdlib%20only-5439b4)](gaap/domain/)
[![Licence](https://img.shields.io/badge/licence-MIT-525a6b)](LICENSE)

<sub>**English** · [Français](README.fr.md)</sub>

</div>

---

## The price that converts best is almost always the one that destroys the most value

That single sentence is the reason this engine exists.

Point a conventional A/B testing tool at a tariff and it will pick the cheapest cell. It converts
better — mechanically. In the demonstration portfolio below, that cell converts at **7.87 %** and
returns **€10.25 per exposed lead**. The cell that converts half as often, at 4.04 %, returns
**€21.65**. This is not an optimisation detail: it is a doubling of margin, on the same population,
on a decision that conversion rate gets backwards.

**GAAP decides on risk-adjusted contribution, and can explain why.** Behind that sentence: a
profitability floor rebuilt component by component (funding, operating costs, PD × LGD, regulatory
capital charge), an O'Brien-Fleming sequential stopping boundary placed on margin rather than on
conversion, adverse-selection detection — because a rising price selects the applicants with the
fewest alternatives — and a hash-chained audit trail. The statistical engine carries no numerical
dependency: the χ², Student and inverse-normal distributions are implemented in it and checked
against published reference values, so that an internal control function can read the formula that
was actually applied.

And every recommendation it issues carries its own caveats: extrapolation beyond the envelope of
tested prices, origination PD that is not realised loss, effect measured over the test window alone.
A pricing recommendation delivered without its limits is an incomplete recommendation.

![GAAP cockpit](docs/assets/01-cockpit.png)

<div align="center"><sub>The cockpit: the experiment portfolio, sorted by what needs a decision.</sub></div>

> The interface ships in French. It was built for a Belgian consumer-credit context, and the
> screenshots are the real application, not mock-ups.

---

### About the name

Each letter carries a pillar of the system: **governance** refuses by default anything that is not
admissible, **arbitrage** settles the volume-versus-margin trade-off, **audit** makes every decision
and every assignment replayable — all applied to **price**. *Arbitrage* is used here in its French
sense of settling a trade-off, not in the Anglo-Saxon sense of riskless profit.

The acronym is also a deliberate nod to *Generally Accepted Accounting Principles*, and it states the
same intention: hold price to the standard accounting holds accounts to — rules fixed **before** the
facts, an audit trail, and a reasoned opinion rather than a bare number.

---

## Why a price test is not a button test

| | Visual test | Price test |
|---|---|---|
| **Reversibility** | Rolling back undoes everything. | Signed contracts carry the tested price for their entire lifetime. |
| **Cost while running** | Marginal. | Every under-priced cell burns margin in real time. |
| **Metric** | Conversion rate is enough. | The best-converting price is the lowest admissible one. It frequently destroys value. |
| **Population** | Stable. | Price **selects** applicants: lowering attracts good risks, raising attracts bad ones. |
| **Constraint** | Aesthetic. | Profitability floor, regulatory capital, prohibition on segmenting by protected characteristic. |

This asymmetry is what GAAP encodes. A general-purpose A/B testing tool pointed at a price will
regularly return the wrong answer — not for want of statistical rigour, but because it optimises the
wrong quantity.

---

## The five situations in the demonstration portfolio

They coexist deliberately in the portfolio above, because these are the five a pricing
experimentation engine has to handle and that most A/B testing tools handle badly:

1. **A switch proven against conversion rate** — the cell that converts least is the one that earns
   most.
2. **A protective stop triggered early** — at only 39 % of planned information, one cell breaches the
   loss tolerance fixed before launch. GAAP cuts the cell, not the experiment.
3. **A test with no economic effect despite a significant conversion gap** (z = −3.92) — concluding
   on conversion would have driven a decision that contribution does not support.
4. **A plan refused before launch** by six blocking guardrails.
5. **An invalidated test** through allocation breakage: the numbers look flattering, they are not
   readable.

---

## The five pillars

### 1. Assignment is computed, never stored

```
u = uint64( SHA-256( salt ‖ namespace ‖ subject_id )[0:8] ) / 2⁶⁴
```

A pure function of the experiment salt and the subject identifier. Three direct consequences:

- **The customer sees the same price again.** No database lookup, no drift between two visits.
- **Every past assignment is replayable.** Reconstructing the offer made to a customer eighteen
  months ago requires only the salt and the plan version, both anchored in the audit trail. No table
  of hundreds of millions of rows to retain — therefore no second source of truth that can diverge
  from the first.
- **Experiments are independent.** Because the salt is per-experiment, a subject is re-randomised
  from one test to the next.

```bash
flask replay pp-taeg-2026q3 CLI-8842910
# Experiment : pp-taeg-2026q3 (Personal loan €12,500 - APR ladder)
# Salt       : pp-taeg-2026q3-0f4c9a
# Draw       : 0.467401937101
# Cell       : m45 - Assigned
# Price      : 6.45 %
```

Two independent random streams (`holdout` and `cell`): mixing them would correlate the control
holdout with price — a bias that shows up in no aggregate.

### 2. The profitability floor, before anything else

```
r_floor = f + o + PD × LGD + k × (h − f),    k = RW × target CET1 ratio
```

Funding, operating costs, expected loss (Basel / IFRS 9) and capital charge. A cell placed below
that threshold destroys shareholder value even when it is accounting-profitable — and GAAP **refuses
to launch it**, rather than noting it afterwards.

The property that makes the model coherent: **at the floor price, RAROC equals the cost of equity
exactly.** It is verified by the test suite, and it is what revealed that an early version wrongly
charged funding on the equity-funded portion of the exposure.

![Experiment detail](docs/assets/02-experience-verdict.png)

### 3. The decision is made on contribution, not conversion

```
RAC = take-up × (r_effective − r_floor) × K × D
```

Risk-adjusted contribution per exposed lead. This is the **only** metric on which GAAP permits a
switch. In the screenshot above, the −45 bps cell converts at 7.87 % against 4.04 % for the +90 bps
cell — and returns €10.25 against €21.65 per lead. GAAP decides on the second quantity, and writes
that trade-off into its rationale.

Arrangement fees are converted into a rate equivalent (`fee / (K × D)`): both price levers live on
the same scale, because they reach the same customer pocket.

### 4. Guardrails refuse by default

An experiment is **refused until proven admissible**. Eight pre-launch checks, five in production,
each carrying a stable code that reappears in the audit trail.

![Plan refused by guardrails](docs/assets/03-garde-fous-refus.png)

| Code | Check | Severity |
|---|---|---|
| `ECO_FLOOR` | No cell below the profitability floor | Blocking |
| `ECO_BAND` | Price amplitude within the authorised band | Blocking |
| `RISK_EXPOSURE` | Share of traffic exposed is capped | Blocking |
| `COMP_PROTECTED` | No targeting rule based on a prohibited discrimination criterion | Blocking |
| `GOV_FOUR_EYES` | The plan's author does not approve their own plan | Blocking |
| `STAT_POWER` | Volume sufficient to detect the declared effect | Blocking below 50 % of required, warning above |
| `STAT_HOLDOUT` | Preserved control holdout | Warning |
| `PLAN_DURATION` | Duration bounded | Warning |

In production, three more: the SRM check, the loss tolerance per lead — a pricing stop-loss fixed
**before** seeing any result — and adverse-selection detection.

A live plan is **frozen**: cells, weights and salt cannot be modified. Changing a plan mid-flight
merges two different experiments into one dataset.

### 5. Everything is sealed

![Audit trail](docs/assets/05-piste-audit.png)

```
h_n = SHA-256( h_{n−1} ‖ timestamp ‖ actor ‖ event ‖ subject ‖ canonical payload )
```

Append-only journal. Modifying or deleting an old entry invalidates every subsequent one, and
verification names both the first broken rank **and** the nature of the break — chaining (an entry
disappeared) or digest (content was rewritten).

This is not a blockchain and does not claim to be: no consensus, no third-party timestamping. It is
a journal that **cannot be falsified silently**, which is the property an internal control function
actually needs.

Logged: design, modification, approval, activation, guardrail refusal, suspension, decision issued,
conclusion. Not logged: individual assignments — they are replayable, and logging them would create
a second source of truth.

---

## The lab: pay for the information, or don't

![GAAP lab](docs/assets/04-laboratoire.png)

A price test burns margin while it runs. Launching one without knowing whether it can conclude
amounts to paying for information you will not obtain.

The lab replays the plan a few hundred times under an assumed elasticity and answers three questions:

- **Can this plan conclude?** In the screenshot: a 67 % chance of switching to the right cell, and a
  25 % chance of switching to a sub-optimal one. That second figure is the more interesting — it
  appears on no conventional experiment design.
- **What does the learning cost?** The distribution, not just the mean. It is the P95 that has to be
  defended in committee.
- **How precisely will elasticity be measured?** Interval coverage at 80 % instead of 95 % signals
  intervals that lie — a worse defect than a lack of power.

Fixed seed: two runs on the same assumptions produce the same result.

---

## Designing a plan

![New plan](docs/assets/06-nouveau-plan.png)

Sizing is recomputed as you type. An under-powered plan discovered three weeks after launch is a
lost plan.

> A lesson from the demonstration portfolio, and an instructive one: detecting **8 % relative** on a
> 6 % take-up with four cells requires **52,000 leads per cell**. The realistic volumes in the
> portfolio only support declaring a 15–18 % MDE. GAAP forces that to be written into the plan
> rather than discovered in the results.

---

## Getting started

```bash
pip install -r requirements.txt

export FLASK_APP=gaap
export GAAP_DATABASE=instance/gaap.sqlite

flask init-db
flask seed --reset        # demonstration portfolio, 100 % synthetic data
python run.py             # http://127.0.0.1:5000
```

In production, serve through a WSGI server and set `GAAP_SECRET_KEY`:

```bash
gunicorn "gaap:create_app('production')" --bind 0.0.0.0:8000 --workers 4
```

Without `GAAP_SECRET_KEY`, the application starts with an ephemeral key **and says so in its logs** —
a loud, therefore visible, default.

### Command line

```bash
flask report pp-taeg-2026q3           # full read-out of an experiment in the console
flask replay pp-taeg-2026q3 CLI-4821  # which price this customer was served, and why
flask verify-ledger                   # recompute the hash chain (exit code 1 if broken)
```

The same engine is reachable through the interface, the API and the command line: a control function
can verify the audit trail without depending on the web application working.

---

## API

The web interface consumes nothing but these routes. What is displayed is exportable, and no
divergence is possible between what an analyst sees and what an auditor extracts.

| Route | Purpose |
|---|---|
| `POST /api/v1/assign` | **Critical path.** Assigns a subject and returns the price to serve. |
| `POST /api/v1/observations` | Records the commercial outcome of an exposed lead. |
| `GET /api/v1/experiments/<key>/report` | Full report: cells, tests, elasticity, guardrails, recommendation. |
| `POST /api/v1/design/power` | Sizing: required sample size and detectable effect. |
| `GET /api/v1/ledger/verify` | Hash-chain verification. |

```bash
curl -s -X POST localhost:5000/api/v1/assign \
     -H 'Content-Type: application/json' \
     -d '{"experiment":"pp-taeg-2026q3","subject_id":"CLI-8842910"}'
```
```json
{"cell": "m45", "rate": 0.0645, "fee": 0.0, "outcome": "assigned",
 "bucket": 0.467401937101, "in_analysis": true, "reason": ""}
```

`/assign` **always returns a price.** Inactive experiment, subject out of scope, excluded segment:
the reference price is served, with the reason. A pricing engine must never have to handle a missing
response from GAAP.

---

## Architecture

```
gaap/
├── domain/              pure Python — no dependency on Flask or on the database
│   ├── stats.py         distributions, intervals, tests, sizing, sequential, Bayesian
│   ├── pricing.py       risk-adjusted floor, contribution, RAROC, Lerner rule
│   ├── allocation.py    deterministic hash-based assignment
│   ├── analysis.py      reading an experiment: SRM → take-up → contribution → elasticity
│   ├── guardrails.py    what the engine refuses, before and during
│   ├── decision.py      decision policy (deliberately separate from measurement)
│   └── models.py        immutable entities
├── infrastructure/      SQLite, repositories, hash-chained audit trail
├── services/            governed lifecycle, analysis, lab, assignment
├── api/                 REST blueprint
└── web/                 views, templates, server-rendered SVG charts
```

Three structural decisions worth defending:

**The engine uses the standard library only.** No numpy, no scipy, no pandas. An internal control
function has to be able to read the formula that was applied without traversing a compiled numerical
stack, and a pricing result must not depend on a BLAS version. The χ², Student and inverse-normal
distributions are implemented and checked against published reference values.

**Charts are SVG rendered server-side.** No CDN, no inline script. That is what makes a strict
Content Security Policy tenable — `default-src 'self'`, with no `unsafe-inline` and no exception —
enforced by a test that fails if a template reintroduces an inline style.

**Measurement and decision are separated.** `analysis.analyse()` measures, `decision.recommend()`
rules. This allows a different decision policy to be replayed on unchanged measurements: the only
honest way to compare two stopping rules.

---

## Statistical method

| Question | Method | Why this one |
|---|---|---|
| Interval on a take-up rate | Wilson score (1927) | Keeps nominal coverage at low rates — the regime of credit take-up |
| Gap between two take-up rates | Newcombe (1998), method 10 | Correct coverage when one arm is deliberately under-exposed |
| Gap in contribution | Welch's *t* test | Variance depends on the cell's price: homoscedasticity is false by construction |
| Multiple comparisons | Bonferroni | Without correction, family-wise error reaches 14 % for three variants |
| Allocation integrity | χ² goodness-of-fit, p < 0.001 | A failure invalidates everything, however good the numbers look |
| Early stopping | O'Brien-Fleming (Lan-DeMets) | A rule written before the test, enforceable, protecting against *peeking* |
| Bayesian read-out | Beta posteriors on **contribution** | Answers "what is my probability of being wrong if I switch?" |
| Elasticity | Weighted log-log regression | Weights = inverse variance of `ln p` by the delta method |

Two points deserve emphasis because they are frequently done badly:

**The sequential boundary applies to contribution, not conversion.** Protecting against peeking on
the statistic you do not decide on makes no sense. The demonstration portfolio contains the case that
proves it: a statistically significant take-up gap (z = −3.92) that is economically neutral —
contribution interval [−1.76 ; +4.19] € per lead — where concluding on conversion would have driven a
decision contribution does not support.

**The theoretical optimal price is bounded to the envelope of tested prices.** The Lerner rule
`(p* − c)/p* = −1/e` extrapolates an elasticity estimated on a handful of steps to the whole curve.
GAAP computes that value, flags it as extrapolation when it falls outside the envelope, and refuses
to act on it alone. Leaving the envelope means replacing a measurement with a functional-form
assumption.

The full methodology note lives **inside the application** (`/methode`) — a method you have to go
looking for elsewhere is not enforceable. A written version is in
[`docs/METHODOLOGIE.md`](docs/METHODOLOGIE.md) (French).

---

## What GAAP does not measure

This section matters as much as the previous ones, and every recommendation restates it:

- **Competitor reaction** to a generalised price change.
- The effect of price on **long-term customer value** — cross-holding, attrition, refinancing.
- **Seasonality** and novelty effects beyond the test window.
- The behaviour of customers **excluded by a guardrail**, unobserved by construction.
- **Realised loss**: only expected loss at origination enters the calculation. Any conclusion about
  risk mix must be confirmed on twelve-month cohorts.

Adverse selection is *detected* — by comparing mean PD of accepted applications across cells — but
the PD used is the scoring model's at the time of offer. It anticipates loss; it does not observe it.

---

## Tests

```bash
pip install -r requirements-dev.txt
pytest                    # 162 tests, ~10 s
```

The suite checks **properties**, not behaviours: assignment stability, hash uniformity, independence
of random streams, floor/RAROC coherence, detection of audit-trail tampering, refusal of illegal
lifecycle transitions.

Statistical reference values come from published tables, not from an earlier run of this code: a test
that compares code against itself verifies nothing.

One test pins the assignment fingerprint of eight subjects. It fails if a change to the hashing
displaces a subject — deliberately: changing the assignment function silently invalidates every
running experiment, and must therefore be a conscious act.

The screenshots in this document are regenerated by `python3 scripts/capture_screens.py`: a
hand-made screenshot becomes wrong at the first interface change, and nobody notices.

---

## Demonstration data

**Every figure in the portfolio is synthetic.** No customer, no contract, no real exposure. The
orders of magnitude — funding rate, PD, LGD, risk weight, take-up — are chosen to be plausible in a
European consumer-credit market; they constitute neither a market reference nor a pricing
recommendation.

The generator is explicit and parameterised: constant-elasticity demand, plus an adverse-selection
term making acceptance depend on applicant risk as price departs from the reference (`gaap/demo.py`).

---

## References

- Kohavi, Tang & Xu (2020), *Trustworthy Online Controlled Experiments*, Cambridge University Press
- Wilson (1927), *JASA* 22(158) — score interval
- Newcombe (1998), *Statistics in Medicine* 17(8) — difference between proportions
- O'Brien & Fleming (1979), *Biometrics* 35(3); Lan & DeMets (1983), *Biometrika* 70(3)
- Fleiss, Levin & Paik (2003), *Statistical Methods for Rates and Proportions*
- Lerner (1934), *Review of Economic Studies* 1(3)
- Basel Committee (2017), *Basel III: Finalising post-crisis reforms*; IFRS 9, *Financial Instruments*

---

<div align="center">

**[DataOptimization.be](https://www.dataoptimization.be)**

<sub>Data science consulting for financial services — pricing, price sensitivity,<br>
credit risk, analytical architecture.</sub>

</div>
