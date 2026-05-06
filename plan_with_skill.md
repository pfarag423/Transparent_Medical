# Insurance vs. Self-Pay Decision Calculator — Project Plan

> **Status:** Research & Planning Phase  
> **Last Updated:** 2026-04-26  
> **Delivery Format:** Claude Code Skill → Excel (.xlsx) output  
> **Primary Market:** Any U.S. hospital market (user-seeded; initially validated against Renton / Greater Seattle, WA)  
> **Target Audience:** General public / healthcare consumers

---

## 1. Problem Statement

Health insurance involves a trade-off that is rarely quantified clearly:

- **With insurance:** You pay monthly premiums, navigate pre-authorization, face claim denials, and still owe deductibles/copays/coinsurance — but are protected from catastrophic costs.
- **Without insurance (self-pay):** You pay discounted cash prices out of pocket, avoid premiums and pre-auth friction, and can sometimes negotiate further — but carry unlimited downside risk.

The central insight driving this application: **hospitals market their self-pay discount as "similar to what insurance companies pay" — but this is materially misleading.** In practice, insurance companies negotiate 50–80% off chargemaster rates, while the typical self-pay discount is only 20–40%. The gap between what an insurer pays and what a self-pay patient pays for the same service can be 2–3x. This skill makes that gap visible and helps users answer:

> **"Given my health, my providers, and my plan options — does insurance actually pay off for me, or am I better off self-paying?"**

---

## 2. Key Research Findings

### 2.1 The "Insurance Discount" Claim Is Misleading

VMC (Valley Medical Center, Renton WA) was used as the reference implementation and illustrates the pattern clearly:

- VMC offers a **flat 30% uninsured discount** off gross chargemaster prices.
- VMC's billing policy describes this as *"a discount similar to the discount taken by our contracted insurance carriers"* — language that appears verbatim in their public billing policy.
- **This framing is inaccurate.** Real insurer negotiated rates at VMC are typically 50–80% off gross, not 30%. Two real examples from the VMC MRF confirm this:

```
Stent Placement (CPT 37238) — outpatient
  Chargemaster (gross):       $30,627.00
  Self-pay (30% off):         $21,438.90
  Kaiser negotiated rate:     $12,622.51  ← 59% off gross
  Min negotiated (any payer): $12,217.11
  Max negotiated (any payer): $44,230.87

Urine Albumin Quantitative (CPT 82043) — outpatient
  Chargemaster (gross):       $60.00
  Self-pay (30% off):         $42.00
  First Choice negotiated:    $16.76      ← 72% off gross
```

The self-pay patient pays **2.5x what an insurer pays** for the same lab test. This is the core financial reality the skill must surface.

### 2.2 Why Existing Hospital Tools Don't Answer This Question

VMC and UW Medicine both offer online cost estimate tools (valleymed.org/estimate, mychart.uwmedicine.org/guestestimates). These tools:

- **Do** apply the self-pay discount when the user selects "self-pay" — they don't show raw chargemaster prices.
- **Do not** show the insurer's actual negotiated rate alongside the self-pay rate for comparison.
- **Have no public API** — they are rendered web UIs with no exposed endpoints. The MyChart-based tool is a server-rendered session UI; there are no REST or GraphQL endpoints available for third-party use.

A user cannot use the hospital's own tools to answer the insurance vs. self-pay question. **That gap is exactly what this skill fills.**

### 2.3 VMC Self-Pay Policy — Full Layered Discount Structure

Understanding the full discount stack at VMC is important for accurate modeling. Each layer is additive and must be modeled separately:

| Discount Layer | Amount | Who qualifies | How to access |
|---|---|---|---|
| Uninsured discount | 30% off gross | All uninsured patients | Applied automatically |
| Prompt-pay discount | Additional % (not publicly stated) | Uninsured patients who pay quickly | Must be requested |
| Financial assistance / charity care | Up to 100% off | Income-qualified patients | Application required; income-based tiers |
| Valley Tax Dividend credit | Up to $3,000 lifetime | King County Hospital District #1 property taxpayers only | Applied after all other payments |

Additional VMC policy notes:
- VMC will **not sell medical debt** to collection agencies.
- VMC will **not deny non-emergency care** due to existing medical debt.
- Payment plans: up to 12 months interest-free (1-855-826-1540).
- Medicaid application assistance offered to uninsured inpatients.

