"""
Fix fragmented sentences and typos in an SRT file.

Reads an auto-generated SRT (Chinese or English), merges entries that were
split mid-sentence, fixes obvious typos, and rewraps long lines to ~7-9
English words per subtitle (or comparable CJK length) for one-line display.
Saves the result next to the input as <name>_fixed.srt.

Usage:
python fix_srt.py <filename>
"""

import argparse
import asyncio
import json
import re
from datetime import timedelta
from pathlib import Path

import srt
from dotenv import load_dotenv
from openai import AsyncOpenAI, RateLimitError

MODEL = "gpt-5-mini-2025-08-07"
CHUNK_SIZE = 30
# Merged text is re-wrapped so each on-screen line is ~this many “words” (Latin)
# or a comparable CJK length when the segment has no spaces.
DISPLAY_WORDS_LO = 7
DISPLAY_WORDS_HI = 9
# CJK (no jieba): one line ≈ 4–5 English short words; map 7–9 “words” to this char range.
CJK_CHARS_LO = 14
CJK_CHARS_HI = 18
TEMPERATURE = (
    float(_t) if (_t := __import__("os").environ.get("OPENAI_TEMPERATURE")) else None
)

load_dotenv()
client = AsyncOpenAI()

INSTRUCTION = """You are editing speech-to-text subtitle output (Chinese or English) from a biking vlog.

You will receive numbered subtitle entries. Your job is to:
1. Merge entries that belong to the same sentence — auto-transcripts often split a single spoken sentence across multiple short entries.
2. Fix obvious typos and speech recognition errors using surrounding context.
3. Add missing punctuation where natural.
4. Preserve the speaker's original meaning, language, and style. Do not translate or paraphrase.
5. The tool will rewrap your merged text into display-sized lines; you may return natural sentences without line breaks.

Return JSON in this exact shape:
{
  "groups": [
    {"indices": [0, 1, 2], "text": "merged corrected text"},
    {"indices": [3], "text": "single entry text"}
  ]
}

Rules:
- Every input index must appear in exactly one group.
- Indices within a group must be consecutive and in ascending order.
- Groups must be returned in order.
- If an entry is already a complete sentence, return it as a single-index group.
"""

_CJK_RE = re.compile(
    r"[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufad9\u3000\u3001-\u3003\u3008-\u3011\uff0c\uff01\uff1b\uff1a\uff1f\uff0e]"  # noqa: E501
)


def _is_dense_cjk(text: str) -> bool:
    s = text.strip()
    if len(s) < 10:
        return False
    cjk = len(_CJK_RE.findall(s))
    return cjk / max(1, len(s)) > 0.4


def _distribute_n_into_k(n: int, k: int) -> list[int]:
    if k <= 0:
        return []
    base, rem = divmod(n, k)
    return [base + (1 if i < rem else 0) for i in range(k)]


def _chunk_sizes_latin_word_count(
    n: int, _lo: int, hi: int, relax_low: int = 3
) -> list[int]:
    """Split n words into k consecutive segments; aim for [lo, hi] words per line."""
    if n == 0:
        return []
    if n <= hi:
        return [n]
    # Smallest k so each part has at most `hi` words (and sizes differ by at most 1).
    k = (n + hi - 1) // hi
    sizes = _distribute_n_into_k(n, k)
    for _ in range(n):
        if not sizes or len(sizes) < 2:
            break
        if all(relax_low <= s <= hi for s in sizes):
            break
        j = int(min(range(len(sizes)), key=lambda i: sizes[i]))
        if sizes[j] < relax_low:
            if j + 1 < len(sizes):
                sizes[j] += sizes[j + 1]
                sizes.pop(j + 1)
            elif j > 0:
                sizes[j - 1] += sizes[j]
                sizes.pop(j)
    return sizes if sizes else [n]


def _chunk_sizes_cjk_char_count(
    n: int, _lo: int, hi: int, relax_low: int = 6
) -> list[int]:
    if n == 0:
        return []
    if n <= hi:
        return [n]
    k = (n + hi - 1) // hi
    sizes = _distribute_n_into_k(n, k)
    for _ in range(n):
        if not sizes or len(sizes) < 2:
            break
        if all(relax_low <= s <= hi for s in sizes):
            break
        j = int(min(range(len(sizes)), key=lambda i: sizes[i]))
        if sizes[j] < relax_low:
            if j + 1 < len(sizes):
                sizes[j] += sizes[j + 1]
                sizes.pop(j + 1)
            elif j > 0:
                sizes[j - 1] += sizes[j]
                sizes.pop(j)
    return sizes if sizes else [n]


def _split_latin_words(words: list[str], lo: int, hi: int) -> list[str]:
    n = len(words)
    if n == 0:
        return []
    sizes = _chunk_sizes_latin_word_count(n, lo, hi)
    out, i = [], 0
    for s in sizes:
        part = words[i : i + s]
        i += s
        line = " ".join(part)
        if line:
            out.append(line)
    return out


