"""Streamlit UI for the audio → JSON → corrected JSON → SRT workflow."""

import asyncio
import os

import streamlit as st
from dotenv import load_dotenv

# Local: pick up keys from .env. Cloud: pull from Streamlit secrets.
load_dotenv()
try:
    if "OPENAI_API_KEY" in st.secrets:
        os.environ["OPENAI_API_KEY"] = st.secrets["OPENAI_API_KEY"]
    if "SONIOX_API_KEY" in st.secrets:
        os.environ["SONIOX_API_KEY"] = st.secrets["SONIOX_API_KEY"]
except Exception:
    pass

openai_key = os.environ.get("OPENAI_API_KEY")
soniox_key = os.environ.get("SONIOX_API_KEY")

# transcribe has no OpenAI dependency so import it unconditionally.
from transcribe import transcribe_audio_json  # noqa: E402

# dual_caption and json_to_srt instantiate the OpenAI client at module load time,
# so only import them when the key is present.
if openai_key:
    from dual_caption import add_dual_captions  # noqa: E402
    from json_to_srt import json_to_srt  # noqa: E402


st.set_page_config(page_title="Dual Caption", layout="centered")
st.title("Dual Caption Workflow")
st.caption("Audio → transcript JSON → manual corrections → SRT.")


# ─────────────────────────── Step 1 ──────────────────────────────
st.header("Step 1 — Transcribe audio to JSON")
st.write(
    "Upload an audio file. Soniox transcribes it and returns a word-level JSON "
    "with `start_ms`, `end_ms`, and `confidence` for every token."
)

if not soniox_key:
    st.warning(
        "`SONIOX_API_KEY` is not set. Configure it via `.env` (local) or Streamlit secrets (cloud) to enable this step."
    )
else:
    audio_file = st.file_uploader(
        "Audio file",
        type=["mp3", "wav", "m4a", "flac", "ogg", "webm", "aac"],
        key="step1_audio",
    )
    if audio_file is not None and st.button(
        "Transcribe", type="primary", key="step1_btn"
    ):
        with st.spinner("Uploading and transcribing..."):
            try:
                output = transcribe_audio_json(
                    audio_file.read(), audio_file.name, soniox_key
                )
            except Exception as e:
                st.error(f"Transcription failed: {e}")
                st.stop()
        stem = audio_file.name.rsplit(".", 1)[0]
        st.success("Transcript ready. Download the JSON below, then move to Step 2.")
        st.download_button(
            "Download transcript JSON",
            data=output.encode("utf-8"),
            file_name=f"{stem}.json",
            mime="application/json",
            key="step1_dl",
        )

st.divider()


# ─────────────────────────── Step 2 ──────────────────────────────
st.header("Step 2 — Manually correct the JSON")
st.markdown(
    """
Open the downloaded JSON in your editor and review it.

- **Edit only the `text` field.** Fix misheard words, wrong place names, missing punctuation, etc.
- **Leave `start_ms`, `end_ms`, and `confidence` untouched** — those drive subtitle timing in Step 3.
- If you need to add a new token, give it sensible timestamps relative to its neighbors.
- Save the file (e.g. `transcript_corrected.json`), then continue to Step 3.

No service runs in this step — the corrections happen on your machine.
"""
)

st.divider()


# ─────────────────────────── Step 3 ──────────────────────────────
st.header("Step 3 — Convert corrected JSON to SRT")
st.write(
    "Upload the corrected JSON. The converter applies rule-based segmentation "
    "(temporal proximity, punctuation, visual length caps), then an LLM refinement "
    "pass that merges fragments, splits over-long lines, and tightens punctuation. "
    "Output is an SRT ready for your video editor."
)

if not openai_key:
    st.warning(
        "`OPENAI_API_KEY` is not set. Configure it via `.env` (local) or Streamlit secrets (cloud) to enable this step."
    )
else:
    json_file = st.file_uploader(
        "Corrected transcript JSON",
        type=["json"],
        key="step3_json",
    )
    use_llm = st.checkbox(
        "LLM refinement (merge fragments, split over-long lines)",
        value=True,
        key="step3_llm",
    )
    use_summary = st.checkbox(
        "Generate video summary for grounding (improves error correction)",
        value=True,
        disabled=not use_llm,
        key="step3_summary",
    )

    if json_file is not None and st.button(
        "Convert to SRT", type="primary", key="step3_btn"
    ):
        try:
            raw = json_file.read().decode("utf-8")
        except UnicodeDecodeError:
            st.error("Could not decode file as UTF-8.")
            st.stop()
        with st.spinner("Generating SRT..."):
            try:
                result = asyncio.run(
                    json_to_srt(raw, use_llm=use_llm, use_summary=use_summary)
                )
            except Exception as e:
                st.error(f"Conversion failed: {e}")
                st.stop()
        stem = json_file.name.rsplit(".", 1)[0]
        st.success("SRT ready.")
        st.download_button(
            "Download SRT",
            data=result.encode("utf-8"),
            file_name=f"{stem}.srt",
            mime="application/x-subrip",
            key="step3_dl",
        )
        with st.expander("Preview"):
            st.text(result)

st.divider()


# ──────────────────── Optional follow-up ─────────────────────────
st.header("Optional — Add Chinese–English dual subtitles")
st.write(
    "Upload an SRT (e.g. the output from Step 3). Each line is translated to "
    "the other language and stacked below the original."
)

if not openai_key:
    st.warning("`OPENAI_API_KEY` is not set. Configure it to enable dual subtitles.")
else:
    srt_file = st.file_uploader("SRT file", type=["srt"], key="dual_srt")
    if srt_file is not None and st.button(
        "Add dual subtitles", type="primary", key="dual_btn"
    ):
        try:
            raw_srt = srt_file.read().decode("utf-8")
        except UnicodeDecodeError:
            st.error("Could not decode file as UTF-8.")
            st.stop()
        with st.spinner("Translating..."):
            try:
                dual = asyncio.run(add_dual_captions(raw_srt))
            except Exception as e:
                st.error(f"Dual caption failed: {e}")
                st.stop()
        stem = srt_file.name.rsplit(".", 1)[0]
        st.success("Dual SRT ready.")
        st.download_button(
            "Download dual SRT",
            data=dual.encode("utf-8"),
            file_name=f"{stem}_dual.srt",
            mime="application/x-subrip",
            key="dual_dl",
        )
        with st.expander("Preview"):
            st.text(dual)
