"""
calculate.py
Pure calculation functions for insurance vs. self-pay comparison.
No I/O, no side effects. All functions take plain dicts and return plain dicts.
"""

import json
import os

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(SKILL_DIR, "data")


# ---------------------------------------------------------------------------
# Pre-auth defaults (industry estimates — cite before v1 release)
# Sources to verify: AHIP Annual Prior Auth Survey, KFF, AMA Prior Auth Survey
# ---------------------------------------------------------------------------
PREAUTH_DEFAULTS = {
    "denial_rate": 0.15,           # 15% of pre-auth requests initially denied
    "pre_auth_hours": 1.5,         # avg patient hours per auth request
    "appeal_hours": 4.0,           # avg hours for a successful appeal
    "appeal_success_rate": 0.40,   # 40% of denied claims win on appeal
}

# Plan type multiplier for pre-auth burden
PREAUTH_PLAN_MULTIPLIER = {
    "HMO": 1.5,
    "PPO": 1.0,
    "HDHP": 0.6,
    "unknown": 1.0,
}


def load_priority_cpts():
    path = os.path.join(DATA_DIR, "priority_cpts.json")
    with open(path) as f:
        return json.load(f)


def load_procedures(fqdn, cache_dir=None):
    if cache_dir is None:
        cache_dir = os.path.join(SKILL_DIR, "cache")
    path = os.path.join(cache_dir, fqdn, "procedures.json")
    if not os.path.exists(path):
        return {}
    with open(path) as f:
        return json.load(f)


def load_provider(fqdn, cache_dir=None):
    if cache_dir is None:
        cache_dir = os.path.join(SKILL_DIR, "cache")
    path = os.path.join(cache_dir, fqdn, "provider.json")
    if not os.path.exists(path):
        return {}
    with open(path) as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Rate lookup helpers
# ---------------------------------------------------------------------------

def lookup_negotiated_rate(cpt, payer_name, procedures):
    """
    Find the best negotiated rate for a CPT code and payer.
    Falls back to min negotiated rate across all payers.
    Returns: (rate, source) where source is 'payer_specific' or 'min_deidentified'
    """
    proc = procedures.get(cpt)
    if not proc:
        return None, "not_found"

    # Try payer-specific match (case-insensitive substring)
    payer_lower = (payer_name or "").lower()
    for entry in proc.get("payer_rates", []):
        if payer_lower and payer_lower[:10] in entry.get("payer", "").lower():
            if entry.get("negotiated"):
                return entry["negotiated"], "payer_specific"

    # Fall back to de-identified minimum
    if proc.get("negotiated_min"):
        return proc["negotiated_min"], "min_deidentified"

    # Fall back to median
    if proc.get("negotiated_median"):
        return proc["negotiated_median"], "median_deidentified"

    return None, "not_found"


def lookup_cash_price(cpt, procedures):
    """Return the self-pay (discounted cash) price for a CPT code."""
    proc = procedures.get(cpt)
    if not proc:
        return None
    return proc.get("discounted_cash_median")


def lookup_gross_price(cpt, procedures):
    """Return the gross chargemaster price for a CPT code."""
    proc = procedures.get(cpt)
    if not proc:
        return None
    return proc.get("gross_charge_median")


# ---------------------------------------------------------------------------
# Utilization expansion: convert user inputs to a flat list of CPT codes
# ---------------------------------------------------------------------------

def build_service_list(user_inputs, priority_cpts_data):
    """
    Expand utilization inputs into a flat list of CPT codes with quantities.
    Returns: list of {"cpt": str, "quantity": int, "category": str}
    """
    services = []
    cpt_meta = {p["cpt"]: p for p in priority_cpts_data["procedures"]}

    def add(cpt, qty=1):
        if cpt in cpt_meta:
            services.append({"cpt": cpt, "quantity": qty, "category": cpt_meta[cpt]["category"]})

    # Primary care
    for _ in range(user_inputs.get("primary_care_visits", 0)):
        add("99214")  # established patient visit

    # Specialist visits (generic — no CPT without more specificity)
    for _ in range(user_inputs.get("specialist_visits", 0)):
        add("99214")  # use same code as proxy; label as specialist

    # Imaging (user may specify types)
    for study in user_inputs.get("imaging_studies", []):
        cpt = study if study in cpt_meta else None
        if cpt:
            add(cpt)

    # Labs
    for lab in user_inputs.get("labs", []):
        cpt = lab if lab in cpt_meta else None
        if cpt:
            add(cpt)

    # ER visits
    er_severity = user_inputs.get("er_severity", "moderate")
    er_cpt = "99285" if er_severity == "major" else "99284"
    for _ in range(user_inputs.get("er_visits", 0)):
        add(er_cpt)

    # Planned procedures
    for cpt in user_inputs.get("planned_procedures", []):
        if cpt in cpt_meta:
            add(cpt)

    return services


