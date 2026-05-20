"""
Convert a Soniox word-level transcript JSON into a high-quality SRT file.

Pipeline:
  1. Normalize tokens (interpolate zero-duration CJK chars).
  2. Rule-based segmentation using word timestamps, punctuation, and visual length caps.
  3. LLM refinement pass (merge/split/fix ASR errors) grounded in a video summary.
  4. Compose SRT, mapping refined text back to original word timestamps.

Usage:
  python json_to_srt.py <transcript.json> [--no-llm] [--no-summary]
"""

import argparse
import asyncio
import difflib
import json
import os
import re
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path

import srt
from dotenv import load_dotenv
from openai import AsyncOpenAI, BadRequestError, RateLimitError

MODEL = "gpt-5-mini-2025-08-07"
CHUNK_SIZE = 30

CHINESE_TARGET_CHARS = 8
CHINESE_MAX_CHARS = 18
ENGLISH_TARGET_WORDS = 5
ENGLISH_MAX_WORDS = 9

HARD_GAP_S = 1.2
SOFT_GAP_S = 0.5
MIN_LINE_DURATION_S = 0.6
MAX_LINE_DURATION_S = 6.0

TEMPERATURE = float(_t) if (_t := os.environ.get("OPENAI_TEMPERATURE")) else None

load_dotenv()
client = AsyncOpenAI() if os.environ.get("OPENAI_API_KEY") else None

_CJK_RE = re.compile(r"[一-鿿]")  # CJK Unified Ideographs (covers simplified Chinese)
_PUNCT_HARD = set("。！？.!?")
_PUNCT_SOFT = set("，、,;:；：")
_PUNCT_ALL = _PUNCT_HARD | _PUNCT_SOFT


@dataclass
class Token:
    text: str  # verbatim Soniox text — leading spaces encode word boundaries
    start_ms: int
    end_ms: int
    is_cjk: bool
    ends_hard: bool  # text ends with hard punctuation (sentence terminator)
    ends_soft: bool  # text ends with soft punctuation (clause separator)
    is_pure_punct: bool  # stripped text contains only punctuation


@dataclass
class Segment:
    tokens: list[Token] = field(default_factory=list)
    text: str = ""

    @property
    def start_ms(self) -> int:
        return self.tokens[0].start_ms

    @property
    def end_ms(self) -> int:
        return self.tokens[-1].end_ms

    @property
    def duration_s(self) -> float:
        return (self.end_ms - self.start_ms) / 1000.0


def _classify(text: str) -> tuple[bool, bool, bool, bool]:
    """Return (is_cjk, ends_hard, ends_soft, is_pure_punct) for a token text."""
    is_cjk = bool(_CJK_RE.search(text))
    stripped = text.strip()
    last = stripped[-1] if stripped else ""
    ends_hard = last in _PUNCT_HARD
    ends_soft = last in _PUNCT_SOFT
    is_pure_punct = bool(stripped) and all(c in _PUNCT_ALL for c in stripped)
    return is_cjk, ends_hard, ends_soft, is_pure_punct


def _normalize_tokens(raw_tokens: list[dict]) -> list[Token]:
    """Drop empty tokens; interpolate zero-duration CJK end_ms to next token's start_ms."""
    cleaned: list[dict] = []
    for t in raw_tokens:
        text = t.get("text") or ""
        if not text.strip():
            continue
        cleaned.append(t)

    tokens: list[Token] = []
    for i, t in enumerate(cleaned):
        text = t["text"]
        start_ms = int(t["start_ms"])
        end_ms = int(t["end_ms"])
        is_cjk, ends_hard, ends_soft, is_pure_punct = _classify(text)
        if end_ms <= start_ms:
            if i + 1 < len(cleaned):
                next_start = int(cleaned[i + 1]["start_ms"])
                if next_start > start_ms:
                    end_ms = next_start
            if end_ms <= start_ms:
                end_ms = start_ms + 1
        tokens.append(
            Token(
                text=text,
                start_ms=start_ms,
                end_ms=end_ms,
                is_cjk=is_cjk,
                ends_hard=ends_hard,
                ends_soft=ends_soft,
                is_pure_punct=is_pure_punct,
            )
        )
    return tokens


