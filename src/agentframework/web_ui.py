"""Streamlit web UI for the Vibe AI agent."""

import asyncio
import os
import streamlit as st
import httpx

from .agent import AgentConfig, create_agent

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
        st.title("⚙️ Agent Settings")

        provider = st.selectbox(
            "Provider",
            options=["ollama", "openai", "anthropic"],
            index=0
        )

        # Dynamic model selection based on provider
        if provider == "ollama":
            available_models = get_ollama_models()
            model = st.selectbox("Model", available_models)
            api_key = None
        elif provider == "openai":
            model = st.selectbox("Model", ["gpt-4o", "gpt-4o-mini", "gpt-3.5-turbo"])
            api_key = st.text_input("API Key", type="password", value=os.getenv("OPENAI_API_KEY", ""))
        else:
            model = st.selectbox("Model", ["claude-3-5-sonnet-20240620", "claude-3-haiku-20240307"])
            api_key = st.text_input("API Key", type="password", value=os.getenv("ANTHROPIC_API_KEY", ""))

        if st.button("Apply Changes"):
            config = AgentConfig(provider=provider, model=model)
            st.session_state.agent = create_agent(config, api_key=api_key)
            st.success(f"Agent updated to use {provider} ({model})")

        st.divider()
        if st.button("Clear History"):
            st.session_state.messages = []
            if st.session_state.agent.session_manager and st.session_state.agent.session_manager.current_session:
                st.session_state.agent.session_manager.current_session.messages = []
                st.session_state.agent.session_manager.save_session()
            st.rerun()

def render_message_content(content: str):
    """Render message content with native Streamlit expanders for thinking blocks."""
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
    with st.chat_message("user"):
        st.markdown(prompt)

    # Process assistant response
    with st.chat_message("assistant"):
        message_placeholder = st.empty()
        full_response = ""

        # We define a custom chunk handler to update the Streamlit UI dynamically
        def on_chunk(chunk: str):
            nonlocal full_response
            full_response += chunk

            # Streamlit is synchronous, we update the placeholder from the async loop
            with message_placeholder.container():
                render_message_content(full_response + "▌")

        try:
            # Tell the agent to use our custom chunk handler for the streaming run
            await st.session_state.agent.run_streaming(prompt, on_chunk=on_chunk)

            # Final render using native st.expander components
            message_placeholder.empty()
            render_message_content(full_response)

            st.session_state.messages.append({"role": "assistant", "content": full_response})
        except Exception as e:
            st.error(f"Error processing request: {str(e)}")


def run_app():
    """Main Streamlit application entry point."""
    st.set_page_config(
        page_title="Vibe AI Enterprise Dashboard",
        page_icon="🤖",
        layout="wide"
    )

    initialize_session_state()
    setup_sidebar()

    st.title("🤖 Vibe AI Web Dashboard")
    st.markdown("Welcome to the Vibe AI Web Interface. This terminal-free dashboard allows you to interact with the underlying execution agent using modern web components.")

    # Display chat history
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            if message["role"] == "assistant":
                render_message_content(message["content"])
            else:
                st.markdown(message["content"])

    # Chat input
    if prompt := st.chat_input("What would you like me to do?"):
        # We run the async process pipeline inside Streamlit's synchronous loop
        asyncio.run(process_chat(prompt))

if __name__ == "__main__":
    run_app()