### 2.4 The MRF (Machine-Readable File) — VMC Reference Implementation

Every U.S. hospital is legally required by CMS to publish a Machine-Readable File (MRF) of standard charges. The VMC file was used to validate the data pipeline:

- **Price transparency page:** `valleymed.org/patients--visitors/billing-and-insurance/price-transparency`
- **Direct MRF download URL** (public, no auth required):
  ```
  https://www.valleymed.org/916000986-1649209230_PUBLIC-HOSPITAL-DISTRICT-NO-1-OF-KING-COUNTY-WASHINGTON-dba-VALLEY-MEDICAL-CENTER_standardcharges.csv
  ```
- **File size:** >73MB — requires streaming/chunked parsing, not full load into memory.
- **Last updated:** December 26, 2025 (CMS requires annual updates).
- **Format:** CMS standard tall CSV, v2 schema (mandatory as of January 1, 2025).

### 2.5 MRF Column Schema (CMS v2 Standard)

As of January 1, 2025, CMS mandates a standardized template. This schema should be **consistent across any compliant U.S. hospital**, making a single parser reusable for any provider the user seeds:

| Column | Description |
|---|---|
| `description` | Human-readable service name |
| `code\|1` | Primary billing code value |
| `code\|1\|type` | Code type: `CPT`, `HCPCS`, `LOCAL`, `CDM`, `NDC`, `RC` |
| `code\|2` through `code\|4` | Additional billing codes |
| `setting` | `inpatient` or `outpatient` |
| `drug_unit_of_measurement` | For drug line items only |
| `drug_type_of_measurement` | For drug line items only |
| `standard_charge\|gross` | **Chargemaster (list) price** — before any discount |
| `standard_charge\|discounted_cash` | **Self-pay price** — the discounted cash rate (e.g., gross × 0.70 at VMC) |
| `payer_name` | Insurance payer name (e.g., `KAISER WASHINGTON CONTRACTED [130118]`) |
| `plan_name` | Specific plan (e.g., `KAISER.COMMERCIAL.FACILITY.VMC`) |
| `modifiers` | CPT/HCPCS billing modifiers |
| `standard_charge\|negotiated_dollar` | **Insurer's contracted rate in dollars** — key comparison value |
| `standard_charge\|negotiated_percentage` | Negotiated rate as % of gross |
| `standard_charge\|negotiated_algorithm` | e.g., "case rate", "fee schedule" |
| `estimated_amount` | Estimated allowed amount |
| `standard_charge\|Min` | Lowest negotiated rate across all payers (de-identified) |
| `standard_charge\|Max` | Highest negotiated rate across all payers (de-identified) |
| `standard_charge\|methodology` | `fee schedule`, `case rate`, `percent of total billed charges` |
| `additional_generic_notes` | Free-text notes |
| `median_allowed_amount` | Median allowed amount across payers |
| `tenth_percentile_allowed_amount` | P10 allowed amount |
| `ninetieth_percentile_allowed_amount` | P90 allowed amount |
| `allowed_amount_count` | Number of claims used in percentile calculations |

**Important caveat:** Not all hospitals are fully CMS v2 compliant yet. Some still publish wide CSV, JSON with different nesting, or older schema versions. The parser must include a validation and fallback layer.

### 2.6 Confirmed Payers in VMC MRF (Partial List)
- Kaiser Washington
- Regence Blue Shield
- First Choice Health / Washington Bakers Trust
- *(Full list to be enumerated during first skill run)*

### 2.7 Greater Seattle Area Providers — Reference Validation Set

These four providers were researched during planning and serve as the test cases for the FQDN discovery workflow:

| Provider | FQDN input | Self-Pay Notes |
|---|---|---|
| UW Medicine / Valley Medical Center | `valleymed.org` | 30% uninsured discount; Financial Advocates at 1-855-826-1540 |
| UW Medicine (Harborview, UWMC) | `uwmedicine.org` | 30% self-pay discount; Financial Access Clearance at 206.598.4388 |
| Providence Swedish | `swedish.org` | Nonprofit; charity care available; billing at 206-320-4476 |
| Overlake Medical (now MultiCare) | `overlakehospital.org` | Joined MultiCare Oct 2024; FinancialCounselors@overlakehospital.org |

