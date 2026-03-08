import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
"""Streamlit web UI for the Echo AI agent."""

import asyncio
import os
import streamlit as st
import httpx
from typing import Any

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
        # Initialize with default config
        config = AgentConfig(provider="ollama", model="qwen3:4b-instruct")
        st.session_state.agent = create_agent(config)

def inject_custom_css():
    """Inject premium CSS to modernize Streamlit's base look."""
    st.markdown("""
        <style>
        /* Hide main menu and footer */
        #MainMenu {visibility: hidden;}
        footer {visibility: hidden;}
        header {visibility: hidden;}

        /* Modern Typography & Spacing */
        .stApp {
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
        }
        
        /* Softer Chat Bubbles */
        .stChatMessage {
            border-radius: 12px;
            padding: 1.5rem;
            margin-bottom: 0.5rem;
            box-shadow: 0 1px 2px rgba(0,0,0,0.05);
        }
        
        /* Premium Buttons */
        .stButton>button {
            border-radius: 8px;
            transition: all 0.2s ease;
            border: 1px solid rgba(128,128,128,0.2);
        }
        .stButton>button:hover {
            transform: translateY(-1px);
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
            border-color: #ff4b4b;
        }
        
        /* Expander Headers */
        .streamlit-expanderHeader {
            border-radius: 8px;
        }

        /* Sleek Status Alerts */
        .stAlert {
            border-radius: 8px;
        }
        </style>
    """, unsafe_allow_html=True)


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
        st.title("🤖 Echo AI")
        st.caption("v1.0.0 Orchestrator")
        st.divider()

        with st.expander("⚙️ Provider Configuration", expanded=False):
            provider = st.selectbox(
                "Provider Backend", options=["ollama", "openai", "anthropic"], index=0
            )

            # Dynamic model selection based on provider
            if provider == "ollama":
                available_models = get_ollama_models()
                model = st.selectbox("Model", available_models)
                api_key = None
            elif provider == "openai":
                model = st.selectbox("Model", ["gpt-4o", "gpt-4o-mini", "gpt-3.5-turbo"])
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

        with st.expander("🗃️ Session History", expanded=True):
            agent = st.session_state.agent
            session_list = ["New Chat"]
            current_session_id = None

            if agent.session_manager and agent.session_manager.current_session:
                current_session_id = agent.session_manager.current_session.id

            if agent.session_manager:
                for sid in agent.list_sessions():
                    if sid not in session_list:
                        session_list.append(sid)

            default_index = 0
            if current_session_id in session_list:
                default_index = session_list.index(current_session_id)

            selected_session = st.selectbox(
                "Active Timeline",
                options=session_list,
                index=default_index,
                label_visibility="collapsed",
            )

            col1, col2 = st.columns(2)
            with col1:
                if st.button("Load Branch", use_container_width=True):
                    if (
                        selected_session != "New Chat"
                        and selected_session != current_session_id
                    ):
                        agent.load_session(selected_session)
                        st.session_state.messages = []
                        for msg in agent.messages:
                            st.session_state.messages.append(
                                {"role": msg.role, "content": msg.content}
                            )
                        st.rerun()
            with col2:
                if st.button("+ Blank", use_container_width=True):
                    if agent.session_manager:
                        agent.session_manager.create_session()
                    agent.messages = []
                    st.session_state.messages = []
                    st.rerun()

            if st.button("🗑️ Erase Active Branch", use_container_width=True, type="secondary"):
                st.session_state.messages = []
                agent.messages = []
                if agent.session_manager and agent.session_manager.current_session:
                    agent.session_manager.current_session.messages = []
                    agent.session_manager.save_session()
                st.rerun()


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


async def process_chat(prompt: str):
    """Process user input through the agent asynchronously."""
    # Add user message to UI
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user", avatar="👤"):
        st.markdown(prompt)

    # Process assistant response
    with st.chat_message("assistant", avatar="🤖"):
        message_placeholder = st.empty()
        full_response = ""

        # We define a custom chunk handler to update the Streamlit UI dynamically
        def on_chunk(chunk: str):
            nonlocal full_response
            full_response += chunk

            # Streamlit is synchronous, we update the placeholder from the async loop
            with message_placeholder.container():
                # Safe-guard translation for literal XML emitted by unconstrained models during stream
                display_content = full_response.replace(
                    "<think>", "__THINKING__"
                ).replace("</think>", "__THINKING_END__")
                render_message_content(display_content + "▌")

        try:
            # Tell the agent to use our custom chunk handler for the streaming run
            await st.session_state.agent.run_streaming(prompt, on_chunk=on_chunk)

            # Final render using native st.expander components
            message_placeholder.empty()
            render_message_content(full_response)

            st.session_state.messages.append(
                {"role": "assistant", "content": full_response}
            )
        except Exception as e:
            st.error(f"Error processing request: {str(e)}")


