"""
Claude API integration for the IASC donor analytics tool.

Handles the tool-use conversation loop: sends user messages to Claude,
executes tool calls when Claude requests them, and returns the final response
with token usage metadata.
"""

import json
import time
import sys
from pathlib import Path
from datetime import datetime
from typing import Optional, Callable

import anthropic

sys.path.insert(0, str(Path(__file__).parent))

from config import DEFAULT_MODEL, MAX_TOOL_CALLS_PER_TURN
from prompts import build_system_prompt, needs_knowledge_base
from token_tracker import APICall, ResponseUsage, SessionTracker
from usage_store import log_api_call, get_usage_summary
import queries

# ─── Tool definitions ────────────────────────────────────────────────────────

TOOLS = [
    {
        "name": "search_donors",
        "description": "Search and filter the donor database. Returns matching contacts with key fields. Use this for any question about finding, filtering, or listing donors.",
        "input_schema": {
            "type": "object",
            "properties": {
                "state": {"type": "string", "description": "2-letter state code (e.g., 'VA', 'NY', 'DC')"},
                "city": {"type": "string", "description": "City name (partial match OK)"},
                "zip_prefix": {"type": "string", "description": "ZIP code prefix to match (e.g., '229' for Charlottesville)"},
                "donor_status": {"type": "string", "enum": ["active", "lapsed", "prospect", "new_donor"], "description": "Filter by donor status"},
                "min_total_gifts": {"type": "number", "description": "Minimum lifetime giving total in dollars"},
                "max_total_gifts": {"type": "number", "description": "Maximum lifetime giving total in dollars"},
                "min_gift_count": {"type": "integer", "description": "Minimum number of gifts made"},
                "subscription_type": {"type": "string", "enum": ["print", "digital", "both", "none"], "description": "Hedgehog Review subscription type"},
                "subscription_status": {"type": "string", "enum": ["active", "expired", "never"], "description": "Subscription status"},
                "min_wealth_score": {"type": "integer", "description": "Minimum WealthEngine score (1-10)"},
                "last_gift_before": {"type": "string", "description": "ISO date (YYYY-MM-DD): only contacts whose last gift was before this date"},
                "last_gift_after": {"type": "string", "description": "ISO date (YYYY-MM-DD): only contacts whose last gift was after this date"},
                "min_email_open_rate": {"type": "number", "description": "Minimum email open rate (0.0 to 1.0)"},
                "has_attended_events": {"type": "boolean", "description": "If true, only include contacts who attended at least one event"},
                "giving_vehicle": {"type": "string", "enum": ["check", "online", "stock", "DAF", "wire"], "description": "Filter by how they give"},
                "sort_by": {"type": "string", "description": "Column to sort by (default: total_gifts)"},
                "sort_order": {"type": "string", "enum": ["asc", "desc"], "description": "Sort direction (default: desc)"},
                "limit": {"type": "integer", "description": "Max results to return (default: 20, max: 50)"},
            },
            "required": []
        }
    },
    {
        "name": "get_donor_detail",
        "description": "Get complete information about a single donor including gift history and interactions. Use when the user asks about a specific person.",
        "input_schema": {
            "type": "object",
            "properties": {
                "contact_id": {"type": "string", "description": "The contact's unique ID"}
            },
            "required": ["contact_id"]
        }
    },
    {
        "name": "get_summary_statistics",
        "description": "Get aggregate statistics about the donor base. Use for questions about totals, averages, distributions, and comparisons across segments.",
        "input_schema": {
            "type": "object",
            "properties": {
                "group_by": {"type": "string", "enum": ["state", "donor_status", "subscription_type", "giving_vehicle"], "description": "Group results by this field"},
                "filter_status": {"type": "string", "enum": ["active", "lapsed", "prospect", "new_donor"], "description": "Only include donors with this status"},
                "filter_state": {"type": "string", "description": "Only include donors from this state"},
            },
            "required": []
        }
    },
    {
        "name": "get_geographic_distribution",
        "description": "Get donor counts and total giving by state. Use for geographic analysis and trip planning questions.",
        "input_schema": {
            "type": "object",
            "properties": {
                "min_total_gifts": {"type": "number", "description": "Only include donors above this giving threshold"},
                "donor_status": {"type": "string", "enum": ["active", "lapsed", "prospect", "new_donor"]},
                "top_n": {"type": "integer", "description": "Number of top states to return (default: 15)"},
            },
            "required": []
        }
    },
    {
        "name": "get_lapsed_donors",
        "description": "Find donors who haven't given recently but have a giving history. Use for re-engagement and lapsed donor questions.",
        "input_schema": {
            "type": "object",
            "properties": {
                "months_since_last_gift": {"type": "integer", "description": "How many months since last gift to be considered lapsed (default: 24)"},
                "min_previous_total": {"type": "number", "description": "Minimum lifetime giving to include"},
                "state": {"type": "string", "description": "Filter by state"},
                "limit": {"type": "integer", "description": "Max results (default: 20)"},
            },
            "required": []
        }
    },
    {
        "name": "get_prospects_by_potential",
        "description": "Find prospects (non-donors) ranked by engagement signals and wealth indicators. Use for prospecting and lead generation questions.",
        "input_schema": {
            "type": "object",
            "properties": {
                "has_subscription": {"type": "boolean", "description": "If true, only prospects with an active subscription"},
                "min_wealth_score": {"type": "integer", "description": "Minimum WealthEngine score (1-10)"},
                "min_email_open_rate": {"type": "number", "description": "Minimum email open rate"},
                "has_attended_events": {"type": "boolean", "description": "Only prospects who attended events"},
                "state": {"type": "string", "description": "Filter by state"},
                "limit": {"type": "integer", "description": "Max results (default: 20)"},
            },
            "required": []
        }
    },
    {
        "name": "get_app_usage_stats",
        "description": "Get cumulative token usage and cost statistics for this application. Use this when the user asks about API usage, token consumption, costs, or billing. Can filter by date range or model.",
        "input_schema": {
            "type": "object",
            "properties": {
                "since": {
                    "type": "string",
                    "description": "ISO date (YYYY-MM-DD) to filter usage from. Omit for all-time stats."
                },
                "model": {
                    "type": "string",
                    "description": "Filter to a specific model name. Omit for all models."
                },
            },
            "required": []
        }
    },
    {
        "name": "plan_fundraising_trip",
        "description": "Find the best contacts to meet during a fundraising trip to a specific area. Ranks by composite score: giving history, wealth, engagement, recency, subscription. Use for trip planning questions.",
        "cache_control": {"type": "ephemeral"},  # caches all 8 tool definitions
        "input_schema": {
            "type": "object",
            "properties": {
                "target_city": {"type": "string", "description": "City for the trip"},
                "target_state": {"type": "string", "description": "State code for the trip (e.g., 'NY', 'DC')"},
                "target_zip_prefix": {"type": "string", "description": "ZIP prefix to narrow the area (e.g., '100' for Manhattan)"},
                "min_total_gifts": {"type": "number", "description": "Only include contacts above this giving threshold"},
                "include_prospects": {"type": "boolean", "description": "Include non-donors with strong engagement (default: true)"},
                "include_lapsed": {"type": "boolean", "description": "Include lapsed donors (default: true)"},
                "limit": {"type": "integer", "description": "Number of contacts to return (default: 10)"},
            },
            "required": []
        }
    },
]

