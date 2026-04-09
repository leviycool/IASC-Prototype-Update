"""
System prompts and prompt templates for the IASC donor analytics assistant.

The system prompt is assembled dynamically: a base prompt defines the assistant's
role and behavior, then the knowledge base content is optionally appended.
The knowledge base is only loaded when the user's question needs it (see
needs_knowledge_base()), saving ~2,000 tokens on pure data queries.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from knowledge import load_knowledge_base

# Concise schema summary injected into the system prompt so Claude knows
# what fields are available without receiving the full data dictionary.
DB_SCHEMA_SUMMARY = """
## Database schema summary

**contacts** table (one row per person):
- contact_id, first_name, last_name, email, city, state, zip_code
- donor_status: "active", "lapsed", "prospect", "new_donor"
- first_gift_date, last_gift_date, total_gifts, total_number_of_gifts, average_gift
- giving_vehicle: "check", "online", "stock", "DAF", "wire"
- subscription_type: "print", "digital", "both", "none"
- subscription_status: "active", "expired", "never"
- email_open_rate (0.0-1.0, NULL for ~15%), last_email_click_date
- event_attendance_count, wealth_score (1-10, NULL for ~40%), notes

**gifts** table: gift_id, contact_id, gift_date, amount, gift_type, campaign
**interactions** table: interaction_id, contact_id, interaction_date, interaction_type, details

Prospects (donor_status="prospect") have NULL for all gift fields — they have never donated.
Lapsed donors have last_gift_date at least 2 years ago.
"""

BASE_SYSTEM_PROMPT = """You are a donor analytics assistant for the Institute for Advanced Studies in Culture (IASC), a nonprofit research center and publisher at the University of Virginia. IASC publishes The Hedgehog Review, a journal of critical reflections on contemporary culture.

You help IASC's development team (primarily Andrew Westhouse, Chief Development Officer, and Rosemary Armato, Development Coordinator) analyze their donor data and make informed decisions about fundraising outreach.

When answering questions:
1. Always use the provided tools to query actual data. Never make up donor names, amounts, or other facts.
2. Explain your reasoning: what filters you applied, how you ranked results, and any assumptions you made.
3. When presenting lists of donors, include key details: name, location, total giving, last gift date, and any relevant engagement indicators.
4. If a query returns no results, say so clearly and suggest how to broaden the search.
5. When recommending donors for meetings or outreach, briefly explain why each person is a good candidate.
6. Be concise but thorough. Development officers need actionable information, not lengthy narratives.
7. When relevant, reference fundraising best practices from your knowledge base to contextualize your recommendations.
8. Use dollar formatting for amounts ($1,234.56) and standard date formats (Month DD, YYYY).
9. If asked about fundraising strategy or best practices, draw on the reference knowledge provided, but note that specific strategic decisions should involve Andrew and Rosemary's institutional knowledge.
10. Keep your explanation aligned with the actual query inputs and results so the dashboard's Data Transparency section accurately reflects the source tables, filters, and ranking logic behind your answer.

