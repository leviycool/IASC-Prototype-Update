"""
IASC Donor Analytics — Streamlit application.

Main entry point: streamlit run src/app.py
"""

import sys
from pathlib import Path
import streamlit as st

# Auto-initialize the donor database if it does not exist.
# Prefer importing the checked-in CSV files so deployments use the latest
# shared dataset, and fall back to generated mock data for developer setups.
import importlib.util

_DATA_DIR = Path(__file__).parent.parent / "data"
_DB_BOOTSTRAP_PATH = _DATA_DIR / "donors.db"
_REQUIRED_CSVS = (
    _DATA_DIR / "synthetic_donors_contacts.csv",
    _DATA_DIR / "synthetic_donors_gifts.csv",
    _DATA_DIR / "synthetic_donors_interactions.csv",
)


def _run_data_script(script_path: Path, module_name: str) -> None:
    spec = importlib.util.spec_from_file_location(module_name, script_path)
    module = importlib.util.module_from_spec(spec)
    module.__file__ = str(script_path)
    if spec.loader is None:
        raise ImportError(f"Could not load {script_path}")
    spec.loader.exec_module(module)

    original_argv = sys.argv[:]
    try:
        sys.argv = [str(script_path)]
        module.main()
    finally:
        sys.argv = original_argv


if not _DB_BOOTSTRAP_PATH.exists():
    importer_path = _DATA_DIR / "import_csv_to_db.py"
    if importer_path.exists() and all(path.exists() for path in _REQUIRED_CSVS):
        _run_data_script(importer_path, "import_csv_to_db")
    else:
        _run_data_script(_DATA_DIR / "generate_mock_data.py", "generate_mock_data")

# Add src to path for imports so this works regardless of where streamlit is launched
sys.path.insert(0, str(Path(__file__).parent))

from config import (
    APP_TITLE,
    APP_SUBTITLE,
    BACKEND_OPTIONS,
    DB_PATH,
    DEFAULT_MODEL,
    DEFAULT_PROVIDER,
    get_api_key_for_provider,
    get_default_model_for_provider,
    get_models_for_provider,
)
from llm import get_response
from token_tracker import SessionTracker
from knowledge import get_knowledge_token_estimate


def _dedupe_preserve_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def _aggregate_provenance(provenance_records: list[dict]) -> dict:
    tools: list[str] = []
    filters: list[str] = []
    notes: list[str] = []
    table_map: dict[str, list[str]] = {}

    for record in provenance_records or []:
        tool_name = record.get("tool")
        if tool_name:
            tools.append(str(tool_name))

        for table in record.get("source_tables", []):
            table_name = table.get("name")
            if not table_name:
                continue
            fields = table_map.setdefault(str(table_name), [])
            for field in table.get("fields", []):
                field_str = str(field)
                if field_str not in fields:
                    fields.append(field_str)

        for filter_item in record.get("filters", []):
            if isinstance(filter_item, dict):
                display = filter_item.get("display")
            else:
                display = str(filter_item)
            if display:
                filters.append(str(display))

        for note in record.get("notes", []):
            if note:
                notes.append(str(note))

    return {
        "tools": _dedupe_preserve_order(tools),
        "tables": [
            {"name": name, "fields": fields}
            for name, fields in table_map.items()
        ],
        "filters": _dedupe_preserve_order(filters),
        "notes": _dedupe_preserve_order(notes),
    }


def _render_data_transparency(provenance_records: list[dict] | None) -> None:
    with st.expander("Data Transparency", expanded=False):
        if not provenance_records:
            st.caption("No donor or usage tables were queried for this answer.")
            return

        aggregated = _aggregate_provenance(provenance_records)

        if aggregated["tools"]:
            st.caption(f"Tool calls: {', '.join(aggregated['tools'])}")

        st.markdown("**Source tables**")
        if aggregated["tables"]:
            for table in aggregated["tables"]:
                fields = ", ".join(table["fields"]) or "No field metadata captured."
                st.write(f"`{table['name']}`: {fields}")
        else:
            st.caption("No source tables were captured for this answer.")

        if aggregated["filters"]:
            st.markdown("**Applied filters**")
            for filter_text in aggregated["filters"]:
                st.caption(filter_text)

        if aggregated["notes"]:
            st.markdown("**Query logic**")
            for note in aggregated["notes"]:
                st.caption(note)

# ─── Page configuration ───────────────────────────────────────────────────────

st.set_page_config(
    page_title=APP_TITLE,
    page_icon="H",  # Hedgehog Review initial
    layout="wide",
)