### 2.8 Third-Party Data Sources

| Source | What it provides | Cost | Commercialization note |
|---|---|---|---|
| **Hospital MRF CSVs** | Gross, self-pay, and payer-specific rates per hospital | Free | No restrictions — mandated public data |
| **Turquoise Health SSP API** | Bundled procedure codes (CPT groupings by event) | Free | Review TOS before production use |
| **Turquoise Health Research Dataset** | Curated shoppable service rates across hospitals | Free | **Non-commercial MSA required** |
| **Turquoise Health Clear Rates** | Full 1B+ record normalized rate database | Paid (enterprise) | Snowflake/S3/SFTP/Trino delivery |
| **CMS Payer MRFs** | What each insurer pays each provider | Free | Enormous files; aggregator recommended |
| **CMS GitHub Schema** | Official MRF data dictionary and templates | Free | No restrictions |
| **WA Healthplanfinder** | WA plan premiums, deductibles, OOP maximums | Free | Public data |

---

## 3. Skill Architecture

### 3.1 Runtime Environment

This is a **Claude Code skill** loaded from `~/.claude/skills/insurance-calculator/`. It runs in the Claude Code local execution environment with:

- Full filesystem read/write access
- Full network access (no domain allowlist restrictions like the claude.ai sandbox)
- Bash tool execution for Python scripts (MRF streaming parser, xlsx generation)
- Persistent local cache between invocations

### 3.2 Skill File Structure

```
~/.claude/skills/insurance-calculator/
├── SKILL.md                  ← skill definition, trigger description, instructions for Claude
├── scripts/
│   ├── discover_mrf.py       ← FQDN → price transparency page → MRF URL
│   ├── parse_mrf.py          ← streaming CSV parser → priority CPT index JSON
│   ├── calculate.py          ← core calculation engine (pure functions)
│   └── generate_xlsx.py      ← Excel workbook builder
├── data/
│   └── priority_cpts.json    ← seed list of priority CPT codes (Section 6)
└── cache/
    └── {fqdn}/
        ├── provider.json      ← cached provider record
        └── procedures.json    ← cached indexed MRF data
```

### 3.3 Output Location

- **Default:** `~/Downloads/insurance-analysis-{YYYY-MM-DD}.xlsx`
- **User-specified:** if the user says "save it to my Desktop" or provides a path during the guided prompt flow, the skill writes there instead.
- Claude confirms the output path at the end of every run.

### 3.4 Local Cache Strategy

MRF files are large (VMC = 73MB) and change at most annually. The skill caches parsed provider data locally to avoid re-downloading on repeat runs:

```
Cache hit logic:
  IF cache/{fqdn}/provider.json exists
  AND provider.json.mrf_last_updated matches current MRF header date
  THEN skip download and parsing, use cached procedures.json
  ELSE re-download, re-parse, update cache
```

Cache lives at `~/.claude/skills/insurance-calculator/cache/{fqdn}/`. Users can clear it manually or the skill can offer a `--refresh` option to force re-parse.

---

## 4. Guided Prompt Flow

The skill is invoked through natural conversation. Claude asks questions progressively, resolving ambiguity before moving to the next input. The user never fills out a form — they just answer questions as they would in a conversation.

### 4.1 Conversation Script (Ordered)