_LEADING_STRIP_RE = re.compile(r"^[\s" + re.escape("".join(_PUNCT_ALL)) + r"]+")


def _segment_text(tokens: list[Token]) -> str:
    """Concatenate Soniox token texts verbatim. Soniox encodes word boundaries
    via leading spaces in the text field; CJK chars and digits come without spaces.
    Leading whitespace/punctuation (left behind when a temporal break orphans a
    comma at the head of a segment) is stripped."""
    text = "".join(t.text for t in tokens)
    return _LEADING_STRIP_RE.sub("", text).strip()


def _visual_len(tokens: list[Token]) -> tuple[int, int]:
    """Return (cjk_char_count, latin_word_count) for the assembled text."""
    text = _segment_text(tokens)
    cjk_chars = len(_CJK_RE.findall(text))
    # Strip CJK and punctuation, count whitespace-separated word tokens.
    latin_only = _CJK_RE.sub(" ", text)
    latin_only = re.sub(r"[" + re.escape("".join(_PUNCT_ALL)) + r"]", " ", latin_only)
    latin_words = len([w for w in latin_only.split() if w])
    return cjk_chars, latin_words


def _exceeds_cap(tokens: list[Token], cap_cjk: int, cap_latin: int) -> bool:
    cjk, latin = _visual_len(tokens)
    return cjk > cap_cjk or latin > cap_latin


def segment_tokens(tokens: list[Token]) -> list[Segment]:
    """Greedy rule-based segmentation."""
    if not tokens:
        return []

    segments: list[Segment] = []
    current: list[Token] = []

    def flush():
        nonlocal current
        if not current:
            return
        # Drop segments that are pure punctuation.
        if all(t.is_pure_punct for t in current):
            current = []
            return
        seg = Segment(tokens=current, text=_segment_text(current))
        segments.append(seg)
        current = []

    for tok in tokens:
        if not current:
            current.append(tok)
            continue

        prev = current[-1]
        gap_s = max(0, tok.start_ms - prev.end_ms) / 1000.0
        cur_dur_s = (tok.start_ms - current[0].start_ms) / 1000.0

        # Rule 1: previous token ended a sentence.
        if prev.ends_hard:
            flush()
            current.append(tok)
            continue

        # Rule 2: hard temporal gap.
        if gap_s >= HARD_GAP_S:
            flush()
            current.append(tok)
            continue

        # Rule 3: max duration exceeded.
        if cur_dur_s >= MAX_LINE_DURATION_S:
            flush()
            current.append(tok)
            continue

        # Rule 4: adding token would exceed visual cap.
        tentative = current + [tok]
        if _exceeds_cap(tentative, CHINESE_MAX_CHARS, ENGLISH_MAX_WORDS):
            # Back up to the latest soft-punct or large-gap word boundary.
            best_split = -1
            for j in range(len(current) - 1, 0, -1):
                if current[j].ends_soft:
                    best_split = j + 1
                    break
                inner_gap = (current[j].start_ms - current[j - 1].end_ms) / 1000.0
                if inner_gap >= SOFT_GAP_S:
                    best_split = j
                    break
            if 0 < best_split < len(current):
                head = current[:best_split]
                tail = current[best_split:]
                current = head
                flush()
                current = tail
            else:
                flush()
            current.append(tok)
            continue

        # Rule 5: soft punctuation + meaningful gap + reached target length.
        if prev.ends_soft and gap_s >= SOFT_GAP_S:
            cjk, latin = _visual_len(current)
            if cjk >= CHINESE_TARGET_CHARS or latin >= ENGLISH_TARGET_WORDS:
                flush()
                current.append(tok)
                continue

        current.append(tok)

    flush()

    # Post-pass: merge sub-MIN_LINE_DURATION segments forward/back if cap allows.
    merged: list[Segment] = []
    for seg in segments:
        if not merged:
            merged.append(seg)
            continue
        prev = merged[-1]
        if seg.duration_s < MIN_LINE_DURATION_S:
            combined = prev.tokens + seg.tokens
            if not _exceeds_cap(combined, CHINESE_MAX_CHARS, ENGLISH_MAX_WORDS):
                merged[-1] = Segment(tokens=combined, text=_segment_text(combined))
                continue
        if prev.duration_s < MIN_LINE_DURATION_S:
            combined = prev.tokens + seg.tokens
            if not _exceeds_cap(combined, CHINESE_MAX_CHARS, ENGLISH_MAX_WORDS):
                merged[-1] = Segment(tokens=combined, text=_segment_text(combined))
                continue
        merged.append(seg)
    return merged


