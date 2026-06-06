"""Streamlit UI for the audio → JSON → corrected JSON → SRT workflow."""

import asyncio
import base64
import json
import mimetypes
import os

import streamlit as st
import streamlit.components.v1 as components
from dotenv import load_dotenv

# Local: pick up keys from .env. Cloud: pull from Streamlit secrets.
load_dotenv()
try:
    for _k in (
        "OPENAI_API_KEY",
        "SONIOX_API_KEY",
        "SMTP_HOST",
        "SMTP_PORT",
        "SMTP_USER",
        "SMTP_PASSWORD",
        "SMTP_FROM",
    ):
        if _k in st.secrets:
            os.environ[_k] = str(st.secrets[_k])
except Exception:
    pass

openai_key = os.environ.get("OPENAI_API_KEY")
soniox_key = os.environ.get("SONIOX_API_KEY")

# transcribe has no OpenAI dependency so import it unconditionally.
from transcribe import transcribe_audio_json  # noqa: E402

# Segmentation helpers have no OpenAI runtime dependency (the module only
# instantiates the client when OPENAI_API_KEY is set), so import unconditionally.
from feedback import FeedbackError, feedback_configured, send_feedback  # noqa: E402
from i18n import COMPONENT_LABELS, TRANSLATIONS, detect_lang  # noqa: E402
from json_to_srt import _normalize_tokens, segment_tokens  # noqa: E402
from retime import retime_line  # noqa: E402

# dual_caption and json_to_srt's OpenAI-backed entrypoints need the key.
if openai_key:
    from dual_caption import add_dual_captions  # noqa: E402
    from json_to_srt import json_to_srt  # noqa: E402


# ─────────────────────────── Language ─────────────────────────────
if "lang" not in st.session_state:
    try:
        _al = st.context.headers.get("Accept-Language", "")
    except Exception:
        _al = ""
    st.session_state["lang"] = detect_lang(_al)

LANG = st.session_state["lang"]


def t(key: str, **kwargs) -> str:
    """Translate a UI string key for the current language."""
    s = TRANSLATIONS.get(LANG, TRANSLATIONS["en"]).get(key) or TRANSLATIONS["en"].get(
        key, key
    )
    return s.format(**kwargs) if kwargs else s


# ─────────────────────────── Component ────────────────────────────
_COMPONENT_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "transcript_editor"
)
_transcript_editor = components.declare_component(
    "transcript_editor", path=_COMPONENT_DIR
)


def transcript_editor(
    lines: list[dict], audio: str, labels: dict, key: str | None = None
):
    """Render the audio-synced line editor; returns the last applied payload."""
    return _transcript_editor(
        lines=lines, audio=audio, labels=labels, key=key, default=None
    )


def _audio_data_url(audio_bytes: bytes, filename: str) -> str:
    mime = mimetypes.guess_type(filename)[0] or "audio/mpeg"
    b64 = base64.b64encode(audio_bytes).decode("ascii")
    return f"data:{mime};base64,{b64}"


def _segment_lines(raw_tokens: list[dict]):
    """Segment Soniox tokens into display lines, keeping both each line's
    original token dicts (for verbatim pass-through of untouched lines) and its
    normalized per-word timing (for re-aligning edited lines)."""
    tokens = _normalize_tokens(raw_tokens)
    segments = segment_tokens(tokens)
    lines, seg_raw, seg_norm, seg_text = [], [], [], []
    for i, s in enumerate(segments):
        lines.append(
            {"index": i, "start_ms": s.start_ms, "end_ms": s.end_ms, "text": s.text}
        )
        seg_raw.append([t.raw for t in s.tokens if t.raw is not None])
        seg_norm.append(
            [
                {"text": tok.text, "start_ms": tok.start_ms, "end_ms": tok.end_ms}
                for tok in s.tokens
            ]
        )
        seg_text.append(s.text)
    return lines, seg_raw, seg_norm, seg_text


