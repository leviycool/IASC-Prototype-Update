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
    DEFAULT_MODEL,
    DEFAULT_PROVIDER,
    get_api_key_for_provider,
    get_default_model_for_provider,
    get_models_for_provider,
)
from data_source import (
    get_default_data_source,
    prepare_uploaded_csv_dataset,
    prepare_uploaded_sqlite_database,
    reset_uploaded_data_source,
)
from llm import get_response
from token_tracker import SessionTracker
from knowledge import get_knowledge_token_estimate
from queries import reset_active_db_path, set_active_db_path
from task_memory import (
    classify_user_message,
    format_task_context_markdown,
    has_active_task,
    initialize_task_memory,
    reset_task_memory,
    sync_memory_with_data_source,
    update_task_memory,
    update_task_memory_from_response,
)

# ─── Page configuration ───────────────────────────────────────────────────────

st.set_page_config(
    page_title=APP_TITLE,
    page_icon="H",  # Hedgehog Review initial
    layout="wide",
)

# ─── Session state initialization ─────────────────────────────────────────────

if "messages" not in st.session_state:
    # Each entry: {"role": str, "content": str, "usage": ResponseUsage|None}
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

if "pending_question_source" not in st.session_state:
    st.session_state.pending_question_source = None

if "session_id" not in st.session_state:
    import uuid
    st.session_state.session_id = str(uuid.uuid4())[:8]

if "data_source" not in st.session_state:
    st.session_state.data_source = get_default_data_source()

if "task_memory" not in st.session_state:
    st.session_state.task_memory = sync_memory_with_data_source(
        initialize_task_memory(),
        st.session_state.data_source,
    )
else:
    st.session_state.task_memory = sync_memory_with_data_source(
        st.session_state.task_memory,
        st.session_state.data_source,
    )

if "current_turn_type" not in st.session_state:
    st.session_state.current_turn_type = None

if "last_response_used_context" not in st.session_state:
    st.session_state.last_response_used_context = False


def _reset_conversation_state(reset_usage: bool = False) -> None:
    """Reset chat and memory while preserving the current data source."""
    st.session_state.messages = []
    if reset_usage:
        st.session_state.tracker = SessionTracker()
    st.session_state.task_memory = sync_memory_with_data_source(
        reset_task_memory(),
        st.session_state.data_source,
    )
    st.session_state.pending_question = None
    st.session_state.pending_question_source = None
    st.session_state.current_turn_type = None
    st.session_state.last_response_used_context = False


active_data_source = st.session_state.data_source
active_db_path = Path(active_data_source["db_path"])

# ─── Sidebar ─────────────────────────────────────────────────────────────────

with st.sidebar:
    st.title(APP_TITLE)
    st.caption(APP_SUBTITLE)
    st.divider()

    # Quick stats from the database — loaded once per sidebar render
    st.subheader("Quick stats")
    if active_db_path.exists():
        try:
            import sqlite3
            conn = sqlite3.connect(f"file:{active_db_path}?mode=ro", uri=True)
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
        st.warning("Active database not found. Upload donor data or switch back to the demo dataset.")

    st.divider()

    st.subheader("Data source")
    st.caption(f"Current source: {active_data_source['label']}")
    st.caption(active_data_source.get("source_note", ""))

    with st.expander("Upload your own data", expanded=False):
        st.caption("Use either one SQLite `.db` file or the three CSV exports used by this app.")
        uploaded_db = st.file_uploader(
            "SQLite donor database",
            type=["db", "sqlite", "sqlite3"],
            key="upload_sqlite_db",
        )
        uploaded_contacts = st.file_uploader(
            "Contacts CSV",
            type=["csv"],
            key="upload_contacts_csv",
        )
        uploaded_gifts = st.file_uploader(
            "Gifts CSV",
            type=["csv"],
            key="upload_gifts_csv",
        )
        uploaded_interactions = st.file_uploader(
            "Interactions CSV",
            type=["csv"],
            key="upload_interactions_csv",
        )

        if st.button("Use uploaded data", key="apply_uploaded_data", use_container_width=True):
            try:
                if uploaded_db is not None:
                    new_data_source = prepare_uploaded_sqlite_database(
                        file_name=uploaded_db.name,
                        file_bytes=uploaded_db.getvalue(),
                        session_id=st.session_state.session_id,
                    )
                elif uploaded_contacts and uploaded_gifts and uploaded_interactions:
                    new_data_source = prepare_uploaded_csv_dataset(
                        contacts_name=uploaded_contacts.name,
                        contacts_bytes=uploaded_contacts.getvalue(),
                        gifts_name=uploaded_gifts.name,
                        gifts_bytes=uploaded_gifts.getvalue(),
                        interactions_name=uploaded_interactions.name,
                        interactions_bytes=uploaded_interactions.getvalue(),
                        session_id=st.session_state.session_id,
                    )
                else:
                    raise ValueError(
                        "Upload either a SQLite `.db` file or all three CSV files: contacts, gifts, and interactions."
                    )

                st.session_state.data_source = new_data_source
                _reset_conversation_state(reset_usage=False)
                st.rerun()
            except Exception as e:
                st.error(f"Could not load uploaded data: {e}")

    if active_data_source["kind"] != "synthetic":
        if st.button("Switch back to demo data", use_container_width=True):
            reset_uploaded_data_source(st.session_state.session_id)
            st.session_state.data_source = get_default_data_source()
            _reset_conversation_state(reset_usage=False)
            st.rerun()

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
            st.session_state.pending_question_source = "sample_question"
            st.rerun()

    st.divider()

    st.subheader("Session memory")
    task_context_markdown = format_task_context_markdown(st.session_state.task_memory)
    if has_active_task(st.session_state.task_memory):
        st.markdown(task_context_markdown)
    else:
        st.caption(task_context_markdown)

    st.divider()

    # Session usage summary
    st.subheader("Session usage")
    session_usage_summary = st.session_state.tracker.format_sidebar()
    session_usage_summary += (
        f"- Memory id: {st.session_state.task_memory.get('memory_id') or 'None'}\n"
        f"- Memory active: {'Yes' if st.session_state.task_memory.get('memory_active') else 'No'}\n"
        f"- Current turn type: {st.session_state.current_turn_type or 'None'}\n"
        f"- Active data source: {st.session_state.data_source['label']}\n"
    )
    st.markdown(session_usage_summary)

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
    if active_data_source["kind"] == "synthetic":
        st.caption("⚠️ All data is synthetic. No real donor information is used.")
    else:
        st.caption(f"Using uploaded donor data: {active_data_source['label']}")

    st.divider()
    if st.button("Clear conversation", use_container_width=True):
        _reset_conversation_state(reset_usage=True)
        st.rerun()

