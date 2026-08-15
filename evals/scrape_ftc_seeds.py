"""
Reusable FTC seed claim scraper — VERBATIM extraction.
Scrapes FTC warning letters and guidance pages, extracts exact quoted claims.
Uses Firecrawl scrape (raw markdown) + regex parsing for quoted violations.

Usage:
    PYTHONPATH=. uv run python evals/scrape_ftc_seeds.py
    PYTHONPATH=. uv run python evals/scrape_ftc_seeds.py --limit 1  # test with one page

Output: evals/seed_claims.json

Adaptive: add new source URLs to FTC_SOURCES list to expand categories.
"""
import argparse
import json
import logging
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("ftc-scraper")

# ── Source registry (add new URLs here to expand categories) ─────────────────

FTC_SOURCES = [
    {
        "id": "ftc-health-compliance",
        "url": "https://www.ftc.gov/business-guidance/resources/health-products-compliance-guidance",
        "name": "FTC Health Products Compliance Guidance",
        "categories": ["health_claim", "misleading_efficacy"],
        "description": "200+ real cases with exact claims ruled illegal",
    },
    {
        "id": "ftc-diabetes-endorsements",
        "url": "https://www.ftc.gov/business-guidance/blog/2018/12/endorsement-enforcement-deceptive-diabetes-claims-challenged",
        "name": "FTC Deceptive Diabetes Claims (endorsement enforcement)",
        "categories": ["health_claim", "misleading_efficacy", "disclosure_violation"],
        "description": "Consumer endorsers with specific quoted claims about diabetes supplements",
    },
    {
        "id": "ftc-amberen-weight-loss",
        "url": "https://www.ftc.gov/news-events/news/press-releases/2016/05/marketers-dietary-supplement-amberen-settle-ftc-charges-regarding-misleading-weight-loss-menopause",
        "name": "FTC vs Amberen - Weight Loss & Menopause Claims",
        "categories": ["health_claim", "misleading_efficacy", "before_after"],
        "description": "Unsubstantiated weight loss and menopause relief claims",
    },
    {
        "id": "ftc-florida-supplements",
        "url": "https://www.ftc.gov/news-events/news/press-releases/2017/11/florida-based-supplement-sellers-settle-ftc-false-advertising-charges",
        "name": "FTC vs Florida Supplement Sellers",
        "categories": ["health_claim", "misleading_efficacy"],
        "description": "Supplements falsely claiming to prevent/treat colds, high blood pressure, HIV/AIDS",
    },
    {
        "id": "ftc-dannon-activia",
        "url": "https://www.ftc.gov/business-guidance/blog/2010/12/ftc-challenges-dannons-claims-activia-yogurt-danactive",
        "name": "FTC vs Dannon Activia/DanActive",
        "categories": ["health_claim", "misleading_efficacy"],
        "description": "National ad campaign with unsubstantiated digestive health claims",
    },
    # ── Add more sources below as needed ──────────────────────────────────────
    # {
    #     "id": "ftc-endorsement-guides",
    #     "url": "https://www.ftc.gov/business-guidance/resources/ftcs-endorsement-guides",
    #     "name": "FTC Endorsement Guides",
    #     "categories": ["disclosure_violation"],
    # },
]

# ── Regex patterns for extracting verbatim quoted claims ─────────────────────

# Pattern: text inside quotation marks (straight or curly quotes)
_QUOTE_PATTERN = re.compile(
    r'["\u201c]([^"\u201d]{10,300})["\u201d]',
    re.UNICODE,
)

# Context patterns: sentences/phrases that indicate the quoted text is a violating claim
_VIOLATION_CONTEXT_PATTERNS = re.compile(
    r"(?:claim|advertis|assert|stat|promot|market|represent|alleg|told consumers|"
    r"misleading|deceptive|unsubstantiated|false|violat|unlawful|illegal|"
    r"without adequate|lack.+evidence|no.+substantiation|not.+supported|"
    r"charged|settled|challenged|warned|cited|prohibited)",
    re.IGNORECASE,
)

