import streamlit as st

from db import init_db

st.set_page_config(page_title="Tasting Tool", page_icon="🥤", layout="wide")
init_db()

params = st.query_params
session_token = params.get("session")

if session_token:
    from taster import render_taster

    render_taster(session_token)
else:
    from admin import render_admin

    render_admin()
