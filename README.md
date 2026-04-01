# IASC Donor Analytics

An AI-powered donor intelligence prototype for the Institute for Advanced Studies in Culture (IASC), a nonprofit research center and publisher at the University of Virginia. The tool lets a development team ask natural language questions about their donor database — "Which lapsed donors in Virginia gave more than $5,000?", "Plan a fundraising trip to NYC", "Who are our highest-potential prospects?" — and receive data-grounded, actionable answers. The default setup uses Claude (Anthropic) for intent parsing and response synthesis, and the configuration layer also includes an OpenAI backend. Python functions query a SQLite database and return structured results; a curated knowledge base of fundraising best practices is injected into the system prompt so every answer is informed by domain expertise.

> **This repository uses entirely synthetic data.** The donor database is generated procedurally by `data/generate_mock_data.py` and contains no real names, contact information, giving history, or any other actual IASC data. No real donor data has ever been committed to this repository.

---

## Setup

```bash
git clone <repo-url>
cd iasc-donor-tool

# Install dependencies (Python 3.11+ required)
pip install -r requirements.txt

# Set your API key(s)
cp .env.example .env
# Open .env and set either ANTHROPIC_API_KEY=... or OPENAI_API_KEY=...

# Generate the mock donor database (300 synthetic records)
python data/generate_mock_data.py

# Launch the app
streamlit run src/app.py
```

The app will open in your browser at `http://localhost:8501`.

### Backend configuration

The app reads API keys from Streamlit secrets first and then from environment variables in `.env`. Backend defaults and model IDs are defined in `src/config.py`.

To use the default Claude backend locally:

```bash
ANTHROPIC_API_KEY=sk-ant-...
LLM_PROVIDER=claude
CLAUDE_MODEL=claude-sonnet-4-20250514
```

To use the OpenAI backend locally:

```bash
OPENAI_API_KEY=sk-proj-...
LLM_PROVIDER=openai
OPENAI_MODEL=gpt-4.1
```

Current model options:

- Claude: `claude-sonnet-4-20250514` or `claude-haiku-4-5-20251001`
- OpenAI: `gpt-4.1` or `gpt-4.1-mini`

If both providers are configured, `LLM_PROVIDER` determines which backend is used. If it is unset, the app defaults to `claude`.

---

## Running in GitHub Codespaces (no local setup required)

1. Click the green **Code** button on the repo page, then **Codespaces > New codespace**.
2. Wait for the environment to build (about 2 minutes the first time).
3. Add your API key as a Codespaces secret: go to github.com > Settings > Codespaces > Secrets,
   create `ANTHROPIC_API_KEY` for Claude or `OPENAI_API_KEY` for OpenAI. If you want OpenAI by default,
   also add `LLM_PROVIDER=openai` and optionally `OPENAI_MODEL=gpt-4.1`.
4. In the Codespace terminal, run: `streamlit run src/app.py`
5. When prompted, click **Open in Browser** to view the app.

The mock database is generated automatically during environment setup.
You do not need to run `generate_mock_data.py` manually.

## Deploying to Streamlit Community Cloud

1. Fork this repo to your own GitHub account.
2. Go to share.streamlit.io and connect your GitHub account.
3. Create a new app, pointing to `src/app.py` in your fork.
4. Under **Advanced settings > Secrets**, paste the contents of `.streamlit/secrets.toml.example`
   and replace the placeholder with your real API key. To use OpenAI on Streamlit Cloud, also add
   `LLM_PROVIDER = "openai"` and optionally `OPENAI_MODEL = "gpt-4.1"` or `OPENAI_MODEL = "gpt-4.1-mini"`.
5. Click **Deploy**. The mock database will be generated automatically on first startup.

Note: do not use real donor data with this deployment. The app has no authentication.

**To rotate the API key after initial deployment:** go to https://share.streamlit.io, find the app, click the three-dot menu (⋮) on the right > **Settings** > **Secrets**, and update the value to the new key in the format `ANTHROPIC_API_KEY = "sk-ant-..."` or `OPENAI_API_KEY = "sk-proj-..."`. The app will restart automatically.

---

## Using the app

**Chat interface:** Type any question about donors in the chat box at the bottom of the page. The configured LLM backend will call one or more data query functions, synthesize the results, and display a response with specific names, amounts, and dates from the database.

**Sample questions:** The left sidebar contains eight pre-written example queries. Click any of them to send it directly to the chat without typing.

**Sidebar stats:** The sidebar shows a live summary of the database — total contacts, active donors, lapsed donors, prospects, total lifetime giving, and average gift — so you always have context at a glance.

**Token usage:** Every assistant response displays an inline usage line below it showing the model used, number of API calls, input/output token counts, estimated cost, and latency. The sidebar accumulates session totals so you can track your spending across a full session.

**Model selection:** In the default Claude configuration, use the Settings section in the sidebar to switch between Claude Sonnet and Claude Haiku. OpenAI backend selection is configured through `LLM_PROVIDER` and `OPENAI_MODEL` as described above.

