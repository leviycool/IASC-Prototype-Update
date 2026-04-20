"""
Helpers for session-scoped task memory and follow-up continuity.

The Streamlit app stores this structure in session state so each user turn can
be classified and merged into an active analytical task without rebuilding the
UI or chat architecture.
"""

from __future__ import annotations

import copy
import re
import uuid
from typing import Any


TASK_MEMORY_TEMPLATE = {
    "task_id": None,
    "task_title": None,
    "task_type": None,
    "status": "idle",
    "current_segment": None,
    "current_geography": None,
    "active_filters": {},
    "current_shortlist": [],
    "last_conclusion": None,
    "open_followups": [],
    "last_user_intent": None,
    "memory_active": False,
    "last_updated_turn": 0,
}

US_STATE_NAMES = {
    "alabama": "Alabama",
    "alaska": "Alaska",
    "arizona": "Arizona",
    "arkansas": "Arkansas",
    "california": "California",
    "colorado": "Colorado",
    "connecticut": "Connecticut",
    "delaware": "Delaware",
    "florida": "Florida",
    "georgia": "Georgia",
    "hawaii": "Hawaii",
    "idaho": "Idaho",
    "illinois": "Illinois",
    "indiana": "Indiana",
    "iowa": "Iowa",
    "kansas": "Kansas",
    "kentucky": "Kentucky",
    "louisiana": "Louisiana",
    "maine": "Maine",
    "maryland": "Maryland",
    "massachusetts": "Massachusetts",
    "michigan": "Michigan",
    "minnesota": "Minnesota",
    "mississippi": "Mississippi",
    "missouri": "Missouri",
    "montana": "Montana",
    "nebraska": "Nebraska",
    "nevada": "Nevada",
    "new hampshire": "New Hampshire",
    "new jersey": "New Jersey",
    "new mexico": "New Mexico",
    "new york": "New York",
    "north carolina": "North Carolina",
    "north dakota": "North Dakota",
    "ohio": "Ohio",
    "oklahoma": "Oklahoma",
    "oregon": "Oregon",
    "pennsylvania": "Pennsylvania",
    "rhode island": "Rhode Island",
    "south carolina": "South Carolina",
    "south dakota": "South Dakota",
    "tennessee": "Tennessee",
    "texas": "Texas",
    "utah": "Utah",
    "vermont": "Vermont",
    "virginia": "Virginia",
    "washington": "Washington",
    "west virginia": "West Virginia",
    "wisconsin": "Wisconsin",
    "wyoming": "Wyoming",
    "district of columbia": "Washington, DC",
}

STATE_CODE_TO_NAME = {
    "AL": "Alabama",
    "AK": "Alaska",
    "AZ": "Arizona",
    "AR": "Arkansas",
    "CA": "California",
    "CO": "Colorado",
    "CT": "Connecticut",
    "DE": "Delaware",
    "FL": "Florida",
    "GA": "Georgia",
    "HI": "Hawaii",
    "ID": "Idaho",
    "IL": "Illinois",
    "IN": "Indiana",
    "IA": "Iowa",
    "KS": "Kansas",
    "KY": "Kentucky",
    "LA": "Louisiana",
    "ME": "Maine",
    "MD": "Maryland",
    "MA": "Massachusetts",
    "MI": "Michigan",
    "MN": "Minnesota",
    "MS": "Mississippi",
    "MO": "Missouri",
    "MT": "Montana",
    "NE": "Nebraska",
    "NV": "Nevada",
    "NH": "New Hampshire",
    "NJ": "New Jersey",
    "NM": "New Mexico",
    "NY": "New York",
    "NC": "North Carolina",
    "ND": "North Dakota",
    "OH": "Ohio",
    "OK": "Oklahoma",
    "OR": "Oregon",
    "PA": "Pennsylvania",
    "RI": "Rhode Island",
    "SC": "South Carolina",
    "SD": "South Dakota",
    "TN": "Tennessee",
    "TX": "Texas",
    "UT": "Utah",
    "VT": "Vermont",
    "VA": "Virginia",
    "WA": "Washington",
    "WV": "West Virginia",
    "WI": "Wisconsin",
    "WY": "Wyoming",
    "DC": "Washington, DC",
}

