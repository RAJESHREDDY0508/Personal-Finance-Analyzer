"""
AI categorization service — GPT-4o-mini with rule-based fallback.

Categories (aligned with common budgeting apps):
  Food & Dining, Groceries, Shopping, Transportation, Entertainment,
  Health & Medical, Housing, Utilities, Travel, Education,
  Personal Care, Gifts & Donations, Business Services, Income, Transfers, Other
"""
import json
import re
import structlog
from openai import AsyncOpenAI

from app.config import settings

logger = structlog.get_logger(__name__)

# ── Category taxonomy ─────────────────────────────────────────

CATEGORIES = [
    "Food & Dining",
    "Groceries",
    "Shopping",
    "Transportation",
    "Entertainment",
    "Health & Medical",
    "Housing",
    "Utilities",
    "Travel",
    "Education",
    "Personal Care",
    "Gifts & Donations",
    "Business Services",
    "Income",
    "Transfers",
    "Other",
]

# ── Rule-based fallback ───────────────────────────────────────

_RULES: list[tuple[re.Pattern, str]] = [
    # Food & Dining
    (re.compile(r"(starbucks|dunkin|coffee|cafe|restaurant|mcdonald|burger|pizza|sushi|taco|chipotle|chick.fil|kfc|subway|domino|grubhub|doordash|ubereats|instacart meal)", re.I), "Food & Dining"),
    # Groceries
    (re.compile(r"(whole foods|trader joe|kroger|safeway|publix|aldi|costco|walmart|target|stop.shop|wegman|sprouts|food lion|heb|meijer|supermarket|grocery)", re.I), "Groceries"),
    # Transportation
    (re.compile(r"(uber|lyft|taxi|transit|metro|bart|mta|amtrak|shell|exxon|chevron|bp gas|sunoco|speedway|pilot travel|fuel|parking|toll|ez.pass|fastrak|zipcar)", re.I), "Transportation"),
    # Shopping
    (re.compile(r"(amazon|ebay|etsy|zara|h&m|gap|old navy|nike|adidas|nordstrom|macys|tjmaxx|marshalls|ross|best buy|apple store|ikea|home depot|lowes)", re.I), "Shopping"),
    # Entertainment
    (re.compile(r"(netflix|hulu|spotify|disney|apple tv|hbo|prime video|youtube|steam|playstation|xbox|ticketmaster|eventbrite|cinema|amc theaters|regal)", re.I), "Entertainment"),
    # Health & Medical
    (re.compile(r"(cvs|walgreens|rite aid|pharmacy|medical|dental|doctor|hospital|clinic|health|optometrist|vision|urgent care|labcorp|quest)", re.I), "Health & Medical"),
    # Housing
    (re.compile(r"(rent|mortgage|hoa|property tax|apartment|lease|real estate)", re.I), "Housing"),
    # Utilities
    (re.compile(r"(electric|gas bill|water bill|internet|comcast|spectrum|at&t|verizon|tmobile|sprint|xfinity|utility|pge|con ed|national grid)", re.I), "Utilities"),
    # Travel
    (re.compile(r"(airline|flight|hotel|airbnb|vrbo|marriott|hilton|hyatt|booking\.com|expedia|delta|united|american air|southwest|spirit air)", re.I), "Travel"),
    # Education
    (re.compile(r"(university|college|tuition|coursera|udemy|skillshare|chegg|student loan|school|textbook)", re.I), "Education"),
    # Personal Care
    (re.compile(r"(salon|barber|spa|beauty|sephora|ulta|gym|fitness|planet fitness|24 hour fitness|equinox|yoga)", re.I), "Personal Care"),
    # Gifts & Donations
    (re.compile(r"(charity|donation|nonprofit|paypal.me|venmo|cashapp|zelle|gift)", re.I), "Gifts & Donations"),
    # Income
    (re.compile(r"(payroll|direct deposit|salary|dividend|interest|refund|tax return|bonus pay|freelance|consulting income)", re.I), "Income"),
    # Transfers
    (re.compile(r"(transfer|wire|ach|payment from|payment to|bank transfer|zelle|venmo|paypal transfer)", re.I), "Transfers"),
]


def _rule_based_category(description: str) -> str | None:
    """Return the first matching rule-based category, or None."""
    for pattern, category in _RULES:
        if pattern.search(description):
            return category
    return None


# ── OpenAI batch categorization ───────────────────────────────

_SYSTEM_PROMPT = f"""You are a financial transaction categorizer.
Given a list of bank transaction descriptions, categorize each into exactly one
of these categories: {', '.join(CATEGORIES)}.

Return a JSON array with one object per transaction:
[{{"index": 0, "category": "Groceries", "subcategory": "Supermarket"}}, ...]

Rules:
- "subcategory" is a short (1-3 word) description of the specific sub-type
- Negative amounts are expenses, positive amounts are income
- Default to "Other" if uncertain
- Never add categories outside the provided list
"""


async def categorize_batch(descriptions: list[str]) -> list[dict]:
    """
    Categorize a batch of transaction descriptions using GPT-4o-mini.
    Returns list of {index, category, subcategory}.
    Falls back to rule-based on error or if OpenAI is not configured.
    """
    if not settings.openai_api_key or settings.openai_api_key == "sk-placeholder":
        return _rule_based_batch(descriptions)

    try:
        client = AsyncOpenAI(api_key=settings.openai_api_key)
        user_content = json.dumps(
            [{"index": i, "description": d} for i, d in enumerate(descriptions)]
        )
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
            response_format={"type": "json_object"},
            temperature=0,
            max_tokens=2000,
        )
        raw = response.choices[0].message.content or "[]"
        # Response is a JSON object with a key like "transactions" or just an array
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            # Find the first list value
            for v in parsed.values():
                if isinstance(v, list):
                    parsed = v
                    break
        return parsed  # type: ignore[return-value]

    except Exception as exc:
        logger.warning("OpenAI categorization failed, using rule-based fallback", error=str(exc))
        return _rule_based_batch(descriptions)


def _rule_based_batch(descriptions: list[str]) -> list[dict]:
    """Rule-based categorization for all descriptions in a batch."""
    results = []
    for i, desc in enumerate(descriptions):
        category = _rule_based_category(desc) or "Other"
        results.append({"index": i, "category": category, "subcategory": ""})
    return results


# ── Single transaction helper ─────────────────────────────────

async def categorize_single(description: str) -> tuple[str, str]:
    """
    Categorize a single transaction.
    Returns (category, subcategory).
    """
    results = await categorize_batch([description])
    if results:
        r = results[0]
        return r.get("category", "Other"), r.get("subcategory", "")
    return "Other", ""
