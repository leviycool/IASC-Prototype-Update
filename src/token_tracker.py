"""
Token usage tracker for the IASC donor analytics tool.

Tracks per-response and per-session token usage and estimated costs,
including prompt caching savings. Designed to be displayed inline with
each response and in the Streamlit sidebar.
"""

import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


# Pricing as of early 2025; update these if pricing changes.
# Source: anthropic.com/pricing
MODEL_PRICING = {
    "claude-sonnet-4-20250514": {
        "input_per_mtok": 3.00,
        "output_per_mtok": 15.00,
        "display_name": "Sonnet",
    },
    "claude-haiku-4-5-20251001": {
        "input_per_mtok": 0.80,
        "output_per_mtok": 4.00,
        "display_name": "Haiku",
    },
    "gpt-4.1": {
        "input_per_mtok": 2.00,
        "output_per_mtok": 8.00,
        "display_name": "GPT-4.1",
    },
    "gpt-4.1-mini": {
        "input_per_mtok": 0.40,
        "output_per_mtok": 1.60,
        "display_name": "GPT-4.1 mini",
    },
}


def get_model_pricing(model: str) -> Optional[dict]:
    """Look up pricing metadata for a model."""
    return MODEL_PRICING.get(model)


@dataclass
class APICall:
    """A single API call within a response."""
    timestamp: datetime
    input_tokens: int
    output_tokens: int
    model: str
    had_tool_use: bool
    latency_ms: float
    cache_creation_input_tokens: int = 0  # tokens written to cache (charged at 1.25x)
    cache_read_input_tokens: int = 0      # tokens read from cache (charged at 0.1x)

    def to_dict(self) -> dict:
        """Serialize one API call for persistence."""
        return {
            "timestamp": self.timestamp.isoformat(),
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "model": self.model,
            "had_tool_use": self.had_tool_use,
            "latency_ms": self.latency_ms,
            "cache_creation_input_tokens": self.cache_creation_input_tokens,
            "cache_read_input_tokens": self.cache_read_input_tokens,
        }

    @classmethod
    def from_dict(cls, payload: dict | None) -> "APICall":
        """Rehydrate a persisted API call."""
        data = payload or {}
        timestamp = data.get("timestamp")
        if timestamp:
            parsed_timestamp = datetime.fromisoformat(timestamp)
        else:
            parsed_timestamp = datetime.fromtimestamp(0)

        return cls(
            timestamp=parsed_timestamp,
            input_tokens=int(data.get("input_tokens", 0)),
            output_tokens=int(data.get("output_tokens", 0)),
            model=data.get("model", ""),
            had_tool_use=bool(data.get("had_tool_use", False)),
            latency_ms=float(data.get("latency_ms", 0)),
            cache_creation_input_tokens=int(data.get("cache_creation_input_tokens", 0)),
            cache_read_input_tokens=int(data.get("cache_read_input_tokens", 0)),
        )


