import time
import argparse
from openai import AsyncOpenAI
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
    return f"""Given the context "{context}", translate the following text to Chinese if it's English or to English if it's Chinese:\n{line}"""


def create_instruction() -> str:
    return "You are a subtitles translator."


def count_words(content: str) -> str:
    return content.count(" ")


async def get_answer(instruction: str, prompt: str):
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