**Clear conversation:** The "Clear conversation" button at the bottom of the sidebar resets both the chat history and the session token tracker.

---

## Architecture

```
User question (Streamlit chat)
        |
        v
Claude API (Sonnet) with tool use
        |                    \
        v                     v
Python functions that     Knowledge base
query SQLite/pandas       (fundraising best practices,
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

**Key design decisions:**

- **Tool use, not RAG:** Donor data is tabular and well-structured. Claude decides which filters and operations to apply; Python executes parameterized SQL queries. This is more reliable and cheaper than embedding donor records.
- **Knowledge base injection:** Fundraising best practices and IASC-specific context are loaded as markdown and appended to the system prompt on every call. This is simple, transparent, and easy to extend.
- **Token tracking:** Every API call is timed and counted. Costs are displayed inline so users develop intuition for what different query types cost.
- **No LangChain or LlamaIndex:** The tool use loop is implemented directly with the Anthropic SDK. This is intentional — the code is easier to read, debug, and teach.

---

## Project structure

```
iasc-donor-tool/
├── README.md                  # This file
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
│   └── README.md                      # How the knowledge base works
├── src/
│   ├── app.py                 # Main Streamlit application
│   ├── llm.py                 # Claude API integration and tool definitions
│   ├── queries.py             # Data query functions (the "tools" Claude can call)
│   ├── knowledge.py           # Knowledge base loader and formatter
│   ├── prompts.py             # System prompts and prompt templates
│   ├── token_tracker.py       # Token usage tracking and cost estimation
│   └── config.py              # Configuration and constants
├── tests/
│   ├── test_queries.py        # Unit tests for query functions (no API calls)
│   └── test_scenarios.py      # Behavioral tests (make real API calls)
└── docs/
    └── build_log.md           # Development notes and decisions
```

---

## Running tests

```bash
# Unit tests for the data query layer — no API calls, no cost
pytest tests/test_queries.py -v

# All tests except those that call the Claude API
pytest tests/ -k "not llm" -v

# Full behavioral tests: real API calls, real cost (~$0.10-0.50 total)
pytest tests/test_scenarios.py -v

# Run a single scenario by name
pytest tests/test_scenarios.py -v -k "top_donors"
```

The test suite requires `data/donors.db` to exist. If it does not, the query tests will be skipped with a clear message. The scenario tests additionally require `ANTHROPIC_API_KEY` to be set.

---

## Cost estimates

| Scenario | Approximate cost |
|---|---|
| Single query (Sonnet, with tool use) | $0.01 – $0.05 |
| Full behavioral test suite | $0.10 – $0.50 |
| Typical 30-minute session | $0.50 – $2.00 |

The system prompt (base instructions + schema summary + knowledge base) consumes approximately 3,000 – 4,000 tokens on every API call. This is the dominant cost for short queries. The knowledge base token estimate is displayed in the sidebar.

Using Haiku instead of Sonnet reduces costs by roughly 75-80% at the expense of response quality. Switch to Haiku in the sidebar for development and back to Sonnet for demos and evaluations.

---

## Known limitations

- **Mock data only.** The 300-record database is synthetic. Real Salesforce, MailChimp, and WealthEngine integration is out of scope for this prototype.
- **No authentication.** The Streamlit app has no login screen. Do not deploy it publicly with real donor data.
- **No data export.** Query results are displayed in the chat; there is no CSV download or report generation.
- **Wealth scores are estimates.** The mock wealth scores (1-10) approximate WealthEngine output. Real scores would come from the WealthEngine API.
- **Email engagement is approximate.** Open rates and click dates in the mock data simulate MailChimp exports. Real integration would pull live MailChimp data.
- **No persistent conversation history.** Closing and reopening the browser tab starts a fresh session.

---

## How to extend

**Add knowledge base content:** Drop a new `.md` file into `knowledge/` and add a load call in `src/knowledge.py` following the pattern for the existing files. Changes take effect immediately without restarting the app.

**Add a new query function:** Write the function in `src/queries.py` following the existing pattern (returns `{"results": [...], "count": int, "summary": str}`), then add a corresponding tool definition in the `TOOLS` list in `src/llm.py` and a mapping in `TOOL_FUNCTIONS`.

**Replace knowledge injection with RAG:** The `load_knowledge_base()` function in `src/knowledge.py` is the single integration point. Replace it with a retrieval function that takes the user's question and returns relevant passages; the rest of the system remains unchanged.

**Add visualizations:** `plotly` is already installed. After Claude returns a response, the relevant query result (as a dict) can be passed to a `plotly` chart and rendered with `st.plotly_chart()` in `src/app.py`.

**Connect real data:** Replace the SQLite queries in `src/queries.py` with Salesforce API calls (using `simple_salesforce`), MailChimp API calls, or WealthEngine API calls. The function signatures and return formats stay the same; only the data source changes.