@dataclass
class ResponseUsage:
    """Aggregated usage for one user question (may involve multiple API calls)."""
    question: str
    calls: list = field(default_factory=list)
    cache_hit: bool = False

    @property
    def total_input_tokens(self) -> int:
        return sum(c.input_tokens for c in self.calls)

    @property
    def total_output_tokens(self) -> int:
        return sum(c.output_tokens for c in self.calls)

    @property
    def total_tokens(self) -> int:
        return self.total_input_tokens + self.total_output_tokens

    @property
    def num_api_calls(self) -> int:
        return len(self.calls)

    @property
    def total_latency_ms(self) -> float:
        return sum(c.latency_ms for c in self.calls)

    @property
    def total_cache_read_tokens(self) -> int:
        return sum(c.cache_read_input_tokens for c in self.calls)

    @property
    def total_cache_creation_tokens(self) -> int:
        return sum(c.cache_creation_input_tokens for c in self.calls)

    def estimated_cost(self, model: str | None = None) -> float:
        """Estimated cost in dollars, accounting for prompt caching pricing.

        Cache writes: 1.25x normal input rate
        Cache reads:  0.10x normal input rate
        Regular input: 1.00x normal input rate
        """
        total_cost = 0.0
        for call in self.calls:
            pricing = get_model_pricing(call.model or model or "")
            if pricing is None:
                continue
            base_rate = pricing["input_per_mtok"]
            # Regular (non-cached) input tokens
            regular_input = (
                call.input_tokens
                - call.cache_creation_input_tokens
                - call.cache_read_input_tokens
            )
            total_cost += (regular_input / 1_000_000) * base_rate
            # Cache writes at 1.25x
            total_cost += (call.cache_creation_input_tokens / 1_000_000) * base_rate * 1.25
            # Cache reads at 0.10x
            total_cost += (call.cache_read_input_tokens / 1_000_000) * base_rate * 0.1
            # Output tokens
            total_cost += (call.output_tokens / 1_000_000) * pricing["output_per_mtok"]

        return total_cost

    def format_inline(self, model: str | None = None) -> str:
        """Format for display below a chat response."""
        if self.cache_hit and not self.calls:
            return "Stats: cached response reused | 0 API call(s) | $0.0000"
        cost = self.estimated_cost(model)
        models_used = [c.model for c in self.calls if c.model]
        unique_models = list(dict.fromkeys(models_used))
        if len(unique_models) == 1:
            pricing = get_model_pricing(unique_models[0])
            model_name = pricing["display_name"] if pricing else unique_models[0]
        elif unique_models:
            model_name = "Mixed models"
        else:
            model_name = model or "Unknown model"
        cache_info = ""
        if self.total_cache_read_tokens > 0:
            cache_info = f" | {self.total_cache_read_tokens:,} cached"
        return (
            f"Stats: {model_name} | {self.num_api_calls} API call(s) | "
            f"{self.total_input_tokens:,} in + {self.total_output_tokens:,} out tokens"
            f"{cache_info} | "
            f"${cost:.4f} | {self.total_latency_ms:.0f}ms"
        )

    def to_dict(self) -> dict:
        """Serialize one aggregated response for persistence."""
        return {
            "question": self.question,
            "cache_hit": self.cache_hit,
            "calls": [call.to_dict() for call in self.calls],
        }

    @classmethod
    def from_dict(cls, payload: dict | None) -> "ResponseUsage":
        """Rehydrate a persisted response usage payload."""
        data = payload or {}
        usage = cls(
            question=data.get("question", ""),
            cache_hit=bool(data.get("cache_hit", False)),
        )
        usage.calls = [APICall.from_dict(call) for call in data.get("calls", [])]
        return usage


class SessionTracker:
    """Tracks all API usage within a Streamlit session."""

    def __init__(self):
        self.responses: list = []

    @property
    def total_input_tokens(self) -> int:
        return sum(r.total_input_tokens for r in self.responses)

    @property
    def total_output_tokens(self) -> int:
        return sum(r.total_output_tokens for r in self.responses)

    @property
    def total_cost(self) -> float:
        return sum(r.estimated_cost() for r in self.responses)

    @property
    def total_api_calls(self) -> int:
        return sum(r.num_api_calls for r in self.responses)

    def format_sidebar(self) -> str:
        """Format summary for the Streamlit sidebar."""
        return (
            f"- Questions asked: {len(self.responses)}\n"
            f"- API calls: {self.total_api_calls}\n"
            f"- Input tokens: {self.total_input_tokens:,}\n"
            f"- Output tokens: {self.total_output_tokens:,}\n"
            f"- Estimated cost: ${self.total_cost:.4f}\n"
        )

    def to_dict(self) -> dict:
        """Serialize the full tracker for persistence or debugging."""
        return {"responses": [response.to_dict() for response in self.responses]}

    @classmethod
    def from_dict(cls, payload: dict | None) -> "SessionTracker":
        """Rehydrate a serialized tracker."""
        tracker = cls()
        for response in (payload or {}).get("responses", []):
            tracker.responses.append(ResponseUsage.from_dict(response))
        return tracker
