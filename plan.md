# Insurance vs. Self-Pay Decision Calculator — Project Plan

> **Status:** Research & Planning Phase  
> **Last Updated:** 2026-04-26  
> **Primary Market:** Any U.S. hospital market (user-seeded; initially validated against Renton / Greater Seattle, WA)  
> **Target Audience:** General public / healthcare consumers

---

## 1. Problem Statement

Health insurance involves a trade-off that is rarely quantified clearly:

- **With insurance:** You pay monthly premiums, navigate pre-authorization, face claim denials, and still owe deductibles/copays/coinsurance — but are protected from catastrophic costs.
- **Without insurance (self-pay):** You pay discounted cash prices out of pocket, avoid premiums and pre-auth friction, and can sometimes negotiate further — but carry unlimited downside risk.

The central insight driving this application: **hospitals market their self-pay discount as "similar to what insurance companies pay" — but this is materially misleading.** In practice, insurance companies negotiate 50–80% off chargemaster rates, while the typical self-pay discount is only 20–40%. The gap between what an insurer pays and what a self-pay patient pays for the same service can be 2–3x. This app makes that gap visible and helps users answer:

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

The self-pay patient pays **2.5x what an insurer pays** for the same lab test. This is the core financial reality the application must surface.

### 2.2 Why Existing Hospital Tools Don't Answer This Question

VMC and UW Medicine both offer online cost estimate tools (valleymed.org/estimate, mychart.uwmedicine.org/guestestimates). These tools:

- **Do** apply the self-pay discount when the user selects "self-pay" — they don't show raw chargemaster prices.
- **Do not** show the insurer's actual negotiated rate alongside the self-pay rate for comparison.
- **Have no public API** — they are rendered web UIs with no exposed endpoints for programmatic access. The MyChart-based tool is a server-rendered session UI; there are no REST or GraphQL endpoints available for third-party use.

This means a user cannot use the hospital's own tools to answer the insurance vs. self-pay question. **That gap is exactly what this application fills.**

### 2.3 VMC Self-Pay Policy — Full Layered Discount Structure

Understanding the full discount stack at VMC is important for accurate modeling. Each layer is additive and must be modeled separately:

| Discount Layer | Amount | Who qualifies | How to access |
|---|---|---|---|
| Uninsured discount | 30% off gross | All uninsured patients | Applied automatically |
| Prompt-pay discount | Additional % (TBD — not publicly stated) | Uninsured patients who pay quickly | Must be requested |
| Financial assistance / charity care | Up to 100% off | Income-qualified patients | Application required; income-based tiers |
| Valley Tax Dividend credit | Up to $3,000 lifetime | King County Hospital District #1 property taxpayers only | Applied after all other payments |

Additional VMC policy notes relevant to the application:
- VMC will **not sell medical debt** to collection agencies.
- VMC will **not deny non-emergency care** due to existing medical debt.
- Payment plans: up to 12 months interest-free through Patient Financial Services (1-855-826-1540).
- Medicaid application assistance is offered to uninsured inpatients.

### 2.4 The MRF (Machine-Readable File) — VMC Reference Implementation

Every U.S. hospital is legally required by CMS to publish a Machine-Readable File (MRF) of their standard charges. The VMC file was used to validate the data pipeline approach:

- **Price transparency page:** `valleymed.org/patients--visitors/billing-and-insurance/price-transparency`
- **Direct MRF download URL** (public, no authentication required):
  ```
  https://www.valleymed.org/916000986-1649209230_PUBLIC-HOSPITAL-DISTRICT-NO-1-OF-KING-COUNTY-WASHINGTON-dba-VALLEY-MEDICAL-CENTER_standardcharges.csv
  ```
- **File size:** >73MB — cannot be loaded into memory naively; requires streaming or chunked parsing.
- **Last updated:** December 26, 2025 (CMS requires annual updates at minimum).
- **Format:** CMS standard tall CSV, v2 schema (mandatory as of January 1, 2025).

