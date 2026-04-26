"""Streamlit UI for the SRT fix and dual-caption services."""

import asyncio
import os

import streamlit as st
from dotenv import load_dotenv

# Local: pick up OPENAI_API_KEY from .env. Cloud: pull from Streamlit secrets.
load_dotenv()
try:
    if "OPENAI_API_KEY" in st.secrets:
        os.environ["OPENAI_API_KEY"] = st.secrets["OPENAI_API_KEY"]
except Exception:
    pass

if not os.environ.get("OPENAI_API_KEY"):
    st.error(
        "OPENAI_API_KEY is not set. Configure it via .env (local) "
        "or Streamlit secrets (cloud)."
    )
    st.stop()

# Import after the API key is in env, since these modules instantiate
# the OpenAI client at module load time.
from dual_caption import add_dual_captions  # noqa: E402
from fix_srt import fix_srt  # noqa: E402


st.set_page_config(page_title="SRT Tools")
st.title("SRT Tools")
st.caption("Fix fragmented sentences or generate Chinese-English dual subtitles.")

service = st.radio(
    "Service",
    [
        "Fix fragmented sentences",
        "Add Chinese-English dual subtitles",
    ],
)

uploaded = st.file_uploader("Upload an SRT file", type=["srt"])

if uploaded is not None and st.button("Run", type="primary"):
    try:
        raw = uploaded.read().decode("utf-8")
    except UnicodeDecodeError:
        st.error("Could not decode file as UTF-8.")
        st.stop()

    with st.spinner("Calling OpenAI..."):
        if service.startswith("Fix"):
            result = asyncio.run(fix_srt(raw))
            suffix = "_fixed.srt"
        else:
            result = asyncio.run(add_dual_captions(raw))
            suffix = "_dual.srt"

    stem = uploaded.name.rsplit(".", 1)[0]
    st.success("Done.")
    st.download_button(
        "Download result",
        data=result.encode("utf-8"),
        file_name=f"{stem}{suffix}",
        mime="application/x-subrip",
    )
    with st.expander("Preview"):
        st.text(result)
