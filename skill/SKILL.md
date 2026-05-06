---
name: insurance-calculator
description: >
  Invoke this skill when the user wants to compare the cost of having health
  insurance vs. paying for medical care out of pocket (self-pay). Triggers
  include phrases like: "is insurance worth it", "should I drop my insurance",
  "compare self-pay vs insurance", "how much would I save without insurance",
  "is my plan worth the premium", or any request to analyze healthcare costs
  relative to an insurance plan. The skill guides the user through a
  conversation to collect their provider(s), insurance plan details, and
  expected healthcare usage, then produces a downloadable Excel workbook with
  a full cost comparison, break-even analysis, and catastrophic scenario
  modeling. Output goes to ~/Downloads/ unless the user specifies otherwise.
---

# Insurance vs. Self-Pay Calculator Skill

## What This Skill Does

Guides the user through a structured conversation to collect:
1. Their medical provider(s) (by name or website, e.g. "valleymed.org")
2. Their insurance plan details (or plans they are considering)
3. Their expected annual healthcare utilization
4. Their time cost and pre-auth friction inputs

Then:
- Automatically discovers and stream-parses the hospital's CMS
  Machine-Readable File (MRF) to extract real gross charges, self-pay
  (discounted cash) prices, and insurer negotiated rates
- Runs the insurance vs. self-pay calculation engine
- Generates a formatted Excel workbook saved to ~/Downloads/

## How to Run This Skill

Execute each script in order using the bash tool from the skill directory:

```
~/.claude/skills/insurance-calculator/
```

### Step 1 — Guided conversation
Conduct the guided prompt flow defined in Section 3 of this file.
Collect all inputs and store them as a Python dict called `user_inputs`.

### Step 2 — Discover and parse MRF for each provider
```bash
python scripts/discover_mrf.py <fqdn>
# Outputs: cache/<fqdn>/provider.json

python scripts/parse_mrf.py <fqdn>
# Outputs: cache/<fqdn>/procedures.json
```

### Step 3 — Generate the Excel workbook
```bash
python scripts/generate_xlsx.py '<user_inputs_json>' <fqdn> [output_path]
# Default output: ~/Downloads/insurance-analysis-YYYY-MM-DD.xlsx
```

### Step 4 — Recalculate formulas
```bash
python scripts/recalc.py ~/Downloads/insurance-analysis-YYYY-MM-DD.xlsx
```

### Step 5 — Confirm output to user
Tell the user where the file was saved and summarize the top-line result
(insurance vs. self-pay annual cost difference and break-even threshold).

---

## Section 1 — Directory Structure

```
~/.claude/skills/insurance-calculator/
├── SKILL.md                    ← this file
├── scripts/
│   ├── discover_mrf.py         ← FQDN → MRF download URL → provider.json
│   ├── parse_mrf.py            ← streaming CSV parser → procedures.json
│   ├── calculate.py            ← pure calculation functions
│   └── generate_xlsx.py        ← Excel workbook builder
├── data/
│   └── priority_cpts.json      ← seed CPT code list with pre-auth flags
└── cache/
    └── {fqdn}/
        ├── provider.json        ← cached provider metadata
        └── procedures.json      ← cached indexed MRF data
```

---

## Section 2 — Cache Behavior

MRF files are large (the VMC reference file is >73MB) and updated at most
annually by hospitals. The skill caches parsed data locally per provider.

Cache hit logic (checked at the start of parse_mrf.py):
- If `cache/{fqdn}/provider.json` exists AND `mrf_last_updated` in that file
  matches the date in the current MRF header → skip download, use cache
- Otherwise → re-download, re-parse, overwrite cache

At the start of each run, surface the `mrf_last_updated` date to the user:
  "Using cached data for valleymed.org — MRF last updated December 26, 2025.
   Say 'refresh' to re-download the latest data."

---

## Section 3 — Guided Prompt Flow

Conduct this conversation before running any scripts. Collect all values
into a `user_inputs` dict. Every question should feel natural — do not
present this as a form. Ask one topic at a time.

### 3.1 Provider Identification (repeat up to 3x)

```
"Which hospital or medical center do you primarily use?
 You can give me the name or the website — for example,
 'Valley Medical' or 'valleymed.org'."
```

- If user gives a name (not a URL): resolve to FQDN using the lookup
  table in Section 5, then confirm: "I found Valley Medical Center at
  valleymed.org — is that right?"
- If user gives a URL: extract base FQDN, strip www. and path.
- After first provider: "Do you use any other hospitals or clinics?
  You can add up to two more, or say 'just the one' to continue."

Store as: `user_inputs['providers'] = ['valleymed.org', ...]`

### 3.2 Insurance Status