### 2.5 MRF Column Schema (CMS v2 Standard)

As of January 1, 2025, CMS mandates a standardized template for all hospital MRFs. This means the schema documented below from VMC should be **consistent across any compliant U.S. hospital** — making a single parser reusable for any provider the user seeds into the application.

| Column | Description |
|---|---|
| `description` | Human-readable service name |
| `code\|1` | Primary billing code value |
| `code\|1\|type` | Code type: `CPT`, `HCPCS`, `LOCAL`, `CDM`, `NDC`, `RC` |
| `code\|2` through `code\|4` | Additional billing codes (a procedure often has multiple) |
| `setting` | `inpatient` or `outpatient` |
| `drug_unit_of_measurement` | For drug line items only |
| `drug_type_of_measurement` | For drug line items only |
| `standard_charge\|gross` | **Chargemaster (list) price** — before any discount |
| `standard_charge\|discounted_cash` | **Self-pay price** — the discounted cash rate (e.g., gross × 0.70 at VMC) |
| `payer_name` | Insurance payer name (e.g., `KAISER WASHINGTON CONTRACTED [130118]`) |
| `plan_name` | Specific plan (e.g., `KAISER.COMMERCIAL.FACILITY.VMC`) |
| `modifiers` | CPT/HCPCS billing modifiers |
| `standard_charge\|negotiated_dollar` | **Insurer's contracted rate in dollars** — the key comparison value |
| `standard_charge\|negotiated_percentage` | Negotiated rate as % of gross |
| `standard_charge\|negotiated_algorithm` | Algorithm description (e.g., "case rate", "fee schedule") |
| `estimated_amount` | Estimated allowed amount |
| `standard_charge\|Min` | Lowest negotiated rate across all payers (de-identified) |
| `standard_charge\|Max` | Highest negotiated rate across all payers (de-identified) |
| `standard_charge\|methodology` | `fee schedule`, `case rate`, `percent of total billed charges` |
| `additional_generic_notes` | Free-text notes |
| `median_allowed_amount` | Median allowed amount across payers |
| `tenth_percentile_allowed_amount` | P10 allowed amount |
| `ninetieth_percentile_allowed_amount` | P90 allowed amount |
| `allowed_amount_count` | Number of claims used in percentile calculations |

**Important caveat:** Not all hospitals are fully compliant with the CMS v2 standard yet. Some still publish in non-standard formats (wide CSV instead of tall, JSON with different nesting, older schema versions). The MRF discovery and parsing pipeline must include a **validation and fallback layer** to handle non-standard files gracefully rather than failing silently.

### 2.6 Confirmed Payers in VMC MRF (Partial List)
- Kaiser Washington
- Regence Blue Shield
- First Choice Health / Washington Bakers Trust
- *(Full list to be enumerated during MRF parse in Phase 1)*

### 2.7 Greater Seattle Area Providers — Research Summary

The following providers were researched during initial planning and serve as the reference validation set for the FQDN-based provider seeding flow. Each follows the same MRF pattern:

| Provider | FQDN input | Self-Pay Notes |
|---|---|---|
| UW Medicine / Valley Medical Center | `valleymed.org` | 30% uninsured discount; Financial Advocates at 1-855-826-1540 |
| UW Medicine (Harborview, UWMC) | `uwmedicine.org` | 30% self-pay discount; Financial Access Clearance Team at 206.598.4388 |
| Providence Swedish | `swedish.org` | Nonprofit; charity care available; billing at 206-320-4476 |
| Overlake Medical (now MultiCare) | `overlakehospital.org` | Joined MultiCare Oct 2024; estimate via FinancialCounselors@overlakehospital.org |

### 2.8 Third-Party Data Sources