def count_pre_auth_events(services, plan_type, priority_cpts_data):
    """Count how many services in the list require pre-authorization for this plan type."""
    cpt_meta = {p["cpt"]: p for p in priority_cpts_data["procedures"]}
    count = 0
    for svc in services:
        meta = cpt_meta.get(svc["cpt"], {})
        pre_auth = meta.get("pre_auth", {})
        if pre_auth.get(plan_type, False):
            count += svc.get("quantity", 1)
    return count


# ---------------------------------------------------------------------------
# Core calculations
# ---------------------------------------------------------------------------

def calc_insurance_cost(user_inputs, services, procedures, priority_cpts_data):
    """
    Calculate total annual cost under insurance.
    Returns dict with cost breakdown.
    """
    monthly_premium = user_inputs.get("monthly_premium", 0)
    annual_deductible = user_inputs.get("annual_deductible", 0)
    oop_max = user_inputs.get("out_of_pocket_maximum", float("inf"))
    coinsurance = user_inputs.get("coinsurance_rate", 0.20)
    plan_type = user_inputs.get("plan_type", "PPO")
    payer_name = user_inputs.get("payer_name", "")
    hourly_rate = user_inputs.get("hourly_value_of_time", 0)

    premium_annual = monthly_premium * 12
    remaining_deductible = annual_deductible
    patient_responsibility = 0
    service_details = []

    for svc in services:
        cpt = svc["cpt"]
        qty = svc.get("quantity", 1)

        negotiated, rate_source = lookup_negotiated_rate(cpt, payer_name, procedures)
        if negotiated is None:
            service_details.append({
                "cpt": cpt,
                "category": svc["category"],
                "qty": qty,
                "negotiated_rate": None,
                "patient_pays": None,
                "note": "rate not found in MRF",
            })
            continue

        service_cost = negotiated * qty
        patient_portion = 0

        if remaining_deductible > 0:
            deductible_applied = min(service_cost, remaining_deductible)
            remaining_deductible -= deductible_applied
            coinsurance_amount = (service_cost - deductible_applied) * coinsurance
            patient_portion = deductible_applied + coinsurance_amount
        else:
            patient_portion = service_cost * coinsurance

        patient_responsibility += patient_portion
        service_details.append({
            "cpt": cpt,
            "category": svc["category"],
            "qty": qty,
            "negotiated_rate": negotiated,
            "patient_pays": round(patient_portion, 2),
            "rate_source": rate_source,
        })

    oop_capped = min(patient_responsibility, oop_max)

    # Pre-auth friction cost
    pre_auth_events = count_pre_auth_events(services, plan_type, priority_cpts_data)
    plan_multiplier = PREAUTH_PLAN_MULTIPLIER.get(plan_type, 1.0)
    denial_rate = user_inputs.get("denial_rate", PREAUTH_DEFAULTS["denial_rate"])
    pre_auth_hours = user_inputs.get("pre_auth_hours_per_event", PREAUTH_DEFAULTS["pre_auth_hours"])
    appeal_hours = user_inputs.get("denial_appeal_hours", PREAUTH_DEFAULTS["appeal_hours"])

    friction_cost = (
        pre_auth_events * pre_auth_hours * plan_multiplier * hourly_rate
        + pre_auth_events * denial_rate * appeal_hours * hourly_rate
    )

    total = premium_annual + oop_capped + friction_cost

    return {
        "premium_annual": round(premium_annual, 2),
        "patient_responsibility_before_cap": round(patient_responsibility, 2),
        "patient_responsibility_capped": round(oop_capped, 2),
        "oop_max": oop_max,
        "hit_oop_max": patient_responsibility >= oop_max,
        "pre_auth_events": pre_auth_events,
        "friction_cost": round(friction_cost, 2),
        "total": round(total, 2),
        "service_details": service_details,
    }


def calc_selfpay_cost(user_inputs, services, procedures, provider):
    """
    Calculate total annual cost under self-pay.
    Returns dict with cost breakdown.
    """
    prompt_pay_discount = user_inputs.get("prompt_pay_discount", 0)
    local_tax_dividend = user_inputs.get("local_tax_dividend_amount", 0)
    self_pay_discount_rate = provider.get("self_pay_discount_rate", 0.30)

    total_cash = 0
    service_details = []

    for svc in services:
        cpt = svc["cpt"]
        qty = svc.get("quantity", 1)

        cash_price = lookup_cash_price(cpt, procedures)
        gross_price = lookup_gross_price(cpt, procedures)

        if cash_price is None and gross_price is not None:
            cash_price = gross_price * (1 - self_pay_discount_rate)

        if cash_price is None:
            service_details.append({
                "cpt": cpt,
                "category": svc["category"],
                "qty": qty,
                "cash_price": None,
                "note": "price not found in MRF",
            })
            continue

        line_total = cash_price * qty
        total_cash += line_total
        service_details.append({
            "cpt": cpt,
            "category": svc["category"],
            "qty": qty,
            "cash_price": round(cash_price, 2),
            "line_total": round(line_total, 2),
        })

    total_after_prompt = total_cash * (1 - prompt_pay_discount)
    total_final = max(total_after_prompt - local_tax_dividend, 0)

    return {
        "total_before_discounts": round(total_cash, 2),
        "prompt_pay_discount_amount": round(total_cash * prompt_pay_discount, 2),
        "local_tax_dividend": round(local_tax_dividend, 2),
        "total": round(total_final, 2),
        "self_pay_discount_rate": self_pay_discount_rate,
        "service_details": service_details,
    }