```
STEP 1 — Provider identification (1–3 providers)
  Claude: "Which hospital or medical center do you primarily use?
           You can give me the name or the website address —
           for example, 'Valley Medical' or 'valleymed.org'."

  [Claude resolves name → FQDN if user gives a name rather than URL,
   then runs the MRF discovery pipeline in the background]

  Claude: "Got it — I found Valley Medical Center at valleymed.org.
           Do you use any other hospitals or clinics for your care?
           You can add up to two more, or say 'just the one' to continue."

STEP 2 — Insurance status
  Claude: "Do you currently have health insurance, or are you
           evaluating whether to get it?"

  Branch A (has insurance):
    Claude: "What's your monthly premium?"
    Claude: "What's your annual deductible?"
    Claude: "What's your out-of-pocket maximum?"
    Claude: "What's your coinsurance rate after the deductible —
             for example, do you pay 20% and insurance pays 80%?"
    Claude: "Is your plan an HMO, PPO, or high-deductible plan (HDHP)?
             If you're not sure, I can explain the difference."
    Claude: "Which insurance company and plan name is it?
             For example, 'Kaiser Gold PPO' or 'Regence BlueCross Silver'."

  Branch B (no insurance / evaluating):
    Claude: "Are you comparing self-pay against a specific plan you're
             considering, or do you want me to model a few typical
             plan types for comparison?"

STEP 3 — Utilization (what care they expect to use)
  Claude: "Now let's talk about how much healthcare you typically use.
           I'll ask about a few categories — just give me rough estimates,
           it doesn't need to be exact."

  Claude: "How many times a year do you usually see a primary care doctor?"
  Claude: "How many specialist visits — like a cardiologist, orthopedist,
           or dermatologist — do you have in a typical year?"
  Claude: "Any imaging — MRIs, CT scans, X-rays — in the past year
           or expected this year?"
  Claude: "Any planned procedures or surgeries coming up?
           If so, what are they?"
  Claude: "How many times have you been to an ER or urgent care
           in the past year?"
  Claude: "Any overnight hospital stays, or do you expect any?"

STEP 4 — Friction inputs
  Claude: "A few questions about your experience with insurance
           paperwork, if you have it:
           Have you ever had a claim or procedure denied and had
           to appeal? How much time does dealing with insurance
           typically take you per year?"
  Claude: "What would you say your time is worth per hour —
           this helps put a dollar value on the administrative
           burden of insurance."

STEP 5 — Self-pay modifiers
  Claude: "A couple of quick questions that can affect your
           self-pay costs specifically:
           Are you a King County property taxpayer?
           [If yes → Valley Tax Dividend may apply at VMC]
           Do you know roughly what your household income is?
           [Optional — used to estimate financial assistance eligibility]"

STEP 6 — Output confirmation
  Claude: "I have everything I need. I'll generate your analysis now
           and save it to ~/Downloads/insurance-analysis-{date}.xlsx.
           Would you like to save it somewhere else?"
```

### 4.2 Natural Language Provider Resolution

When a user says "Valley Medical" instead of "valleymed.org", the skill needs to resolve the name to a FQDN. Resolution order:

1. **Exact match** against a small bundled lookup table of common hospital names → FQDNs (the four Seattle-area providers plus any others added over time)
2. **Web search fallback** — search `"{hospital name}" hospital official website` and extract the FQDN from the top result
3. **User confirmation** — always confirm the resolved FQDN with the user before proceeding: *"I found valleymed.org — is that the right Valley Medical Center in Renton?"*

---

## 5. Provider Onboarding Pipeline

For each confirmed FQDN, the skill runs the following automated discovery steps — the same process performed manually during this planning phase:

```
Step 1 — Resolve price transparency page
  Probe common URL patterns:
    /patients--visitors/billing-and-insurance/price-transparency
    /billing/price-transparency
    /patients/billing/price-transparency
    /billing-and-insurance/price-transparency
    /for-patients/billing/pricing
    /about/legal/pricing-transparency
  Fallback: parse sitemap.xml

Step 2 — Extract MRF download link
  Parse page HTML for links where:
    - filename contains "standardcharges"
    - extension is .csv, .json, or .xlsx
    - link text contains "machine readable", "MRF", "standard charges",
      "comprehensive pricing", or "download"
    - CMS filename pattern: {EIN}_{hospital-name}_standardcharges.{ext}

Step 3 — Validate MRF (HEAD request only)
  Confirm: 200 OK, correct Content-Type, note file size
  Extract: last_updated_on from first header rows via partial download

Step 4 — Detect schema version (stream first 5KB)
  v2 (Jan 2025+): tall CSV, pipe-delimited column names  ← handle fully
  v1 (legacy):    wide CSV, payer names as column headers ← best-effort
  Non-standard:   flag to user, attempt column mapping

Step 5 — Stream and index priority procedures
  Chunk-stream the CSV; extract rows matching priority CPT list (Section 6)
  Store per procedure: description, cpt_code, setting, gross_charge,
    discounted_cash, min_negotiated, max_negotiated, median_negotiated,
    payer_name, plan_name, negotiated_dollar, methodology

Step 6 — Compute and confirm self-pay discount rate
  implied_discount = 1 - (discounted_cash / gross_charge)
  Compute across multiple rows; confirm consistency
  (Expected: 0.30 at VMC — i.e., 30% off gross)

Step 7 — Write provider cache
  ~/.claude/skills/insurance-calculator/cache/{fqdn}/provider.json
  ~/.claude/skills/insurance-calculator/cache/{fqdn}/procedures.json
```

