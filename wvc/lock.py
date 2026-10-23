# -*- coding: utf-8 -*-
"""锁 —— 判据不许被悄悄放松。

问题不是"有人会恶意改判据"，而是**没人会注意到**：把 `blocking: true` 改成
`false`、把 `max_hours: 24` 改成 `72`、把一条判据删掉，契约照样加载、照样跑分，
只是门槛矮了一截。分数不会变红，它只会变得更好看。

锁只做一件事：**给每份契约留一份基线**（判据 id + 是否阻断 + 判定内容的指纹）。
下次改动与基线一比，"放松"就必须出现在 diff 里，并且必须升版本。

它做不到什么（写在这里，免得被当成银弹）
------------------------------------------
- 它不是防篡改。重新生成锁只要一条命令，谁都能做 —— 但那会留下一个可见的 diff。
  锁把"悄悄放松"变成"必须当众放松"，不是变成"不可能放松"。
- 它不判方向。`min_bytes: 400 → 800` 是收紧，`24h → 72h` 是放松，指纹一样是"变了"，
  所以规则统一成：**判定内容变了就得升版本**（与 `docs/契约规范.md` §2 一致）。
- `why` / `title` 不进指纹。说明文字改了不改判定，不该逼人升版本。
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from .contract import Contract, Criterion

FORMAT = "workcovenant.lock/1"


def fingerprint(c: Criterion) -> str:
    """判定内容的指纹。只装"会改变结果"的东西。"""
    payload = {
        "kind": c.kind,
        "blocking": c.blocking,
        "requires": list(c.requires),
        "run": c.run,
        "expect": dict(c.expect),
        "path": c.path,
        "contains": c.contains,
        "min_bytes": c.min_bytes,
        "evidence": c.evidence,
        "assert": [dict(a) for a in c.asserts],
    }
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return "sha256:" + hashlib.sha256(blob).hexdigest()[:16]


def make(contract: Contract) -> dict:
    return {
        "format": FORMAT,
        "contract": contract.id,
        "version": contract.version,
        "criteria": {c.id: {"blocking": c.blocking, "fp": fingerprint(c)}
                     for c in contract.criteria},
    }


def dumps(lock: Mapping[str, Any]) -> str:
    return json.dumps(lock, ensure_ascii=False, indent=2) + "\n"


def read(path: str | Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def verify(contract: Contract, lock: Mapping[str, Any],
           changelog: str = "") -> tuple[list[str], list[str]]:
    """返回 (errors, notes)。errors 非空 = 红。

    `changelog` 传 `CHANGELOG.md` 全文：升版本之后，"放松"还要留下理由。
    这条检查很弱（只认判据 id 有没有被提到），但它把"放宽可以，要写理由"
    从一句 checklist 变成了会红的门。
    """
    errs: list[str] = []
    notes: list[str] = []
    if lock.get("format") != FORMAT:
        errs.append(f"锁的 format 应是 {FORMAT}，实际是 {lock.get('format')!r}")
    if lock.get("contract") != contract.id:
        errs.append(f"这把锁属于 {lock.get('contract')!r}，不是 {contract.id!r}")
    old = lock.get("criteria")
    if not isinstance(old, dict) or not old:
        errs.append("锁里一条判据都没有 —— 空锁等于没锁")
        return errs, notes

    new = {c.id: c for c in contract.criteria}
    changed: list[tuple[str, str]] = []
    for cid, entry in old.items():
        c = new.get(cid)
        if c is None:
            changed.append((cid, "删除"))
        elif bool(entry.get("blocking")) and not c.blocking:
            changed.append((cid, "降级"))
        elif fingerprint(c) != entry.get("fp"):
            changed.append((cid, "改动"))
    added = [cid for cid in new if cid not in old]

    diff = [f"{how} {cid}" for cid, how in changed] + [f"新增 {cid}" for cid in added]
    same_version = lock.get("version") == contract.version
    if diff and same_version:
        errs.append(f"契约内容变了，但 version 还是 {lock.get('version')}："
                    f"{'、'.join(diff)} —— 改了判定就必须升版本，"
                    "否则没人知道验的还是不是原来那条")
        return errs, notes

    for cid, how in changed:
        if cid not in changelog:
            errs.append(f"{how}了判据 {cid}（version 已升到 {contract.version}），"
                        "但 CHANGELOG.md 里没提它 —— 放宽可以，必须留下理由")
        else:
            notes.append(f"{how} {cid}（CHANGELOG 已记录）")
    if added:
        notes.append(f"新增 {', '.join(added)}")
    if not same_version:
        notes.append(f"版本 {lock.get('version')} → {contract.version}")
    return errs, notes