```
"Do you currently have health insurance, or are you figuring out
 whether to get it?"
```

**Branch A — Has insurance:**
```
"What's your monthly premium?"
→ monthly_premium: float

"What's your annual deductible?"
→ annual_deductible: float

"What's your out-of-pocket maximum for the year?"
→ out_of_pocket_maximum: float

"After you hit your deductible, what percentage do you pay?
 For example, 20% means you pay 20% and insurance pays 80%."
→ coinsurance_rate: float (store as decimal, e.g. 0.20)

"What's your copay for a primary care visit? And for a specialist?"
→ copay_primary_care: float
→ copay_specialist: float

"Is your plan an HMO, PPO, or high-deductible plan (HDHP)?
 If you're not sure, just say so and I can explain the difference."
→ plan_type: str  # "HMO" | "PPO" | "HDHP" | "unknown"

"Which insurance company and plan is it? For example,
 'Kaiser Gold PPO' or 'Regence BlueCross Silver'."
→ payer_name: str
→ plan_name: str
```

**Branch B — No insurance / evaluating:**
```
"Are you comparing self-pay against a specific plan you're
 considering, or would you like me to model a few typical
 plan types so you can see the range?"
```
- If specific plan: collect same fields as Branch A
- If model typical plans: set flag `use_preset_plans: true`
  and model Bronze HDHP / Silver PPO / Gold HMO presets

### 3.3 Utilization

```
"Now let's talk about how much healthcare you typically use in a year.
 Rough estimates are fine."

"How many times do you see a primary care doctor in a typical year?"
→ primary_care_visits: int

"How many specialist visits — like a cardiologist, orthopedist,
 or dermatologist?"
→ specialist_visits: int

"Any imaging studies — MRIs, CT scans, X-rays — in the past year
 or expected this year? If so, roughly what kind?"
→ imaging_studies: list[str]  # CPT codes resolved from user description

"Any planned procedures or surgeries coming up?"
→ planned_procedures: list[str]  # CPT codes

"How many ER or urgent care visits in the past year?"
→ er_visits: int
→ er_severity: str  # "minor" | "moderate" | "major"

"Any overnight hospital stays, or do you expect any?"
→ inpatient_days: int
```

### 3.4 Friction Inputs

```
"A couple of questions about the administrative side of insurance —
 just give me your best estimate.

 Have you had claims denied and needed to appeal? About how many
 hours a year do you spend on insurance paperwork and phone calls?"
→ pre_auth_hours_per_event: float  # default 1.5 if user unsure
→ denial_rate: float               # default 0.15 if user unsure

"What would you say your time is worth per hour? This helps put
 a dollar value on the hassle of dealing with insurance."
→ hourly_value_of_time: float
```

### 3.5 Self-Pay Modifiers

```
"Two quick questions that can affect your self-pay costs:

 Are you a property taxpayer in King County, WA?
 [If yes and provider is VMC → Valley Tax Dividend may apply]"
→ local_tax_dividend_eligible: bool

"Do you know roughly your household income bracket?
 This is optional — I use it to estimate whether you might
 qualify for financial assistance or charity care."
→ income_bracket: str  # "under_30k" | "30k_60k" | "60k_100k" | "over_100k" | "skip"
```

### 3.6 Output Confirmation

```
"I have everything I need. I'll run the analysis now and save your
 workbook to ~/Downloads/insurance-analysis-{date}.xlsx.
 Would you like to save it somewhere else?"
```

---

## Section 4 — Calculation Summary

All math lives in `scripts/calculate.py`. Summary for reference:

### Insurance Annual Cost
```
(monthly_premium × 12)
+ min(sum(patient_responsibility_per_service), out_of_pocket_maximum)
+ pre_auth_friction_cost

where:
  patient_responsibility = negotiated_rate up to deductible,
                           then negotiated_rate × coinsurance_rate
  negotiated_rate = MRF standard_charge|negotiated_dollar for user's payer
                    fallback: standard_charge|Min
  pre_auth_friction = pre_auth_events × hours × hourly_rate
                    + pre_auth_events × denial_rate × appeal_hours × hourly_rate
```

### Self-Pay Annual Cost
```
sum(standard_charge|discounted_cash per service)
× (1 - prompt_pay_discount)
- local_tax_dividend_credit
```

### Break-Even Annual Medical Spend
```
(monthly_premium × 12) / (insurer_discount_rate - self_pay_discount_rate)

Example (VMC + Kaiser):
  Kaiser discount ≈ 59% off gross
  VMC self-pay discount = 30% off gross
  Gap = 29 percentage points
  Premium = $5,400/yr → break-even = $5,400 / 0.29 = ~$18,621/yr
```

