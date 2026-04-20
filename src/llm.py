"""
LLM integration for the IASC donor analytics tool.

This module owns the tool-use conversation loop. It supports the existing
Claude flow used by the app and a compatible OpenAI chat-completions flow for
environments configured with OpenAI models.
"""

import json
import hashlib
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

try:
    import anthropic
    AnthropicRateLimitError = anthropic.RateLimitError
except ModuleNotFoundError:
    anthropic = None

    class AnthropicRateLimitError(Exception):
        """Fallback error type used when anthropic is unavailable."""


try:
    from openai import OpenAI, RateLimitError as OpenAIRateLimitError
except ModuleNotFoundError:
    OpenAI = None

    class OpenAIRateLimitError(Exception):
        """Fallback error type used when openai is unavailable."""

sys.path.insert(0, str(Path(__file__).parent))

import queries
from config import (
    DEFAULT_MODEL,
    LLM_TEMPERATURE,
    MAX_TOOL_CALLS_PER_TURN,
    RESPONSE_CACHE_ENABLED,
    get_api_key_for_provider,
    get_base_url_for_provider,
)
from prompts import (
    build_system_prompt,
    build_system_prompt_text,
    needs_knowledge_base,
)
from task_memory import build_contextual_prompt
from response_cache import get_cached_response, put_cached_response
from token_tracker import APICall, ResponseUsage, SessionTracker
from usage_store import get_usage_summary, log_api_call


TOOLS = [
    {
        "name": "search_donors",
        "description": (
            "Search and filter the donor database. Returns matching contacts with key "
            "fields. Use this for any question about finding, filtering, or listing donors."
        ),
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
            "required": [],
        },
    },
    {
        "name": "get_donor_detail",
        "description": (
            "Get complete information about a single donor including gift history and "
            "interactions. Use when the user asks about a specific person."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "contact_id": {"type": "string", "description": "The contact's unique ID"},
            },
            "required": ["contact_id"],
        },
    },
    {
        "name": "get_summary_statistics",
        "description": (
            "Get aggregate statistics about the donor base. Use for questions about "
            "totals, averages, distributions, and comparisons across segments."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "group_by": {"type": "string", "enum": ["state", "donor_status", "subscription_type", "giving_vehicle"], "description": "Group results by this field"},
                "filter_status": {"type": "string", "enum": ["active", "lapsed", "prospect", "new_donor"], "description": "Only include donors with this status"},
                "filter_state": {"type": "string", "description": "Only include donors from this state"},
            },
            "required": [],
        },
    },
    {
        "name": "get_geographic_distribution",
        "description": (
            "Get donor counts and total giving by state. Use for geographic analysis "
            "and trip planning questions."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "min_total_gifts": {"type": "number", "description": "Only include donors above this giving threshold"},
                "donor_status": {"type": "string", "enum": ["active", "lapsed", "prospect", "new_donor"]},
                "top_n": {"type": "integer", "description": "Number of top states to return (default: 15)"},
            },
            "required": [],
        },
    },
    {
        "name": "get_lapsed_donors",
        "description": (
            "Find donors who haven't given recently but have a giving history. Use for "
            "re-engagement and lapsed donor questions."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "months_since_last_gift": {"type": "integer", "description": "How many months since last gift to be considered lapsed (default: 24)"},
                "min_previous_total": {"type": "number", "description": "Minimum lifetime giving to include"},
                "state": {"type": "string", "description": "Filter by state"},
                "limit": {"type": "integer", "description": "Max results (default: 20)"},
            },
            "required": [],
        },
    },
    {
        "name": "get_prospects_by_potential",
        "description": (
            "Find prospects (non-donors) ranked by engagement signals and wealth "
            "indicators. Use for prospecting and lead generation questions."
        ),
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
            "required": [],
        },
    },
    {
        "name": "get_app_usage_stats",
        "description": (
            "Get cumulative token usage and cost statistics for this application. Use "
            "this when the user asks about API usage, token consumption, costs, or "
            "billing. Can filter by date range or model."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "since": {"type": "string", "description": "ISO date (YYYY-MM-DD) to filter usage from. Omit for all-time stats."},
                "model": {"type": "string", "description": "Filter to a specific model name. Omit for all models."},
            },
            "required": [],
        },
    },
    {
        "name": "plan_fundraising_trip",
        "description": (
            "Find the best contacts to meet during a fundraising trip to a specific "
            "area. Ranks by composite score: giving history, wealth, engagement, "
            "recency, subscription. Use for trip planning questions."
        ),
        "cache_control": {"type": "ephemeral"},
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
            "required": [],
        },
    },
]

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

