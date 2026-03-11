"""Streamlit web UI for the Echo AI agent."""

import sys
import os
import asyncio
import streamlit as st
import httpx
from typing import Any

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from src.agentframework.agent import AgentConfig, create_agent

# Make sure we have an event loop running in the streamlit thread
try:
    asyncio.get_running_loop()
except RuntimeError:
    asyncio.set_event_loop(asyncio.new_event_loop())


def initialize_session_state():
    """Initialize Streamlit session state variables."""
    if "messages" not in st.session_state:
        st.session_state.messages = []
    if "agent" not in st.session_state:
        config = AgentConfig(provider="ollama", model="qwen3:4b-instruct")
        st.session_state.agent = create_agent(config)
    if "theme" not in st.session_state:
        st.session_state.theme = "dark"


def inject_custom_css():
    """Inject premium CSS to modernize Streamlit's base look."""
    theme = st.session_state.get("theme", "dark")

    if theme == "dark":
        bg_color = "#0e1117"
        surface_color = "#1e2130"
        text_color = "#e0e0e0"
        accent_color = "#ff6b6b"
        border_color = "#2d3748"
        user_bg = "#2d3748"
        bot_bg = "#1e2130"
    else:
        bg_color = "#ffffff"
        surface_color = "#f7fafc"
        text_color = "#1a202c"
        accent_color = "#e53e3e"
        border_color = "#e2e8f0"
        user_bg = "#ed8936"
        bot_bg = "#f7fafc"

    st.markdown(
        f"""
        <style>
        /* Hide main menu and footer */
        #MainMenu {{visibility: hidden;}}
        footer {{visibility: hidden;}}
        header {{visibility: hidden;}}

        /* Base Theme */
        .stApp {{
            background-color: {bg_color};
            color: {text_color};
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
        }}
        
        /* Sidebar styling */
        [data-testid="stSidebar"] {{
            background-color: {surface_color};
            border-right: 1px solid {border_color};
        }}
        
        /* Modern Chat Bubbles */
        [data-testid="stChatMessage"] {{
            border-radius: 16px;
            padding: 1.25rem;
            margin-bottom: 1rem;
            box-shadow: 0 2px 8px rgba(0,0,0,0.08);
        }}
        
        [data-testid="stChatMessageContent"] {{
            border-radius: 12px;
        }}
        
        /* User message */
        [data-testid="stChatMessage-user"] {{
            background-color: {user_bg};
        }}
        
        /* Bot message */
        [data-testid="stChatMessage-assistant"] {{
            background-color: {bot_bg};
        }}
        
        /* Premium Buttons */
        .stButton>button {{
            border-radius: 10px;
            transition: all 0.2s ease;
            border: 1px solid {border_color};
            font-weight: 500;
        }}
        .stButton>button:hover {{
            transform: translateY(-2px);
            box-shadow: 0 4px 12px rgba(0,0,0,0.15);
            border-color: {accent_color};
        }}
        
        /* Primary button */
        .stButton>button[kind="primary"] {{
            background: linear-gradient(135deg, {accent_color}, #ff8787);
            border: none;
        }}
        
        /* Input field styling */
        .stTextInput>div>div>input {{
            border-radius: 12px;
            border: 1px solid {border_color};
            background-color: {surface_color};
        }}
        
        /* Select box styling */
        .stSelectbox>div>div>div {{
            border-radius: 10px;
            border: 1px solid {border_color};
        }}
        
        /* Expander styling */
        .streamlit-expanderHeader {{
            border-radius: 10px;
            background-color: {surface_color};
            border: 1px solid {border_color};
        }}
        
        /* Status alerts */
        .stAlert {{
            border-radius: 12px;
            border: none;
        }}
        
        /* Dividers */
        [data-testid="stDivider"] {{
            border-color: {border_color};
        }}
        
        /* Chat input container */
        [data-testid="stChatInputContainer"] {{
            border-radius: 16px;
            border: 1px solid {border_color};
            background-color: {surface_color};
        }}
        
        /* Message timestamp styling */
        .message-timestamp {{
            font-size: 0.7rem;
            color: #888;
            margin-top: 0.5rem;
        }}
        
        /* Quick action buttons grid */
        .quick-actions {{
            display: flex;
            gap: 0.5rem;
            flex-wrap: wrap;
            margin-bottom: 1rem;
        }}
        
        /* Custom scrollbar */
        ::-webkit-scrollbar {{
            width: 8px;
            height: 8px;
        }}
        ::-webkit-scrollbar-track {{
            background: {bg_color};
        }}
        ::-webkit-scrollbar-thumb {{
            background: {border_color};
            border-radius: 4px;
        }}
        ::-webkit-scrollbar-thumb:hover {{
            background: #888;
        }}
        
        /* Title styling */
        h1, h2, h3 {{
            font-weight: 600;
        }}
        
        /* Tool usage badge */
        .tool-badge {{
            display: inline-block;
            padding: 2px 8px;
            border-radius: 4px;
            font-size: 0.7rem;
            background-color: {surface_color};
            border: 1px solid {border_color};
            margin-right: 4px;
            margin-top: 4px;
        }}
        </style>
    """,
        unsafe_allow_html=True,
    )