CITY_ALIASES = {
    "nyc": "NYC",
    "new york city": "NYC",
    "manhattan": "Manhattan",
    "brooklyn": "Brooklyn",
    "washington dc": "Washington, DC",
    "washington, dc": "Washington, DC",
    "dc": "Washington, DC",
    "d.c.": "Washington, DC",
    "boston": "Boston",
    "charlottesville": "Charlottesville",
    "richmond": "Richmond",
    "los angeles": "Los Angeles",
    "san francisco": "San Francisco",
    "chicago": "Chicago",
    "atlanta": "Atlanta",
}

STRATEGY_KEYWORDS = (
    "best practice",
    "best practices",
    "strategy",
    "how to",
    "approach",
    "advice",
    "recommendation",
    "recommendations",
)

REFINEMENT_KEYWORDS = (
    "only",
    "just",
    "narrow",
    "filter",
    "limit",
    "exclude",
    "include",
    "sort",
    "rank",
    "focus on",
    "show the ones",
)

EXPLANATION_KEYWORDS = (
    "why",
    "how did you",
    "explain",
    "walk me through",
    "what makes",
    "reasoning",
)

CONTINUATION_KEYWORDS = (
    "continue",
    "keep going",
    "go on",
    "what else",
    "who else",
    "show more",
    "more",
    "next",
)

FOLLOW_UP_REFERENCES = (
    "them",
    "those",
    "these",
    "that list",
    "the list",
    "the ones",
    "same group",
    "same people",
    "what about",
)

NEW_TASK_MARKERS = (
    "new question",
    "different question",
    "switch topics",
    "another topic",
    "separate question",
)

SHORTLIST_LINE_PATTERN = re.compile(
    r"^\s*(?:[-*]|\d+\.)\s+(?:\*\*)?([A-Z][A-Za-z'.-]+(?:\s+[A-Z][A-Za-z'.-]+){1,3})(?:\*\*)?",
    re.MULTILINE,
)
SHORTLIST_BOLD_PATTERN = re.compile(
    r"\*\*([A-Z][A-Za-z'.-]+(?:\s+[A-Z][A-Za-z'.-]+){1,3})\*\*"
)


def initialize_task_memory() -> dict[str, Any]:
    """Return a fresh task memory payload for Streamlit session state."""
    return copy.deepcopy(TASK_MEMORY_TEMPLATE)


def reset_task_memory() -> dict[str, Any]:
    """Reset all persisted task context."""
    return initialize_task_memory()


def coerce_task_memory(task_state: dict[str, Any] | None) -> dict[str, Any]:
    """Normalize a stored task object so all expected keys exist."""
    normalized = initialize_task_memory()
    if not task_state:
        return normalized

    for key, default_value in TASK_MEMORY_TEMPLATE.items():
        value = task_state.get(key, default_value)
        if isinstance(default_value, dict):
            normalized[key] = copy.deepcopy(value or {})
        elif isinstance(default_value, list):
            normalized[key] = copy.deepcopy(value or [])
        else:
            normalized[key] = value

    return normalized


def has_active_task(task_state: dict[str, Any] | None) -> bool:
    """Check whether there is an active reusable task in session state."""
    state = coerce_task_memory(task_state)
    return bool(state["memory_active"] and state["task_id"])


def classify_user_message(
    message: str,
    task_state: dict[str, Any] | None,
    chat_history: list[dict] | None,
    is_sample_question: bool = False,
) -> str:
    """Classify the current user message before the model call."""
    state = coerce_task_memory(task_state)
    msg_lower = message.strip().lower()
    inferred = infer_task_attributes(message)

    if is_sample_question:
        return "topic_switch" if has_active_task(state) else "new_task"

    if not has_active_task(state):
        return "new_task"

    if any(marker in msg_lower for marker in NEW_TASK_MARKERS):
        return "topic_switch"

    if _looks_like_topic_switch(msg_lower, inferred, state):
        return "topic_switch"

    if any(msg_lower.startswith(keyword) for keyword in EXPLANATION_KEYWORDS):
        return "explanation"

    if any(keyword in msg_lower for keyword in REFINEMENT_KEYWORDS):
        return "refinement"

    if infer_active_filters(message):
        return "refinement"

    if any(keyword in msg_lower for keyword in CONTINUATION_KEYWORDS):
        return "continuation"

    if any(reference in msg_lower for reference in FOLLOW_UP_REFERENCES):
        return "follow_up"

    if chat_history:
        return "follow_up"

    return "continuation"


