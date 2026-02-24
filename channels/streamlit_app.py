"""
Streamlit chat UI for the Claude Booking Bot.
Connects to the FastAPI /chat endpoint.
"""

import streamlit as st
import requests

API_URL = "http://localhost:8000/chat"

st.set_page_config(page_title="Property Booking Bot", page_icon="🏠")
st.title("🏠 Property Booking Bot")

# Session state
if "messages" not in st.session_state:
    st.session_state.messages = []
if "user_id" not in st.session_state:
    st.session_state.user_id = ""

# Sidebar for user config
with st.sidebar:
    st.header("Settings")
    user_id = st.text_input("Phone Number (User ID)", value=st.session_state.user_id, placeholder="e.g. 919250515253")
    if user_id:
        st.session_state.user_id = user_id

    if st.button("Clear Chat"):
        st.session_state.messages = []
        st.rerun()

# Display chat history
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# Chat input
if prompt := st.chat_input("Type your message..."):
    if not st.session_state.user_id:
        st.error("Please enter your phone number in the sidebar first.")
    else:
        # Show user message
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        # Call API
        with st.chat_message("assistant"):
            with st.spinner("Thinking..."):
                try:
                    resp = requests.post(
                        API_URL,
                        json={
                            "user_id": st.session_state.user_id,
                            "message": prompt,
                        },
                        timeout=60,
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    reply = data.get("response", "Sorry, something went wrong.")
                except requests.exceptions.ConnectionError:
                    reply = "Could not connect to the server. Make sure it's running on port 8000."
                except Exception as e:
                    reply = f"Error: {str(e)}"

            st.markdown(reply)
            st.session_state.messages.append({"role": "assistant", "content": reply})
