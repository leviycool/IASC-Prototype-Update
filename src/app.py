"""
IASC Donor Analytics — Streamlit application.

Main entry point: streamlit run src/app.py
"""

import sys
from pathlib import Path
import streamlit as st

# Auto-initialize the donor database if it does not exist.
# This runs on first startup in Streamlit Cloud and GitHub Codespaces.
import importlib.util

_db_path = Path(__file__).parent.parent / "data" / "donors.db"
if not _db_path.exists():
    _gen_path = Path(__file__).parent.parent / "data" / "generate_mock_data.py"
    spec = importlib.util.spec_from_file_location("generate_mock_data", _gen_path)
    _gen = importlib.util.module_from_spec(spec)
    _gen.__file__ = str(_gen_path)  # ensures Path(__file__).parent resolves correctly inside the script
    spec.loader.exec_module(_gen)
    _gen.main()  # main() only runs under __name__ == "__main__", so call it explicitly

# Add src to path for imports so this works regardless of where streamlit is launched
sys.path.insert(0, str(Path(__file__).parent))

from config import APP_TITLE, APP_SUBTITLE, AVAILABLE_MODELS, DEFAULT_MODEL, DB_PATH
from llm import get_response
from token_tracker import SessionTracker
from knowledge import get_knowledge_token_estimate

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
        st.warning("Database not found. Run: `python data/generate_mock_data.py`")

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

    # Model selector
    st.subheader("Settings")
    # Build the display list from AVAILABLE_MODELS, preserving order
    model_labels = list(AVAILABLE_MODELS.values())
    current_label = AVAILABLE_MODELS.get(st.session_state.selected_model, model_labels[0])
    selected_label = st.selectbox(
        "Model",
        options=model_labels,
        index=model_labels.index(current_label),
    )
    # Map the chosen label back to a model ID
    for model_id, label in AVAILABLE_MODELS.items():
        if label == selected_label:
            st.session_state.selected_model = model_id
            break

    # Knowledge base size hint — helps students understand token costs
    kb_tokens = get_knowledge_token_estimate()
    st.caption(f"Knowledge base: ~{kb_tokens:,} tokens per query")

    # Clear conversation
    st.divider()
    if st.button("Clear conversation", use_container_width=True):
        st.session_state.messages = []
        st.session_state.tracker = SessionTracker()
        st.rerun()

# ─── Main chat area ────────────────────────────────────────────────────────────

st.header(APP_TITLE)
st.caption(APP_SUBTITLE)

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
                response_text, response_usage = get_response(
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
                    "Please check your ANTHROPIC_API_KEY in `.env` and try again."
                )
                response_usage = None

        st.markdown(response_text)
        if response_usage is not None:
            st.caption(response_usage.format_inline(st.session_state.selected_model))

    # Persist the assistant message with usage metadata for the next render
    st.session_state.messages.append({
        "role": "assistant",
        "content": response_text,
        "usage": response_usage,
    })

    # Rerun so the sidebar session-usage section (rendered earlier in the
    # script) picks up the tracker update from this response immediately.
    st.rerun()