def update_task_memory(
    message: str,
    classification: str,
    task_state: dict[str, Any] | None,
    turn_index: int,
) -> dict[str, Any]:
    """Merge the new user message into structured task memory."""
    state = coerce_task_memory(task_state)
    inferred = infer_task_attributes(message)
    starts_new_task = classification in {"new_task", "topic_switch"} or not has_active_task(state)

    if starts_new_task:
        state = initialize_task_memory()
        state["task_id"] = _new_task_id()
        state["task_type"] = inferred["task_type"] or "donor_analysis"
        state["current_segment"] = inferred["current_segment"]
        state["current_geography"] = inferred["current_geography"]
        state["active_filters"] = inferred["active_filters"]
        state["current_shortlist"] = []
        state["last_conclusion"] = None
        state["open_followups"] = []
    else:
        if inferred["task_type"] and inferred["task_type"] != "donor_analysis":
            state["task_type"] = inferred["task_type"]
        if inferred["current_segment"]:
            state["current_segment"] = inferred["current_segment"]
        if inferred["current_geography"]:
            state["current_geography"] = inferred["current_geography"]
        if inferred["active_filters"]:
            state["active_filters"].update(inferred["active_filters"])

    state["task_title"] = build_task_title(state, message)
    state["status"] = "active"
    state["last_user_intent"] = classification
    state["memory_active"] = True
    state["last_updated_turn"] = turn_index
    return state


def update_task_memory_from_response(
    response_text: str,
    task_state: dict[str, Any] | None,
) -> dict[str, Any]:
    """Persist concise conclusions and any shortlist names from the assistant."""
    state = coerce_task_memory(task_state)
    if not has_active_task(state):
        return state

    conclusion = summarize_response_text(response_text)
    if conclusion:
        state["last_conclusion"] = conclusion

    shortlist = extract_shortlist(response_text)
    if shortlist:
        state["current_shortlist"] = shortlist

    return state


def infer_task_attributes(message: str) -> dict[str, Any]:
    """Infer task metadata from a user message or sample question."""
    task_type = infer_task_type(message)
    current_segment = infer_segment(message)
    current_geography = infer_geography(message)
    active_filters = infer_active_filters(message)

    return {
        "task_type": task_type,
        "current_segment": current_segment,
        "current_geography": current_geography,
        "active_filters": active_filters,
    }


def infer_task_type(message: str) -> str:
    """Guess the active task type from the user's wording."""
    msg_lower = message.strip().lower()

    if any(term in msg_lower for term in ("trip", "meet", "visit", "travel")):
        return "trip_planning"

    if any(term in msg_lower for term in STRATEGY_KEYWORDS):
        return "strategy_guidance"

    if "pipeline" in msg_lower or "distribution" in msg_lower:
        return "portfolio_overview"

    if "prospect" in msg_lower or "never donated" in msg_lower or "subscriber" in msg_lower:
        return "prospecting"

    if any(term in msg_lower for term in ("lapsed", "re-engage", "cultivate", "top donor", "top 10", "shortlist", "prioritize")):
        return "donor_prioritization"

    return "donor_analysis"


def infer_segment(message: str) -> str | None:
    """Extract the donor segment or analytical cohort from the message."""
    msg_lower = message.lower()

    if "lapsed donor" in msg_lower or "lapsed donors" in msg_lower:
        return "lapsed donors"
    if "new donor" in msg_lower or "new donors" in msg_lower:
        return "new donors"
    if "active donor" in msg_lower or "active donors" in msg_lower:
        return "active donors"
    if "prospect" in msg_lower or "prospects" in msg_lower:
        return "prospects"
    if "subscriber" in msg_lower and "never donated" in msg_lower:
        return "subscribers who have never donated"
    if "top donor" in msg_lower or "top 10 donors" in msg_lower or "top 5 donors" in msg_lower:
        return "top donors"
    if "stock" in msg_lower or "daf" in msg_lower:
        return "donors giving via stock or DAF"

    return None


def infer_geography(message: str) -> str | None:
    """Extract a normalized geography label from the user's message."""
    msg_lower = message.lower()

    for alias, label in CITY_ALIASES.items():
        if re.search(rf"\b{re.escape(alias)}\b", msg_lower):
            return label

    for state_name, normalized in US_STATE_NAMES.items():
        if re.search(rf"\b{re.escape(state_name)}\b", msg_lower):
            return normalized

    for token in re.findall(r"\b[A-Z]{2}\b", message):
        normalized = STATE_CODE_TO_NAME.get(token)
        if normalized:
            return normalized

    return None