| Source | What it provides | Cost | Commercialization note |
|---|---|---|---|
| **Hospital MRF CSVs** | Gross, self-pay, and payer-specific rates per hospital | Free | No restrictions — mandated public data |
| **Turquoise Health SSP API** | Bundled procedure codes (CPT groupings by event) | Free | Review TOS before production use |
| **Turquoise Health Research Dataset** | Curated shoppable service rates across hospitals | Free | **Non-commercial MSA required** — paid tier needed for commercial products |
| **Turquoise Health Clear Rates** | Full 1B+ record normalized rate database | Paid (enterprise) | Snowflake/S3/SFTP/Trino delivery |
| **CMS Payer MRFs** | What each insurer pays each provider | Free | Enormous files; aggregator recommended |
| **CMS GitHub Schema** | Official MRF data dictionary and templates | Free | No restrictions |
| **WA Healthplanfinder** | WA plan premiums, deductibles, OOP maximums | Free | Public data |

---

## 3. Provider Seeding Architecture

### 3.1 Core Design Decision

Rather than hardcoding specific hospitals, the application is built around **user-seeded providers**. Each user enters 1–3 medical providers they actually use, identified by the **base FQDN of the provider's website** — for example:

```
valleymed.org
swedish.org
overlakehospital.org
```

This mirrors how users naturally identify their hospital (the same way a user would reference a provider at the start of a conversation), gives the application a deterministic unambiguous starting point, and makes the app nationally applicable without any hardcoded provider list.

### 3.2 Provider Onboarding Workflow

For each FQDN entered, the application executes the following automated discovery pipeline — the same steps performed manually during this planning phase:

```
Step 1 — Resolve the price transparency page
  Input:  base FQDN (e.g., "valleymed.org")
  Action: probe common URL patterns for hospital price transparency pages:
          /patients--visitors/billing-and-insurance/price-transparency
          /billing/price-transparency
          /patients/billing/price-transparency
          /billing-and-insurance/price-transparency
          /for-patients/billing/pricing
          /about/legal/pricing-transparency
          (+ sitemap.xml fallback if none match)
  Output: confirmed price transparency page URL

Step 2 — Locate the MRF download link
  Input:  price transparency page URL
  Action: parse page HTML for links matching known MRF patterns:
          - filename contains "standardcharges"
          - filename ends in .csv, .json, or .xlsx
          - link text contains "machine readable", "MRF", "standard charges",
            "comprehensive pricing", or "download"
          - CMS standard filename: {EIN}_{hospital-name}_standardcharges.{ext}
  Output: direct MRF download URL

Step 3 — Validate the MRF
  Input:  MRF download URL
  Action: fetch headers only (HEAD request) to confirm:
          - File accessible (200 OK)
          - Content-Type is text/csv, application/json, or xlsx equivalent
          - File size (flag if <1MB = likely incomplete; note if >100MB = streaming required)
          - Extract last_updated_on from file header rows
  Output: validated MRF URL + file metadata

Step 4 — Detect schema version
  Input:  first 5KB of MRF (stream header rows only)
  Action: identify CMS template version from column headers:
          - v2 (current, Jan 2025+): tall CSV with pipe-delimited column names
          - v1 (legacy): wide CSV with payer names as column headers
          - Non-standard: flag for fallback handling
  Output: schema version + column map

Step 5 — Stream and index priority procedures
  Input:  MRF URL + schema version + priority CPT code list (Section 5)
  Action: stream-parse file in chunks; extract rows matching priority CPT codes;
          store per procedure:
            description, cpt_code, setting,
            gross_charge, discounted_cash,
            min_negotiated, max_negotiated, median_negotiated,
            payer_name, plan_name, negotiated_dollar, methodology
  Output: provider-keyed JSON index of priority procedures

Step 6 — Extract and confirm self-pay discount rate
  Input:  discounted_cash and gross values from Step 5
  Action: compute implied_discount = 1 - (discounted_cash / gross_charge)
          across multiple rows; confirm consistency
          (e.g., should consistently equal 0.30 at VMC)
  Output: confirmed self_pay_discount_rate for this provider

Step 7 — Store provider record
  {
    fqdn: "valleymed.org",
    hospital_name: "Valley Medical Center",
    address: "400 S. 43rd Street, Renton, WA 98055",
    mrf_url: "https://..._standardcharges.csv",
    mrf_last_updated: "2025-12-26",
    schema_version: "v2",
    self_pay_discount_rate: 0.30,
    procedures: { ...indexed by CPT code... },
    payers_available: ["Kaiser Washington", "Regence Blue Shield", ...]
  }
```

