import streamlit as st
import time

if "run" not in st.session_state:
    st.session_state.run = False

if st.button("Run"):
    st.session_state.run = True

def render_content(content: str):
    if "__THINKING__" in content:
        parts = content.split("__THINKING__")
        st.markdown(parts[0])
        for p in parts[1:]:
            if "__THINKING_END__" in p:
                thinking, rest = p.split("__THINKING_END__", 1)
                with st.expander("🤔 Thought Process", expanded=False):
                    st.markdown(thinking)
                st.markdown(rest)
            else:
                with st.expander("🤔 Thought Process", expanded=True):
                    st.markdown(p)
    else:
        st.markdown(content)

if st.session_state.run:
    placeholder = st.empty()
    text = "Hello\n__THINKING__\n"
    for i in range(10):
        text += f"Thinking line {i}...\n"
        with placeholder.container():
            render_content(text)
        time.sleep(0.1)

    text += "__THINKING_END__\n\nAnd now the final answer."
    for i in range(10):
        text += f" Word{i}"
        with placeholder.container():
            render_content(text)
        time.sleep(0.1)
    st.session_state.run = False