MAX_RETRIES = 3
RESPONSE_CACHE_VERSION = 1
RESPONSE_CACHE_FINGERPRINT_PATHS = (
    Path(__file__),
    Path(__file__).with_name("prompts.py"),
    Path(__file__).with_name("queries.py"),
)


def execute_tool(tool_name: str, tool_input: dict) -> str:
    """Execute a tool call and return the result as JSON."""
    if tool_name not in TOOL_FUNCTIONS:
        return json.dumps({"error": f"Unknown tool: {tool_name}"})

    try:
        result = TOOL_FUNCTIONS[tool_name](**tool_input)
        return json.dumps(result, default=str)
    except TypeError as exc:
        return json.dumps({"error": f"Invalid parameters for {tool_name}: {exc}"})
    except Exception as exc:
        return json.dumps({"error": f"Tool execution failed: {exc}"})


def _response_cache_fingerprint(active_db_path: str | None = None) -> list[dict]:
    """Capture the parts of local state that should invalidate cached answers."""
    fingerprint: list[dict] = []
    fingerprint_paths = list(RESPONSE_CACHE_FINGERPRINT_PATHS)
    if active_db_path:
        fingerprint_paths.append(Path(active_db_path))
    else:
        fingerprint_paths.append(Path(__file__).parent.parent / "data" / "donors.db")

    for path in fingerprint_paths:
        if path.exists():
            stat = path.stat()
            fingerprint.append(
                {
                    "path": str(path),
                    "mtime_ns": stat.st_mtime_ns,
                    "size": stat.st_size,
                }
            )
        else:
            fingerprint.append(
                {
                    "path": str(path),
                    "missing": True,
                }
            )
    return fingerprint


def _build_response_cache_key(
    provider: str,
    model: str,
    system_prompt,
    user_message: str,
    conversation_history: list[dict],
    active_db_path: str | None = None,
) -> str:
    """Hash the effective request so identical inputs can reuse exact answers."""
    payload = {
        "version": RESPONSE_CACHE_VERSION,
        "provider": provider,
        "model": model,
        "system_prompt": system_prompt,
        "user_message": user_message.strip(),
        "conversation_history": conversation_history,
        "current_date": datetime.now().date().isoformat(),
        "active_db_path": active_db_path,
        "fingerprint": _response_cache_fingerprint(active_db_path),
    }
    payload_json = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(payload_json.encode("utf-8")).hexdigest()


def _maybe_get_cached_response(
    cache_key: str,
    response_usage: ResponseUsage,
    progress_callback: Optional[Callable[[str], None]],
) -> Optional[tuple[str, ResponseUsage]]:
    """Return a cached exact-match response when caching is enabled."""
    if not RESPONSE_CACHE_ENABLED:
        return None

    cached_response = get_cached_response(cache_key)
    if cached_response is None:
        return None

    response_usage.cache_hit = True
    if progress_callback:
        progress_callback("Reusing cached answer...")
    return cached_response, response_usage


def _summarize_tool_params(tool_name: str, params: dict) -> str:
    """Create a short summary for status updates."""
    if not params:
        return ""
    items = []
    for key, value in list(params.items())[:3]:
        if isinstance(value, str) and len(value) > 20:
            value = value[:17] + "..."
        items.append(f"{key}={value!r}")
    suffix = ", ..." if len(params) > 3 else ""
    return ", ".join(items) + suffix