Context about IASC's fundraising:
- IASC is a small nonprofit; their donor base is in the hundreds, not thousands.
- Most donors give once per year, often in response to year-end appeals.
- Andrew uses a "center-out" approach: starting with the closest supporters and expanding outward.
- They are in a cultivation phase, focused on acquiring new donors and re-engaging lapsed ones.
- The Hedgehog Review subscriber list is a key source of prospects.
- IASC is based in Charlottesville, Virginia, but has supporters nationwide.
- They track donors in Salesforce, email engagement in MailChimp, and wealth data via WealthEngine.
"""

# Keywords that indicate the user's question needs fundraising best-practice context.
# A false negative just means the response won't reference best practices (minor downside);
# a false positive costs ~2,000 extra input tokens (cheap). Err toward inclusion.
KNOWLEDGE_TRIGGER_KEYWORDS = [
    "best practice", "strategy", "how to", "recommend", "advice",
    "approach", "re-engage", "re-engagement", "cultivate", "cultivation",
    "retention", "pipeline", "moves management", "major gift",
    "prospect research", "donor pyramid", "rfm", "wealth screen",
    "center-out", "stewardship", "solicitation", "annual fund",
    "capital campaign", "planned giving", "donor lifecycle",
    "engagement strategy", "outreach plan", "thank", "acknowledge",
]


def needs_knowledge_base(user_message: str) -> bool:
    """Check whether the user's question likely needs fundraising best-practice context.

    Uses simple keyword matching. This avoids an extra API call; a false negative
    just means the response won't reference best practices (the user can ask a
    follow-up), while a false positive only costs ~2K extra input tokens.
    """
    msg_lower = user_message.lower()
    return any(kw in msg_lower for kw in KNOWLEDGE_TRIGGER_KEYWORDS)


def _build_provider_note(provider: str) -> str:
    """Return provider-specific app context for the system prompt."""
    if provider == "openai":
        return (
            "About this application:\n"
            "- This tool is currently powered by OpenAI's API.\n"
            "- You have a tool called get_app_usage_stats that can retrieve cumulative token usage for this application.\n"
            "- If users ask about API usage, billing, or token consumption, use that tool. "
            "For detailed billing information, direct them to the OpenAI usage and billing dashboard.\n"
        )

    return (
        "About this application:\n"
        "- This tool is currently powered by Anthropic's Claude API.\n"
        "- You have a tool called get_app_usage_stats that can retrieve cumulative token usage for this application.\n"
        "- If users ask about API usage, billing, or token consumption, use that tool. "
        "For detailed billing information, direct them to the Anthropic console at "
        "https://console.anthropic.com/ or https://platform.claude.com/usage.\n"
    )


def build_system_prompt_text(
    include_knowledge: bool = False,
    provider: str = "claude",
) -> str:
    """Assemble a plain-text system prompt for providers that expect a string."""
    prompt = BASE_SYSTEM_PROMPT + "\n" + _build_provider_note(provider) + "\n" + DB_SCHEMA_SUMMARY

    if include_knowledge:
        prompt += "\n\n" + load_knowledge_base()
    else:
        prompt += (
            "\n\nNote: A fundraising best-practices knowledge base is available. "
            "If the user asks about strategy, best practices, or 'how to' questions "
            "about fundraising, let them know you can provide guidance and ask them "
            "to rephrase if needed.\n"
        )

    return prompt


def build_system_prompt(
    include_knowledge: bool = False,
    provider: str = "claude",
) -> list[dict]:
    """Assemble the system prompt as a list of content blocks for the API.

    Returns a list of dicts suitable for the 'system' parameter of messages.create().
    The last block carries cache_control so the entire prefix is cached by the API.

    Args:
        include_knowledge: If True, append the fundraising knowledge base. Set this
                           based on needs_knowledge_base() for the current query.
    """
    base_content = BASE_SYSTEM_PROMPT + "\n" + _build_provider_note(provider) + "\n" + DB_SCHEMA_SUMMARY

    if include_knowledge:
        kb_content = load_knowledge_base()
        # Two blocks: base prompt is a stable cacheable prefix; KB block gets the
        # cache breakpoint so both are cached together on the second call.
        return [
            {"type": "text", "text": base_content},
            {
                "type": "text",
                "text": kb_content,
                "cache_control": {"type": "ephemeral"},
            },
        ]
    else:
        # Single block with a short note so Claude knows the KB exists but isn't loaded.
        # cache_control here caches the base prompt + schema (~1,500 tokens).
        fallback_note = (
            "\n\nNote: A fundraising best-practices knowledge base is available. "
            "If the user asks about strategy, best practices, or 'how to' questions "
            "about fundraising, let them know you can provide guidance and ask them "
            "to rephrase if needed.\n"
        )
        return [
            {
                "type": "text",
                "text": base_content + fallback_note,
                "cache_control": {"type": "ephemeral"},
            },
        ]