def _rebuild_corrected(
    edits: list[dict],
    seg_raw: list[list[dict]],
    seg_norm: list[list[dict]],
    seg_text: list[str],
) -> list[dict]:
    """Reassemble a word-level token JSON. Unchanged lines pass through their
    original tokens verbatim; edited lines are re-aligned to word-level
    timestamps so unchanged words keep their times and split/inserted words get
    proportional ones."""
    edit_map = {e["index"]: e.get("text", "") for e in edits}
    out: list[dict] = []
    for i, orig in enumerate(seg_text):
        new = edit_map.get(i, orig)
        if new.strip() == orig.strip():
            out.extend(seg_raw[i])
        else:
            out.extend(retime_line(new, seg_norm[i]))
    return out


st.set_page_config(page_title=t("page_title"), layout="centered")
st.title(t("title"))
st.caption(t("subtitle"))


# ───────────────── Floating top bar: language + feedback ──────────
@st.dialog(t("feedback_title"))
def _feedback_dialog():
    st.write(t("feedback_intro"))
    msg = st.text_area(
        t("feedback_msg_label"),
        key="fb_msg",
        height=160,
        placeholder=t("feedback_msg_placeholder"),
    )
    contact = st.text_input(t("feedback_email_label"), key="fb_contact")
    if st.button(t("feedback_send"), type="primary", key="fb_send"):
        if not msg.strip():
            st.warning(t("feedback_empty"))
        elif not feedback_configured():
            st.error(t("feedback_not_configured"))
        else:
            try:
                send_feedback(msg, contact)
            except FeedbackError as e:
                st.error(t("feedback_error", err=e))
            else:
                st.success(t("feedback_sent"))


st.markdown(
    """
    <style>
    .st-key-floatbar {
        position: fixed; top: 3.25rem; left: 1rem; width: auto; z-index: 1000001;
    }
    .st-key-floatbar [data-testid="stVerticalBlock"] {
        flex-direction: row; gap: 0.5rem; width: auto; align-items: center;
    }
    .st-key-floatbar [data-testid="stElementContainer"],
    .st-key-floatbar [data-testid="stButton"] { width: auto; }
    .st-key-lang_toggle button {
        border-radius: 999px; padding: 0.45rem 1.0rem; font-weight: 700;
        background: rgba(128, 128, 128, 0.18); border: 1px solid rgba(128, 128, 128, 0.35);
    }
    .st-key-feedback_fab button {
        border-radius: 999px; padding: 0.5rem 1.1rem; font-weight: 700;
        background: #ff4b4b; color: #fff; border: none;
        box-shadow: 0 4px 16px rgba(0, 0, 0, 0.28);
    }
    .st-key-feedback_fab button:hover { filter: brightness(1.06); color: #fff; }
    </style>
    """,
    unsafe_allow_html=True,
)
with st.container(key="floatbar"):
    if st.button(t("lang_button"), key="lang_toggle"):
        st.session_state["lang"] = "zh" if LANG == "en" else "en"
        st.rerun()
    if st.button(t("feedback_button"), key="feedback_fab"):
        _feedback_dialog()


# ─────────────────────────── Step 1 ──────────────────────────────
st.header(t("step1_header"))
st.write(t("step1_desc"))

if not soniox_key:
    st.warning(t("soniox_warn"))