def _provider_for_model(model: str) -> str:
    if model.startswith("gpt-"):
        return "openai"
    return "claude"


def _normalize_progress_message(message: str) -> str:
    """Keep status text short and provider-neutral in the UI."""
    if message.startswith("OpenAI requested a regional endpoint; retrying"):
        return "Generating answer..."
    return message


def _build_openai_client(api_key: str, base_url: str | None = None):
    client_kwargs = {"api_key": api_key}
    if base_url:
        client_kwargs["base_url"] = base_url
    return OpenAI(**client_kwargs)


def _infer_openai_base_url_from_error(exc: Exception) -> str | None:
    """Extract a regional OpenAI hostname from an API error, if present."""
    message = str(exc)
    match = re.search(r"request to ([a-z]{2}\.api\.openai\.com)", message)
    if not match:
        return None
    return f"https://{match.group(1)}/v1"


def _openai_tools() -> list[dict]:
    tools = []
    for tool in TOOLS:
        tools.append(
            {
                "type": "function",
                "function": {
                    "name": tool["name"],
                    "description": tool["description"],
                    "parameters": tool["input_schema"],
                },
            }
        )
    return tools


def _log_usage(
    response_usage: ResponseUsage,
    api_call: APICall,
    user_message: str,
    st_session_id: Optional[str],
) -> None:
    response_usage.calls.append(api_call)
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


def _finalize_response(
    final_text: str,
    response_usage: ResponseUsage,
    session_tracker: Optional[SessionTracker],
) -> tuple[str, ResponseUsage]:
    if session_tracker is not None:
        session_tracker.responses.append(response_usage)
    return final_text, response_usage


def _should_include_knowledge_base(
    user_message: str,
    task_state: Optional[dict],
) -> bool:
    """Decide whether to include the fundraising best-practices knowledge base."""
    if needs_knowledge_base(user_message):
        return True
    return (task_state or {}).get("task_type") == "strategy_guidance"