# ─── Session state initialization ─────────────────────────────────────────────

if "messages" not in st.session_state:
    # Each entry: {"role": str, "content": str, "usage": ResponseUsage|None,
    #              "provenance": list[dict]|None}
    st.session_state.messages = []

if "tracker" not in st.session_state:
    st.session_state.tracker = SessionTracker()

if "selected_model" not in st.session_state:
    st.session_state.selected_model = DEFAULT_MODEL

if "selected_provider" not in st.session_state:
    st.session_state.selected_provider = DEFAULT_PROVIDER

# pending_question is set by sample question buttons and consumed on the next run.
# This is necessary because st.button() callbacks can't directly inject into
# st.chat_input(); instead we store the pending question in session state,
# call st.rerun(), and pick it up as user_input on the next render cycle.
if "pending_question" not in st.session_state:
    st.session_state.pending_question = None

if "session_id" not in st.session_state:
    import uuid
    st.session_state.session_id = str(uuid.uuid4())[:8]

# ─── Sidebar ─────────────────────────────────────────────────────────────────

with st.sidebar:
    st.title(APP_TITLE)
    st.caption(APP_SUBTITLE)
    st.divider()

    # Quick stats from the database — loaded once per sidebar render
    st.subheader("Quick stats")
    if DB_PATH.exists():
        try:
            import sqlite3
            conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()

            stats = cur.execute("""
                SELECT
                    COUNT(*) as total,
                    SUM(CASE WHEN donor_status IN ('active','lapsed','new_donor') THEN 1 ELSE 0 END) as donors,
                    SUM(CASE WHEN donor_status = 'prospect' THEN 1 ELSE 0 END) as prospects,
                    SUM(CASE WHEN donor_status = 'lapsed' THEN 1 ELSE 0 END) as lapsed,
                    SUM(CASE WHEN donor_status = 'active' THEN 1 ELSE 0 END) as active,
                    SUM(CASE WHEN donor_status = 'new_donor' THEN 1 ELSE 0 END) as new_donors,
                    ROUND(SUM(COALESCE(total_gifts, 0)), 0) as total_giving,
                    ROUND(AVG(CASE WHEN average_gift IS NOT NULL THEN average_gift END), 0) as avg_gift
                FROM contacts
            """).fetchone()
            conn.close()

            total_giving_fmt = f"${stats['total_giving']:,.0f}" if stats['total_giving'] else "N/A"
            avg_gift_fmt = f"${stats['avg_gift']:,.0f}" if stats['avg_gift'] else "N/A"

            st.metric("Total contacts", f"{stats['total']:,}")
            col1, col2 = st.columns(2)
            col1.metric("Active donors", stats['active'])
            col2.metric("Lapsed donors", stats['lapsed'])
            col1.metric("Prospects", stats['prospects'])
            col2.metric("New donors", stats['new_donors'])
            st.metric("Total lifetime giving", total_giving_fmt)
            st.metric("Average gift", avg_gift_fmt)
        except Exception as e:
            st.warning(f"Could not load stats: {e}")
    else:
        st.warning("Database not found. Run: `python data/import_csv_to_db.py` or `python data/generate_mock_data.py`")

    st.divider()

    # Sample questions — clicking one sets pending_question and reruns the app
    st.subheader("Sample questions")
    sample_questions = [
        "Who are our top 10 donors by lifetime giving?",
        "Which lapsed donors in Virginia should we re-engage?",
        "Plan a fundraising trip to NYC: who should we meet?",
        "How many subscribers have never donated but have high wealth scores?",
        "What does our donor pipeline look like?",
        "Which new donors from the last year should we cultivate?",
        "Show me donors who gave via stock or DAF",
        "What are best practices for re-engaging lapsed donors?",
    ]

    for q in sample_questions:
        if st.button(q, key=f"sample_{hash(q)}", use_container_width=True):
            st.session_state.pending_question = q
            st.rerun()

    st.divider()

    # Session usage summary
    st.subheader("Session usage")
    st.markdown(st.session_state.tracker.format_sidebar())

    st.divider()

    # Backend + model selector
    st.subheader("Settings")

    backend_options = {
        key: label for key, label in BACKEND_OPTIONS.items()
        if key in {"claude", "openai"}
    }
    backend_keys = list(backend_options.keys())
    if st.session_state.selected_provider not in backend_keys:
        st.session_state.selected_provider = DEFAULT_PROVIDER

    selected_backend = st.selectbox(
        "Backend",
        options=backend_keys,
        index=backend_keys.index(st.session_state.selected_provider),
        format_func=lambda key: backend_options[key],
    )
    st.session_state.selected_provider = selected_backend

    provider_models = get_models_for_provider(selected_backend)
    if st.session_state.selected_model not in provider_models:
        st.session_state.selected_model = get_default_model_for_provider(selected_backend)

    model_labels = list(provider_models.values())
    current_label = provider_models.get(st.session_state.selected_model, model_labels[0])
    selected_label = st.selectbox(
        "Model",
        options=model_labels,
        index=model_labels.index(current_label),
    )

    for model_id, label in provider_models.items():
        if label == selected_label:
            st.session_state.selected_model = model_id
            break

    if not get_api_key_for_provider(selected_backend):
        backend_name = backend_options[selected_backend]
        st.caption(f"{backend_name} API key not configured for this deployment.")

    # Knowledge base size hint — helps students understand token costs
    kb_tokens = get_knowledge_token_estimate()
    st.caption(f"Knowledge base: ~{kb_tokens:,} tokens per query")

    # Clear conversation
    st.divider()
    st.caption("⚠️ All data is synthetic. No real donor information is used.")

    st.divider()
    if st.button("Clear conversation", use_container_width=True):
        st.session_state.messages = []
        st.session_state.tracker = SessionTracker()
        st.rerun()

