import re
import time
import argparse
from openai import AsyncOpenAI
from openai import RateLimitError
import srt
import asyncio

client = AsyncOpenAI()
parser = argparse.ArgumentParser()

parser.add_argument("filename", type=str)

args = parser.parse_args()


def get_content_from_srt(raw_srt: str) -> list[str]:
    sub_generator = srt.parse(raw_srt)
    subs = list(sub_generator)
    lines = []
    for line in subs:
        lines.append(line.content)
    return lines


def add_second_subtitles(raw_srt: str, lines: list[str]) -> str:
    sub_generator = srt.parse(raw_srt)
    subs = list(sub_generator)
    for sub, line in zip(subs, lines):
        sub.content += f"\n{line}"
    return srt.compose(subs)


def load_srt(filename: str) -> str:
    with open(filename, "r", encoding="utf8") as f:
        raw_srt = f.read()
    return raw_srt


def save_srt(raw_srt: str, filename: str = "dual.srt") -> None:
    with open(filename, "w", encoding="utf8") as f:
        f.write(raw_srt)


def create_prompt(line: str, context: str) -> str:
    return f"""Given the context from two previous lines to two next lines "{context}", translate the below text to Chinese if it's English or to English if it's Chinese. Make sure to (1) correct any grammarly mistake since it's a biking vlog, (2) be faithfuly to the original meaning not verbatim translation, (3) only return the translated sentence, nothing else.\n{line}"""


def create_instruction() -> str:
    return "You are a subtitles translator."


def count_words(content: str) -> str:
    return content.count(" ")


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
                model="gpt-4.1-2025-04-14",
                messages=[
                    {"role": "system", "content": instruction},
                    {"role": "user", "content": prompt},
                ],
                # max_tokens=4096,
                temperature=0.5,
            )
            print(response.choices[0].message.content)
            return response.choices[0].message.content, response.usage.total_tokens
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


async def async_main(raw_srt: str):
    lines = get_content_from_srt(raw_srt)
    instruction = create_instruction()
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
        # Collect up to two previous and two next lines
        start = max(0, i - 2)
        end = min(len(lines), i + 3)  # +3 because slice end is exclusive
        context_lines = lines[start:end]

        # Build context (includes up to 5 lines: prev2, prev1, current, next1, next2)
        context = "\n".join(context_lines)

        prompt = create_prompt(line, context)
        task = asyncio.create_task(get_answer(instruction, prompt))
        tasks.append(task)

    results = await asyncio.gather(*tasks)
    total_results += results

    total_usage = 0
    lines = []
    for line, usage in total_results:
        lines.append(line)
        total_usage += usage

    print(f"total token used: {total_usage}")

    new_srt = add_second_subtitles(raw_srt, lines)
    save_srt(new_srt, args.filename[:-4] + "_output.srt")


def main():
    raw_srt = load_srt(args.filename)
    asyncio.run(async_main(raw_srt))


if __name__ == "__main__":
    main()
    # raw_srt = load_srt("en.srt")
    # content = get_content_from_srt(raw_srt)
    # print(content)