### 3.3 Fallback Handling

| Failure mode | Fallback behavior |
|---|---|
| Price transparency page not found via URL probing | Prompt user to manually paste the page URL |
| MRF link not found on price transparency page | Prompt user to manually paste the MRF download URL |
| Non-standard schema (pre-CMS v2) | Flag to user; attempt best-effort column mapping; allow manual correction |
| File too large to stream in reasonable time | Extract headers only; queue background job; notify user when ready |
| Provider not CMS-compliant (no MRF published) | Inform user; offer Turquoise Health data as fallback for that provider |
| Inconsistent self-pay discount rate across rows | Surface the range to user; use median; flag as approximate |

### 3.4 Multi-Provider Comparison

- Users seed **1 to 3 providers** per session/profile.
- All calculation scenarios run against each provider's indexed data independently.
- Side-by-side comparison: for the same CPT code, show each provider's self-pay price, insurer min/max negotiated range, and the gap between self-pay and best insurer rate.
- This surfaces cases where switching providers for a planned procedure could save money even on a self-pay basis.

---

## 4. Calculation Model

### 4.1 Core Variables (User Inputs)

```
INSURANCE PATH
├── monthly_premium            (user enters from their plan documents)
├── annual_deductible
├── out_of_pocket_maximum
├── coinsurance_rate           (e.g., 20% after deductible)
├── copay_primary_care
├── copay_specialist
└── plan_type                  (HMO / PPO / HDHP — drives pre-auth burden defaults)

SELF-PAY PATH
├── self_pay_discount_rate     (extracted from provider MRF in Step 6; e.g., 0.30 at VMC)
├── prompt_pay_discount        (optional additional %; user confirms if applicable)
├── financial_assistance       (boolean — triggers income bracket input for charity care)
└── local_tax_dividend         (boolean — provider-specific; e.g., VMC Valley Tax Dividend)

UTILIZATION INPUTS
├── primary_care_visits        (count/year)
├── specialist_visits          (count/year)
├── imaging_studies            (count/year, by type)
├── labs                       (count/year)
├── er_visits                  (count/year, by severity)
├── inpatient_days             (count/year)
└── planned_procedures         (user selects from priority CPT list or searches by name)

FRICTION INPUTS
├── hourly_value_of_time       ($/hr — user's self-reported cost of their time)
├── pre_auth_hours_per_event   (default: 1.5 hrs; user-adjustable)
├── denial_rate                (default: 15%; user-adjustable based on experience)
└── denial_appeal_hours        (default: 4 hrs; user-adjustable)
```

### 4.2 Insurance Path Formula

```
annual_insurance_cost =
  (monthly_premium × 12)
  + min(
      sum(patient_responsibility_per_service),
      out_of_pocket_maximum
    )
  + pre_auth_friction_cost

where:
  patient_responsibility_per_service =
    IF service_cost <= remaining_deductible:
      service_cost at negotiated_rate        ← fully patient's responsibility
    ELSE:
      (service_cost - remaining_deductible) × coinsurance_rate

  pre_auth_friction_cost =
    (pre_auth_events × pre_auth_hours × hourly_value_of_time)
    + (pre_auth_events × denial_rate × denial_appeal_hours × hourly_value_of_time)

  negotiated_rate = standard_charge|negotiated_dollar from MRF for user's payer/plan
                    if unavailable: use standard_charge|Min as conservative estimate
```

### 4.3 Self-Pay Path Formula

```
annual_selfpay_cost =
  sum(standard_charge|discounted_cash per service)
  × (1 - prompt_pay_discount)
  - local_tax_dividend_credit
```