### Catastrophic Scenario
```
Insurance: monthly_premium × 12 + out_of_pocket_maximum (always hits cap)
Self-pay:  sum(discounted_cash_price for all services in event bundle)
Protection value: self-pay total - OOP max
```

---

## Section 5 — Provider Name Lookup Table

Used to resolve plain-language provider names to FQDNs.
Extend this table as more providers are validated.

```python
PROVIDER_LOOKUP = {
    # Seattle / Puget Sound
    "valley medical": "valleymed.org",
    "valley medical center": "valleymed.org",
    "vmc": "valleymed.org",
    "uw medicine valley": "valleymed.org",
    "swedish": "swedish.org",
    "providence swedish": "swedish.org",
    "overlake": "overlakehospital.org",
    "overlake medical": "overlakehospital.org",
    "uw medicine": "uwmedicine.org",
    "harborview": "uwmedicine.org",
    "uw medical center": "uwmedicine.org",
    "multicare": "multicare.org",
    "multicare auburn": "multicare.org",
    # Fallback: web search for "{name} hospital official website"
}
```

If the name is not in the lookup table, perform a web search:
`"{provider name}" hospital official website`
Extract the FQDN from the top result and confirm with the user.

---

## Section 6 — MRF Discovery URL Patterns

`discover_mrf.py` probes these paths in order on the provider's domain:

```python
TRANSPARENCY_PATHS = [
    "/patients--visitors/billing-and-insurance/price-transparency",
    "/patients/billing-and-insurance/price-transparency",
    "/billing/price-transparency",
    "/billing-and-insurance/price-transparency",
    "/patients/billing/price-transparency",
    "/for-patients/billing/pricing",
    "/about/legal/pricing-transparency",
    "/patients-visitors/billing-and-insurance/price-transparency",
    "/patient-resources/billing-and-insurance/price-transparency",
    "/billing-support/pricing-transparency",
    "/visit/billing-insurance/healthcare-costs",
]
# Fallback: fetch sitemap.xml and search for transparency-related URLs
```

MRF link detection — look for `<a>` tags where:
- `href` filename contains `standardcharges`
- `href` ends in `.csv`, `.json`, or `.xlsx`
- OR link text (case-insensitive) contains any of:
  `machine readable`, `mrf`, `standard charges`,
  `comprehensive pricing`, `download`, `chargemaster`

---

## Section 7 — Excel Workbook Tab Reference

| Tab | Name | Contents |
|-----|------|----------|
| 1 | Summary Dashboard | Top-line answer, key metrics, traffic lights, main chart |
| 2 | Your Inputs | All user inputs as editable blue cells; drives all other tabs |
| 3 | Procedure Cost Comparison | Per-CPT: gross, self-pay, insurer min/max, your insured cost |
| 4 | Annual Cost Scenarios | Low / Expected / High utilization × insurance vs. self-pay |
| 5 | Break-Even Analysis | Break-even spend threshold + chart with user's spend plotted |
| 6 | Catastrophic Scenarios | ER, appendectomy, knee replacement, stent, chemo, childbirth |
| 7 | Pre-Auth Friction Detail | Which procedures need pre-auth, time cost, total friction $ |
| 8 | Provider Data | Raw MRF extract — audit trail, source URLs, dates |
| 9 | Methodology & Notes | How rates work, why the "insurance discount" claim is misleading |

Color coding follows industry standard (from xlsx SKILL.md):
- Blue text: hardcoded inputs (user-editable)
- Black text: all formulas and calculations
- Green text: cross-sheet references
- Yellow background: key assumptions needing attention

---

## Section 8 — Known Limitations (surface in Tab 9)

- **Inpatient DRG pricing:** Overnight hospitalizations are priced by
  Diagnosis-Related Group, not CPT. The skill uses a per-diem approximation
  from inpatient MRF rows × estimated length of stay. Flag as approximate.

- **Pre-auth defaults:** Denial rate (15%), time per auth (1.5hrs), and
  appeal time (4hrs) are industry estimates. Source: to be cited from AHIP /
  KFF / AMA prior auth surveys before v1 release.

- **Self-pay discount rate:** Extracted from the MRF by computing
  `1 - (discounted_cash / gross)` across multiple rows. At VMC this is
  consistently 30%. May vary at other providers.

- **Financial assistance:** Not fully modeled for all providers. The skill
  flags eligibility based on income bracket input but cannot guarantee
  accuracy of charity care tiers without provider-specific policy data.

- **MRF compliance:** Not all hospitals are fully CMS v2 compliant.
  Non-standard schemas are handled on a best-effort basis.

- **Premium data:** For WA state users, WA Healthplanfinder provides
  accurate plan premium data. For other states, the user must enter premiums
  manually — the skill does not yet auto-fetch out-of-state plan data.
