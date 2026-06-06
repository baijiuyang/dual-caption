"""Re-align edited subtitle-line text back to word-level timestamps.

The Step 2 editor lets users edit whole lines as free text, but the downstream
pipeline wants word-level tokens carrying timestamps. When a line is edited we
character-align the new text against the original tokens (which carry per-word
timing) and redistribute timestamps: unchanged characters keep their exact
times, and changed/inserted characters get proportionally interpolated times
from the span they replaced. The characters are then regrouped into word
tokens, so a word that survives the edit keeps its original timing and a word
that was split inherits a proportional slice of the original word's span.
"""

import difflib

from json_to_srt import _CJK_RE, _LEADING_STRIP_RE, _PUNCT_ALL


def _char_times(tokens: list[dict]) -> list[tuple[str, int, int]]:
    """Per-character (char, start_ms, end_ms) for the line's displayed text.

    Each token's span is interpolated linearly across its characters, then the
    same leading/trailing strip the editor used to render the line is applied so
    the character sequence matches exactly what the user edited.
    """
    chars: list[tuple[str, int, int]] = []
    for t in tokens:
        text = t["text"]
        if not text:
            continue
        s = int(t["start_ms"])
        e = int(t["end_ms"])
        span = max(e - s, 0)
        m = len(text)
        for k, ch in enumerate(text):
            chars.append((ch, s + span * k // m, s + span * (k + 1) // m))

    full = "".join(c[0] for c in chars)
    core = _LEADING_STRIP_RE.sub("", full)  # strip leading whitespace/punct
    lead = len(full) - len(core)
    trail = len(core) - len(core.rstrip())  # strip trailing whitespace
    return chars[lead : len(chars) - trail] if trail else chars[lead:]


def _regroup(new_text: str, times: list[tuple[int, int]]) -> list[dict]:
    """Group characters + their times into word tokens (Soniox conventions):
    each CJK char (plus trailing punctuation) is its own token; a run of Latin
    text is one token with a leading space (except the first token in the line).
    """
    out: list[dict] = []
    n = len(new_text)
    i = 0
    first = True
    while i < n:
        ch = new_text[i]
        if ch.isspace():
            i += 1
            continue
        if _CJK_RE.match(ch):
            start, end = times[i]
            j = i + 1
            while j < n and new_text[j] in _PUNCT_ALL:
                end = max(end, times[j][1])
                j += 1
            out.append(
                {
                    "text": new_text[i:j],
                    "start_ms": start,
                    "end_ms": end,
                    "confidence": 1.0,
                }
            )
            i = j
        else:
            j = i
            while (
                j < n and not new_text[j].isspace() and not _CJK_RE.match(new_text[j])
            ):
                j += 1
            seg = new_text[i:j]
            starts = [times[k][0] for k in range(i, j)]
            ends = [times[k][1] for k in range(i, j)]
            out.append(
                {
                    "text": seg if first else " " + seg,
                    "start_ms": min(starts),
                    "end_ms": max(ends),
                    "confidence": 1.0,
                }
            )
            i = j
        first = False
    return out


def retime_line(new_text: str, tokens: list[dict]) -> list[dict]:
    """Return word-level token dicts for an edited line, preserving timestamps
    of unchanged characters and interpolating changed/inserted ones.

    `tokens` are the line's original (normalized) token dicts with text /
    start_ms / end_ms. `new_text` is the user's edited line text.
    """
    chars = _char_times(tokens)
    orig = "".join(c[0] for c in chars)
    new = new_text.strip()
    times: list[tuple[int, int] | None] = [None] * len(new)

    sm = difflib.SequenceMatcher(None, orig, new, autojunk=False)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            for off in range(j2 - j1):
                times[j1 + off] = (chars[i1 + off][1], chars[i1 + off][2])
        elif tag == "delete":
            continue
        else:  # replace / insert: distribute the replaced span across new chars
            if i2 > i1:
                bs, be = chars[i1][1], chars[i2 - 1][2]
            elif i1 > 0:
                bs = be = chars[i1 - 1][2]
            elif chars:
                bs = be = chars[0][1]
            else:
                bs = be = 0
            cnt = j2 - j1
            for off in range(cnt):
                times[j1 + off] = (
                    bs + (be - bs) * off // cnt,
                    bs + (be - bs) * (off + 1) // cnt,
                )

    # Fill any gaps and enforce monotonic, non-negative durations.
    prev = 0
    filled: list[tuple[int, int]] = []
    for t in times:
        s, e = t if t is not None else (prev, prev)
        s = max(s, prev)
        e = max(e, s)
        filled.append((s, e))
        prev = e

    return _regroup(new, filled)