**Fallback handling:**

| Failure mode | Behavior |
|---|---|
| Price transparency page not found | Ask user to paste the URL directly |
| MRF link not found on page | Ask user to paste the MRF download URL directly |
| Non-standard schema | Flag to user; attempt best-effort column mapping |
| File too large / slow network | Stream header only; proceed with cached data if available |
| Provider not CMS-compliant | Inform user; offer to use Turquoise Health data as fallback |
| Inconsistent self-pay discount across rows | Use median; flag as approximate in output |

---

## 6. Calculation Engine

All calculation logic lives in `scripts/calculate.py` as pure functions with no side effects. The engine is called by `generate_xlsx.py` to populate the workbook.

### 6.1 Core Variables

```python
# INSURANCE PATH
monthly_premium: float
annual_deductible: float
out_of_pocket_maximum: float
coinsurance_rate: float          # e.g., 0.20
copay_primary_care: float
copay_specialist: float
plan_type: str                   # "HMO" | "PPO" | "HDHP"
payer_name: str                  # matched against MRF payer list

# SELF-PAY PATH
self_pay_discount_rate: float    # extracted from MRF (e.g., 0.30 at VMC)
prompt_pay_discount: float       # optional additional discount
financial_assistance: bool
local_tax_dividend: float        # 0 if not applicable

# UTILIZATION
primary_care_visits: int
specialist_visits: int
imaging_studies: list[str]       # CPT codes
labs: list[str]                  # CPT codes
er_visits: list[str]             # CPT codes by severity
inpatient_days: int
planned_procedures: list[str]    # CPT codes

# FRICTION
hourly_value_of_time: float
pre_auth_hours_per_event: float  # default 1.5
denial_rate: float               # default 0.15
denial_appeal_hours: float       # default 4.0
```

### 6.2 Insurance Path

```python
def calc_insurance_annual_cost(inputs, provider_index):
    premium_cost = inputs.monthly_premium * 12

    patient_responsibility = 0
    remaining_deductible = inputs.annual_deductible

    for service in inputs.all_services:
        negotiated = lookup_negotiated_rate(service.cpt, inputs.payer_name, provider_index)
        # Falls back to standard_charge|Min if payer not in MRF

        if remaining_deductible > 0:
            deductible_applied = min(negotiated, remaining_deductible)
            patient_responsibility += deductible_applied
            remaining_deductible -= deductible_applied
            coinsurance_portion = (negotiated - deductible_applied) * inputs.coinsurance_rate
        else:
            coinsurance_portion = negotiated * inputs.coinsurance_rate

        patient_responsibility += coinsurance_portion

    oop_capped = min(patient_responsibility, inputs.out_of_pocket_maximum)

    pre_auth_events = count_pre_auth_required(inputs.all_services, inputs.plan_type)
    friction = (
        pre_auth_events * inputs.pre_auth_hours_per_event * inputs.hourly_value_of_time
        + pre_auth_events * inputs.denial_rate * inputs.denial_appeal_hours * inputs.hourly_value_of_time
    )

    return premium_cost + oop_capped + friction
```

### 6.3 Self-Pay Path

```python
def calc_selfpay_annual_cost(inputs, provider_index):
    total = 0
    for service in inputs.all_services:
        cash_price = lookup_discounted_cash(service.cpt, provider_index)
        total += cash_price

    total *= (1 - inputs.prompt_pay_discount)
    total -= inputs.local_tax_dividend
    return max(total, 0)
```

### 6.4 Break-Even

```python
def calc_break_even(inputs, provider_index):
    annual_premium = inputs.monthly_premium * 12
    insurer_discount = calc_effective_insurer_discount(inputs.payer_name, provider_index)
    self_pay_discount = provider_index['self_pay_discount_rate']
    discount_gap = insurer_discount - self_pay_discount

    if discount_gap <= 0:
        return None  # self-pay always wins on cost (edge case)

    return annual_premium / discount_gap
    # i.e.: medical spend level at which insurance savings = premium cost
```

### 6.5 Catastrophic Scenario

