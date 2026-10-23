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

import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote

from .contract import Criterion

PASS, FAIL, SKIP = "pass", "fail", "skip"
MARKS = {PASS: "✅", FAIL: "❌", SKIP: "—"}


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
    return {"cmd": _cmd, "file": _file, "links": _links, "manual": _manual,
            "data": _data}[c.kind](c, root)


# ------------------------------------------------------------------ cmd
def _cmd(c: Criterion, root: Path) -> tuple[str, str]:
    run = c.run.replace("{python}", _quote(sys.executable))
    try:
        proc = subprocess.run(run, shell=True, cwd=str(root), capture_output=True,
                              timeout=c.timeout)
    except subprocess.TimeoutExpired:
        return FAIL, f"命令 {c.timeout}s 没跑完：{_short(c.run)}"

    out = _decode(proc.stdout or b"").strip()
    err = _decode(proc.stderr or b"").strip()
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
        text = _norm(_decode(p.read_bytes()))
        m = re.search(c.contains, text, re.MULTILINE)
        if not m:
            return FAIL, f"{c.path} 里找不到 /{c.contains}/"
        return PASS, f"{c.path} {_kb(size)} · 命中 {m.group(0).strip()[:60]!r}"
    return PASS, f"{c.path} {_kb(size)}"


# ------------------------------------------------------------------ links
_FENCE = re.compile(r"^[ \t]*(?:```|~~~).*?^[ \t]*(?:```|~~~)", re.S | re.M)
_INLINE_CODE = re.compile(r"`[^`\n]*`")
_LINK = re.compile(r"!?\[[^\]]*\]\(\s*(<[^>\n]*>|[^)\s]+)(?:\s+(?:\"[^\"]*\"|'[^']*'))?\s*\)")
_REF_DEF = re.compile(r"^\[[^\]]+\]:\s*(\S+)", re.M)
_SKIP_PREFIX = ("#", "http://", "https://", "mailto:", "tel:", "data:", "/", "?")


def _links(c: Criterion, root: Path) -> tuple[str, str]:
    """markdown 里的相对链接必须都能解析。链接断了 = 结论指不到出处。

    四种形态都要认，否则"检查通过"只是没看见：
    带标题 `[a](b.md "t")`、尖括号 `<my file.md>`、URL 编码 `%20`、引用式 `[a]: b.md`。
    代码块与行内代码里的示例链接要跳过 —— 否则文档里教一次写法，检查就红一次。
    """
    p = root / c.path
    if not p.is_file():
        return FAIL, f"{c.path} 不存在"
    text = _norm(_decode(p.read_bytes()))
    text = _FENCE.sub("", text)
    text = _INLINE_CODE.sub("", text)
    targets = [m.group(1) for m in _LINK.finditer(text)] + _REF_DEF.findall(text)

    bad, checked = [], 0
    for t in targets:
        t = t.strip().strip("<>").strip()
        if not t or t.startswith(_SKIP_PREFIX) or "{" in t or "}" in t:
            continue
        t = unquote(t.split("#", 1)[0]).strip()
        if not t:
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
    text = _norm(_decode(p.read_bytes()))
    if "❌" in text:
        return FAIL, f"证据判红：{c.evidence}"
    if "✅" not in text:
        return SKIP, f"证据里没有 ✅/❌ 结论：{c.evidence}"
    first = next((ln.strip() for ln in text.splitlines() if ln.strip().startswith("✅")), "")
    if not first:
        first = next((ln.strip() for ln in text.splitlines() if "✅" in ln), "")
    return PASS, f"证据：{first[:80]}"


# ------------------------------------------------------------------ data
def _data(c: Criterion, root: Path) -> tuple[str, str]:
    """一批记录 × 一组子句。规则写在契约里，不藏在脚本里。

    为什么不复用 `cmd`：`cmd` 也能读 JSON，但规则会躲进那一行 Python 里 ——
    契约上只剩一句"跑个脚本"，读的人看不出到底在验什么。`data` 保证
    **看契约就知道判什么**，所以子句只有四种形状，多一个都不认。
    """
    p = root / c.path
    if not p.is_file():
        return FAIL, f"{c.path} 不存在 —— 该交的数据没交"
    try:
        raw = json.loads(_decode(p.read_bytes()))
    except json.JSONDecodeError as exc:
        return FAIL, f"{c.path} 不是合法 JSON：第 {exc.lineno} 行第 {exc.colno} 列"
    records = raw.get("items") if isinstance(raw, dict) else raw
    if not isinstance(records, list):
        return FAIL, f'{c.path} 里没有记录数组（要 list，或 {{"items": [...]}}）'

    bad: list[str] = []
    for i, rec in enumerate(records, 1):
        if not isinstance(rec, dict):
            bad.append(f"第 {i} 条不是对象")
            continue
        for clause in c.asserts:
            if not _when_ok(rec, clause.get("when")):
                continue
            msg = _clause_bad(rec, clause)
            if msg:
                bad.append(f"{_rid(rec, i)} {msg}")
    if bad:
        more = f"（另有 {len(bad) - 3} 处）" if len(bad) > 3 else ""
        return FAIL, f"{len(bad)} 处不合格：{'；'.join(bad[:3])}{more}"
    return PASS, f"{len(records)} 条记录 · {len(c.asserts)} 个子句全部成立"


