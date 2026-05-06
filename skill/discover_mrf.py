#!/usr/bin/env python3
"""
discover_mrf.py
Given a provider FQDN, finds the price transparency page and MRF download URL.
Writes cache/{fqdn}/provider.json

Usage:
    python scripts/discover_mrf.py valleymed.org
    python scripts/discover_mrf.py swedish.org --force-refresh
"""

import sys
import json
import os
import re
import argparse
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError
from urllib.parse import urlparse
from html.parser import HTMLParser

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE_DIR = os.path.join(SKILL_DIR, "cache")

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
    "/patients-visitors/billing/transparency/",
    "/patients/financial-services/billing/price-transparency",
]

MRF_FILENAME_PATTERNS = [
    r"standardcharges",
    r"standard[_-]charges",
    r"chargemaster",
]

MRF_EXTENSIONS = [".csv", ".json", ".xlsx", ".zip"]

MRF_LINK_TEXT = [
    "machine readable", "machine-readable", "mrf",
    "standard charges", "comprehensive pricing",
    "download", "chargemaster", "price list",
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; InsuranceCalcSkill/1.0)"
}


class LinkExtractor(HTMLParser):
    def __init__(self, base_url):
        super().__init__()
        self.base_url = base_url
        self.links = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            attrs = dict(attrs)
            href = attrs.get("href", "")
            text = ""
            self._current_href = href
            self._current_text = []

    def handle_data(self, data):
        if hasattr(self, "_current_text"):
            self._current_text.append(data.strip())

    def handle_endtag(self, tag):
        if tag == "a" and hasattr(self, "_current_href"):
            text = " ".join(self._current_text).lower()
            href = self._current_href
            self.links.append({"href": href, "text": text})
            del self._current_href
            del self._current_text


def fetch(url, timeout=15):
    try:
        req = Request(url, headers=HEADERS)
        with urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="replace"), resp.url
    except (URLError, HTTPError):
        return None, None


def head_request(url, timeout=10):
    try:
        req = Request(url, method="HEAD", headers=HEADERS)
        with urlopen(req, timeout=timeout) as resp:
            return {
                "status": resp.status,
                "content_type": resp.headers.get("Content-Type", ""),
                "content_length": resp.headers.get("Content-Length", ""),
                "last_modified": resp.headers.get("Last-Modified", ""),
            }
    except Exception:
        return None


def normalize_fqdn(fqdn):
    fqdn = fqdn.lower().strip()
    fqdn = re.sub(r"^https?://", "", fqdn)
    fqdn = re.sub(r"^www\.", "", fqdn)
    fqdn = fqdn.split("/")[0]
    return fqdn


def find_transparency_page(fqdn):
    print(f"  Searching for price transparency page on {fqdn}...")
    for path in TRANSPARENCY_PATHS:
        for scheme in ["https", "http"]:
            url = f"{scheme}://{fqdn}{path}"
            html, final_url = fetch(url)
            if html and len(html) > 500:
                print(f"  Found: {final_url}")
                return final_url, html
    # Fallback: try sitemap
    sitemap_url = f"https://{fqdn}/sitemap.xml"
    sitemap, _ = fetch(sitemap_url)
    if sitemap:
        urls = re.findall(r"<loc>(.*?)</loc>", sitemap)
        for url in urls:
            if any(kw in url.lower() for kw in ["price-transparency", "price_transparency", "chargemaster", "standard-charges"]):
                html, final_url = fetch(url)
                if html and len(html) > 500:
                    print(f"  Found via sitemap: {final_url}")
                    return final_url, html
    return None, None


def is_mrf_link(href, text):
    href_lower = href.lower()
    # Check filename patterns
    if any(re.search(p, href_lower) for p in MRF_FILENAME_PATTERNS):
        return True
    # Check extension + link text
    if any(href_lower.endswith(ext) for ext in MRF_EXTENSIONS):
        if any(kw in text for kw in MRF_LINK_TEXT):
            return True
    return False


def resolve_url(href, base_url):
    if href.startswith("http"):
        return href
    if href.startswith("//"):
        return "https:" + href
    parsed = urlparse(base_url)
    if href.startswith("/"):
        return f"{parsed.scheme}://{parsed.netloc}{href}"
    return f"{parsed.scheme}://{parsed.netloc}/{href}"


def find_mrf_url(page_url, html):
    print("  Searching for MRF download link...")
    extractor = LinkExtractor(page_url)
    extractor.feed(html)

    candidates = []
    for link in extractor.links:
        href = link["href"]
        text = link["text"]
        if not href:
            continue
        if is_mrf_link(href, text):
            full_url = resolve_url(href, page_url)
            candidates.append(full_url)

    # Prefer CSV, then JSON, then xlsx
    for ext in [".csv", ".json", ".xlsx"]:
        for c in candidates:
            if c.lower().endswith(ext) or ext in c.lower():
                print(f"  Found MRF link: {c}")
                return c

    if candidates:
        print(f"  Found MRF link (unverified extension): {candidates[0]}")
        return candidates[0]

    return None


