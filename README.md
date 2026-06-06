# Dual Caption — Free AI Subtitle & Bilingual Caption Generator

**Live app: [dual-caption.streamlit.app](https://dual-caption.streamlit.app/) — free to use, no sign‑up, no API key required.**

Dual Caption is a free online tool that turns audio or video speech into clean,
accurately‑timed **SRT subtitles**, and can stack a **Chinese ⇄ English
translation** under every line to create **bilingual (dual‑language) captions**.
It's built for creators who subtitle **vlogs, interviews, lectures, and
mixed‑language Mandarin/English content** and want broadcast‑quality results
without hours of manual cleanup.

> **100% free right now.** Just open the [web app](https://dual-caption.streamlit.app/)
> and start — you do **not** need an OpenAI key, a Soniox key, or any paid
> account. The hosted service covers the speech‑to‑text and AI costs for you.

Keywords: free subtitle generator, automatic captions, audio/video to SRT,
speech‑to‑text transcription, AI caption maker, Chinese English bilingual
subtitles, dual‑language subtitles, online SRT generator.

## Why it's better than Premiere Pro's auto‑captions

Subtitling a bilingual (Chinese/English) vlog with **Premiere Pro's built‑in
transcribe + caption tools** typically leaves about **50% of lines needing
manual correction** — misheard words, awkward sentence breaks, and lines that
are too long or too short on screen.

With Dual Caption that drops to roughly **5% of lines**. A stronger multilingual
speech model, rule‑based + AI line segmentation, and an audio‑synced in‑app
correction step do the heavy lifting, so you spend minutes polishing instead of
hours rebuilding. **~10× less manual subtitle correction.**

## Features

A guided four‑step workflow, where each step's output flows straight into the
next (and every step also offers a download):

1. **Transcribe audio → JSON.** Upload an audio file and get a word‑level
   transcript with a start/end timestamp and confidence for every token.
2. **Correct the transcript while listening.** An in‑browser editor plays the
   audio and **highlights the line being spoken**, with click‑to‑seek, line
   numbers, and a progress counter. Edit any line in place — word‑level
   timestamps are preserved (unchanged words keep their exact times; split or
   inserted words get proportional ones).
3. **Convert to SRT.** Rule‑based segmentation plus an AI refinement pass turn
   the corrected transcript into a polished `.srt` ready for any video editor.
4. **Add dual subtitles (optional).** Translate each line into the other
   language and stack it beneath the original, producing a bilingual `.srt`.

Plus a **bilingual UI** (English / 简体中文) that auto‑detects your browser
language with a one‑click toggle, and a built‑in **feedback** button.

## FAQ

**Is Dual Caption free?**
Yes. The hosted app at
[dual-caption.streamlit.app](https://dual-caption.streamlit.app/) is completely
free right now, with no account and no API key needed.

**Do I need an OpenAI or LLM API key?**
No. To use the live web app you don't need any API key — speech‑to‑text and AI
processing are handled by the hosted service. (You only need your own keys if
you choose to self‑host the code, see below.)

**What languages does it support?**
It's optimized for **English, Mandarin Chinese, and mixed English/Chinese
speech**, and produces **Chinese ⇄ English bilingual subtitles**.

**What file formats can I use?**
Input: common audio formats (mp3, wav, m4a, flac, ogg, webm, aac). Output:
standard `.srt` subtitle files that work in Premiere Pro, DaVinci Resolve,
CapCut, Final Cut, YouTube, and most players/editors.

**How is it more accurate than automatic captions in my editor?**
A better multilingual speech model, a two‑stage (rules + AI) line segmenter
grounded in a video summary, and an audio‑synced human correction step together
cut manual cleanup from ~50% of lines to ~5%.

**Is my audio kept private?**
Audio is processed only to produce your transcript and subtitles; it isn't
published anywhere by the app.

## How it works

- **Speech‑to‑text — [Soniox](https://soniox.com/).** Audio is transcribed with
  Soniox's async multilingual model, with English/Chinese language hints and a
  structured‑context prompt (speaker, topic, domain terms) so proper nouns and
  jargon come through correctly. The result is a word‑level JSON with precise
  per‑token timing.

- **Segmentation — rules first, then AI.** Words are grouped into subtitle lines
  using timing gaps, punctuation, and on‑screen length caps (tuned separately
  for CJK characters vs. Latin words, with min/max line durations). An **OpenAI
  (gpt‑5‑mini)** pass then refines those candidates: it merges fragments, splits
  over‑long lines at natural clause boundaries, fixes obvious speech‑recognition
  typos, and tightens punctuation. To stay grounded, the model is first given a
  compact **video summary** (setting, people, recurring terms) generated from
  the transcript, and the refined text is always mapped back onto the **original
  word timestamps** so timing never drifts.

- **Translation — context‑aware.** For dual subtitles, each line is translated
  with its neighbouring lines and the video summary as context (so meaning and
  terminology stay consistent), favouring faithful meaning over literal
  word‑for‑word output. Repeated lines are cached and requests are batched with
  rate‑limit handling.

These quality measures — strong multilingual STT, structured context, a
two‑stage (rules + AI) segmenter grounded in a video summary, timestamp‑safe
remapping, and an audio‑synced human correction step — are what cut the manual
cleanup from ~50% of lines to ~5%.

## Self‑hosting (optional, for developers)

Using the [live app](https://dual-caption.streamlit.app/) needs nothing. To run
your **own** copy you supply your own API keys in a `.env` file (see
[.env.example](.env.example)):

```
OPENAI_API_KEY=sk-...
SONIOX_API_KEY=...
# Optional: SMTP_* to enable the feedback button
```

Then run with Docker:

```bash
docker compose up --build
```

or directly with [uv](https://docs.astral.sh/uv/):

```bash
uv run streamlit run app.py
```

You can also run individual stages from the command line without the web UI
(`json_to_srt.py` for transcript → SRT, `dual_caption.py` for SRT → bilingual
SRT).