async def execute_workflow(graph: Any, topic: str):
    """Dynamically traverse a generic graph loaded from the registry container."""
    import streamlit as st
    status = st.status("Initializing Graph Execution Pipeline...", expanded=True)
    try:
        async for current_node, current_state in graph.run_streaming({"topic": topic}):
            if current_node == "__INTERRUPT__":
                status.update(label="Pipeline Paused -> Awaiting Verification", state="error", expanded=False)
                st.warning("This node requires explicit human-in-the-loop validation.")
                break
            elif current_node == graph.END:
                status.update(label="Workflow Complete!", state="complete", expanded=False)
                st.success("Final Result:")
                st.markdown(current_state.get("final", current_state.get("output", "Done.")))
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
    st.markdown("<h3 style='margin-bottom: 0.5rem;'>✨ Workflow Orchestration</h3>", unsafe_allow_html=True)
    st.markdown("<p style='color: #888; margin-bottom: 2rem;'>Trigger autonomous multi-step Directed Acyclic Graph pipelines.</p>", unsafe_allow_html=True)
    
    workflows = get_available_workflows()
    if not workflows:
        st.info("No workflow templates found in `src/workflows/`. Define a python pipeline with `get_workflow()` to begin.")
        return

    col1, col2 = st.columns([1, 2])
    with col1:
        st.markdown("##### Registry Catalog")
        selected_name = st.selectbox("Select Target Pipeline", list(workflows.keys()), label_visibility="collapsed")
        graph = workflows[selected_name]

        with st.expander("📊 View Architecture Blueprint", expanded=True):
            mermaid_syntax = graph.to_mermaid()
            st.markdown(f"```mermaid\n{mermaid_syntax}\n```")

    with col2:
        with st.container(border=True):
            st.markdown(f"#### 🚀 Deploy: {selected_name}")
            st.caption("Provide the entry payload to process through the designated architecture.")
            topic = st.text_area("Execution Payload:", placeholder="e.g. Extract names from this text block...", height=150)

            if st.button("Initialize Pipeline", type="primary", use_container_width=True):
                if topic:
                    import asyncio
                    asyncio.run(execute_workflow(graph, topic))
                else:
                    st.warning("Please provide an execution payload.")


def run_app():
    """Main Streamlit application entry point."""
    st.set_page_config(
        page_title="Echo AI Dashboard", page_icon="🤖", layout="wide"
    )

    inject_custom_css()
    initialize_session_state()
    setup_sidebar()

    st.title("🤖 Echo AI")
    st.markdown(
        "Welcome to the Echo AI Web Interface. This terminal-free dashboard allows you to interact with the underlying execution agent using modern web components."
    )

    tab_chat, tab_workflows = st.tabs(["💬 Chat", "⚙️ Workflows"])

    with tab_chat:
        prompt = st.chat_input("What would you like me to do?")
        
        # Display Welcome Screen if Empty
        if not st.session_state.messages and not prompt:
            st.markdown("<div style='margin-top: 5vh; text-align: center;'>", unsafe_allow_html=True)
            st.markdown("<h2 style='color: #888; font-weight: 400; margin-bottom: 2rem;'>How can I help you today?</h2>", unsafe_allow_html=True)
            
            c1, c2, c3 = st.columns(3)
            with c1:
                if st.button("🌐 Search Latest AI News", use_container_width=True):
                    prompt = "Search the web for the latest news on Artificial Intelligence and write a short summary."
            with c2:
                if st.button("🐍 Write a Python Server", use_container_width=True):
                    prompt = "Write a python script that implements a simple FastAPI backend caching server."
            with c3:
                if st.button("📊 Extract Data Elements", use_container_width=True):
                    prompt = "Help me extract structured entity data (people/dates/locations) from a messy block of text."
            st.markdown("</div>", unsafe_allow_html=True)

        # Display chat history
        for message in st.session_state.messages:
            avatar = "👤" if message["role"] == "user" else "🤖"
            with st.chat_message(message["role"], avatar=avatar):
                if message["role"] == "assistant":
                    render_message_content(message["content"])
                else:
                    st.markdown(message["content"])

        # Chat execution logic triggered either via input text bar or welcome buttons
        if prompt:
            # We run the async process pipeline inside Streamlit's synchronous loop
            asyncio.run(process_chat(prompt))

    with tab_workflows:
        render_workflows_tab()


if __name__ == "__main__":
    run_app()