# -- LLM refinement -----------------------------------------------------------

SUMMARY_INSTRUCTION = "You are a video content analyst."
SUMMARY_PROMPT_TEMPLATE = (
    "Below are subtitle lines from a video. Produce a compact structured summary "
    "to help an editor fix grammar and speech recognition errors. Include:\n"
    "- Setting: location, time, season, or event\n"
    "- People: names and roles of anyone mentioned\n"
    "- Events: main narrative arc in 2-3 sentences\n"
    "- Tone: style of the content (casual vlog, technical, race commentary, etc.)\n"
    "- Terms: recurring domain-specific words or proper nouns that speech recognition might misrecognize\n\n"
    "Be concise. Use bullet points.\n\n"
    "Subtitles:\n{content}"
)

REFINE_INSTRUCTION_BASE = """You are finalizing speech-to-text subtitle candidates from a biking vlog (simplified Chinese, English, or mixed). If you write any Chinese, use simplified characters only.

You will receive numbered subtitle candidates. For each input index, you may either:
  - keep it as-is,
  - merge it with adjacent entries (consecutive indices only), or
  - split a single entry into two sub-lines (only if it exceeds ~9 English words or ~18 Chinese chars and a natural clause boundary exists).

Also fix obvious ASR typos and add missing punctuation using context. Do NOT translate or paraphrase.

Return JSON in this exact shape:
{
  "groups": [
    {"indices": [0, 1], "text": "merged corrected text"},
    {"indices": [2], "text": "single entry text"},
    {"indices": [3], "splits": ["first half", "second half"]}
  ]
}

Hard rules:
- Every input index appears in exactly one group.
- Indices within a group are consecutive and in ascending order.
- Groups are returned in order.
- For a split, "indices" must contain exactly one index and "splits" must contain exactly two strings.
- Keep each output line short (about one subtitle line: ~9 English words or ~18 Chinese chars max).
- Preserve the speaker's original meaning, language, and style.
"""


def _build_refine_instruction(video_summary: str) -> str:
    if not video_summary:
        return REFINE_INSTRUCTION_BASE
    return (
        REFINE_INSTRUCTION_BASE
        + f"\nVideo summary (use for context when fixing errors):\n{video_summary}\n"
    )


def _parse_retry_after(error: RateLimitError) -> float | None:
    if hasattr(error, "response") and error.response is not None:
        retry_after = error.response.headers.get("Retry-After")
        if retry_after:
            try:
                return float(retry_after)
            except ValueError:
                pass
    m = re.search(r"try again in (\d+)(ms|s)?", str(error), re.I)
    if m:
        val = int(m.group(1))
        unit = (m.group(2) or "s").lower()
        return val / 1000.0 if unit == "ms" else float(val)
    return None


async def _call_llm(
    instruction: str, prompt: str, json_mode: bool = True, max_retries: int = 10
) -> tuple[str, int]:
    base_delay = 1.0
    for attempt in range(max_retries):
        try:
            kwargs: dict = {}
            if TEMPERATURE is not None:
                kwargs["temperature"] = TEMPERATURE
            if json_mode:
                kwargs["response_format"] = {"type": "json_object"}

            try:
                response = await client.chat.completions.create(
                    model=MODEL,
                    messages=[
                        {"role": "system", "content": instruction},
                        {"role": "user", "content": prompt},
                    ],
                    **kwargs,
                )
            except BadRequestError as e:
                msg = str(e)
                if (
                    "temperature" in msg
                    and "Only the default (1) value is supported" in msg
                    and "temperature" in kwargs
                ):
                    kwargs.pop("temperature")
                    response = await client.chat.completions.create(
                        model=MODEL,
                        messages=[
                            {"role": "system", "content": instruction},
                            {"role": "user", "content": prompt},
                        ],
                        **kwargs,
                    )
                else:
                    raise
            return response.choices[0].message.content, response.usage.total_tokens
        except RateLimitError as e:
            if attempt == max_retries - 1:
                raise
            wait_time = _parse_retry_after(e) or base_delay * (2**attempt)
            wait_time = max(wait_time, 1.0)
            print(
                f"Rate limit. Waiting {wait_time:.1f}s ({attempt + 1}/{max_retries})..."
            )
            await asyncio.sleep(wait_time)