def infer_active_filters(message: str) -> dict[str, str]:
    """Extract human-readable filters that should persist across follow-ups."""
    msg_lower = message.lower()
    filters: dict[str, str] = {}

    wealth_match = re.search(r"wealth score[s]?\s*(?:>=|>|at least|above|over)\s*(\d+)", msg_lower)
    if wealth_match:
        filters["wealth_score"] = f"wealth score >= {wealth_match.group(1)}"
    elif "wealth" in msg_lower and "high" in msg_lower:
        filters["wealth_score"] = "high wealth scores only"

    recent_match = re.search(r"(?:gave|donated|gift).*(?:last|past)\s+(\d+)\s+year", msg_lower)
    if recent_match:
        years = recent_match.group(1)
        filters["recency"] = f"gave in the last {years} years"
    elif "last two years" in msg_lower or "past two years" in msg_lower:
        filters["recency"] = "gave in the last 2 years"
    elif "last year" in msg_lower or "past year" in msg_lower:
        filters["recency"] = "gave in the last year"

    min_gift_match = re.search(r"(?:more than|over|above|at least)\s+\$([\d,]+)", msg_lower)
    if min_gift_match:
        filters["min_total_gifts"] = f"lifetime giving >= ${min_gift_match.group(1)}"

    if "stock" in msg_lower and "daf" in msg_lower:
        filters["giving_vehicle"] = "stock or DAF gifts"
    elif "stock" in msg_lower:
        filters["giving_vehicle"] = "stock gifts"
    elif "daf" in msg_lower:
        filters["giving_vehicle"] = "DAF gifts"

    if "event" in msg_lower and ("attended" in msg_lower or "attendance" in msg_lower):
        filters["event_history"] = "attended at least one event"

    if "email open" in msg_lower and ("high" in msg_lower or "strong" in msg_lower):
        filters["email_engagement"] = "high email open rates"

    return filters


def build_task_title(task_state: dict[str, Any] | None, fallback_message: str) -> str:
    """Create a concise human-readable task title."""
    state = coerce_task_memory(task_state)
    task_type = state.get("task_type") or "donor_analysis"
    segment = state.get("current_segment")
    geography = state.get("current_geography")

    if task_type == "trip_planning":
        return f"Plan fundraising trip to {geography}" if geography else "Plan fundraising trip"

    if task_type == "donor_prioritization":
        if segment and geography:
            return f"Prioritize {segment} in {geography}"
        if segment:
            return f"Prioritize {segment}"

    if task_type == "prospecting":
        return f"Prospecting in {geography}" if geography else "Prospect identification"

    if task_type == "portfolio_overview":
        return "Donor pipeline overview"

    if task_type == "strategy_guidance":
        return "Fundraising strategy guidance"

    cleaned = " ".join(fallback_message.strip().split())
    return cleaned[:80] if cleaned else "Active donor analysis"


def summarize_filters(active_filters: dict[str, str] | None) -> str:
    """Convert persisted filters into a compact display string."""
    if not active_filters:
        return "None"
    return ", ".join(active_filters.values())


def summarize_task_scope(task_state: dict[str, Any] | None) -> str:
    """Summarize the active segment, geography, and filters for the UI."""
    state = coerce_task_memory(task_state)
    if not has_active_task(state):
        return "No active scope"

    parts = []
    if state["current_segment"]:
        parts.append(state["current_segment"])
    if state["current_geography"]:
        parts.append(f"in {state['current_geography']}")
    if state["active_filters"]:
        parts.append(f"filters: {summarize_filters(state['active_filters'])}")

    return " | ".join(parts) if parts else state["task_title"] or "Active donor analysis"


def format_task_context_markdown(task_state: dict[str, Any] | None) -> str:
    """Render the sidebar current-task block as markdown."""
    state = coerce_task_memory(task_state)
    if not has_active_task(state):
        return "No active task."

    last_conclusion = state["last_conclusion"] or "None yet"
    if len(last_conclusion) > 220:
        last_conclusion = last_conclusion[:217].rstrip() + "..."

    return (
        f"- Current task: {state['task_title'] or 'Untitled task'}\n"
        f"- Task type: {state['task_type'] or 'Unknown'}\n"
        f"- Current segment: {state['current_segment'] or 'Not set'}\n"
        f"- Geography: {state['current_geography'] or 'Not set'}\n"
        f"- Active filters: {summarize_filters(state['active_filters'])}\n"
        f"- Last conclusion: {last_conclusion}\n"
        f"- Memory status: {'Active' if state['memory_active'] else 'Inactive'}\n"
    )