def _get_claude_response(
    user_message: str,
    conversation_history: list[dict],
    model: str,
    session_tracker: Optional[SessionTracker],
    progress_callback: Optional[Callable[[str], None]],
    st_session_id: Optional[str],
    task_state: Optional[dict],
    turn_type: Optional[str],
    use_prior_context: bool,
    active_db_path: Optional[str],
) -> tuple[str, ResponseUsage]:
    if anthropic is None:
        raise RuntimeError(
            "The `anthropic` package is not installed. Add it to the environment "
            "or switch to the OpenAI backend."
        )
    api_key = get_api_key_for_provider("claude")
    if not api_key:
        raise RuntimeError("Missing ANTHROPIC_API_KEY for the Claude backend.")

    client = anthropic.Anthropic(api_key=api_key)
    include_kb = _should_include_knowledge_base(user_message, task_state)
    system_prompt = build_system_prompt(
        include_knowledge=include_kb,
        provider="claude",
    )
    effective_user_message = build_contextual_prompt(
        message=user_message,
        task_state=task_state,
        chat_history=conversation_history,
        turn_type=turn_type,
        use_prior_context=use_prior_context,
    )
    messages = conversation_history + [{"role": "user", "content": effective_user_message}]
    response_usage = ResponseUsage(question=user_message)
    cache_key = _build_response_cache_key(
        provider="claude",
        model=model,
        system_prompt=system_prompt,
        user_message=effective_user_message,
        conversation_history=conversation_history,
        active_db_path=active_db_path,
    )
    tool_call_count = 0

    def update_progress(message: str) -> None:
        if progress_callback:
            progress_callback(_normalize_progress_message(message))

    cached_result = _maybe_get_cached_response(cache_key, response_usage, progress_callback)
    if cached_result is not None:
        cached_text, cached_usage = cached_result
        return _finalize_response(cached_text, cached_usage, session_tracker)

    if include_kb:
        update_progress("Loading fundraising knowledge base...")
    update_progress("Analyzing your question...")

    while tool_call_count <= MAX_TOOL_CALLS_PER_TURN:
        start_time = time.time()
        response = None

        for attempt in range(MAX_RETRIES):
            try:
                response = client.messages.create(
                    model=model,
                    max_tokens=4096,
                    temperature=LLM_TEMPERATURE,
                    system=system_prompt,
                    tools=TOOLS,
                    messages=messages,
                )
                break
            except AnthropicRateLimitError:
                if attempt == MAX_RETRIES - 1:
                    raise
                wait_time = 2 ** attempt * 5
                update_progress(
                    f"Rate limited; waiting {wait_time}s before retry "
                    f"({attempt + 1}/{MAX_RETRIES})..."
                )
                time.sleep(wait_time)

        latency_ms = (time.time() - start_time) * 1000
        had_tool_use = any(block.type == "tool_use" for block in response.content)
        api_call = APICall(
            timestamp=datetime.now(),
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            model=model,
            had_tool_use=had_tool_use,
            latency_ms=latency_ms,
            cache_creation_input_tokens=getattr(response.usage, "cache_creation_input_tokens", 0) or 0,
            cache_read_input_tokens=getattr(response.usage, "cache_read_input_tokens", 0) or 0,
        )
        _log_usage(response_usage, api_call, user_message, st_session_id)

        if response.stop_reason == "end_turn" or not had_tool_use:
            text_blocks = [block.text for block in response.content if hasattr(block, "text")]
            final_text = "\n".join(text_blocks) if text_blocks else "(No response generated)"
            if RESPONSE_CACHE_ENABLED:
                put_cached_response(cache_key, "claude", model, final_text)
            return _finalize_response(final_text, response_usage, session_tracker)

        tool_results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            tool_call_count += 1
            params_summary = _summarize_tool_params(block.name, block.input)
            update_progress(f"Querying: {block.name}({params_summary})")
            result_str = execute_tool(block.name, block.input)
            tool_results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": result_str,
                }
            )

        update_progress("Interpreting results...")
        messages.append({"role": "assistant", "content": response.content})
        messages.append({"role": "user", "content": tool_results})

    return _finalize_response(
        "I reached the maximum number of tool calls for this question. Please try a more specific query.",
        response_usage,
        session_tracker,
    )