```python
def calc_catastrophic(inputs, provider_index, event: str):
    # event = one of the high-cost CPT bundles (e.g., "knee_replacement")
    services = CATASTROPHIC_BUNDLES[event]

    insurance_cost = inputs.out_of_pocket_maximum  # always hits OOP max
    selfpay_cost = sum(
        lookup_discounted_cash(cpt, provider_index) for cpt in services
    )

    return {
        'insurance_total': inputs.monthly_premium * 12 + insurance_cost,
        'selfpay_total': selfpay_cost,
        'insurance_protection_value': selfpay_cost - insurance_cost
    }
```

### 6.6 DRG-Based Inpatient (MVP Approximation)

Inpatient stays are priced by DRG (Diagnosis-Related Group), not CPT. No single CPT code maps to a multi-day hospitalization. MVP approach:

- Derive a per-diem rate from inpatient rows in the MRF
- Multiply by user-estimated length of stay
- Flag in the spreadsheet as an approximation
- Full DRG model is a future enhancement

---

## 7. Excel Output Specification

The workbook is generated by `scripts/generate_xlsx.py`. It is self-contained — all formulas, charts, and reference data are embedded. The user does not need to be connected to anything to use it after it's generated.

### 7.1 Workbook Structure

```
Tab 1: Summary Dashboard
Tab 2: Your Inputs
Tab 3: Procedure Cost Comparison
Tab 4: Annual Cost Scenarios
Tab 5: Break-Even Analysis
Tab 6: Catastrophic Scenarios
Tab 7: Pre-Auth Friction Detail
Tab 8: Provider Data (raw MRF extract)
Tab 9: Methodology & Notes
```

### 7.2 Tab Specifications

**Tab 1 — Summary Dashboard**
- Top-line answer: "Based on your inputs, [insurance / self-pay] saves you approximately $X per year"
- Key metrics: annual insurance cost, annual self-pay cost, break-even spend threshold, catastrophic protection value
- Traffic-light indicators: green = clear winner, yellow = close call, red = significant risk either way
- Single chart: stacked bar comparing the two paths across Low / Expected / High utilization scenarios

**Tab 2 — Your Inputs**
- All user-provided values displayed cleanly
- Editable cells highlighted — user can tweak values and see Tab 1/4/5 update via Excel formulas
- Sourced from guided prompt responses; labeled clearly

**Tab 3 — Procedure Cost Comparison**
- Table of all procedures in the user's utilization profile
- Columns: Procedure, CPT Code, Gross Charge, Self-Pay Price, Insurer Min Rate, Insurer Max Rate, Median Rate, Your Est. Insured Cost
- Color-coded: red where self-pay is more than 2x insurer rate, yellow where 1.5–2x, green where close
- If user has multiple providers: one column set per provider for side-by-side comparison

**Tab 4 — Annual Cost Scenarios**
- Three utilization scenarios: Low (half expected), Expected (as entered), High (1.5x expected)
- For each: Insurance Total, Self-Pay Total, Difference
- All values formula-driven from Tab 2 — updating Tab 2 recalculates this tab automatically

**Tab 5 — Break-Even Analysis**
- Break-even annual medical spend (dollar threshold)
- Plain-English explanation of what this means
- Chart: X-axis = annual medical spend, Y-axis = total annual cost; two lines (insurance vs. self-pay) crossing at the break-even point
- Annotation: user's expected spend plotted as a vertical line showing which side of break-even they fall on

**Tab 6 — Catastrophic Scenarios**
- Pre-built event bundles: ER visit, appendectomy, knee replacement, cardiac stent, cancer (chemo), childbirth (vaginal and C-section)
- For each event: self-pay total cost, insurance cost (OOP max + premiums YTD), insurance protection value
- Key message: this is where insurance almost always wins — stated explicitly

**Tab 7 — Pre-Auth Friction Detail**
- Which of the user's procedures require pre-authorization (by plan type)
- Estimated hours and dollar cost of pre-auth burden per procedure
- Total annual friction cost in dollars
- Note: based on industry averages (source to be cited); user-adjustable in Tab 2

**Tab 8 — Provider Data**
- Raw extracted MRF data for the user's provider(s) and their specific procedures
- Columns: Provider, Procedure, CPT, Gross, Self-Pay, Payer, Negotiated Rate, Methodology
- Source URL, MRF last updated date, skill run date
- Intended as an audit trail / reference, not primary reading material