def _split_cjk_string(text: str, lo: int, hi: int) -> list[str]:
    s = re.sub(r"\s+", " ", text.strip())
    n = len(s)
    if n == 0:
        return []
    if n <= hi:
        return [s]
    sizes = _chunk_sizes_cjk_char_count(n, lo, hi)
    out, i = [], 0
    for sl in sizes:
        chunk = s[i : i + sl]
        i += sl
        if chunk:
            out.append(chunk)
    return out


def _split_merged_text_for_display(
    text: str,
    lo: int = DISPLAY_WORDS_LO,
    hi: int = DISPLAY_WORDS_HI,
) -> list[str]:
    t = re.sub(r"\s+", " ", (text or "").strip())
    if not t:
        return []
    words = t.split(" ")
    if len(words) == 1 and _is_dense_cjk(words[0]):
        return _split_cjk_string(words[0], CJK_CHARS_LO, CJK_CHARS_HI)
    return _split_latin_words(words, lo, hi)


def _line_weights(lines: list[str]) -> list[float]:
    w = [max(1.0, float(len(s))) for s in lines]
    s = float(sum(w))
    return [x / s for x in w]


def _time_slices(
    start: timedelta, end: timedelta, weights: list[float]
) -> list[tuple[timedelta, timedelta]]:
    if not weights:
        return []
    wsum = float(sum(weights)) or 1.0
    span = (end - start).total_seconds()
    if span < 0:
        span = 0.0
    edges: list[timedelta] = [start]
    acc = 0.0
    for w in weights[:-1]:
        acc += w * span / wsum
        edges.append(start + timedelta(seconds=acc))
    edges.append(end)
    return list(zip(edges, edges[1:]))


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


async def call_llm(prompt: str, max_retries: int = 10) -> tuple[str, int]:
    base_delay = 1.0
    for attempt in range(max_retries):
        try:
            # Some models only support the default temperature. To stay compatible,
            # we omit `temperature` unless explicitly configured.
            kwargs = {}
            if TEMPERATURE is not None:
                kwargs["temperature"] = TEMPERATURE

            response = await client.chat.completions.create(
                model=MODEL,
                messages=[
                    {"role": "system", "content": INSTRUCTION},
                    {"role": "user", "content": prompt},
                ],
                response_format={"type": "json_object"},
                **kwargs,
            )
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


async def fix_chunk(subs: list[srt.Subtitle], offset: int) -> tuple[list[dict], int]:
    numbered = "\n".join(f"[{offset + i}] {s.content}" for i, s in enumerate(subs))
    raw, tokens = await call_llm(f"Entries:\n{numbered}")
    groups = json.loads(raw)["groups"]

    expected = list(range(offset, offset + len(subs)))
    seen = [i for g in groups for i in g["indices"]]
    if seen != expected:
        print(f"Chunk at {offset}: invalid indices from model, keeping originals")
        groups = [
            {"indices": [offset + i], "text": s.content} for i, s in enumerate(subs)
        ]

    return groups, tokens


def chunk_subs(
    subs: list[srt.Subtitle], target: int = CHUNK_SIZE, window: int = 5
) -> list[tuple[int, list[srt.Subtitle]]]:
    """Split subs into chunks of ~target size, snapping boundaries to the largest
    inter-entry time gap within ±window of the target boundary."""
    chunks = []
    i = 0
    n = len(subs)
    while i < n:
        if i + target >= n:
            chunks.append((i, subs[i:]))
            break
        lo = max(i + 1, i + target - window)
        hi = min(n, i + target + window)
        best_split = i + target
        best_gap = -1.0
        for j in range(lo, hi):
            gap = (subs[j].start - subs[j - 1].end).total_seconds()
            if gap > best_gap:
                best_gap = gap
                best_split = j
        chunks.append((i, subs[i:best_split]))
        i = best_split
    return chunks


async def fix_srt(raw_srt: str) -> str:
    subs = list(srt.parse(raw_srt))
    chunks = chunk_subs(subs)

    results = await asyncio.gather(*(fix_chunk(c, off) for off, c in chunks))

    all_groups = []
    total_tokens = 0
    for groups, tokens in results:
        all_groups.extend(groups)
        total_tokens += tokens
    print(f"Total tokens used: {total_tokens}")

    new_subs: list[srt.Subtitle] = []
    for g in all_groups:
        indices = g["indices"]
        start, end = subs[indices[0]].start, subs[indices[-1]].end
        lines = _split_merged_text_for_display(g["text"])
        if not lines:
            continue
        wts = _line_weights(lines)
        slices = _time_slices(start, end, wts)
        for line, (s0, s1) in zip(lines, slices):
            new_subs.append(
                srt.Subtitle(
                    index=len(new_subs) + 1,
                    start=s0,
                    end=s1,
                    content=line,
                )
            )
    return srt.compose(new_subs)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("filename", type=str)
    args = parser.parse_args()

    input_path = Path(args.filename)
    raw = input_path.read_text(encoding="utf8")
    fixed = asyncio.run(fix_srt(raw))

    output_path = input_path.with_name(f"{input_path.stem}_fixed.srt")
    output_path.write_text(fixed, encoding="utf8")
    print(f"Saved: {output_path}")


if __name__ == "__main__":
    main()