@st.cache_data(ttl=60)
def get_ollama_models() -> list[str]:
    """Fetch locally installed Ollama models from the daemon API."""
    try:
        ollama_host = os.getenv("OLLAMA_HOST", "http://localhost:11434")
        response = httpx.get(f"{ollama_host}/api/tags", timeout=2.0)
        if response.status_code == 200:
            models = response.json().get("models", [])
            if models:
                return [m["name"] for m in models]
    except Exception:
        pass
    # Fallback to standard defaults if daemon is offline or empty
    return ["qwen3:4b-instruct", "llama3:8b", "phi3:mini"]


def setup_sidebar():
    """Configure the sidebar settings."""
    with st.sidebar:
        # Theme toggle at top
        col1, col2 = st.columns([1, 2])
        with col1:
            st.title("Echo AI")
        with col2:
            theme = st.session_state.get("theme", "dark")
            new_theme = st.toggle(
                "Dark Mode",
                value=(theme == "dark"),
                key="theme_toggle",
            )
            if new_theme != (theme == "dark"):
                st.session_state.theme = "dark" if new_theme else "light"
                st.rerun()

        st.caption("v1.0.0 Orchestrator")
        st.divider()

        with st.expander("Provider Configuration", expanded=False):
            provider = st.selectbox(
                "Provider Backend", options=["ollama", "openai", "anthropic"], index=0
            )

            # Dynamic model selection based on provider
            if provider == "ollama":
                available_models = get_ollama_models()
                model = st.selectbox("Model", available_models)
                api_key = None
            elif provider == "openai":
                model = st.selectbox(
                    "Model", ["gpt-4o", "gpt-4o-mini", "gpt-3.5-turbo"]
                )
                api_key = st.text_input(
                    "API Key", type="password", value=os.getenv("OPENAI_API_KEY", "")
                )
            else:
                model = st.selectbox(
                    "Model", ["claude-3-5-sonnet-20240620", "claude-3-haiku-20240307"]
                )
                api_key = st.text_input(
                    "API Key", type="password", value=os.getenv("ANTHROPIC_API_KEY", "")
                )

            if st.button("Apply Backend Changes", use_container_width=True):
                config = AgentConfig(provider=provider, model=model)
                st.session_state.agent = create_agent(config, api_key=api_key)
                st.success(f"Backend hot-swapped => {provider} ({model})")

        # Primary Navigation Switcher
        st.subheader("Navigation")
        active_tab = st.radio(
            "Primary Menu",
            ["Chat Interface", "Workflow Orchestration"],
            label_visibility="collapsed",
        )
        st.divider()

        # Model indicator
        st.markdown("### Current Model")
        model_info = (
            st.session_state.agent.config.model
            if hasattr(st.session_state.agent, "config")
            else "qwen3:4b-instruct"
        )
        st.success(f"Running: {model_info}")

        # Session History as markdown list with clickable buttons
        st.markdown("### Sessions")

        agent = st.session_state.agent
        sessions = []

        if agent.session_manager:
            sessions = agent.list_sessions()

        current_session_id = None
        if agent.session_manager and agent.session_manager.current_session:
            current_session_id = agent.session_manager.current_session.id

        # Show current session indicator
        if current_session_id:
            st.caption(f"Active: {current_session_id}")

        # New chat button
        if st.button("+ New Chat", use_container_width=True):
            if agent.session_manager:
                agent.session_manager.create_session()
            agent.messages = []
            st.session_state.messages = []
            st.rerun()

        st.markdown("---")
        st.caption("Available Sessions:")

        # Session buttons as a list
        if sessions:
            for sid in sessions:
                is_active = sid == current_session_id
                button_type = "primary" if is_active else "secondary"
                if st.button(f"{sid}", use_container_width=True, type=button_type):
                    if sid != current_session_id:
                        agent.load_session(sid)
                        st.session_state.messages = []
                        for msg in agent.messages:
                            st.session_state.messages.append(
                                {
                                    "role": msg.role,
                                    "content": msg.content,
                                    "timestamp": "",
                                }
                            )
                        st.rerun()
        else:
            st.caption("No saved sessions yet")

        st.divider()

        # Session stats
        if st.session_state.messages:
            msg_count = len(st.session_state.messages)
            st.caption(f"Messages: {msg_count}")

        return active_tab