async def summarize_segments(segments: list[Segment]) -> str:
    content = "\n".join(s.text for s in segments)
    prompt = SUMMARY_PROMPT_TEMPLATE.format(content=content)
    summary, _ = await _call_llm(SUMMARY_INSTRUCTION, prompt, json_mode=False)
    return summary


def _chunk_segments(
    segments: list[Segment], target: int = CHUNK_SIZE, window: int = 5
) -> list[tuple[int, list[Segment]]]:
    """Snap chunk boundaries to the largest inter-segment time gap within ±window."""
    chunks: list[tuple[int, list[Segment]]] = []
    i = 0
    n = len(segments)
    while i < n:
        if i + target >= n:
            chunks.append((i, segments[i:]))
            break
        lo = max(i + 1, i + target - window)
        hi = min(n, i + target + window)
        best_split = i + target
        best_gap = -1.0
        for j in range(lo, hi):
            gap = (segments[j].start_ms - segments[j - 1].end_ms) / 1000.0
            if gap > best_gap:
                best_gap = gap
                best_split = j
        chunks.append((i, segments[i:best_split]))
        i = best_split
    return chunks


def _split_segment_at_text(
    seg: Segment, first_half_text: str
) -> tuple[list[Token], list[Token]] | None:
    """Find the best token index k so that text(seg.tokens[:k]) best matches first_half_text.

    Returns (head_tokens, tail_tokens) or None if seg has fewer than 2 word tokens.
    """
    word_indices = [i for i, t in enumerate(seg.tokens) if not t.is_pure_punct]
    if len(word_indices) < 2:
        return None

    target = first_half_text.strip()
    best_k = word_indices[len(word_indices) // 2]
    best_score = -1.0
    # Candidate split positions: after each token except the last (so both halves are non-empty).
    for k in range(1, len(seg.tokens)):
        head = seg.tokens[:k]
        if all(t.is_pure_punct for t in head):
            continue
        tail = seg.tokens[k:]
        if all(t.is_pure_punct for t in tail):
            continue
        head_text = _segment_text(head)
        score = difflib.SequenceMatcher(None, head_text, target).ratio()
        if score > best_score:
            best_score = score
            best_k = k

    return seg.tokens[:best_k], seg.tokens[best_k:]


async def _refine_chunk(
    chunk: list[Segment], offset: int, instruction: str
) -> tuple[list[dict], int]:
    numbered = "\n".join(f"[{offset + i}] {s.text}" for i, s in enumerate(chunk))
    raw, tokens = await _call_llm(instruction, f"Entries:\n{numbered}")
    try:
        groups = json.loads(raw).get("groups", [])
    except json.JSONDecodeError:
        print(f"Chunk at {offset}: invalid JSON from model, keeping originals")
        return [
            {"indices": [offset + i], "text": s.text} for i, s in enumerate(chunk)
        ], tokens

    expected = list(range(offset, offset + len(chunk)))
    seen: list[int] = []
    for g in groups:
        seen.extend(g.get("indices", []))
    if seen != expected:
        print(f"Chunk at {offset}: invalid indices from model, keeping originals")
        groups = [
            {"indices": [offset + i], "text": s.text} for i, s in enumerate(chunk)
        ]
    return groups, tokens


def _apply_groups(segments: list[Segment], groups: list[dict]) -> list[Segment]:
    """Map refined groups back to Segments with correct timestamps."""
    out: list[Segment] = []
    for g in groups:
        indices = g.get("indices", [])
        if not indices:
            continue

        # Split case: single index, two output lines.
        if (
            "splits" in g
            and len(indices) == 1
            and isinstance(g.get("splits"), list)
            and len(g["splits"]) == 2
        ):
            src = segments[indices[0]]
            halves = _split_segment_at_text(src, g["splits"][0])
            if halves is None:
                out.append(Segment(tokens=src.tokens, text=src.text))
                continue
            head_tokens, tail_tokens = halves
            out.append(Segment(tokens=head_tokens, text=g["splits"][0].strip()))
            out.append(Segment(tokens=tail_tokens, text=g["splits"][1].strip()))
            continue

        # Merge / keep case.
        new_text = (g.get("text") or "").strip()
        merged_tokens: list[Token] = []
        for idx in indices:
            merged_tokens.extend(segments[idx].tokens)
        if not new_text:
            new_text = _segment_text(merged_tokens)

        # Safety net: if the merged text blows past the cap, keep originals.
        if len(indices) > 1:
            cjk_count = sum(1 for ch in new_text if _CJK_RE.match(ch))
            latin_words = len(
                [w for w in re.split(r"\s+", new_text) if w and not _CJK_RE.search(w)]
            )
            if cjk_count > CHINESE_MAX_CHARS or latin_words > ENGLISH_MAX_WORDS:
                for idx in indices:
                    s = segments[idx]
                    out.append(Segment(tokens=s.tokens, text=s.text))
                continue

        out.append(Segment(tokens=merged_tokens, text=new_text))
    return out


async def refine_with_llm(segments: list[Segment], video_summary: str) -> list[Segment]:
    instruction = _build_refine_instruction(video_summary)
    chunks = _chunk_segments(segments)
    results = await asyncio.gather(
        *(_refine_chunk(c, off, instruction) for off, c in chunks)
    )
    all_groups: list[dict] = []
    total_tokens = 0
    for groups, tokens in results:
        all_groups.extend(groups)
        total_tokens += tokens
    print(f"Refinement tokens used: {total_tokens}")
    return _apply_groups(segments, all_groups)


# -- Compose ------------------------------------------------------------------


def compose_srt(segments: list[Segment]) -> str:
    subs: list[srt.Subtitle] = []
    for i, seg in enumerate(segments, start=1):
        subs.append(
            srt.Subtitle(
                index=i,
                start=timedelta(milliseconds=seg.start_ms),
                end=timedelta(milliseconds=seg.end_ms),
                content=seg.text,
            )
        )
    return srt.compose(subs)


async def json_to_srt(
    raw_json: str, use_llm: bool = True, use_summary: bool = True
) -> str:
    raw_tokens = json.loads(raw_json)
    tokens = _normalize_tokens(raw_tokens)
    segments = segment_tokens(tokens)
    print(f"Rule-based segmentation produced {len(segments)} segments.")

    if use_llm:
        if client is None:
            raise RuntimeError(
                "OPENAI_API_KEY is not set; cannot run LLM refinement. Use --no-llm to skip."
            )
        video_summary = ""
        if use_summary:
            print("Summarizing video content...")
            video_summary = await summarize_segments(segments)
            print(f"Video summary:\n{video_summary}\n")
        segments = await refine_with_llm(segments, video_summary)
        print(f"After LLM refinement: {len(segments)} segments.")

    return compose_srt(segments)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("filename", type=str, help="Path to Soniox JSON transcript")
    parser.add_argument(
        "--no-llm", action="store_true", help="Skip LLM refinement (rule-based only)"
    )
    parser.add_argument(
        "--no-summary", action="store_true", help="Skip video summary call"
    )
    args = parser.parse_args()

    input_path = Path(args.filename)
    raw = input_path.read_text(encoding="utf8")
    result = asyncio.run(
        json_to_srt(raw, use_llm=not args.no_llm, use_summary=not args.no_summary)
    )

    output_path = input_path.with_suffix(".srt")
    output_path.write_text(result, encoding="utf8")
    print(f"Saved: {output_path}")


if __name__ == "__main__":
    main()
