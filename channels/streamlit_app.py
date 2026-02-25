"""
Streamlit chat UI for the Claude Booking Bot.
Connects to the FastAPI /chat endpoint.
"""

import streamlit as st
import requests

API_URL = "http://localhost:8000/chat"

# Default OxOtel PG IDs
OXOTEL_PG_IDS = [
    "l5zf3ckOnRQV9OHdv5YTTXkvLHp1",
    "egu5HmrYFMP8MRJyMsefnpaL7ka2",
    "Z2wyLOXXp5QA596DQ6aZAQpakmQ2",
    "UaDCGP3dzzZRgVIzBDgXb5ry5ng2",
    "EqhTMiUNksgXh5QhGQRsY5DQiO42",
    "fzDBxYtHgVV21ertfkUdSHeomiv2",
    "CUxtdeaGxYS8IMXmGZ1yUnqyfOn2",
    "wtlUSKV9H8bkNqvlGmnogwoqwyk2",
    "1Dy0t6YeIHh3kQhqvQR8tssHWKt1",
    "U2uYCaeiCebrE95iUDsS4PwEd1J2",
]
DEFAULT_PG_IDS_STR = ", ".join(OXOTEL_PG_IDS)

st.set_page_config(page_title="Property Booking Bot", page_icon="🏠")
st.title("🏠 Property Booking Bot")

# Session state
if "messages" not in st.session_state:
    st.session_state.messages = []
if "user_id" not in st.session_state:
    st.session_state.user_id = ""
if "account_saved" not in st.session_state:
    st.session_state.account_saved = False

# Sidebar for user config
with st.sidebar:
    st.header("Settings")
    user_id = st.text_input(
        "Phone Number (User ID)",
        value=st.session_state.user_id,
        placeholder="e.g. 919250515253",
    )
    if user_id:
        st.session_state.user_id = user_id

    st.divider()
    st.header("Account Context")
    st.caption("PG IDs identify the whitelabel property group. All Rentok API calls depend on this.")

    pg_ids_input = st.text_area(
        "PG IDs (comma-separated)",
        value=DEFAULT_PG_IDS_STR,
        height=100,
        help="Firebase-like IDs that identify the property groups. Passed to Rentok API for search, booking, payments, etc.",
    )
    brand_name = st.text_input("Brand Name", value="Rentok", placeholder="e.g. Rentok, OxoTel")
    cities = st.text_input("Cities", value="Bangalore, Mumbai", placeholder="e.g. Bangalore, Mumbai, Delhi")
    areas = st.text_input("Areas", value="Koramangala, Indiranagar, HSR Layout, Whitefield", placeholder="e.g. Koramangala, Indiranagar")
    kyc_enabled = st.checkbox("KYC Enabled", value=True)

    with st.expander("WhatsApp Config (optional)"):
        wa_phone_number_id = st.text_input("WhatsApp Phone Number ID", value="")
        wa_access_token = st.text_input("WhatsApp Access Token", value="", type="password")
        is_meta = st.checkbox("Is Meta (vs Interakt)", value=True)
        waba_id = st.text_input("WABA ID (Interakt)", value="")

    if st.button("Save Account Context"):
        st.session_state.account_saved = True
        st.success("Account context will be sent with the next message.")

    st.divider()
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

        # Build account values (mirrors the extra_keys from WhatsApp webhook)
        account_values = {}
        if st.session_state.account_saved or brand_name:
            # Parse pg_ids from comma-separated input
            pg_ids = [pid.strip() for pid in pg_ids_input.split(",") if pid.strip()] if pg_ids_input else []

            account_values = {
                "pg_ids": pg_ids,
                "brand_name": brand_name,
                "brand_value": brand_name,
                "cities": cities,
                "areas": areas,
                "kyc_enabled": kyc_enabled,
            }
            if wa_phone_number_id:
                account_values["whatsapp_phone_number_id"] = wa_phone_number_id
                account_values["phone_number_id"] = wa_phone_number_id
            if wa_access_token:
                account_values["whatsapp_access_token"] = wa_access_token
                account_values["is_meta"] = is_meta
            if waba_id:
                account_values["waba_id"] = waba_id
                account_values["x-waba-id"] = waba_id

        # Call API
        with st.chat_message("assistant"):
            with st.spinner("Thinking..."):
                try:
                    resp = requests.post(
                        API_URL,
                        json={
                            "user_id": st.session_state.user_id,
                            "message": prompt,
                            "account_values": account_values,
                        },
                        timeout=120,
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    reply = data.get("response", "Sorry, something went wrong.")
                    agent = data.get("agent", "")
                except requests.exceptions.ConnectionError:
                    reply = "Could not connect to the server. Make sure it's running on port 8000."
                    agent = ""
                except Exception as e:
                    reply = f"Error: {str(e)}"
                    agent = ""

            st.markdown(reply)
            if agent:
                st.caption(f"Agent: {agent}")
            st.session_state.messages.append({"role": "assistant", "content": reply})