def render_message_content(content: str):
    """Render message content with native Streamlit expanders for thinking blocks."""
    # Translate raw literal <think> blocks from uncensored models into system markers
    content = content.replace("<think>", "__THINKING__").replace(
        "</think>", "__THINKING_END__"
    )

    if "__THINKING__" in content:
        parts = content.split("__THINKING__")
        if parts[0].strip():
            st.markdown(parts[0])

        for part in parts[1:]:
            if "__THINKING_END__" in part:
                thinking, rest = part.split("__THINKING_END__", 1)
                if thinking.strip():
                    with st.expander("🤔 Thought Process"):
                        st.markdown(thinking)
                if rest.strip():
                    st.markdown(rest)
            else:
                if part.strip():
                    with st.expander("🤔 Thought Process", expanded=True):
                        st.markdown(part)
    else:
        st.markdown(content)


def process_chat(prompt: str):
    """Process user input through the agent synchronously to avoid Streamlit event contention."""
    from datetime import datetime

    # Add user message to UI with timestamp
    timestamp = datetime.now().strftime("%H:%M")
    st.session_state.messages.append(
        {"role": "user", "content": prompt, "timestamp": timestamp}
    )
    with st.chat_message("user"):
        st.markdown(prompt)
        st.caption(timestamp)

    # Process assistant response with streaming
    try:
        import asyncio
        from datetime import datetime

        # Show thinking inline during streaming (Streamlit limitation: expanders can't update in real-time)
        thinking_placeholder = st.empty()
        content_placeholder = st.empty()

        accumulated_content = ""
        thinking_content = ""

        def on_chunk(chunk: str):
            nonlocal accumulated_content, thinking_content

            # Handle thinking markers
            if "__THINKING__" in chunk:
                chunk = chunk.replace("__THINKING__", "")
            if "__THINKING_END__" in chunk:
                chunk = chunk.replace("__THINKING_END__", "")

            if chunk:
                accumulated_content += chunk
                # Show thinking inline (will be moved to expander after)
                thinking_placeholder.markdown(f"**Thinking...**\n\n{thinking_content}")
                content_placeholder.markdown(accumulated_content)

        # Run streaming
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        resp = loop.run_until_complete(
            st.session_state.agent.run_streaming(prompt, on_chunk=on_chunk)
        )
        loop.close()

        # Use accumulated content or final response
        final_content = accumulated_content if accumulated_content else resp

        # Extract thinking from content
        thinking = ""
        if "__THINKING__" in final_content:
            parts = final_content.split("__THINKING__")
            final_content = parts[0] + parts[-1].replace("__THINKING_END__", "")
            # Get thinking part
            if len(parts) > 1:
                thinking = parts[1].replace("__THINKING_END__", "")

        # Clear placeholders and show final result
        thinking_placeholder.empty()
        content_placeholder.empty()

        # Show thinking in expander if present
        if thinking:
            with st.expander("Thought Process", expanded=False):
                st.markdown(thinking)

        # Show final content
        st.markdown(final_content)

        # Add assistant message with timestamp to session state
        timestamp = datetime.now().strftime("%H:%M")
        st.session_state.messages.append(
            {
                "role": "assistant",
                "content": final_content,
                "timestamp": timestamp,
                "thinking": thinking,
            }
        )

        # Rerun to render all messages from session state
        st.rerun()

    except Exception as e:
        import traceback

        st.error(f"Execution fault: {str(e)}\n\n{traceback.format_exc()}")


async def execute_workflow(graph: Any, topic: str):
    """Dynamically traverse a generic graph loaded from the registry container."""
    import streamlit as st

    status = st.status("Initializing Graph Execution Pipeline...", expanded=True)
    try:
        async for current_node, current_state in graph.run_streaming({"topic": topic}):
            if current_node == "__INTERRUPT__":
                status.update(
                    label="Pipeline Paused -> Awaiting Verification",
                    state="error",
                    expanded=False,
                )
                st.warning("This node requires explicit human-in-the-loop validation.")
                break
            elif current_node == graph.END:
                status.update(
                    label="Workflow Complete!", state="complete", expanded=False
                )
                st.success("Final Result:")
                st.markdown(
                    current_state.get("final", current_state.get("output", "Done."))
                )
            else:
                status.write(f"Executing step: `{current_node}`...")
                status.update(label=f"Tracking node => `{current_node}`")
    except Exception as e:
        status.update(label=f"Error Occurred: {e}", state="error")
        st.error(f"Fatal orchestration error: {e}")


