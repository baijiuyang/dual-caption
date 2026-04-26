"""
Fix fragmented sentences and typos in an SRT file.

Reads an auto-generated SRT (Chinese or English), merges entries that were
split mid-sentence, and fixes obvious typos.
Saves the result next to the input as <name>_fixed.srt.

Usage:
python fix_srt.py <filename>
"""

import argparse
import asyncio
import json
import re
from pathlib import Path

import srt
from dotenv import load_dotenv
from openai import AsyncOpenAI, BadRequestError, RateLimitError

MODEL = "gpt-5-mini-2025-08-07"
CHUNK_SIZE = 30
# Keep merged subtitles short to preserve timing faithfulness.
# If the model returns a too-long merge, we fall back to keeping originals.
MAX_MERGED_WORDS = 9
MAX_MERGED_CJK_CHARS = 18
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
- Keep each group's final text short (about one subtitle line). Prefer smaller merges over long merged sentences.
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


def _is_too_long_for_merge(text: str) -> bool:
    t = re.sub(r"\s+", " ", (text or "").strip())
    if not t:
        return False
    words = t.split(" ")
    # If it's mostly CJK and has no spaces, use char count heuristic.
    if len(words) == 1 and _is_dense_cjk(words[0]):
        return len(words[0]) > MAX_MERGED_CJK_CHARS
    return len(words) > MAX_MERGED_WORDS


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

            try:
                response = await client.chat.completions.create(
                    model=MODEL,
                    messages=[
                        {"role": "system", "content": INSTRUCTION},
                        {"role": "user", "content": prompt},
                    ],
                    response_format={"type": "json_object"},
                    **kwargs,
                )
            except BadRequestError as e:
                msg = str(e)
                if (
                    "temperature" in msg
                    and "Only the default (1) value is supported" in msg
                    and "temperature" in kwargs
                ):
                    response = await client.chat.completions.create(
                        model=MODEL,
                        messages=[
                            {"role": "system", "content": INSTRUCTION},
                            {"role": "user", "content": prompt},
                        ],
                        response_format={"type": "json_object"},
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
        # If the merged text is too long, keep originals for timing fidelity.
        if _is_too_long_for_merge(g["text"]):
            for idx in indices:
                new_subs.append(
                    srt.Subtitle(
                        index=len(new_subs) + 1,
                        start=subs[idx].start,
                        end=subs[idx].end,
                        content=subs[idx].content,
                    )
                )
            continue

        new_subs.append(
            srt.Subtitle(
                index=len(new_subs) + 1,
                start=subs[indices[0]].start,
                end=subs[indices[-1]].end,
                content=(g["text"] or "").strip(),
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
