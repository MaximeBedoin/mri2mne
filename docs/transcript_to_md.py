"""Convert a Claude Code .jsonl session transcript into a readable, REDACTED
Markdown document — complete (user + assistant text, chain-of-thought, tool
calls and tool results), with personal data scrubbed.

This is the exact tool used to produce CHAT_TRANSCRIPT.md in this folder. The
REDACTIONS list below ships with **placeholders**: fill in your own personal
data (e-mail, license keys, local username) before running it on your own
transcript. Review the OUTPUT before publishing — redaction is best-effort.

Usage:
    python transcript_to_md.py INPUT.jsonl OUTPUT.md
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter

# --- Redaction rules (applied to every rendered string) --------------------
# (pattern, replacement). Order matters: redact the e-mail before the username.
# >>> Replace the placeholders below with the values YOU want scrubbed. <<<
REDACTIONS = [
    (re.compile(r"your\.name@example\.com", re.I), "[REDACTED-EMAIL]"),
    (re.compile(r"YOUR_LICENSE_KEY"), "[REDACTED-LICENSE-KEY]"),
    # Local Windows/WSL username, any case, any path separator style. The word
    # boundaries keep look-alike words (e.g. "maximum") untouched.
    (re.compile(r"\bYOUR_USERNAME\b", re.I), "USER"),
    # WSL machine hostname (leaks via `uname -a` output).
    (re.compile(r"YOUR_HOSTNAME", re.I), "WSL-HOST"),
]

# Cap long tool payloads (they can be megabytes). Text and thinking are NEVER
# capped -- they are the substance. Set to 0 for no cap.
MAX_TOOL_CHARS = 4000

# Optional free-text note appended to the header (e.g. tokens spent by sub-agents
# that ran in SEPARATE sessions and are therefore absent from this .jsonl). Set
# to "" to omit. The task runner reports sub-agent usage as a single combined
# (read+write) figure, so it cannot be split like the main-session totals.
SUBAGENT_NOTE = (
    "Sub-agent reviews (Fable, run in separate sessions and NOT included in the "
    "totals above): two code reviews at ~76,515 and ~124,280 tokens "
    "(~200,795 combined read+write, as reported by the task runner)."
)

_redaction_counts: Counter = Counter()


def redact(text: str) -> str:
    if not isinstance(text, str):
        text = str(text)
    for pat, repl in REDACTIONS:
        text, n = pat.subn(repl, text)
        if n:
            _redaction_counts[repl] += n
    return text


def cap(text: str, limit: int) -> str:
    if limit and len(text) > limit:
        return text[:limit] + f"\n…[truncated {len(text) - limit} chars]"
    return text


def result_to_text(content) -> str:
    """A tool_result 'content' is a str or a list of blocks."""
    if isinstance(content, str):
        return content
    parts = []
    if isinstance(content, list):
        for b in content:
            if isinstance(b, dict):
                if b.get("type") == "text":
                    parts.append(b.get("text", ""))
                elif b.get("type") == "image":
                    parts.append("[image omitted]")
                else:
                    parts.append(json.dumps(b, ensure_ascii=False)[:500])
            else:
                parts.append(str(b))
    return "\n".join(parts)


def render_blocks(content, out: list[str]) -> None:
    if isinstance(content, str):
        if content.strip():
            out.append(redact(content))
        return
    if not isinstance(content, list):
        return
    for b in content:
        if not isinstance(b, dict):
            continue
        bt = b.get("type")
        if bt == "text":
            if b.get("text", "").strip():
                out.append(redact(b["text"]))
        elif bt == "thinking":
            think = redact(b.get("thinking", ""))
            out.append(
                "<details><summary>💭 Chain of thought</summary>\n\n"
                "```text\n" + think + "\n```\n</details>"
            )
        elif bt == "tool_use":
            name = b.get("name", "tool")
            payload = cap(
                json.dumps(b.get("input", {}), ensure_ascii=False, indent=2),
                MAX_TOOL_CHARS,
            )
            out.append(
                f"<details><summary>🔧 Tool call: <code>{name}</code></summary>\n\n"
                "```json\n" + redact(payload) + "\n```\n</details>"
            )
        elif bt == "tool_result":
            body = cap(redact(result_to_text(b.get("content", ""))), MAX_TOOL_CHARS)
            out.append(
                "<details><summary>📤 Tool result</summary>\n\n"
                "```text\n" + body + "\n```\n</details>"
            )


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    src, dst = sys.argv[1], sys.argv[2]

    sections: list[str] = []
    n_user = n_assistant = 0
    read_tokens = write_tokens = 0
    with open(src, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                o = json.loads(line)
            except json.JSONDecodeError:
                continue
            # Token accounting (from every message that carries a usage block).
            u = None
            _m = o.get("message")
            if isinstance(_m, dict) and isinstance(_m.get("usage"), dict):
                u = _m["usage"]
            elif isinstance(o.get("usage"), dict):
                u = o["usage"]
            if u:
                read_tokens += (
                    u.get("input_tokens", 0)
                    + u.get("cache_creation_input_tokens", 0)
                    + u.get("cache_read_input_tokens", 0)
                )
                write_tokens += u.get("output_tokens", 0)
            if o.get("type") not in ("user", "assistant", "system"):
                continue
            msg = o.get("message")
            if not isinstance(msg, dict):
                continue
            role = msg.get("role") or o.get("type")
            content = msg.get("content")

            blocks: list[str] = []
            render_blocks(content, blocks)
            if not blocks:
                continue

            is_tool_carrier = isinstance(content, list) and all(
                isinstance(b, dict) and b.get("type") == "tool_result"
                for b in content
            )
            if role == "user" and not is_tool_carrier:
                header = "## 👤 User"
                n_user += 1
            elif role == "user":
                header = "### 📤 (tool results)"
            elif role == "assistant":
                header = "## 🤖 Assistant"
                n_assistant += 1
            else:
                header = "### ⚙️ System"
            ts = o.get("timestamp", "")
            if ts:
                header += f"  <sub>{ts}</sub>"
            sections.append(header + "\n\n" + "\n\n".join(blocks))

    head = (
        "# Chat transcript (redacted)\n\n"
        "> Automatically converted from a Claude Code session, **complete** "
        "(user + assistant messages, chain-of-thought, tool calls and results). "
        "Personal data (e-mail, license key, local user paths) has been "
        "redacted; long tool outputs are truncated. Review before reuse.\n\n"
        f"> Human prompts: {n_user} · Assistant messages: {n_assistant}\n>\n"
        f"> Token usage (this session): **read {read_tokens:,}** "
        f"(input, incl. prompt-cache reads) · **write {write_tokens:,}** "
        "(output). Note: the read total counts the cached context re-read each "
        "turn, so it is far larger than the conversation itself.\n"
        + (f">\n> {SUBAGENT_NOTE}\n" if SUBAGENT_NOTE else "")
        + "\n---\n"
    )
    with open(dst, "w", encoding="utf-8") as out:
        out.write(head + "\n" + "\n\n---\n\n".join(sections) + "\n")

    print(f"Wrote {dst}")
    print(f"  human prompts    : {n_user}")
    print(f"  assistant blocks : {n_assistant}")
    print("  redactions applied:")
    for k, v in _redaction_counts.items():
        print(f"    {k}: {v}")
    if not _redaction_counts:
        print("    (none matched -- fill in the REDACTIONS list / review manually)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
