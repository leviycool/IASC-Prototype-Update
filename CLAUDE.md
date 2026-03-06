# IASC Donor Analytics Prototype

## Project overview

This is a working prototype of an AI-powered donor analytics tool for the Institute for Advanced Studies in Culture (IASC), a nonprofit publisher at the University of Virginia. IASC publishes The Hedgehog Review, a journal of critical reflections on contemporary culture.

The prototype is being built by the course instructor (Gregory) to understand the technical challenges and provide realistic guidance to 28 graduate students building the production version in QMSS 5055 (Data Science Practicum) at Columbia University.

## What this tool does

IASC's development team (Andrew Westhouse, Chief Development Officer; Rosemary Armato, Development Coordinator) manages donor and prospect information across Salesforce, MailChimp, and WealthEngine. They currently rely on manual effort and institutional memory to identify high-potential donors and prioritize outreach.

This tool lets them ask natural language questions about their donor data and receive actionable, data-grounded answers. Example queries:

- "Which long-term Hedgehog Review subscribers in NYC are likely to become donors?"
- "Which 5 supporters would be most valuable to meet during an April fundraising trip to DC?"
- "Show me lapsed donors who gave more than $1,000 but haven't donated in 3+ years"
- "What's the geographic distribution of our top 50 donors?"
- "Which subscribers show signs of high giving capacity but have never donated?"

## Architecture

```
User question (Streamlit chat)
        |
        v
Claude API (Haiku by default; switchable to Sonnet in UI) with tool use
        |                    \
        v                     v
Python functions that     Knowledge base
query pandas DataFrames   (fundraising best practices,
        |                  injected into system prompt)
        v                     |
Query results returned ------/
to Claude
        |
        v
Claude generates natural language response
with data citations + best practice guidance
        |
        v
Displayed in Streamlit UI
(with token usage and cost per response)
```

Key design decisions:
- Structured queries via function calling (not RAG); donor data is tabular, not unstructured text
- Claude decides which filters and operations to apply; Python executes them
- SQLite for storage; pandas for in-memory analysis
- Fundraising knowledge base loaded as markdown and injected into the system prompt (designed to be replaceable with RAG or a Claude Skill later)
- Token usage tracked per API call and displayed with each response
- Streamlit for the UI
- No LangChain or LlamaIndex needed at this stage

## Tech stack

- Python 3.11+
- Streamlit (UI)
- Anthropic SDK (LLM; Claude Haiku by default, Sonnet available)
- SQLite (data storage)
- pandas (data manipulation and querying)
- plotly (optional charts)

## Project structure

```
iasc-donor-tool/
├── CLAUDE.md                  # This file
├── README.md                  # Setup and usage instructions
├── requirements.txt           # Python dependencies
├── .env.example               # Template for API keys
├── data/
│   ├── generate_mock_data.py  # Script to create synthetic donor database
│   ├── donors.db              # SQLite database (generated)
│   ├── data_dictionary.md     # Field definitions and source mappings
│   └── sample_salesforce.csv  # Real IASC sample (91 records, anonymized)
├── knowledge/
│   ├── fundraising_best_practices.md  # Core knowledge base document
│   ├── iasc_context.md                # IASC-specific organizational context
│   └── README.md                      # How the knowledge base works and how to extend it
├── src/
│   ├── app.py                 # Main Streamlit application
│   ├── llm.py                 # Claude API integration and tool definitions
│   ├── queries.py             # Data query functions (the "tools" Claude can call)
│   ├── knowledge.py           # Knowledge base loader and formatter
│   ├── prompts.py             # System prompts and prompt templates
│   ├── token_tracker.py       # Token usage tracking and cost estimation
│   ├── usage_store.py         # Persistent SQLite log of all API calls across sessions
│   └── config.py              # Configuration and constants
├── tests/
│   ├── test_queries.py        # Unit tests for query functions
│   └── test_scenarios.py      # Behavioral test cases (user scenarios)
└── docs/
    └── build_log.md           # Development notes and decisions
```

## Data context

The real IASC sample has 91 records with 7 columns: Contact ID, Mailing Zip/Postal Code, First Gift Date, Last Gift Date, Average Gift, Total Gifts, Total Number of Gifts. Gift amounts range from $10 to $8.7M; giving histories span 1993-2025; there is a cluster of Virginia 229xx zip codes near Charlottesville (IASC's home base).

The mock dataset expands this to 300 records with additional fields we expect from Salesforce, MailChimp, and WealthEngine: donor status, subscription info, email engagement, event attendance, giving vehicle, and wealth scores. See data/data_dictionary.md for details.

## Coding conventions

- Use type hints for all function signatures
- Keep functions small and well-documented; this is a teaching tool
- Prefer explicit code over clever abstractions
- Log all LLM calls (input tokens, output tokens, latency) for cost tracking
- Use f-strings for formatting; avoid overly complex string templates
- Error messages should be helpful and suggest next steps
- Comments should explain "why" not "what"

## Important constraints

- API budget is limited (roughly $70 for the semester). Default model is **Haiku** (`claude-haiku-4-5-20251001`) for cost efficiency; switch to Sonnet (`claude-sonnet-4-20250514`) in the UI for more complex queries. Avoid Opus unless testing capability differences.
- All donor data is synthetic / anonymized. Never store or display real donor PII.
- The tool should work offline with mock data; real data integration comes later.
- Keep dependencies minimal; students need to understand and modify this code.
- Streamlit is the UI framework (not React, not Flask). Keep it simple.

## Common tasks

- **Initial setup**: `pip install -r requirements.txt && cp .env.example .env`
  - Then add your `ANTHROPIC_API_KEY` to `.env`
- **Run the app**: `streamlit run src/app.py`
- **Regenerate mock data**: `python data/generate_mock_data.py`
- **Run tests**: `pytest tests/`
- **Run tests without LLM calls**: `pytest tests/ -k "not llm"`
- **Check API costs**: Token usage is displayed inline with each response and summarized in the sidebar

## Build strategy: parallel subagents

This project has several independent components that can be built in parallel. When using Claude Code, use subagents (via the Task tool) to parallelize work across independent workstreams:

**Workstream A (data layer):** generate_mock_data.py, data_dictionary.md, sample data validation
**Workstream B (knowledge base):** fundraising_best_practices.md, iasc_context.md, knowledge.py loader
**Workstream C (query functions):** queries.py with all tool functions, test_queries.py
**Workstream D (LLM + UI):** llm.py, token_tracker.py, prompts.py, app.py, config.py

Dependencies: D depends on A, B, and C being complete. A, B, and C are independent of each other and should be built simultaneously. Within each workstream, build files in the order listed.

After all workstreams complete, do a final integration pass: wire everything together in app.py, run the test suite, and verify the end-to-end flow.

## What "good" looks like

A good response from this tool:
1. Answers the actual question asked (not a related but different question)
2. Cites specific data (names, amounts, dates) rather than vague summaries
3. Explains its reasoning ("I filtered for donors in NYC zip codes with last gift before 2023...")
4. Acknowledges limitations ("Note: wealth scores are estimates and may not reflect current capacity")
5. Suggests follow-up actions when appropriate ("You might also want to check their MailChimp engagement before scheduling meetings")

A bad response:
1. Hallucinated donor names or amounts not in the database
2. Ignored geographic or temporal filters in the question
3. Returned raw data dumps without interpretation
4. Made recommendations without supporting data
5. Failed silently (returned generic text when the query returned no results)