def get_available_workflows() -> dict[str, Any]:
    """Dynamically introspect out-of-box template DAG processes configured by the developer module hierarchy."""
    import pkgutil
    import importlib
    import os
    import sys

    # Pre-add local path to pathspec explicitly
    if os.getcwd() not in sys.path:
        sys.path.insert(0, os.getcwd())

    try:
        import src.workflows
    except ImportError:
        return {}

    registry = {}
    for _, modname, _ in pkgutil.iter_modules(src.workflows.__path__):
        try:
            module = importlib.import_module(f"src.workflows.{modname}")
            if hasattr(module, "get_workflow"):
                display_name = modname.replace("_", " ").title()
                registry[display_name] = module.get_workflow()
        except Exception:
            pass

    return registry


def render_workflows_tab():
    """Render the orchestration workflows UI."""
    st.markdown(
        "<h3 style='margin-bottom: 0.5rem;'>✨ Workflow Orchestration</h3>",
        unsafe_allow_html=True,
    )
    st.markdown(
        "<p style='color: #888; margin-bottom: 2rem;'>Trigger autonomous multi-step Directed Acyclic Graph pipelines.</p>",
        unsafe_allow_html=True,
    )

    workflows = get_available_workflows()
    if not workflows:
        st.info(
            "No workflow templates found in `src/workflows/`. Define a python pipeline with `get_workflow()` to begin."
        )
        return

    col1, col2 = st.columns([1, 2])
    with col1:
        st.markdown("##### Registry Catalog")
        selected_name = st.selectbox(
            "Select Target Pipeline",
            list(workflows.keys()),
            label_visibility="collapsed",
        )
        graph = workflows[selected_name]

        with st.expander("View Architecture Blueprint", expanded=True):
            mermaid_syntax = graph.to_mermaid()
            st.markdown(f"```mermaid\n{mermaid_syntax}\n```")

    with col2:
        with st.container(border=True):
            st.markdown(f"#### Deploy: {selected_name}")
            st.caption(
                "Provide the entry payload to process through the designated architecture."
            )
            topic = st.text_area(
                "Execution Payload:",
                placeholder="e.g. Extract names from this text block...",
                height=150,
            )

            if st.button(
                "Initialize Pipeline", type="primary", use_container_width=True
            ):
                if topic:
                    import asyncio

                    asyncio.run(execute_workflow(graph, topic))
                else:
                    st.warning("Please provide an execution payload.")


def run_app():
    """Main Streamlit application entry point."""
    st.set_page_config(page_title="Echo AI Dashboard", page_icon="AI", layout="wide")

    inject_custom_css()
    initialize_session_state()
    active_tab = setup_sidebar()

    st.title("Echo AI")
    st.markdown(
        "Welcome to the Echo AI Web Interface. This terminal-free dashboard allows you to interact with the underlying execution agent using modern web components."
    )

    if active_tab == "Chat Interface":
        prompt = st.chat_input("What would you like me to do?")

        # Display Welcome Screen if Empty
        if not st.session_state.messages and not prompt:
            st.markdown(
                "<div style='margin-top: 5vh; text-align: center;'>",
                unsafe_allow_html=True,
            )
            st.markdown(
                "<h2 style='color: #888; font-weight: 400; margin-bottom: 2rem;'>How can I help you today?</h2>",
                unsafe_allow_html=True,
            )

            c1, c2, c3 = st.columns(3)
            with c1:
                if st.button("Search Latest AI News", use_container_width=True):
                    prompt = "Search the web for the latest news on Artificial Intelligence and write a short summary."
            with c2:
                if st.button("Write a Python Server", use_container_width=True):
                    prompt = "Write a python script that implements a simple FastAPI backend caching server."
            with c3:
                if st.button("Extract Data Elements", use_container_width=True):
                    prompt = "Help me extract structured entity data (people/dates/locations) from a messy block of text."
            st.markdown("</div>", unsafe_allow_html=True)

        # Display chat history
        for i, message in enumerate(st.session_state.messages):
            with st.chat_message(message["role"]):
                if message["role"] == "assistant":
                    # Show thinking if present
                    thinking = message.get("thinking", "")
                    if thinking:
                        with st.expander("Thought Process", expanded=False):
                            st.markdown(thinking)
                    render_message_content(message["content"])
                else:
                    st.markdown(message["content"])

                # Show timestamp
                timestamp = message.get("timestamp", "")
                if timestamp:
                    st.caption(timestamp)
                else:
                    # Add timestamp to message if not present
                    from datetime import datetime

                    st.caption(datetime.now().strftime("%H:%M"))

        # Execute Chat Event
        if prompt:
            process_chat(prompt)

    elif active_tab == "Workflow Orchestration":
        render_workflows_tab()


if __name__ == "__main__":
    run_app()