# ─── Tool execution ───────────────────────────────────────────────────────────

TOOL_FUNCTIONS = {
    "search_donors": queries.search_donors,
    "get_donor_detail": queries.get_donor_detail,
    "get_summary_statistics": queries.get_summary_statistics,
    "get_geographic_distribution": queries.get_geographic_distribution,
    "get_lapsed_donors": queries.get_lapsed_donors,
    "get_prospects_by_potential": queries.get_prospects_by_potential,
    "plan_fundraising_trip": queries.plan_fundraising_trip,
    "get_app_usage_stats": lambda **kwargs: get_usage_summary(**kwargs),
}


def execute_tool(tool_name: str, tool_input: dict) -> str:
    """Execute a tool call and return the result as a JSON string.

    All results are serialized to JSON so Claude can read them.
    Errors are caught and returned as error messages (not raised)
    so Claude can report them gracefully to the user.
    """
    if tool_name not in TOOL_FUNCTIONS:
        return json.dumps({"error": f"Unknown tool: {tool_name}"})

    try:
        result = TOOL_FUNCTIONS[tool_name](**tool_input)
        return json.dumps(result, default=str)  # default=str handles dates
    except TypeError as e:
        return json.dumps({"error": f"Invalid parameters for {tool_name}: {e}"})
    except Exception as e:
        return json.dumps({"error": f"Tool execution failed: {e}"})


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _summarize_tool_params(tool_name: str, params: dict) -> str:
    """Create a brief human-readable summary of tool call parameters for progress display."""
    if not params:
        return ""
    items = []
    for k, v in list(params.items())[:3]:
        if isinstance(v, str) and len(v) > 20:
            v = v[:17] + "..."
        items.append(f"{k}={v!r}")
    suffix = ", ..." if len(params) > 3 else ""
    return ", ".join(items) + suffix


MAX_RETRIES = 3

# ─── Main conversation function ───────────────────────────────────────────────

