"""
Generate English Chinese dual language subtitles.

Usage:
python dual_caption.py <filename>
"""

import re
import time
import argparse
from pathlib import Path
from openai import AsyncOpenAI
from openai import RateLimitError
import srt
import asyncio

MODEL = "gpt-4.1-2025-04-14"

client = AsyncOpenAI()
parser = argparse.ArgumentParser()

parser.add_argument("filename", type=str)

args = parser.parse_args()


def load_subs(filename: str) -> list[srt.Subtitle]:
    with open(filename, "r", encoding="utf8") as f:
        return list(srt.parse(f.read()))


def add_second_subtitles(subs: list[srt.Subtitle], lines: list[str]) -> str:
    for sub, line in zip(subs, lines):
        sub.content += f"\n{line}"
    return srt.compose(subs)


def save_srt(raw_srt: str, filename: str) -> None:
    with open(filename, "w", encoding="utf8") as f:
        f.write(raw_srt)


def create_prompt(context_lines: list[str], target_idx: int) -> str:
    marked = [
        f">>> {line} <<<" if i == target_idx else line
        for i, line in enumerate(context_lines)
    ]
    block = "\n".join(marked)
    return (
        "Translate the line marked with >>> <<< to Chinese if it's English, or to "
        "English if it's Chinese. The unmarked lines are surrounding context only — "
        "do not translate them. Be faithful to the original meaning rather than "
        "verbatim. Return only the translated sentence, nothing else.\n\n"
        f"Context (biking vlog):\n{block}"
    )


def create_instruction() -> str:
    return "You are a subtitles translator."


def _parse_retry_after(error: RateLimitError) -> float | None:
    """从 RateLimitError 中解析建议的重试等待时间（秒）"""
    # 1. 尝试从响应头获取 Retry-After
    if hasattr(error, "response") and error.response is not None:
        retry_after = error.response.headers.get("Retry-After")
        if retry_after:
            try:
                return float(retry_after)
            except ValueError:
                pass
    # 2. 尝试从错误信息解析 "try again in 266ms" 或 "try again in 30s"
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
            response = await client.chat.completions.create(
                model=MODEL,
                messages=[
                    {"role": "system", "content": instruction},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.5,
            )
            content = (response.choices[0].message.content or "").strip().strip('"\'').strip()
            print(content)
            return content, response.usage.total_tokens
        except RateLimitError as e:
            if attempt == max_retries - 1:
                raise
            wait_time = _parse_retry_after(e)
            if wait_time is None:
                wait_time = base_delay * (2**attempt)
            else:
                # API 返回的时间可能很短，至少等 1 秒
                wait_time = max(wait_time, 1.0)
            print(
                f"Rate limit reached. Waiting {wait_time:.1f}s before retry ({attempt + 1}/{max_retries})..."
            )
            await asyncio.sleep(wait_time)


async def async_main(subs: list[srt.Subtitle]):
    lines = [s.content for s in subs]
    instruction = create_instruction()
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
        prompt = create_prompt(context_lines, target_idx)
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

    new_srt = add_second_subtitles(subs, out_lines)
    input_path = Path(args.filename)
    output_path = input_path.with_stem(f"{input_path.stem}_output")
    save_srt(new_srt, str(output_path))


def main():
    subs = load_subs(args.filename)
    asyncio.run(async_main(subs))


if __name__ == "__main__":
    main()
