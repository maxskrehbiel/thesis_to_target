# Target brief: Commercial fire and life-safety services, US Midwest

> Synthetic demonstration. Every company, source record, database listing and number below was generated from seed 42; no real business is described.

## Thesis

Founder-owned providers of fire sprinkler, fire alarm, extinguisher and suppression installation, inspection and testing for commercial buildings. Inspection and testing are code-mandated and recur every year, which makes revenue sticky; the market is fragmented across many small local operators.

| Parameter | Value |
| --- | --- |
| EBITDA band | $1.00M to $5.00M |
| Geography | IL, IN, IA, KS, MI, MN, MO, NE, ND, OH, SD, WI |
| Sources | business_registry (trust 0.9), state_license (trust 0.85), trade_association (trust 0.7), web_listing (trust 0.6) |
| Presence checked in | commercial_db_a, commercial_db_b, investor_db |

## Funnel

| Step | Count |
| --- | ---: |
| Raw records (business_registry 58, state_license 40, trade_association 19, web_listing 50) | 167 |
| Companies after entity resolution | 66 |
| Record pairs left for human review | 17 |
| In thesis geography | 54 |
| In geography with sector evidence (fit tier A to C) | 45 |
| In scope after all screens | 42 |
| In scope and sized | 37 |
| In scope with P(EBITDA in band) >= 0.5 | 16 |
| In scope and non-obvious | 20 |
| Priority tier | 12 |

## Top 10 targets

| Rank | Tier | Company | State | Fit | Segment | EBITDA median (95% range) | P(in band) | Non-obvious | Sources |
| ---: | --- | --- | --- | --- | --- | --- | ---: | --- | ---: |
| 1 | Priority | Maldmere Fire Sprinkler Systems | SD | A | sprinkler | $3.01M ($1.47M to $6.15M) | 0.92 | yes | 4 |
| 2 | Priority | Lombfield Fire Inspection Services | IL | A | inspection | $1.54M ($0.75M to $3.17M) | 0.88 | yes | 3 |
| 3 | Priority | Lomblund Fire and Alarm | IL | A | alarm | $1.55M ($0.86M to $2.78M) | 0.93 | no | 4 |
| 4 | Priority | Veltthwaite Fire Detection | OH | A | alarm | $1.21M ($0.68M to $2.15M) | 0.74 | yes | 3 |
| 5 | Priority | Ruskfield Fire Extinguisher | IN | A | suppression | $1.27M ($0.60M to $2.69M) | 0.73 | yes | 4 |
| 6 | Priority | Dovrvane Fire Alarm | SD | A | alarm | $1.31M ($0.73M to $2.38M) | 0.82 | no | 2 |
| 7 | Priority | Tambholt Sprinkler | IN | A | sprinkler | $1.48M ($0.53M to $4.16M) | 0.76 | no | 2 |
| 8 | Priority | Maldshaw Life Safety Systems | SD | A | alarm | $1.07M ($0.49M to $2.32M) | 0.56 | yes | 4 |
| 9 | Priority | Wexllund Fire Sprinkler Systems | KS | A | sprinkler | $1.34M ($0.68M to $2.62M) | 0.80 | no | 3 |
| 10 | Priority | Kivelrigg Fire Equipment | MI | A | suppression | $1.34M ($0.51M to $3.54M) | 0.72 | no | 3 |

## Target profiles

### 1. Maldmere Fire Sprinkler Systems (C0018), Glenhaven, SD

| Aspect | Evidence | Confidence | Claim |
| --- | --- | --- | --- |
| Fit | A (verified): sector license 'Fire Sprinkler Contractor' | strong | `C0018.08` |
| Size | 105 employees x $177k revenue/employee (sprinkler) x 16.1% margin (recurring_heavy) = $3.01M median; 95% range $1.47M-$6.15M (sigma 0.36, endpoints) | inferred | `C0018.15` |
| P(EBITDA in band) | log-normal(mu=14.92, sigma=0.36): P($1.00M <= EBITDA <= $5.00M) | inferred | `C0018.17` |
| Visibility | (0.35xcommercial_db_a(0) + 0.30xcommercial_db_b(0) + 0.25xinvestor_db(0) + 0.10x website(0)) / total weight = 0.00; non-obvious (cut-off 0.30) | inferred | `C0018.21` |
| Assembled from | merged pairs: LIC-0009~REG-0032 (name 100, same ZIP); REG-0032~WEB-0041 (name 100, same ZIP); LIC-0009~WEB-0041 (name 100, same ZIP); ASN-0018~REG-0032 (name 100); ASN-0018~LIC-0009 (name 100); +1 more | strong | `C0018.03` |