# Patterns to EXCLUDE (not advertising claims — legal boilerplate, citations, etc.)
_EXCLUDE_PATTERNS = re.compile(
    r"(?:^Section \d|^FTC Act|^\d+ U\.S\.C|^See |^Id\.|^In re |"
    r"^http|^www\.|consent order|stipulated|click here|learn more|"
    r"read more|view the|download|pdf|press release|"
    # Legal terminology that gets quoted but isn't ad copy
    r"^unfair|^deceptive|^advertising$|^structure.function|^publication bias|"
    r"^FDA|^DSHEA|^substantiation|^reasonable basis|^competent and reliable|"
    r"liaison agreement|^material connection)",
    re.IGNORECASE,
)

# Only keep claims that look like ad copy (consumer-facing language)
_AD_COPY_INDICATORS = re.compile(
    r"(?:product|supplement|pill|formula|ingredient|weight|pound|fat|"
    r"lose|burn|slim|energy|boost|immune|joint|pain|anti.?aging|"
    r"wrinkle|skin|hair|growth|muscle|performance|endurance|"
    r"cure|treat|prevent|heal|relieve|reduce|eliminate|"
    r"clinically|proven|doctor|tested|research|study|"
    r"guarantee|risk.?free|money.?back|results|work|effective|"
    r"no.?side.?effect|natural|organic|safe|100%|"
    r"\d+%|\d+ pound|\d+ day|\d+ week)",
    re.IGNORECASE,
)

# Category detection from surrounding context
_CATEGORY_KEYWORDS = {
    "health_claim": re.compile(r"health|disease|cure|treat|prevent|medical|clinical|symptom", re.I),
    "misleading_efficacy": re.compile(r"efficacy|weight.?loss|pounds|fat.?burn|slim|rapid|fast.?result", re.I),
    "before_after": re.compile(r"before.?and.?after|testimonial|typical|results.?may.?vary", re.I),
    "disclosure_violation": re.compile(r"disclos|endors|sponsor|paid|material.?connection|#ad", re.I),
    "financial_claim": re.compile(r"invest|return|profit|guaranteed|risk.?free|income|earn", re.I),
    "deceptive_urgency": re.compile(r"limited.?time|today.?only|act.?now|expire|last.?chance|hurry", re.I),
}


# ── Core scraping logic ──────────────────────────────────────────────────────

def _get_firecrawl_client():
    """Get Firecrawl v4 client."""
    api_key = os.getenv("FIRECRAWL_API_KEY", "")
    if not api_key:
        raise ValueError("FIRECRAWL_API_KEY not set in environment")
    from firecrawl import FirecrawlApp
    return FirecrawlApp(api_key=api_key)


def _detect_category(context: str) -> str:
    """Detect violation category from surrounding text."""
    for category, pattern in _CATEGORY_KEYWORDS.items():
        if pattern.search(context):
            return category
    return "health_claim"  # default for FTC pages


def _extract_context(text: str, match_start: int, match_end: int, window: int = 200) -> str:
    """Extract surrounding context around a quote for violation reason."""
    start = max(0, match_start - window)
    end = min(len(text), match_end + window)
    context = text[start:end].strip()
    # Clean up markdown artifacts
    context = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', context)  # remove links
    context = re.sub(r'[#*_]+', '', context)  # remove markdown formatting
    return context