def get_response(
    user_message: str,
    conversation_history: list[dict],
    model: str = DEFAULT_MODEL,
    session_tracker: Optional[SessionTracker] = None,
    progress_callback: Optional[Callable[[str], None]] = None,
    st_session_id: Optional[str] = None,
) -> tuple[str, ResponseUsage]:
    """Send a user message through the full tool-use conversation loop.

    Returns:
    - The final text response from Claude
    - A ResponseUsage object with token usage for this question

    The conversation loop:
    1. Decide whether the question needs the knowledge base (keyword check)
    2. Send message + history + tools to Claude
    3. If Claude requests tool calls: execute them, append results, repeat
    4. Once Claude returns a text response: return it

    Token usage is accumulated across all API calls for this one user question.

    Args:
        progress_callback: Optional function that receives status strings for UI display.
                           Called at each step (KB load, tool calls, interpretation).
    """
    client = anthropic.Anthropic()

    def update_progress(msg: str):
        if progress_callback:
            progress_callback(msg)

    # Decide whether to include the knowledge base based on the query content.
    # This skips ~2,000 tokens on pure data queries.
    include_kb = needs_knowledge_base(user_message)
    if include_kb:
        update_progress("Loading fundraising knowledge base...")
    system_prompt = build_system_prompt(include_knowledge=include_kb)

    update_progress("Analyzing your question...")

    # Build the messages list for this turn.
    messages = conversation_history + [{"role": "user", "content": user_message}]

    # Track usage for this response (may span multiple API calls)
    response_usage = ResponseUsage(question=user_message)

    tool_call_count = 0

    while tool_call_count <= MAX_TOOL_CALLS_PER_TURN:
        # Time the API call (with exponential-backoff retry for rate limits)
        start_time = time.time()
        response = None

        for attempt in range(MAX_RETRIES):
            try:
                response = client.messages.create(
                    model=model,
                    max_tokens=4096,
                    system=system_prompt,
                    tools=TOOLS,
                    messages=messages,
                )
                break  # success — exit retry loop
            except anthropic.RateLimitError:
                if attempt < MAX_RETRIES - 1:
                    wait_time = 2 ** attempt * 5  # 5s, 10s, 20s
                    update_progress(
                        f"Rate limited; waiting {wait_time}s before retry "
                        f"({attempt + 1}/{MAX_RETRIES})..."
                    )
                    time.sleep(wait_time)
                else:
                    raise  # re-raise on the final attempt

        latency_ms = (time.time() - start_time) * 1000

        # Record this API call, including cache usage if present
        had_tool_use = any(block.type == "tool_use" for block in response.content)
        api_call = APICall(
            timestamp=datetime.now(),
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            model=model,
            had_tool_use=had_tool_use,
            latency_ms=latency_ms,
            # These fields are only present when caching is active; default to 0
            cache_creation_input_tokens=getattr(response.usage, "cache_creation_input_tokens", 0) or 0,
            cache_read_input_tokens=getattr(response.usage, "cache_read_input_tokens", 0) or 0,
        )
        response_usage.calls.append(api_call)

        # Persist to the cross-session usage log
        log_api_call(
            timestamp=api_call.timestamp,
            model=api_call.model,
            input_tokens=api_call.input_tokens,
            output_tokens=api_call.output_tokens,
            cache_creation_input_tokens=api_call.cache_creation_input_tokens,
            cache_read_input_tokens=api_call.cache_read_input_tokens,
            had_tool_use=api_call.had_tool_use,
            latency_ms=api_call.latency_ms,
            question=user_message,
            session_id=st_session_id,
        )

        # If Claude is done (no tool use), return the text response
        if response.stop_reason == "end_turn" or not had_tool_use:
            text_blocks = [b.text for b in response.content if hasattr(b, "text")]
            final_text = "\n".join(text_blocks) if text_blocks else "(No response generated)"

            if session_tracker is not None:
                session_tracker.responses.append(response_usage)

            return final_text, response_usage

        # Claude wants to call tools — execute them and collect results
        tool_results = []
        for block in response.content:
            if block.type == "tool_use":
                tool_call_count += 1
                params_summary = _summarize_tool_params(block.name, block.input)
                update_progress(f"Querying: {block.name}({params_summary})")
                result_str = execute_tool(block.name, block.input)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": result_str,
                })

        update_progress("Interpreting results...")

        # Append Claude's response (with tool_use blocks) and the tool results.
        # The Anthropic API requires that tool results be sent as a "user" turn
        # following the "assistant" turn that requested the tools.
        messages.append({"role": "assistant", "content": response.content})
        messages.append({"role": "user", "content": tool_results})

    # Safety valve: exceeded MAX_TOOL_CALLS_PER_TURN
    if session_tracker is not None:
        session_tracker.responses.append(response_usage)
    return (
        "I reached the maximum number of tool calls for this question. "
        "Please try a more specific query.",
        response_usage,
    )
