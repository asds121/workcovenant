# -*- coding: utf-8 -*-
"""契约的加载与校验 —— schema v1.0。

先立一条口径：**契约文件坏掉的时候，必须比它没写更吵。**
一份字段缺一半的契约如果被静默放过，它产出的分数比没有分数更糟 ——
那正是核心文档里说的「默认低标准」，只是换成了 YAML 的样子。

所以这里的校验是**全量**的：一次把所有问题列出来，不做"检查到第一个错就返回"。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

FORMAT = "workcovenant.contract/1"

# 判据只有四种可执行的形态。加新形态要同时加执行器（wvc/checks.py）和本文档。
KINDS = ("cmd", "file", "links", "manual")
# `cmd` 的 expect 只认这几个键；写错的键必须报错，不许当没看见。
EXPECT_KEYS = ("exit", "stdout_contains", "stdout_regex", "stderr_contains")
WEIGHTS = (1, 2, 3)


class ContractError(Exception):
    """契约读不进来（文件不在 / 不是 JSON）。"""


@dataclass(frozen=True)
class Criterion:
    id: str
    title: str
    why: str
    kind: str
    blocking: bool = False
    weight: int = 1
    requires: tuple[str, ...] = ()
    run: str = ""
    expect: Mapping[str, Any] = field(default_factory=dict)
    path: str = ""
    contains: str = ""
    min_bytes: int = 0
    evidence: str = ""


@dataclass(frozen=True)
class Requirement:
    id: str
    title: str
    verbatim: str
    loop: tuple[str, ...]
    criteria: tuple[Criterion, ...]


@dataclass(frozen=True)
class Contract:
    id: str
    name: str
    profession: str
    version: str
    owner: str
    note: str
    requirements: tuple[Requirement, ...]
    source: str = ""

    @property
    def criteria(self) -> list[Criterion]:
        return [c for r in self.requirements for c in r.criteria]

    @property
    def blocking(self) -> list[str]:
        return [c.id for c in self.criteria if c.blocking]


def load(path: str | Path) -> Contract:
    """读进来 + 校验。校验不过抛 `ContractError`，消息里带文件与字段位置。"""
    p = Path(path)
    if not p.is_file():
        raise ContractError(f"契约文件不存在：{p}")
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ContractError(f"{p} 不是合法 JSON：第 {exc.lineno} 行第 {exc.colno} 列 {exc.msg}") from exc
    if not isinstance(raw, dict):
        raise ContractError(f"{p} 的顶层必须是对象，实际是 {type(raw).__name__}")

    errors = validate(raw)
    if errors:
        head = f"{p} 有 {len(errors)} 处不合 schema {FORMAT}："
        raise ContractError("\n".join([head, *[f"  · {e}" for e in errors]]))
    return _build(raw, str(p))


def validate(raw: Mapping[str, Any]) -> list[str]:
    """全量校验，返回全部错误（空列表 = 合格）。"""
    errs: list[str] = []

    def need(obj: Mapping[str, Any], key: str, where: str, kind: type | tuple = str) -> None:
        v = obj.get(key)
        if v is None or (isinstance(v, str) and not v.strip()):
            errs.append(f"{where} 缺 `{key}`")
        elif not isinstance(v, kind):
            errs.append(f"{where} 的 `{key}` 类型应为 {kind}，实际是 {type(v).__name__}")

    if raw.get("format") != FORMAT:
        errs.append(f"`format` 必须是 `{FORMAT}`，实际是 {raw.get('format')!r}")
    for k in ("id", "name", "profession", "version", "owner"):
        need(raw, k, "顶层")
    if isinstance(raw.get("version"), str) and not re.fullmatch(r"\d+\.\d+\.\d+", raw["version"]):
        errs.append(f"`version` 要写成 x.y.z，实际是 {raw['version']!r}")

    reqs = raw.get("requirements")
    if not isinstance(reqs, list) or not reqs:
        errs.append("`requirements` 必须是非空数组")
        return errs

    seen_req: set[str] = set()
    seen_cri: dict[str, str] = {}
    for i, req in enumerate(reqs):
        where = f"requirements[{i}]"
        if not isinstance(req, dict):
            errs.append(f"{where} 必须是对象")
            continue
        rid = req.get("id")
        if not isinstance(rid, str) or not rid.strip():
            errs.append(f"{where} 缺 `id`")
            rid = f"#{i}"
        else:
            where = f"需求 {rid}"
            if rid in seen_req:
                errs.append(f"{where} 的 id 重复")
            seen_req.add(rid)
        for k in ("title", "verbatim"):
            need(req, k, where)
        loop = req.get("loop")
        if not isinstance(loop, list) or not loop or not all(isinstance(s, str) and s.strip() for s in loop):
            errs.append(f"{where} 的 `loop`（最小闭环）必须是非空字符串数组 —— 没有闭环就没有验收")

        cris = req.get("criteria")
        if not isinstance(cris, list) or not cris:
            errs.append(f"{where} 缺 `criteria`（至少一条判据）")
            continue
        for j, c in enumerate(cris):
            cwhere = f"{where} 的 criteria[{j}]"
            if not isinstance(c, dict):
                errs.append(f"{cwhere} 必须是对象")
                continue
            cid = c.get("id")
            if not isinstance(cid, str) or not cid.strip():
                errs.append(f"{cwhere} 缺 `id`")
                cid = f"#{j}"
            else:
                cwhere = f"判据 {cid}"
                if cid in seen_cri:
                    errs.append(f"{cwhere} 的 id 重复（已出现在 {seen_cri[cid]}）")
                seen_cri[cid] = where
            for k in ("title", "why"):
                need(c, k, cwhere)

            kind = c.get("kind")
            if kind not in KINDS:
                errs.append(f"{cwhere} 的 `kind` 必须是 {'/'.join(KINDS)} 之一，实际是 {kind!r}")
                continue
            if kind == "cmd":
                need(c, "run", cwhere)
                exp = c.get("expect", {})
                if not isinstance(exp, dict):
                    errs.append(f"{cwhere} 的 `expect` 必须是对象")
                else:
                    for k in exp:
                        if k not in EXPECT_KEYS:
                            errs.append(f"{cwhere} 的 `expect.{k}` 不认识（只认 {'/'.join(EXPECT_KEYS)}）")
                    if "exit" in exp and not isinstance(exp["exit"], int):
                        errs.append(f"{cwhere} 的 `expect.exit` 必须是整数")
            if kind in ("file", "links"):
                need(c, "path", cwhere)
            if kind == "manual":
                need(c, "evidence", cwhere)

            blocking = c.get("blocking", False)
            if not isinstance(blocking, bool):
                errs.append(f"{cwhere} 的 `blocking` 必须是 true/false")
            elif blocking and kind == "manual":
                errs.append(f"{cwhere} 是阻断项，但 kind=manual —— 阻断项必须机器可判，"
                            "靠人留证据的不能一票否决")
            w = c.get("weight", 1)
            if not isinstance(w, int) or w not in WEIGHTS:
                errs.append(f"{cwhere} 的 `weight` 必须是 {WEIGHTS} 之一，实际是 {w!r}")
            mb = c.get("min_bytes", 0)
            if not isinstance(mb, int) or mb < 0:
                errs.append(f"{cwhere} 的 `min_bytes` 必须是非负整数，实际是 {mb!r}")
    return errs


def _as_tuple(v) -> tuple[str, ...]:
    """`requires` 允许写成字符串或数组；缺省 = 空元组。

    注意这里**不许**写成 `tuple(c.get("requires", ()))` —— 缺省时那是 `(None,)`，
    一进执行器就 `Path / None` 崩掉，五条判据全红（2026-10-20 实际踩过）。
    """
    if v is None:
        return ()
    if isinstance(v, str):
        return (v,) if v.strip() else ()
    return tuple(str(x) for x in v if str(x).strip())


def _build(raw: Mapping[str, Any], source: str) -> Contract:
    reqs = []
    for r in raw["requirements"]:
        cris = tuple(
            Criterion(
                id=c["id"], title=c["title"], why=c["why"], kind=c["kind"],
                blocking=bool(c.get("blocking", False)), weight=int(c.get("weight", 1)),
                requires=_as_tuple(c.get("requires")),
                run=c.get("run", ""), expect=dict(c.get("expect", {})),
                path=c.get("path", ""), contains=c.get("contains", ""),
                min_bytes=int(c.get("min_bytes", 0)), evidence=c.get("evidence", ""),
            )
            for c in r["criteria"]
        )
        reqs.append(Requirement(id=r["id"], title=r["title"], verbatim=r["verbatim"],
                                loop=tuple(r["loop"]), criteria=cris))
    return Contract(
        id=raw["id"], name=raw["name"], profession=raw["profession"],
        version=raw["version"], owner=raw["owner"], note=raw.get("note", ""),
        requirements=tuple(reqs), source=source,
    )
