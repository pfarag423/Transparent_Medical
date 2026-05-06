# Transparent Medical — Insurance vs. Self-Pay Calculator

A Claude Code skill that answers the question: **is your health insurance actually worth what you pay for it?**

It pulls real price data directly from your hospital's CMS machine-readable file (MRF), compares what you'd pay insured vs. out-of-pocket for your actual expected healthcare usage, and saves a formatted Excel workbook with the full breakdown.

---

## What It Does

1. **Guided conversation** — asks about your provider, insurance plan, and how much healthcare you use in a year
2. **Live MRF data** — automatically discovers and streams your hospital's price transparency file (the same data hospitals are required by law to publish)
3. **Real rate comparison** — extracts your insurer's negotiated rates, the self-pay (discounted cash) price, and gross charges for the CPT codes that match your usage
4. **Excel workbook** — saves to `~/Downloads/insurance-analysis-YYYY-MM-DD.xlsx` with 9 tabs:

| Tab | Contents |
|-----|----------|
| Summary Dashboard | Top-line answer, key metrics, traffic-light indicators |
| Your Inputs | All inputs as editable cells — change any assumption and the rest recalculates |
| Procedure Cost Comparison | Per-CPT: gross, self-pay, insurer min/max, your insured cost |
| Annual Cost Scenarios | Low / Expected / High utilization × insurance vs. self-pay |
| Break-Even Analysis | The annual spend threshold where insurance starts saving money |
| Catastrophic Scenarios | ER, appendectomy, knee replacement, stent, chemo, childbirth |
| Pre-Auth Friction Detail | Which procedures need prior auth, time cost, total friction $ |
| Provider Data | Raw MRF extract — audit trail, source URLs, dates |
| Methodology & Notes | How the math works and why the "insurance discount" claim is often misleading |

Currently validated against **Valley Medical Center** (valleymed.org). Other CMS-compliant hospitals should work with no changes.

---

## Requirements

- [Claude Code](https://claude.ai/code) (CLI or desktop app)
- Python 3.9+
- The following Python packages:

```
pip install openpyxl requests
```

---

## Installation

1. Copy the `skill/` directory to your Claude skills folder:

```bash
mkdir -p ~/.claude/skills/insurance-calculator
cp skill/* ~/.claude/skills/insurance-calculator/
```

2. Register the skill in your Claude Code settings (`~/.claude/settings.json`):

```json
{
  "skills": [
    "~/.claude/skills/insurance-calculator/SKILL.md"
  ]
}
```

3. Verify the skill is loaded by running `/insurance-calculator` in Claude Code, or asking "is my insurance worth it?"

---

## Usage

Just ask Claude Code:

> "Is my insurance worth it?"
> "Compare self-pay vs insurance for me"
> "Should I drop my health insurance?"

Claude will walk you through a short conversation, then run the analysis and open the workbook.

---

## How the Math Works

**Insurance annual cost:**
```
(monthly_premium × 12)
+ min(sum(patient cost-share per service), out-of-pocket maximum)
+ pre-authorization friction cost
```

**Self-pay annual cost:**
```
sum(discounted cash price per service)
× (1 − prompt-pay discount)
− local tax dividend credit (if eligible)
```

**Break-even threshold:**
```
annual_premium / (insurer_discount_rate − self_pay_discount_rate)
```

Example: at Valley Medical Center, Premera's negotiated discount is ~59% off gross vs. 30% for self-pay. That 29-point gap means you need roughly $29,000/year in gross medical spend before the premium pays for itself — for most people, insurance wins well before that.

---

## Data Source

Hospital machine-readable files (MRFs) are published under the [CMS Price Transparency Rule (45 CFR 180)](https://www.cms.gov/hospital-price-transparency). The skill auto-discovers the MRF URL from the hospital's price transparency page and streams it — no manual download needed. MRF data is cached locally and refreshed when the hospital publishes an update.

---

## Limitations

- Inpatient/overnight stays use a per-diem approximation (DRG pricing is not yet fully modeled)
- Prior auth denial rates and time estimates use industry averages (AHIP/KFF/AMA surveys) unless you provide your own
- Financial assistance eligibility is flagged by income bracket but not fully calculated
- Premium data must be entered manually for states other than Washington (WA Healthplanfinder not yet integrated)
