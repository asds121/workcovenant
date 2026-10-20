# -*- coding: utf-8 -*-
"""判据执行器 —— 一条判据 = 一个动作，跑完必须能说出"差在哪"。

三档结果，一个都不许含糊
------------------------
| 结果 | 意思 | 什么时候用 |
|---|---|---|
| `pass` | 过了，且证据是一句话能复核的 | 判据成立 |
| `fail` | 没过 —— 证据里写清**差在哪** | 判据不成立（这是下一步要做的事，不是要遮的丑） |
| `skip` | **没验**（缺料 / 没留证据）。不算过，也不许当成过 | `requires` 缺、`manual` 没证据 |

`requires` 与 `path` 的区别是刻意的：
- `requires` 是**前置料**（没有它这条根本不该判）→ `skip`
- `path` 是**交付物**（它就是这条要交的东西）→ `fail`

把两者混成一个，就会得到"文件没交 → 显示未验 → 看起来没毛病"的分数。
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from .contract import Criterion

PASS, FAIL, SKIP = "pass", "fail", "skip"
MARKS = {PASS: "✅", FAIL: "❌", SKIP: "—"}

TIMEOUT = 120


@dataclass
class Result:
    state: str
    evidence: str
    seconds: float = 0.0

    @property
    def ok(self) -> bool:
        return self.state == PASS


def execute(c: Criterion, root: Path) -> Result:
    """跑一条判据。任何异常都变成 `fail`，绝不冒泡成"整个脚本挂了"。"""
    t0 = time.perf_counter()
    try:
        state, evidence = _dispatch(c, root)
    except Exception as exc:                      # noqa: BLE001 —— 判据坏了要算红，不是崩
        state, evidence = FAIL, f"执行判据时出错：{type(exc).__name__}: {exc}"
    return Result(state, evidence, time.perf_counter() - t0)


def _dispatch(c: Criterion, root: Path) -> tuple[str, str]:
    for need in c.requires:
        if not (root / need).exists():
            return SKIP, f"缺料：{need} 不在 —— 这条没验，不算过"
    return {"cmd": _cmd, "file": _file, "links": _links, "manual": _manual}[c.kind](c, root)


# ------------------------------------------------------------------ cmd
def _cmd(c: Criterion, root: Path) -> tuple[str, str]:
    run = c.run.replace("{python}", _quote(sys.executable))
    try:
        proc = subprocess.run(run, shell=True, cwd=str(root), capture_output=True,
                              text=True, encoding="utf-8", errors="replace", timeout=TIMEOUT)
    except subprocess.TimeoutExpired:
        return FAIL, f"命令 {TIMEOUT}s 没跑完：{_short(c.run)}"

    out, err = (proc.stdout or "").strip(), (proc.stderr or "").strip()
    want_exit = int(c.expect.get("exit", 0))
    if proc.returncode != want_exit:
        return FAIL, f"退出码 {proc.returncode}（期望 {want_exit}）· {_tail(out, err)}"
    for needle in _as_list(c.expect.get("stdout_contains")):
        if needle not in out:
            return FAIL, f"输出里没有 {needle!r} · {_tail(out, err)}"
    if pattern := c.expect.get("stdout_regex"):
        if not re.search(pattern, out, re.MULTILINE):
            return FAIL, f"输出不匹配 /{pattern}/ · {_tail(out, err)}"
    for needle in _as_list(c.expect.get("stderr_contains")):
        if needle not in err:
            return FAIL, f"stderr 里没有 {needle!r} · {_tail(out, err)}"
    return PASS, f"退出码 0 · {_tail(out, err)}" if (out or err) else "退出码 0"


# ------------------------------------------------------------------ file
def _file(c: Criterion, root: Path) -> tuple[str, str]:
    p = root / c.path
    if not p.is_file():
        return FAIL, f"{c.path} 不存在 —— 该交的东西没交"
    size = p.stat().st_size
    if c.min_bytes and size < c.min_bytes:
        return FAIL, f"{c.path} 只有 {size} 字节，少于要求的 {c.min_bytes}"
    if c.contains:
        text = p.read_text(encoding="utf-8", errors="replace")
        m = re.search(c.contains, text, re.MULTILINE)
        if not m:
            return FAIL, f"{c.path} 里找不到 /{c.contains}/"
        return PASS, f"{c.path} {_kb(size)} · 命中 {m.group(0).strip()[:60]!r}"
    return PASS, f"{c.path} {_kb(size)}"


# ------------------------------------------------------------------ links
def _links(c: Criterion, root: Path) -> tuple[str, str]:
    """markdown 里的相对链接必须都能解析。链接断了 = 结论指不到出处。"""
    p = root / c.path
    if not p.is_file():
        return FAIL, f"{c.path} 不存在"
    text = p.read_text(encoding="utf-8", errors="replace")
    targets = re.findall(r"\[[^\]]*\]\(([^)]+)\)", text)
    bad, checked = [], 0
    for t in targets:
        t = t.split("#", 1)[0].strip()
        if not t or t.startswith(("http://", "https://", "mailto:", "/")) or "{" in t:
            continue
        checked += 1
        if not (p.parent / t).exists():
            bad.append(t)
    if bad:
        return FAIL, f"{len(bad)}/{checked} 条链接断了：{'、'.join(bad[:5])}"
    return PASS, f"{checked} 条相对链接全部解析得到"


# ------------------------------------------------------------------ manual
def _manual(c: Criterion, root: Path) -> tuple[str, str]:
    """视觉项 / 主观项留证据。证据文件里写 `✅` 或 `❌`，没有就记「没验」。"""
    p = root / c.evidence
    if not p.is_file():
        return SKIP, f"没留证据（{c.evidence}）—— 不算过"
    text = p.read_text(encoding="utf-8", errors="replace")
    if "❌" in text:
        return FAIL, f"证据判红：{c.evidence}"
    if "✅" not in text:
        return SKIP, f"证据里没有 ✅/❌ 结论：{c.evidence}"
    first = next((ln.strip() for ln in text.splitlines() if ln.strip().startswith("✅")), "")
    if not first:
        first = next((ln.strip() for ln in text.splitlines() if "✅" in ln), "")
    return PASS, f"证据：{first[:80]}"


# ------------------------------------------------------------------ 小工具
def _quote(s: str) -> str:
    return f'"{s}"' if os.sep in s or " " in s else s


def _as_list(v) -> list[str]:
    if v is None:
        return []
    return [v] if isinstance(v, str) else list(v)


def _tail(out: str, err: str) -> str:
    s = " / ".join(x for x in (out, err) if x)
    s = " ".join(s.split())
    return (s[:160] + "…") if len(s) > 160 else (s or "（无输出）")


def _short(s: str) -> str:
    return (s[:60] + "…") if len(s) > 60 else s


def _kb(n: int) -> str:
    return f"{n / 1024:.1f} KB" if n >= 1024 else f"{n} B"