Full trail: claims `C0018.01` to `C0018.23` in `evidence_ledger.csv`.

### 2. Lombfield Fire Inspection Services (C0006), Milldale, IL

| Aspect | Evidence | Confidence | Claim |
| --- | --- | --- | --- |
| Fit | A (verified): sector license 'Fire Protection Inspector' | strong | `C0006.08` |
| Size | 70 employees x $136k revenue/employee (inspection) x 16.1% margin (recurring_heavy) = $1.54M median; 95% range $0.75M-$3.17M (sigma 0.37, endpoints) | inferred | `C0006.14` |
| P(EBITDA in band) | log-normal(mu=14.25, sigma=0.37): P($1.00M <= EBITDA <= $5.00M) | inferred | `C0006.16` |
| Visibility | (0.35xcommercial_db_a(0) + 0.30xcommercial_db_b(0) + 0.25xinvestor_db(0) + 0.10x website(0)) / total weight = 0.00; non-obvious (cut-off 0.30) | inferred | `C0006.20` |
| Assembled from | merged pairs: LIC-0018~REG-0003 (name 100, same ZIP); ASN-0006~REG-0003 (name 100); ASN-0006~LIC-0018 (name 100, same phone) | strong | `C0006.03` |

Full trail: claims `C0006.01` to `C0006.22` in `evidence_ledger.csv`.

### 3. Lomblund Fire and Alarm (C0008), Pineford, IL

| Aspect | Evidence | Confidence | Claim |
| --- | --- | --- | --- |
| Fit | A (verified): sector license 'Fire Alarm Contractor' | strong | `C0008.09` |
| Size | 58 employees x $165k revenue/employee (alarm) x 16.1% margin (recurring_heavy) = $1.55M median; 95% range $0.86M-$2.78M (sigma 0.30, endpoints) | inferred | `C0008.15` |
| P(EBITDA in band) | log-normal(mu=14.25, sigma=0.30): P($1.00M <= EBITDA <= $5.00M) | inferred | `C0008.17` |
| Visibility | (0.35xcommercial_db_a(0) + 0.30xcommercial_db_b(1) + 0.25xinvestor_db(0) + 0.10x website(1)) / total weight = 0.40; obvious (cut-off 0.30) | inferred | `C0008.21` |
| Assembled from | merged pairs: LIC-0034~REG-0019 (name 100, same ZIP); ASN-0008~REG-0019 (name 100); REG-0019~WEB-0048 (name 100, same ZIP); ASN-0008~LIC-0034 (name 100); LIC-0034~WEB-0048 (name 100, same ZIP); +1 more | strong | `C0008.03` |

Full trail: claims `C0008.01` to `C0008.23` in `evidence_ledger.csv`.

## Open items

- 17 record pair(s) in `review_queue.csv` await a merge/reject decision.
- 5 in-scope companies could not be sized (no size signal in any record).
- Clusters flagged for low cohesion: none.

## QA against ground truth

Graded against the ground truth the sources supplied. These numbers describe synthetic data only.

| Check | Result |
| --- | --- |
| Entity resolution, pairwise precision | 1.000 |
| Entity resolution, pairwise recall | 0.994 |
| Records / true firms / resolved companies | 167 / 65 / 66 |
| True EBITDA inside the reported 95% range | 0.865 of 37 graded |
| Mean P(in band) vs observed share in band | 0.432 vs 0.378 |
| Brier score of P(in band) | 0.195 |
| Presence flags agreeing with truth | 1.0 of 198 |

## Method notes

EBITDA median = employee-range midpoint x segment revenue per employee x service-mix margin. Uncertainty is log-normal, so each company carries P(EBITDA in band) rather than a point guess.

Obviousness is the weighted share of large commercial databases (and the open web) that already list a company; non-obvious targets are the ones a database-only search misses.

Every number above traces to `evidence_ledger.csv` (Claim, Value, Evidence, Source, Confidence).