else:
    audio_file = st.file_uploader(
        t("audio_file_label"),
        type=["mp3", "wav", "m4a", "flac", "ogg", "webm", "aac"],
        key="step1_audio",
    )
    if audio_file is not None and st.button(
        t("transcribe_button"), type="primary", key="step1_btn"
    ):
        audio_bytes = audio_file.read()
        with st.spinner(t("transcribing")):
            try:
                output = transcribe_audio_json(audio_bytes, audio_file.name, soniox_key)
            except Exception as e:
                st.error(t("transcribe_failed", err=e))
                st.stop()
        # Stash for Step 2 (in-app correction) and reset any prior corrections.
        st.session_state["transcript_json"] = output
        st.session_state["audio_bytes"] = audio_bytes
        st.session_state["audio_name"] = audio_file.name
        st.session_state["transcript_stem"] = audio_file.name.rsplit(".", 1)[0]
        # New transcript invalidates any downstream outputs.
        for _k in ("corrected_json", "srt_result", "dual_result"):
            st.session_state.pop(_k, None)
        st.success(t("transcript_ready"))

    if "transcript_json" in st.session_state:
        _stem = st.session_state.get("transcript_stem", "transcript")
        st.download_button(
            t("download_transcript"),
            data=st.session_state["transcript_json"].encode("utf-8"),
            file_name=f"{_stem}.json",
            mime="application/json",
            key="step1_dl",
        )

st.divider()


# ─────────────────────────── Step 2 ──────────────────────────────
st.header(t("step2_header"))
st.write(t("step2_desc"))

# Allow standalone entry: upload a transcript JSON + audio if none in session.
if "transcript_json" not in st.session_state or "audio_bytes" not in st.session_state:
    with st.expander(t("step2_no_transcript")):
        up_json = st.file_uploader(
            t("transcript_json_label"), type=["json"], key="step2_json_up"
        )
        up_audio = st.file_uploader(
            t("matching_audio_label"),
            type=["mp3", "wav", "m4a", "flac", "ogg", "webm", "aac"],
            key="step2_audio_up",
        )
        if up_json is not None and up_audio is not None:
            try:
                st.session_state["transcript_json"] = up_json.read().decode("utf-8")
            except UnicodeDecodeError:
                st.error(t("decode_json_failed"))
                st.stop()
            st.session_state["audio_bytes"] = up_audio.read()
            st.session_state["audio_name"] = up_audio.name
            st.session_state["transcript_stem"] = up_json.name.rsplit(".", 1)[0]
            for _k in ("corrected_json", "srt_result", "dual_result"):
                st.session_state.pop(_k, None)
            st.rerun()

if "transcript_json" in st.session_state and "audio_bytes" in st.session_state:
    try:
        raw_tokens = json.loads(st.session_state["transcript_json"])
        lines, seg_raw, seg_norm, seg_text = _segment_lines(raw_tokens)
    except Exception as e:
        st.error(t("parse_json_failed", err=e))
        lines = None

    if lines:
        audio_url = _audio_data_url(
            st.session_state["audio_bytes"], st.session_state.get("audio_name", "a.mp3")
        )
        result = transcript_editor(
            lines=lines,
            audio=audio_url,
            labels=COMPONENT_LABELS.get(LANG, COMPONENT_LABELS["en"]),
            key="step2_editor",
        )

        # A custom component replays its last value on every rerun, so only act
        # when the user actually clicks "Apply" again — detected via the nonce.
        if (
            result
            and isinstance(result, dict)
            and result.get("lines")
            and result.get("nonce") != st.session_state.get("step2_nonce")
        ):
            st.session_state["step2_nonce"] = result.get("nonce")
            corrected = _rebuild_corrected(result["lines"], seg_raw, seg_norm, seg_text)
            st.session_state["corrected_json"] = json.dumps(
                corrected, ensure_ascii=False, indent=2
            )
            # New corrections invalidate the downstream SRT / dual SRT.
            for _k in ("srt_result", "dual_result"):
                st.session_state.pop(_k, None)
            n_edited = sum(
                1
                for e in result["lines"]
                if e.get("text", "").strip() != seg_text[e["index"]].strip()
            )
            st.success(t("corrections_applied", n=n_edited))

        if "corrected_json" in st.session_state:
            stem = st.session_state.get("audio_name", "transcript").rsplit(".", 1)[0]
            st.download_button(
                t("download_corrected"),
                data=st.session_state["corrected_json"].encode("utf-8"),
                file_name=f"{stem}_corrected.json",
                mime="application/json",
                key="step2_dl",
            )

st.divider()