### 4.4 Break-Even Analysis

```
break_even_annual_medical_spend =
  (monthly_premium × 12) / (insurer_discount_rate - self_pay_discount_rate)

i.e.: the total annual medical bill amount at which insurance savings
      on the negotiated rates exceed the annual premium paid.

Example using real VMC data:
  Kaiser discount on stent ≈ 59% off gross
  VMC self-pay discount = 30% off gross
  Discount gap = 29 percentage points
  Annual premium = $5,400 ($450/mo)
  Break-even = $5,400 / 0.29 = ~$18,621/year in medical bills

  → Below ~$18,600/year in bills: self-pay costs less than insured
  → Above that threshold: insurance negotiated savings exceed premium cost
  (this calculation precedes OOP max protection and pre-auth friction adjustments)
```

### 4.5 Catastrophic Scenario Model

Run the full model assuming a major medical event from the high-cost procedure list (Section 5):

- **Insurance path:** total patient cost is capped at `out_of_pocket_maximum` regardless of actual service costs. This is insurance's core value proposition and where it almost always wins.
- **Self-pay path:** no cap. Total = sum of `discounted_cash_price` for all services in the event bundle. For a knee replacement or cardiac event this can reach $20,000–$100,000+ even after the 30% discount.
- Output clearly labeled: "Insurance protection value = [catastrophic self-pay cost] - [OOP max]"

This scenario should be presented honestly — the math strongly favors insurance for catastrophic events and the app should not obscure that.

### 4.6 DRG-Based Inpatient Pricing

Inpatient hospitalizations are not priced by CPT code — they are priced by **DRG (Diagnosis-Related Group)**, which bundles all services for an admission into a single payment rate based on primary diagnosis.

- The MRF includes inpatient DRG rows with gross and negotiated rates.
- **MVP approach:** model inpatient cost using a per-diem estimate (cost per day) derived from MRF inpatient data × estimated length of stay. Flag as approximation in the UI.
- **Phase 2:** full DRG lookup table for accurate catastrophic modeling.

---

## 5. Priority Procedure List (Seed Dataset)

Extracted from each provider's MRF during the seeding process. Covers the most common self-pay scenarios across all three utilization tiers.

### Routine / Outpatient
| Category | Procedure | CPT |
|---|---|---|
| Primary care | Office visit, new patient (moderate) | 99204 |
| Primary care | Office visit, established (moderate) | 99214 |
| Urgent care | Urgent care visit | 99213 |
| Lab | Comprehensive metabolic panel | 80053 |
| Lab | Complete blood count | 85025 |
| Lab | Lipid panel | 80061 |
| Lab | Urine albumin quantitative | 82043 |
| Lab | HbA1c | 83036 |
| Imaging | X-ray, chest (2 views) | 71046 |
| Imaging | MRI brain without contrast | 70553 |
| Imaging | MRI lumbar spine | 72148 |
| Imaging | CT abdomen/pelvis with contrast | 74177 |
| Imaging | Ultrasound, abdomen | 76700 |
| Imaging | Mammogram, diagnostic | 77066 |
| Preventive | Colonoscopy, screening | 45378 |
| Preventive | Annual wellness visit | G0439 |

### Emergency / Acute
| Category | Procedure | CPT |
|---|---|---|
| ER | ER visit, moderate complexity | 99284 |
| ER | ER visit, high complexity | 99285 |
| Surgery | Appendectomy, laparoscopic | 44950 |
| Surgery | Cholecystectomy, laparoscopic | 47562 |
| Cardiac | EKG | 93000 |
| Cardiac | Echocardiogram | 93306 |

### High-Cost / Catastrophic
| Category | Procedure | CPT |
|---|---|---|
| Orthopedic | Knee replacement (total) | 27447 |
| Orthopedic | Hip replacement (total) | 27130 |
| Cardiac | Coronary angioplasty / stent | 37238 |
| Oncology | Chemotherapy administration | 96413 |
| Delivery | Vaginal delivery | 59400 |
| Delivery | Cesarean delivery | 59510 |
| Inpatient | Hospital admission (DRG-based — see 4.6) | N/A |