# ─── Main chat area ────────────────────────────────────────────────────────────

st.header(APP_TITLE)
st.caption(APP_SUBTITLE)

if active_data_source["kind"] == "synthetic":
    st.warning(
        "**Synthetic data only.** All donor names, contact details, gift amounts, and "
        "engagement records shown here are computer-generated and fictitious. This prototype "
        "does not contain real IASC donor information, confidential fundraising data, or "
        "personally identifiable information of any kind.",
        icon="⚠️",
    )
else:
    st.info(
        f"Using uploaded donor data for this session: {active_data_source['label']}.",
        icon="📁",
    )

# Render the full conversation history
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])
        # Show token usage inline below each assistant message
        if msg.get("usage") is not None:
            st.caption(msg["usage"].format_inline(st.session_state.selected_model))

# ─── Input handling ────────────────────────────────────────────────────────────

# The chat_input widget always renders at the bottom of the page
user_input = st.chat_input("Ask a question about your donors...")
user_input_source = "chat"

# If a sidebar sample question was clicked on the previous run, use it now.
# We only consume pending_question when there is no direct chat_input (the user
# didn't type something simultaneously, which is theoretically impossible but
# we guard for it anyway).
if st.session_state.pending_question and not user_input:
    user_input = st.session_state.pending_question
    user_input_source = st.session_state.pending_question_source or "sample_question"
    st.session_state.pending_question = None
    st.session_state.pending_question_source = None

if user_input:
    st.session_state.task_memory = sync_memory_with_data_source(
        st.session_state.task_memory,
        st.session_state.data_source,
    )
    turn_index = sum(1 for msg in st.session_state.messages if msg["role"] == "user") + 1
    turn_type = classify_user_message(
        user_input,
        st.session_state.task_memory,
        st.session_state.messages,
        is_sample_question=(user_input_source == "sample_question"),
    )
    use_prior_context = has_active_task(st.session_state.task_memory) and turn_type in {
        "follow_up",
        "refinement",
        "explanation",
        "continuation",
    }
    st.session_state.task_memory = update_task_memory(
        user_input,
        turn_type,
        st.session_state.task_memory,
        turn_index,
    )
    st.session_state.current_turn_type = turn_type
    st.session_state.last_response_used_context = use_prior_context

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
            db_token = set_active_db_path(active_db_path)
            try:
                response_text, response_usage = get_response(
                    user_message=user_input,
                    conversation_history=history,
                    model=st.session_state.selected_model,
                    session_tracker=st.session_state.tracker,
                    progress_callback=lambda msg: status.update(label=msg),
                    st_session_id=st.session_state.session_id,
                    task_state=st.session_state.task_memory,
                    turn_type=turn_type,
                    use_prior_context=use_prior_context,
                    active_db_path=str(active_db_path),
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
            finally:
                reset_active_db_path(db_token)

        st.markdown(response_text)
        if response_usage is not None:
            st.caption(response_usage.format_inline(st.session_state.selected_model))
            st.session_state.task_memory = update_task_memory_from_response(
                response_text,
                st.session_state.task_memory,
            )

    # Persist the assistant message with usage metadata for the next render
    st.session_state.messages.append({
        "role": "assistant",
        "content": response_text,
        "usage": response_usage,
    })

    # Rerun so the sidebar session-usage section (rendered earlier in the
    # script) picks up the tracker update from this response immediately.
    st.rerun()