# ─── Main chat area ────────────────────────────────────────────────────────────

st.header(APP_TITLE)
st.caption(APP_SUBTITLE)

st.warning(
    "**Synthetic data only.** All donor names, contact details, gift amounts, and "
    "engagement records shown here are computer-generated and fictitious. This prototype "
    "does not contain real IASC donor information, confidential fundraising data, or "
    "personally identifiable information of any kind.",
    icon="⚠️",
)

# Render the full conversation history
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])
        if msg["role"] == "assistant":
            _render_data_transparency(msg.get("provenance"))
        # Show token usage inline below each assistant message
        if msg.get("usage") is not None:
            st.caption(msg["usage"].format_inline(st.session_state.selected_model))

# ─── Input handling ────────────────────────────────────────────────────────────

# The chat_input widget always renders at the bottom of the page
user_input = st.chat_input("Ask a question about your donors...")

# If a sidebar sample question was clicked on the previous run, use it now.
# We only consume pending_question when there is no direct chat_input (the user
# didn't type something simultaneously, which is theoretically impossible but
# we guard for it anyway).
if st.session_state.pending_question and not user_input:
    user_input = st.session_state.pending_question
    st.session_state.pending_question = None

if user_input:
    # Immediately display the user's message
    with st.chat_message("user"):
        st.markdown(user_input)
    st.session_state.messages.append({"role": "user", "content": user_input, "usage": None})

    # Build the conversation history to pass to the API.
    # We exclude the message we just appended (it will be the new user_message
    # argument to get_response) and strip the usage metadata the API doesn't need.
    history = [
        {"role": m["role"], "content": m["content"]}
        for m in st.session_state.messages[:-1]
    ]

    # Call Claude with a live progress display using st.status.
    # progress_callback updates the status label at each step so the user can
    # see which tool is being called rather than staring at a static spinner.
    with st.chat_message("assistant"):
        with st.status("Working on your question...", expanded=True) as status:
            try:
                response_text, response_usage, response_provenance = get_response(
                    user_message=user_input,
                    conversation_history=history,
                    model=st.session_state.selected_model,
                    session_tracker=st.session_state.tracker,
                    progress_callback=lambda msg: status.update(label=msg),
                    st_session_id=st.session_state.session_id,
                )
                status.update(label="Done", state="complete", expanded=False)
            except Exception as e:
                status.update(label="Error", state="error", expanded=False)
                response_text = (
                    f"**Error:** {e}\n\n"
                    "Please check your configured API key (`ANTHROPIC_API_KEY` or "
                    "`OPENAI_API_KEY`) in `.env` or Streamlit secrets and try again. "
                    "If your OpenAI project uses a regional endpoint, also set "
                    "`OPENAI_BASE_URL` (for example `https://us.api.openai.com/v1`)."
                )
                response_usage = None
                response_provenance = None

        st.markdown(response_text)
        _render_data_transparency(response_provenance)
        if response_usage is not None:
            st.caption(response_usage.format_inline(st.session_state.selected_model))

    # Persist the assistant message with usage metadata for the next render
    st.session_state.messages.append({
        "role": "assistant",
        "content": response_text,
        "usage": response_usage,
        "provenance": response_provenance,
    })

    # Rerun so the sidebar session-usage section (rendered earlier in the
    # script) picks up the tracker update from this response immediately.
    st.rerun()