---

## 6. Pre-Authorization Friction Model

Pre-auth friction is central to the insurance vs. self-pay question and the hardest variable to quantify. Approach:

**Default values** *(flagged as industry estimates — need citation before v1 release; candidate sources: AHIP Annual Prior Auth Survey, KFF Health System Tracker, AMA Prior Auth Survey)*:
- ~15% of prior authorization requests are initially denied
- Average patient time per auth request: 1.5 hours (range: 1–3 hrs)
- Average time to complete a successful appeal: 4 hours (range: 3–5 hrs)
- ~40% of denied claims that are appealed are eventually approved

**User configurability:** All defaults are exposed as adjustable inputs. Users with relevant personal experience (e.g., chronic condition requiring repeated prior auths) should override to reflect their actual history.

**Monetary conversion:** `friction_cost = hours × hourly_value_of_time` (user input in Section 4.1).

**Pre-auth burden by plan type:**
- HMO: highest (referrals required for all specialist visits; pre-auth for most imaging)
- PPO: moderate (pre-auth for major procedures and elective surgery)
- HDHP: lower pre-auth burden but higher OOP exposure before deductible is met

**Procedure-level pre-auth flags** (which of the priority procedures typically require pre-auth):

| Commonly requires pre-auth | Typically does not |
|---|---|
| MRI and advanced imaging (HMO plans) | Primary care / urgent care visits |
| Elective surgery (knee/hip replacement) | Basic labs (CBC, CMP, lipids) |
| Specialist referrals (HMO) | ER visits (retroactive review only) |
| Chemotherapy and oncology treatment | Annual wellness visits |
| Inpatient elective admissions | X-rays |
| Colonoscopy (some plans) | EKG |

---

## 7. Open Questions / Decisions Needed

| # | Question | Notes |
|---|---|---|
| 1 | Where does premium data come from? | WA Healthplanfinder has downloadable plan data. Need equivalent for other states or fall back to user manual entry for national use. |
| 2 | Default insurance plan presets | Suggest Bronze HDHP, Silver PPO, Gold HMO as starting points. Kaiser, Regence, First Choice confirmed in VMC MRF. |
| 3 | Non-CMS-compliant MRF handling | Schema detection + fallback defined. Need to specify what "manual correction" UI looks like. |
| 4 | Turquoise Health commercialization | Free research dataset requires non-commercial MSA. If app monetizes, need paid Clear Rates tier or alternative data source. |
| 5 | EOB import | User uploads Explanation of Benefits → app extracts their actual negotiated rates. High value, Phase 2 complexity. |
| 6 | Full DRG inpatient model | Per-diem approximation for MVP. Full DRG lookup table needed for accurate catastrophic modeling in Phase 2. |
| 7 | Scope: dental / vision / mental health | Suggest out of scope for v1. Mental health parity laws and separate coverage structures add significant complexity. |
| 8 | Financial assistance income tiers | The charity care tier structure for VMC (and other providers) is not yet fully documented. Pull from each provider's financial assistance policy page during seeding. |
| 9 | Pre-auth default value sources | 15% denial rate and time estimates need published citation. AHIP, KFF, or AMA prior auth surveys are the right sources. |
| 10 | Tech stack | TBD. Calculation engine should be written as stack-agnostic pure functions first, before any UI decisions are made. |

---

## 8. External Links & References