**Tab 9 — Methodology & Notes**
- How chargemaster, self-pay, and negotiated rates relate to each other
- VMC's "similar to insurance discount" claim and why it's misleading (with the real numbers)
- Why the break-even calculation works the way it does
- Limitations: DRG inpatient approximation, pre-auth defaults, financial assistance not modeled for all providers
- Data sources and links

---

## 8. Priority Procedure List (Seed Dataset)

Defined in `data/priority_cpts.json`. Extracted from each provider's MRF during the seeding pipeline.

### Routine / Outpatient
| Category | Procedure | CPT | Pre-auth required |
|---|---|---|---|
| Primary care | Office visit, new patient (moderate) | 99204 | No |
| Primary care | Office visit, established (moderate) | 99214 | No |
| Urgent care | Urgent care visit | 99213 | No |
| Lab | Comprehensive metabolic panel | 80053 | No |
| Lab | Complete blood count | 85025 | No |
| Lab | Lipid panel | 80061 | No |
| Lab | Urine albumin quantitative | 82043 | No |
| Lab | HbA1c | 83036 | No |
| Imaging | X-ray, chest (2 views) | 71046 | No |
| Imaging | MRI brain without contrast | 70553 | HMO yes / PPO sometimes |
| Imaging | MRI lumbar spine | 72148 | HMO yes / PPO sometimes |
| Imaging | CT abdomen/pelvis with contrast | 74177 | HMO yes / PPO sometimes |
| Imaging | Ultrasound, abdomen | 76700 | Sometimes |
| Imaging | Mammogram, diagnostic | 77066 | No |
| Preventive | Colonoscopy, screening | 45378 | Sometimes |
| Preventive | Annual wellness visit | G0439 | No |

### Emergency / Acute
| Category | Procedure | CPT | Pre-auth required |
|---|---|---|---|
| ER | ER visit, moderate complexity | 99284 | No (retroactive review) |
| ER | ER visit, high complexity | 99285 | No (retroactive review) |
| Surgery | Appendectomy, laparoscopic | 44950 | Emergency: No / Elective: Yes |
| Surgery | Cholecystectomy, laparoscopic | 47562 | Yes |
| Cardiac | EKG | 93000 | No |
| Cardiac | Echocardiogram | 93306 | Yes |

### High-Cost / Catastrophic
| Category | Procedure | CPT | Pre-auth required |
|---|---|---|---|
| Orthopedic | Knee replacement (total) | 27447 | Yes |
| Orthopedic | Hip replacement (total) | 27130 | Yes |
| Cardiac | Coronary angioplasty / stent | 37238 | Yes |
| Oncology | Chemotherapy administration | 96413 | Yes |
| Delivery | Vaginal delivery | 59400 | Yes |
| Delivery | Cesarean delivery | 59510 | Yes |
| Inpatient | Hospital admission (DRG-based) | N/A | Yes (non-emergency) |

---

## 9. Pre-Authorization Friction Model

**Default values** *(flagged as industry estimates — need citation before v1; candidate sources: AHIP Annual Prior Auth Survey, KFF Health System Tracker, AMA Prior Auth Survey)*:
- ~15% of prior authorization requests are initially denied
- Average patient time per auth request: 1.5 hours (range: 1–3 hrs)
- Average time for a successful appeal: 4 hours (range: 3–5 hrs)
- ~40% of denied claims that are appealed are eventually approved

**Pre-auth burden by plan type:**
- HMO: highest (referrals for all specialists; pre-auth for most imaging)
- PPO: moderate (pre-auth for major procedures and elective surgery)
- HDHP: lower pre-auth burden but higher OOP exposure before deductible

All defaults are surfaced in Tab 2 of the workbook as editable cells.

---

## 10. Open Questions / Decisions Needed