def scrape_source(source: dict) -> list[dict]:
    """Scrape a single FTC source page and extract verbatim quoted claims."""
    logger.info("Scraping: %s", source["name"])
    logger.info("  URL: %s", source["url"])

    app = _get_firecrawl_client()

    try:
        # ponytail: scrape returns raw markdown (1 credit). No LLM paraphrasing.
        result = app.scrape(source["url"], formats=["markdown"])
    except Exception as exc:
        logger.error("  Firecrawl scrape failed: %s", exc)
        return []

    # Get markdown content
    markdown = None
    if hasattr(result, "markdown"):
        markdown = result.markdown
    elif isinstance(result, dict):
        markdown = result.get("markdown", "")

    if not markdown:
        logger.warning("  No markdown content returned")
        return []

    logger.info("  Page length: %d chars", len(markdown))

    # Extract all quoted strings
    seeds = []
    seen_claims = set()

    for match in _QUOTE_PATTERN.finditer(markdown):
        claim_text = match.group(1).strip()

        # Skip if too short, too long, or looks like boilerplate
        if len(claim_text) < 25 or len(claim_text) > 250:
            continue
        if _EXCLUDE_PATTERNS.search(claim_text):
            continue
        # Skip if contains markdown artifacts (links, footnotes, formatting)
        if re.search(r'\[\\?\[|\\]|http|\.gov|\.com|\*\*|##|\\n', claim_text):
            continue
        # Skip if starts with punctuation/whitespace junk
        if re.match(r'^[)\]\s*#\-]', claim_text):
            continue

        # Check if surrounding context indicates this is a violating claim
        context = _extract_context(markdown, match.start(), match.end(), window=300)
        if not _VIOLATION_CONTEXT_PATTERNS.search(context):
            continue

        # Must look like actual ad copy (consumer-facing language), not legal terminology
        if not _AD_COPY_INDICATORS.search(claim_text) and not _AD_COPY_INDICATORS.search(context):
            continue

        # Deduplicate
        key = claim_text.lower().strip()
        if key in seen_claims:
            continue
        seen_claims.add(key)

        # Detect category from context
        category = _detect_category(context)

        # Extract violation reason from context (the sentence containing the quote)
        # Find the sentence that contains this quote
        sentence_start = markdown.rfind(".", 0, match.start())
        sentence_end = markdown.find(".", match.end())
        if sentence_start == -1:
            sentence_start = 0
        if sentence_end == -1:
            sentence_end = min(len(markdown), match.end() + 100)
        violation_sentence = markdown[sentence_start + 1:sentence_end + 1].strip()
        # Clean markdown from the sentence
        violation_sentence = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', violation_sentence)
        violation_sentence = re.sub(r'[#*_]+', '', violation_sentence).strip()

        seed = {
            "id": f"{source['id']}-{len(seeds) + 1:03d}",
            "source": source["name"],
            "source_url": source["url"],
            "category": category,
            "claim_text": claim_text,
            "violation_reason": violation_sentence[:300] if violation_sentence else "",
            "cited_rule": "FTC Act Section 5 - Deceptive practices",
            "platform_relevant": ["youtube", "meta", "tiktok"],
            "expected_status": "FAIL",
            "severity": "CRITICAL",
            "verbatim": True,  # flag: this is exact text from FTC, not paraphrased
        }
        seeds.append(seed)

    logger.info("  Extracted %d verbatim claims", len(seeds))
    return seeds


def scrape_all(limit: int | None = None) -> list[dict]:
    """Scrape all FTC sources (or first N if limit specified)."""
    sources = FTC_SOURCES[:limit] if limit else FTC_SOURCES
    all_seeds = []

    for source in sources:
        seeds = scrape_source(source)
        all_seeds.extend(seeds)

    # Final dedup across all sources
    seen = set()
    deduped = []
    for seed in all_seeds:
        key = seed["claim_text"].lower().strip()
        if key not in seen:
            seen.add(key)
            deduped.append(seed)

    logger.info("\nTotal: %d unique verbatim claims from %d sources", len(deduped), len(sources))
    return deduped


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Scrape FTC pages for verbatim violating claims")
    parser.add_argument("--limit", type=int, default=None, help="Max number of sources to scrape")
    parser.add_argument("--output", type=str, default="evals/seed_claims.json", help="Output path")
    args = parser.parse_args()

    seeds = scrape_all(limit=args.limit)

    if not seeds:
        logger.error("No seeds extracted. Check Firecrawl API key and network.")
        sys.exit(1)

    # Save
    output_path = Path(args.output)
    output_path.parent.mkdir(exist_ok=True)

    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_count": len(FTC_SOURCES[:args.limit] if args.limit else FTC_SOURCES),
        "total_seeds": len(seeds),
        "extraction_method": "verbatim_quotes",
        "note": "All claim_text fields are exact quotes from FTC publications, not paraphrased",
        "seeds": seeds,
    }

    with open(output_path, "w") as f:
        json.dump(output, f, indent=2)

    logger.info("Saved to %s", output_path)

    # Summary by category
    from collections import Counter
    cats = Counter(s["category"] for s in seeds)
    logger.info("\nBy category:")
    for cat, count in cats.most_common():
        logger.info("  %s: %d", cat, count)


if __name__ == "__main__":
    main()
