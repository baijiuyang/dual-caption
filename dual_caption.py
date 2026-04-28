"""
Generate English Chinese dual language subtitles.

Usage:
python dual_caption.py <filename>
"""

import re
import time
import argparse
import asyncio
import os
from pathlib import Path

import srt
from dotenv import load_dotenv
from openai import AsyncOpenAI, BadRequestError, RateLimitError

MODEL = "gpt-5-mini-2025-08-07"
TEMPERATURE = float(_t) if (_t := os.environ.get("OPENAI_TEMPERATURE")) else None

load_dotenv()
client = AsyncOpenAI()


def add_second_subtitles(subs: list[srt.Subtitle], lines: list[str]) -> str:
    for sub, line in zip(subs, lines):
        sub.content += f"\n{line}"
    return srt.compose(subs)


def save_srt(raw_srt: str, filename: str) -> None:
    with open(filename, "w", encoding="utf8") as f:
        f.write(raw_srt)


async def summarize_srt(lines: list[str]) -> str:
    content = "\n".join(lines)
    instruction = "You are a video content analyst."
    prompt = (
        "Below are subtitle lines from a video. Produce a compact structured summary "
        "to help a translator. Include:\n"
        "- Setting: location, time, season, or event\n"
        "- People: names and roles of anyone mentioned\n"
        "- Events: main narrative arc in 2-3 sentences\n"
        "- Tone: style of the content (casual vlog, technical, race commentary, etc.)\n"
        "- Terms: recurring domain-specific words or proper nouns needing consistent translation\n\n"
        "Be concise. Use bullet points. Do not translate anything.\n\n"
        f"Subtitles:\n{content}"
    )
    summary, _ = await get_answer(instruction, prompt)
    return summary


def create_prompt(context_lines: list[str], target_idx: int, video_summary: str = "") -> str:
    marked = [
        f">>> {line} <<<" if i == target_idx else line
        for i, line in enumerate(context_lines)
    ]
    block = "\n".join(marked)
    summary_section = f"Video summary:\n{video_summary}\n\n" if video_summary else ""
    return (
        "Translate the line marked with >>> <<< to Chinese if it's English, or to "
        "English if it's Chinese. The unmarked lines are surrounding context only — "
        "do not translate them. Be faithful to the original meaning rather than "
        "verbatim. Return only the translated sentence, nothing else.\n\n"
        f"{summary_section}"
        f"Lines:\n{block}"
    )


def create_instruction() -> str:
    return "You are a subtitles translator."


def _parse_retry_after(error: RateLimitError) -> float | None:
    """Parse the suggested retry wait time (seconds) from a RateLimitError."""
    # 1. Try the Retry-After response header
    if hasattr(error, "response") and error.response is not None:
        retry_after = error.response.headers.get("Retry-After")
        if retry_after:
            try:
                return float(retry_after)
            except ValueError:
                pass
    # 2. Try parsing the error message for "try again in 266ms" or "try again in 30s"
    err_str = str(error)
    m = re.search(r"try again in (\d+)(ms|s)?", err_str, re.I)
    if m:
        val = int(m.group(1))
        unit = (m.group(2) or "s").lower()
        return val / 1000.0 if unit == "ms" else float(val)
    return None


async def get_answer(instruction: str, prompt: str, max_retries: int = 10):
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
                        {"role": "system", "content": instruction},
                        {"role": "user", "content": prompt},
                    ],
                    **kwargs,
                )
            except BadRequestError as e:
                # If a model rejects non-default temperature, retry once without it.
                msg = str(e)
                if (
                    "temperature" in msg
                    and "Only the default (1) value is supported" in msg
                    and "temperature" in kwargs
                ):
                    response = await client.chat.completions.create(
                        model=MODEL,
                        messages=[
                            {"role": "system", "content": instruction},
                            {"role": "user", "content": prompt},
                        ],
                    )
                else:
                    raise
            content = (
                (response.choices[0].message.content or "").strip().strip("\"'").strip()
            )
            print(content)
            return content, response.usage.total_tokens
        except RateLimitError as e:
            if attempt == max_retries - 1:
                raise
            wait_time = _parse_retry_after(e)
            if wait_time is None:
                wait_time = base_delay * (2**attempt)
            else:
                # API-suggested wait may be very short; floor at 1 second
                wait_time = max(wait_time, 1.0)
            print(
                f"Rate limit reached. Waiting {wait_time:.1f}s before retry ({attempt + 1}/{max_retries})..."
            )
            await asyncio.sleep(wait_time)


async def add_dual_captions(raw_srt: str) -> str:
    subs = list(srt.parse(raw_srt))
    lines = [s.content for s in subs]
    instruction = create_instruction()

    print("Summarizing video content...")
    video_summary = await summarize_srt(lines)
    print(f"Video summary:\n{video_summary}\n")

    cache: dict[str, asyncio.Task] = {}
    tasks = []
    total_results = []
    for i in range(len(lines)):
        if i > 450 and i % 450 == 1:
            print("Reached 450 RPM. Wait for 62s.")
            results = await asyncio.gather(*tasks)
            total_results += results
            tasks = []
            time.sleep(62)
        line = lines[i]
        if line in cache:
            tasks.append(cache[line])
            continue
        # Collect up to two previous and two next lines
        start = max(0, i - 2)
        end = min(len(lines), i + 3)  # +3 because slice end is exclusive
        context_lines = lines[start:end]
        target_idx = i - start
        prompt = create_prompt(context_lines, target_idx, video_summary)
        task = asyncio.create_task(get_answer(instruction, prompt))
        cache[line] = task
        tasks.append(task)

    results = await asyncio.gather(*tasks)
    total_results += results

    total_usage = 0
    out_lines = []
    for line, usage in total_results:
        out_lines.append(line)
        total_usage += usage
    print(f"total token used: {total_usage}")

    return add_second_subtitles(subs, out_lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("filename", type=str)
    args = parser.parse_args()

    input_path = Path(args.filename)
    raw_srt = input_path.read_text(encoding="utf8")
    new_srt = asyncio.run(add_dual_captions(raw_srt))
    output_path = input_path.with_stem(f"{input_path.stem}_output")
    save_srt(new_srt, str(output_path))


if __name__ == "__main__":
    main()