| # | Question | Notes |
|---|---|---|
| 1 | Premium data source outside WA | WA Healthplanfinder works for WA users. For other states, fall back to user manual entry for v1. |
| 2 | Natural language → FQDN resolution | Small bundled lookup table + web search fallback. Need to decide lookup table scope at launch. |
| 3 | Non-CMS-compliant MRF handling | Schema detection defined. Need to specify what best-effort column mapping looks like in code. |
| 4 | Turquoise Health MSA | Free research dataset requires non-commercial agreement. If skill is distributed commercially, need paid Clear Rates tier. |
| 5 | Full DRG inpatient model | Per-diem approximation for MVP. Full DRG lookup in Phase 2. |
| 6 | Scope: dental / vision / mental health | Out of scope for v1. |
| 7 | Financial assistance income tiers | VMC charity care tier details not yet fully documented. Pull from each provider's financial assistance policy page during seeding. |
| 8 | Pre-auth default citations | 15% denial rate and time estimates need published source before v1 ships. |
| 9 | SKILL.md trigger language | Need to write the description that tells Claude when to invoke this skill vs. answer directly. |
| 10 | Cache invalidation UX | How does the user know cached MRF data is stale? Skill should surface mrf_last_updated date at start of each run and offer refresh. |

---

## 11. External Links & References

| Resource | URL |
|---|---|
| **VMC — Price Transparency Page** | https://www.valleymed.org/patients--visitors/billing-and-insurance/price-transparency |
| **VMC — MRF CSV (direct download)** | https://www.valleymed.org/916000986-1649209230_PUBLIC-HOSPITAL-DISTRICT-NO-1-OF-KING-COUNTY-WASHINGTON-dba-VALLEY-MEDICAL-CENTER_standardcharges.csv |
| **VMC — Cost Estimator Tool** | https://www.valleymed.org/estimate/ |
| **VMC — Billing & Collection Policy** | https://www.valleymed.org/patients--visitors/billing-and-insurance/financial-help--options/vmc-billing--collection-policy |
| **VMC — Financial Help & Options** | https://www.valleymed.org/patients--visitors/billing-and-insurance/financial-help--options |
| **UW Medicine — Price Transparency** | https://www.uwmedicine.org/patient-resources/billing-and-insurance/price-transparency |
| **UW Medicine — Shopper Estimate FAQ** | https://www.uwmedicine.org/sites/stevie/files/2022-11/ShopperEstimateFAQ%2020221014_a11y%20(1).pdf |
| **Providence/Swedish — Price Transparency** | https://www.providence.org/billing-support/pricing-transparency |
| **Overlake — Cost Estimate** | https://www.overlakehospital.org/visit/billing-insurance/healthcare-costs |
| **Turquoise Health — Free Research Data** | https://turquoise.health/researchers |
| **Turquoise Health — SSP API (free)** | https://turquoise.health/products/ssps |
| **Turquoise Health — Provider Lookup** | https://turquoise.health/providers |
| **CMS MRF Schema & GitHub Templates** | https://github.com/CMSgov/hospital-price-transparency |
| **WA Healthplanfinder** | https://www.wahealthplanfinder.org |
| **WSHA Hospital Pricing** | https://www.wsha.org/for-patients/hospital-pricing |

---

## 12. Suggested Next Steps (In Order)

1. **Write `SKILL.md`** — the skill definition file that tells Claude Code when and how to invoke the skill. Include trigger description, input summary, output description, and reference to the guided prompt flow.

2. **Write `scripts/discover_mrf.py`** — FQDN → price transparency page → MRF download URL. Test against all four Seattle-area reference providers.

3. **Write `scripts/parse_mrf.py`** — schema detection, streaming chunk parser, CPT code extraction, self-pay discount rate computation, cache write. VMC's 73MB CSV is the primary test case.

4. **Write `scripts/calculate.py`** — pure calculation functions (insurance path, self-pay path, break-even, catastrophic). Unit-testable independently of MRF data.

5. **Write `scripts/generate_xlsx.py`** — workbook builder per the Tab 9 specification above. Reference the xlsx skill pattern at `/mnt/skills/public/xlsx/SKILL.md`.

6. **Populate `data/priority_cpts.json`** — the seed CPT list from Section 8, structured for lookup by the parser.

7. **Validate end-to-end** — run the full skill against `valleymed.org` with a sample user profile; verify the xlsx output matches expected calculations.

8. **Expand validation set** — run against `swedish.org`, `overlakehospital.org`, `uwmedicine.org` to confirm the discovery pipeline and parser handle schema variations correctly.

9. **Source pre-auth default citations** — AHIP, KFF, or AMA prior auth survey data to back the default values in Section 9.

10. **Write the natural language → FQDN lookup table** — start with the four Seattle-area providers; define the web search fallback logic for unknown provider names.