| Resource | URL |
|---|---|
| **VMC — Price Transparency Page** | https://www.valleymed.org/patients--visitors/billing-and-insurance/price-transparency |
| **VMC — MRF CSV (direct download)** | https://www.valleymed.org/916000986-1649209230_PUBLIC-HOSPITAL-DISTRICT-NO-1-OF-KING-COUNTY-WASHINGTON-dba-VALLEY-MEDICAL-CENTER_standardcharges.csv |
| **VMC — Cost Estimator Tool** | https://www.valleymed.org/estimate/ |
| **VMC — Billing & Collection Policy** | https://www.valleymed.org/patients--visitors/billing-and-insurance/financial-help--options/vmc-billing--collection-policy |
| **VMC — Financial Help & Options** | https://www.valleymed.org/patients--visitors/billing-and-insurance/financial-help--options |
| **VMC — Request Cost Estimate Form** | https://www.valleymed.org/forms/cost-estimate-form |
| **UW Medicine — Price Transparency** | https://www.uwmedicine.org/patient-resources/billing-and-insurance/price-transparency |
| **UW Medicine — Patient Estimates** | https://www.uwmedicine.org/patient-resources/billing-and-insurance/estimate-options |
| **UW Medicine — Shopper Estimate FAQ** | https://www.uwmedicine.org/sites/stevie/files/2022-11/ShopperEstimateFAQ%2020221014_a11y%20(1).pdf |
| **Providence/Swedish — Price Transparency** | https://www.providence.org/billing-support/pricing-transparency |
| **Providence/Swedish — Price Estimator** | https://www.providence.org/billing-support/price-estimate |
| **Overlake — Cost Estimate** | https://www.overlakehospital.org/visit/billing-insurance/healthcare-costs |
| **Turquoise Health — Free Research Data** | https://turquoise.health/researchers |
| **Turquoise Health — SSP API (free)** | https://turquoise.health/products/ssps |
| **Turquoise Health — Provider Lookup** | https://turquoise.health/providers |
| **CMS MRF Schema & GitHub Templates** | https://github.com/CMSgov/hospital-price-transparency |
| **WA Healthplanfinder** | https://www.wahealthplanfinder.org |
| **WSHA Hospital Pricing** | https://www.wsha.org/for-patients/hospital-pricing |
| **New Choice Health — Seattle Procedure Comparison** | https://www.newchoicehealth.com/places/washington/seattle |

---

## 9. Suggested Next Steps (In Order)

1. **Build and test the MRF discovery crawler** — given a FQDN, find the price transparency page and extract the MRF download URL. Validate against all four Seattle-area reference providers: `valleymed.org`, `swedish.org`, `overlakehospital.org`, `uwmedicine.org`.

2. **Build the streaming MRF parser** — detect schema version from header rows, stream-parse in chunks, extract all priority CPT codes (Section 5), output a clean provider JSON index. VMC's 73MB CSV is the primary test case.

3. **Validate self-pay discount extraction** — confirm the implied discount rate computed from `discounted_cash / gross` is consistent across rows per provider. Should consistently equal 0.30 at VMC.

4. **Enumerate all payers per provider** — extract the full unique list of `payer_name` and `plan_name` values from each MRF. This drives the insurance plan selection UI and determines which plans can have real negotiated rates shown vs. estimated.

5. **Seed premium data** — pull 3–5 representative plans from WA Healthplanfinder (Bronze HDHP, Silver PPO, Gold HMO) with premium, deductible, OOP max, and coinsurance. This is the other half of the insurance path inputs.

6. **Build the calculation engine** — pure functions, no UI. Inputs: provider index + utilization profile + plan details. Outputs: annual insurance cost, annual self-pay cost, break-even spend threshold, catastrophic scenario delta.

7. **Define utilization personas** — preset profiles that represent common user types:
   - "Healthy adult" (1 PCP visit, 2 labs/year, no imaging)
   - "Family with young kids" (higher PCP and urgent care frequency)
   - "Managing a chronic condition" (regular specialist, labs, and imaging)
   - "Planning an elective procedure" (specific high-cost CPT)
   - "Catastrophic baseline" (major illness or accident scenario)

8. **Source and cite pre-auth default values** — find published data (AHIP, KFF, AMA) backing the 15% denial rate and time estimates before v1 ships.

9. **Decide on tech stack and app form factor.**