def _clause_bad(rec: dict, clause: dict) -> str:
    """返回一处不合格的说明（空串 = 这条记录在这个子句下合格）。"""
    if "required" in clause:
        miss = [f for f in clause["required"] if not _filled(rec.get(f))]
        return f"缺 {', '.join(miss)}" if miss else ""
    if "forbidden" in clause:
        spec = clause["forbidden"]
        for f in spec["fields"]:
            text = rec.get(f)
            if not isinstance(text, str):
                continue
            for term in spec["terms"]:
                if term in text:
                    return f"{f} 里有禁词「{term}」"
        return ""
    if "compare" in clause:
        spec = clause["compare"]
        for a, b in spec["pairs"]:
            va, vb = rec.get(a), rec.get(b)
            if not _filled(va) or not _filled(vb):
                return f"{a}/{b} 有一个为空，无法比对"
            if spec["expect"] == "ne" and _same(va, vb):
                return f"{a} 与 {b} 相同（{va}），这里必须不同"
            if spec["expect"] == "eq" and not _same(va, vb):
                return f"{a}={va} 与 {b}={vb} 不一致，这里必须相等"
        return ""
    spec = clause["sla"]
    start, end = rec.get(spec["start"]), rec.get(spec["end"])
    if not _filled(start) or not _filled(end):
        return f"缺 {spec['start']}/{spec['end']}，无法证明未超时"
    try:
        t0, t1 = datetime.fromisoformat(str(start)), datetime.fromisoformat(str(end))
        hours = (t1 - t0).total_seconds() / 3600
    except (ValueError, TypeError):
        return "时间字段不是 ISO 8601，算不出间隔"
    if hours < 0:
        return f"{spec['end']} 早于 {spec['start']}，记录本身是坏的"
    if hours > spec["max_hours"]:
        return f"{hours:.1f}h > {spec['max_hours']}h"
    return ""


def _when_ok(rec: dict, when: dict | None) -> bool:
    if not when:
        return True
    v = rec.get(when["field"])
    if "nonempty" in when:
        return _filled(v)
    return any(_same(v, want) for want in when["in"])


def _rid(rec: dict, i: int) -> str:
    rid = rec.get("id")
    return rid if isinstance(rid, str) and rid.strip() else f"第 {i} 条"


def _filled(v) -> bool:
    """`0` / `false` 是值，不是空 —— 只有 None、空串、空容器才算缺。"""
    if v is None:
        return False
    if isinstance(v, str):
        return bool(v.strip())
    if isinstance(v, (list, dict)):
        return bool(v)
    return True


def _same(a, b) -> bool:
    """`1` 和 `True` 在 Python 里相等，但在数据里是两个意思。"""
    if isinstance(a, bool) != isinstance(b, bool):
        return False
    return a == b


# ------------------------------------------------------------------ 小工具
def _decode(blob: bytes) -> str:
    """先按 UTF-8，再按 GB18030（GBK 的超集）—— 中文 Windows 的控制台输出常是 GBK。

    先 UTF-8 是安全的：GBK 尾部字节很少能凑成合法 UTF-8，反过来却经常成立。
    两种都不行才 replace，绝不让一个判据因为编码而崩掉。
    """
    for enc in ("utf-8", "gb18030"):
        try:
            return blob.decode(enc)
        except UnicodeDecodeError:
            continue
    return blob.decode("utf-8", "replace")


def _norm(text: str) -> str:
    """正则匹配前统一换行。

    仓库在 Windows 上检出可能是 CRLF；不归一的话 `$` 锚点会匹配到 `\\r` 前面那一位，
    一条完全正确的判据会在别人的机器上红。
    """
    return text.replace("\r\n", "\n").replace("\r", "\n")


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