def extract_mrf_metadata(mrf_url):
    print("  Fetching MRF metadata (HEAD request)...")
    meta = head_request(mrf_url)
    if not meta:
        return {}

    # Peek at first 2KB to get last_updated_on from header rows
    last_updated = None
    try:
        req = Request(mrf_url, headers={**HEADERS, "Range": "bytes=0-4096"})
        with urlopen(req, timeout=20) as resp:
            chunk = resp.read().decode("utf-8", errors="replace")
            # CMS v2: look for date in format YYYY-MM-DD or MM/DD/YYYY
            date_match = re.search(
                r"last_updated_on[,\|]?\s*[\"']?(\d{1,2}/\d{1,2}/\d{4}|\d{4}-\d{2}-\d{2})",
                chunk
            )
            if date_match:
                last_updated = date_match.group(1)

            # Also look for schema version
            schema_version = "unknown"
            if "standard_charge|gross" in chunk or "standard_charge|discounted_cash" in chunk:
                schema_version = "v2"
            elif "Gross Charges" in chunk or "Gross_Charge" in chunk:
                schema_version = "v1_wide"

    except Exception:
        pass

    size_bytes = int(meta.get("content_length", 0) or 0)
    return {
        "content_type": meta.get("content_type", ""),
        "size_bytes": size_bytes,
        "size_mb": round(size_bytes / 1024 / 1024, 1) if size_bytes else None,
        "last_modified_header": meta.get("last_modified", ""),
        "mrf_last_updated": last_updated,
        "schema_version": schema_version if 'schema_version' in dir() else "unknown",
        "requires_streaming": size_bytes > 50 * 1024 * 1024,
    }


def load_cache(fqdn):
    path = os.path.join(CACHE_DIR, fqdn, "provider.json")
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return None


def write_cache(fqdn, data):
    cache_dir = os.path.join(CACHE_DIR, fqdn)
    os.makedirs(cache_dir, exist_ok=True)
    path = os.path.join(cache_dir, "provider.json")
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
    print(f"  Cached provider record: {path}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("fqdn", help="Provider base domain, e.g. valleymed.org")
    parser.add_argument("--force-refresh", action="store_true")
    args = parser.parse_args()

    fqdn = normalize_fqdn(args.fqdn)
    print(f"\n=== MRF Discovery: {fqdn} ===\n")

    if not args.force_refresh:
        cached = load_cache(fqdn)
        if cached:
            print(f"  Cache hit — MRF last updated: {cached.get('mrf_last_updated', 'unknown')}")
            print(f"  MRF URL: {cached.get('mrf_url')}")
            print(json.dumps(cached, indent=2))
            return 0

    page_url, html = find_transparency_page(fqdn)
    if not page_url:
        print(f"\nERROR: Could not find price transparency page for {fqdn}.")
        print("Please paste the price transparency page URL manually and re-run:")
        print(f"  python scripts/discover_mrf.py {fqdn} --page-url <url>")
        return 1

    mrf_url = find_mrf_url(page_url, html)
    if not mrf_url:
        print(f"\nERROR: Could not find MRF download link on {page_url}.")
        print("Please paste the MRF download URL manually.")
        return 1

    print("  Validating MRF...")
    meta = extract_mrf_metadata(mrf_url)

    provider_record = {
        "fqdn": fqdn,
        "transparency_page_url": page_url,
        "mrf_url": mrf_url,
        "mrf_last_updated": meta.get("mrf_last_updated"),
        "schema_version": meta.get("schema_version", "unknown"),
        "size_mb": meta.get("size_mb"),
        "requires_streaming": meta.get("requires_streaming", False),
        "content_type": meta.get("content_type"),
        "discovered_at": __import__("datetime").date.today().isoformat(),
        "self_pay_discount_rate": None,
        "payers_available": [],
        "hospital_name": None,
        "hospital_address": None,
    }

    write_cache(fqdn, provider_record)

    print(f"\nProvider record written. Summary:")
    print(f"  MRF URL:          {mrf_url}")
    print(f"  Last updated:     {meta.get('mrf_last_updated', 'unknown')}")
    print(f"  Schema version:   {meta.get('schema_version', 'unknown')}")
    print(f"  File size:        {meta.get('size_mb', '?')} MB")
    print(f"  Streaming needed: {meta.get('requires_streaming', False)}")
    print(f"\nNext step: python scripts/parse_mrf.py {fqdn}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