def build_contextual_prompt(
    message: str,
    task_state: dict[str, Any] | None,
    chat_history: list[dict] | None,
    turn_type: str | None,
    use_prior_context: bool,
) -> str:
    """Wrap the raw user message with the current task summary for the LLM."""
    state = coerce_task_memory(task_state)
    if not has_active_task(state):
        return message

    shortlist = ", ".join(state["current_shortlist"]) if state["current_shortlist"] else "None yet"
    prior_turns = sum(1 for msg in (chat_history or []) if msg.get("role") == "user")
    transition_guidance = (
        "Treat this as a fresh task and do not carry forward older scope unless the user explicitly asks for it."
        if turn_type in {"new_task", "topic_switch"}
        else "Continue the active task and reuse prior geography, segment, and filters unless the user overrides them."
    )

    lines = [
        "Session task context:",
        f"- Current task summary: {state['task_title'] or 'Active donor analysis'}",
        f"- Task type: {state['task_type'] or 'donor_analysis'}",
        f"- Current segment: {state['current_segment'] or 'Not set'}",
        f"- Geography: {state['current_geography'] or 'Not set'}",
        f"- Active filters: {summarize_filters(state['active_filters'])}",
        f"- Current shortlist: {shortlist}",
        f"- Last conclusion: {state['last_conclusion'] or 'None yet'}",
        f"- Turn classification: {turn_type or state['last_user_intent'] or 'new_task'}",
        f"- Using prior-turn context: {'yes' if use_prior_context else 'no'}",
        f"- Prior user turns in session: {prior_turns}",
        f"- Guidance: {transition_guidance}",
        "",
        f"Current user message: {message}",
    ]
    return "\n".join(lines)


def summarize_response_text(response_text: str) -> str | None:
    """Capture the first substantive paragraph as a reusable conclusion."""
    paragraphs = [segment.strip() for segment in response_text.split("\n\n") if segment.strip()]
    if not paragraphs:
        return None

    summary = _strip_markdown(paragraphs[0])
    if len(summary) > 280:
        summary = summary[:277].rstrip() + "..."
    return summary or None


def extract_shortlist(response_text: str) -> list[str]:
    """Try to extract donor names from bullet lists in the assistant response."""
    matches = SHORTLIST_LINE_PATTERN.findall(response_text)
    matches.extend(SHORTLIST_BOLD_PATTERN.findall(response_text))

    shortlist: list[str] = []
    seen: set[str] = set()
    for raw_name in matches:
        cleaned = _strip_markdown(raw_name)
        if len(cleaned.split()) < 2 or cleaned.lower() in seen:
            continue
        seen.add(cleaned.lower())
        shortlist.append(cleaned)
        if len(shortlist) == 8:
            break
    return shortlist


def _looks_like_topic_switch(
    msg_lower: str,
    inferred: dict[str, Any],
    task_state: dict[str, Any],
) -> bool:
    """Heuristic for detecting when the user is clearly starting a new task."""
    current_type = task_state.get("task_type")
    new_type = inferred.get("task_type")

    if not new_type or new_type == current_type:
        return False

    if any(reference in msg_lower for reference in FOLLOW_UP_REFERENCES):
        return False

    if any(keyword in msg_lower for keyword in REFINEMENT_KEYWORDS):
        return False

    standalone_starts = (
        "who",
        "what",
        "which",
        "where",
        "when",
        "why",
        "how many",
        "how much",
        "show me",
        "plan",
        "compare",
    )
    return msg_lower.startswith(standalone_starts) or msg_lower.endswith("?")


def _new_task_id() -> str:
    """Generate a short readable task identifier for the sidebar."""
    return f"task-{uuid.uuid4().hex[:8]}"


def _strip_markdown(text: str) -> str:
    """Remove simple markdown characters from a short snippet."""
    cleaned = re.sub(r"[*_`>#]", "", text)
    return " ".join(cleaned.split())