# ─────────────────────────── Step 3 ──────────────────────────────
st.header(t("step3_header"))
st.write(t("step3_desc"))

if not openai_key:
    st.warning(t("openai_warn"))
else:
    raw = None
    stem = "transcript"

    if "corrected_json" in st.session_state:
        st.info(t("using_corrected"))
        raw = st.session_state["corrected_json"]
        stem = st.session_state.get("audio_name", "transcript").rsplit(".", 1)[0]
        use_upload = st.checkbox(
            t("upload_other_json"), value=False, key="step3_override"
        )
    else:
        use_upload = True

    if use_upload:
        json_file = st.file_uploader(
            t("corrected_json_label"),
            type=["json"],
            key="step3_json",
        )
        if json_file is not None:
            try:
                raw = json_file.read().decode("utf-8")
            except UnicodeDecodeError:
                st.error(t("decode_failed"))
                st.stop()
            stem = json_file.name.rsplit(".", 1)[0]

    use_llm = st.checkbox(t("use_llm_label"), value=True, key="step3_llm")
    use_summary = st.checkbox(
        t("use_summary_label"),
        value=True,
        disabled=not use_llm,
        key="step3_summary",
    )

    if raw is not None and st.button(
        t("convert_button"), type="primary", key="step3_btn"
    ):
        with st.spinner(t("generating_srt")):
            try:
                srt_result = asyncio.run(
                    json_to_srt(raw, use_llm=use_llm, use_summary=use_summary)
                )
            except Exception as e:
                st.error(t("conversion_failed", err=e))
                st.stop()
        st.session_state["srt_result"] = srt_result
        st.session_state["srt_stem"] = stem
        st.session_state.pop("dual_result", None)  # invalidate stale dual SRT
        st.success(t("srt_ready"))

    if "srt_result" in st.session_state:
        st.download_button(
            t("download_srt"),
            data=st.session_state["srt_result"].encode("utf-8"),
            file_name=f"{st.session_state.get('srt_stem', 'transcript')}.srt",
            mime="application/x-subrip",
            key="step3_dl",
        )
        with st.expander(t("preview_srt")):
            st.text(st.session_state["srt_result"])

st.divider()


# ──────────────────── Optional follow-up ─────────────────────────
st.header(t("dual_header"))
st.write(t("dual_desc"))

if not openai_key:
    st.warning(t("openai_warn_dual"))
else:
    raw_srt = None
    dual_stem = "subtitles"

    if "srt_result" in st.session_state:
        st.info(t("using_srt"))
        raw_srt = st.session_state["srt_result"]
        dual_stem = st.session_state.get("srt_stem", "subtitles")
        dual_upload = st.checkbox(
            t("upload_other_srt"), value=False, key="dual_override"
        )
    else:
        dual_upload = True

    if dual_upload:
        srt_file = st.file_uploader(t("srt_file_label"), type=["srt"], key="dual_srt")
        if srt_file is not None:
            try:
                raw_srt = srt_file.read().decode("utf-8")
            except UnicodeDecodeError:
                st.error(t("decode_failed"))
                st.stop()
            dual_stem = srt_file.name.rsplit(".", 1)[0]

    if raw_srt is not None and st.button(
        t("add_dual_button"), type="primary", key="dual_btn"
    ):
        with st.spinner(t("translating")):
            try:
                dual = asyncio.run(add_dual_captions(raw_srt))
            except Exception as e:
                st.error(t("dual_failed", err=e))
                st.stop()
        st.session_state["dual_result"] = dual
        st.session_state["dual_stem"] = dual_stem
        st.success(t("dual_ready"))

    if "dual_result" in st.session_state:
        st.download_button(
            t("download_dual"),
            data=st.session_state["dual_result"].encode("utf-8"),
            file_name=f"{st.session_state.get('dual_stem', 'subtitles')}_dual.srt",
            mime="application/x-subrip",
            key="dual_dl",
        )
        with st.expander(t("preview_dual")):
            st.text(st.session_state["dual_result"])