def calc_break_even(user_inputs, provider, procedures):
    """
    Calculate the annual medical spend at which insurance savings = premium cost.
    Returns the break-even spend threshold in dollars, or None if gap <= 0.
    """
    monthly_premium = user_inputs.get("monthly_premium", 0)
    annual_premium = monthly_premium * 12
    payer_name = user_inputs.get("payer_name", "")

    self_pay_discount = provider.get("self_pay_discount_rate", 0.30)

    # Compute effective insurer discount from available MRF data
    # Use stent (37238) and lab (82043) as reference points if available
    reference_cpts = ["37238", "82043", "27447", "72148", "44950"]
    discount_samples = []
    for cpt in reference_cpts:
        proc = procedures.get(cpt)
        if not proc:
            continue
        gross = proc.get("gross_charge_median")
        if not gross:
            continue
        neg, _ = lookup_negotiated_rate(cpt, payer_name, procedures)
        if neg and gross and gross > 0:
            discount_samples.append(1 - (neg / gross))

    if not discount_samples:
        # Fall back to a reasonable estimate for PPO-type plans
        insurer_discount = 0.55
        insurer_discount_source = "estimated (no MRF data for payer)"
    else:
        insurer_discount = sum(discount_samples) / len(discount_samples)
        insurer_discount_source = f"computed from {len(discount_samples)} MRF samples"

    discount_gap = insurer_discount - self_pay_discount
    if discount_gap <= 0:
        return {
            "break_even_spend": None,
            "insurer_discount": insurer_discount,
            "self_pay_discount": self_pay_discount,
            "discount_gap": discount_gap,
            "note": "Self-pay discount equals or exceeds insurer discount — self-pay always wins on cost",
            "insurer_discount_source": insurer_discount_source,
        }

    break_even = annual_premium / discount_gap
    return {
        "break_even_spend": round(break_even, 2),
        "annual_premium": round(annual_premium, 2),
        "insurer_discount": round(insurer_discount, 4),
        "self_pay_discount": round(self_pay_discount, 4),
        "discount_gap": round(discount_gap, 4),
        "insurer_discount_source": insurer_discount_source,
    }


def calc_catastrophic(user_inputs, procedures, provider):
    """
    Model catastrophic event scenarios.
    Returns dict of event name → {insurance_total, selfpay_total, protection_value}
    """
    cpts_data = load_priority_cpts()
    bundles = cpts_data.get("catastrophic_bundles", {})
    monthly_premium = user_inputs.get("monthly_premium", 0)
    oop_max = user_inputs.get("out_of_pocket_maximum", float("inf"))
    self_pay_discount_rate = provider.get("self_pay_discount_rate", 0.30)

    results = {}
    for event_name, cpt_list in bundles.items():
        selfpay_total = 0
        for cpt in cpt_list:
            cash = lookup_cash_price(cpt, procedures)
            if cash is None:
                gross = lookup_gross_price(cpt, procedures)
                cash = gross * (1 - self_pay_discount_rate) if gross else 0
            selfpay_total += (cash or 0)

        # Insurance: always hits OOP max on catastrophic events
        insurance_oop = min(selfpay_total, oop_max)
        insurance_total = monthly_premium * 12 + insurance_oop

        results[event_name] = {
            "selfpay_total": round(selfpay_total, 2),
            "insurance_medical_oop": round(insurance_oop, 2),
            "insurance_total_with_premiums": round(insurance_total, 2),
            "insurance_protection_value": round(selfpay_total - insurance_oop, 2),
        }

    return results


def run_all_scenarios(user_inputs, fqdn):
    """
    Master function: load data, run all calculations, return full results dict.
    """
    provider = load_provider(fqdn)
    procedures = load_procedures(fqdn)
    priority_cpts_data = load_priority_cpts()

    services = build_service_list(user_inputs, priority_cpts_data)

    insurance = calc_insurance_cost(user_inputs, services, procedures, priority_cpts_data)
    selfpay = calc_selfpay_cost(user_inputs, services, procedures, provider)
    break_even = calc_break_even(user_inputs, provider, procedures)
    catastrophic = calc_catastrophic(user_inputs, procedures, provider)

    annual_savings = selfpay["total"] - insurance["total"]
    winner = "insurance" if annual_savings > 0 else "self_pay"

    return {
        "fqdn": fqdn,
        "provider_name": provider.get("hospital_name", fqdn),
        "insurance": insurance,
        "selfpay": selfpay,
        "break_even": break_even,
        "catastrophic": catastrophic,
        "summary": {
            "winner": winner,
            "annual_difference": round(abs(annual_savings), 2),
            "insurance_total": insurance["total"],
            "selfpay_total": selfpay["total"],
            "break_even_spend": break_even.get("break_even_spend"),
        },
    }