def _get_openai_response(
    user_message: str,
    conversation_history: list[dict],
    model: str,
    session_tracker: Optional[SessionTracker],
    progress_callback: Optional[Callable[[str], None]],
    st_session_id: Optional[str],
    task_state: Optional[dict],
    turn_type: Optional[str],
    use_prior_context: bool,
    active_db_path: Optional[str],
) -> tuple[str, ResponseUsage]:
    if OpenAI is None:
        raise RuntimeError(
            "The `openai` package is not installed. Add it to the environment "
            "or switch to the Claude backend."
        )
    api_key = get_api_key_for_provider("openai")
    if not api_key:
        raise RuntimeError("Missing OPENAI_API_KEY for the OpenAI backend.")
    base_url = get_base_url_for_provider("openai")
    client = _build_openai_client(api_key, base_url)
    include_kb = _should_include_knowledge_base(user_message, task_state)
    system_prompt = build_system_prompt_text(
        include_knowledge=include_kb,
        provider="openai",
    )
    effective_user_message = build_contextual_prompt(
        message=user_message,
        task_state=task_state,
        chat_history=conversation_history,
        turn_type=turn_type,
        use_prior_context=use_prior_context,
    )
    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(conversation_history)
    messages.append({"role": "user", "content": effective_user_message})
    response_usage = ResponseUsage(question=user_message)
    cache_key = _build_response_cache_key(
        provider="openai",
        model=model,
        system_prompt=system_prompt,
        user_message=effective_user_message,
        conversation_history=conversation_history,
        active_db_path=active_db_path,
    )
    tool_call_count = 0
    openai_tools = _openai_tools()

    def update_progress(message: str) -> None:
        if progress_callback:
            progress_callback(_normalize_progress_message(message))

    cached_result = _maybe_get_cached_response(cache_key, response_usage, progress_callback)
    if cached_result is not None:
        cached_text, cached_usage = cached_result
        return _finalize_response(cached_text, cached_usage, session_tracker)

    if include_kb:
        update_progress("Loading fundraising knowledge base...")
    update_progress("Analyzing your question...")

    while tool_call_count <= MAX_TOOL_CALLS_PER_TURN:
        start_time = time.time()
        response = None

        for attempt in range(MAX_RETRIES):
            try:
                response = client.chat.completions.create(
                    model=model,
                    max_tokens=4096,
                    temperature=LLM_TEMPERATURE,
                    messages=messages,
                    tools=openai_tools,
                    tool_choice="auto",
                )
                break
            except OpenAIRateLimitError:
                if attempt == MAX_RETRIES - 1:
                    raise
                wait_time = 2 ** attempt * 5
                update_progress(
                    f"Rate limited; waiting {wait_time}s before retry "
                    f"({attempt + 1}/{MAX_RETRIES})..."
                )
                time.sleep(wait_time)
            except Exception as exc:
                inferred_base_url = _infer_openai_base_url_from_error(exc)
                if inferred_base_url and inferred_base_url != base_url:
                    base_url = inferred_base_url
                    client = _build_openai_client(api_key, base_url)
                    update_progress(
                        f"OpenAI requested a regional endpoint; retrying with {base_url}..."
                    )
                    continue
                raise

        latency_ms = (time.time() - start_time) * 1000
        message = response.choices[0].message
        tool_calls = list(message.tool_calls or [])
        api_call = APICall(
            timestamp=datetime.now(),
            input_tokens=(response.usage.prompt_tokens if response.usage else 0) or 0,
            output_tokens=(response.usage.completion_tokens if response.usage else 0) or 0,
            model=model,
            had_tool_use=bool(tool_calls),
            latency_ms=latency_ms,
        )
        _log_usage(response_usage, api_call, user_message, st_session_id)

        if not tool_calls:
            final_text = message.content or "(No response generated)"
            if RESPONSE_CACHE_ENABLED:
                put_cached_response(cache_key, "openai", model, final_text)
            return _finalize_response(final_text, response_usage, session_tracker)

        messages.append(message.model_dump(exclude_none=True))

        for tool_call in tool_calls:
            tool_call_count += 1
            tool_input = json.loads(tool_call.function.arguments or "{}")
            params_summary = _summarize_tool_params(tool_call.function.name, tool_input)
            update_progress(f"Querying: {tool_call.function.name}({params_summary})")
            result_str = execute_tool(tool_call.function.name, tool_input)
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": result_str,
                }
            )

        update_progress("Interpreting results...")

    return _finalize_response(
        "I reached the maximum number of tool calls for this question. Please try a more specific query.",
        response_usage,
        session_tracker,
    )


def get_response(
    user_message: str,
    conversation_history: list[dict],
    model: str = DEFAULT_MODEL,
    session_tracker: Optional[SessionTracker] = None,
    progress_callback: Optional[Callable[[str], None]] = None,
    st_session_id: Optional[str] = None,
    task_state: Optional[dict] = None,
    turn_type: Optional[str] = None,
    use_prior_context: bool = False,
    active_db_path: Optional[str] = None,
) -> tuple[str, ResponseUsage]:
    """Send a user message through the full tool-use loop."""
    provider = _provider_for_model(model)
    if provider == "openai":
        return _get_openai_response(
            user_message=user_message,
            conversation_history=conversation_history,
            model=model,
            session_tracker=session_tracker,
            progress_callback=progress_callback,
            st_session_id=st_session_id,
            task_state=task_state,
            turn_type=turn_type,
            use_prior_context=use_prior_context,
            active_db_path=active_db_path,
        )
    return _get_claude_response(
        user_message=user_message,
        conversation_history=conversation_history,
        model=model,
        session_tracker=session_tracker,
        progress_callback=progress_callback,
        st_session_id=st_session_id,
        task_state=task_state,
        turn_type=turn_type,
        use_prior_context=use_prior_context,
        active_db_path=active_db_path,
    )
