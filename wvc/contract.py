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
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

FORMAT = "workcovenant.contract/1"

# 判据只有五种可执行的形态。加新形态要同时加执行器（wvc/checks.py）和本文档。
KINDS = ("cmd", "file", "links", "manual", "data")
# `cmd` 的 expect 只认这几个键；写错的键必须报错，不许当没看见。
EXPECT_KEYS = ("exit", "stdout_contains", "stdout_regex", "stderr_contains")
WEIGHTS = (1, 2, 3)
DEFAULT_TIMEOUT = 120
MAX_TIMEOUT = 600

# 字段白名单：不在这里的键一律拒绝。
# 为什么连"多写一个字段"都要拒绝：`blockng: true` 会被旧校验静默忽略，
# 那条判据照常加载、照常显示，只是**再也不阻断**。一个没人看得见的降级，
# 比明着写错危险得多 —— 所以宁可在加载时吵一次。
TOP_KEYS = frozenset({"format", "id", "name", "profession", "version", "owner",
                      "note", "requirements"})
REQ_KEYS = frozenset({"id", "title", "verbatim", "loop", "criteria"})
UNIVERSAL_KEYS = frozenset({"id", "title", "why", "kind", "blocking", "weight", "requires"})
KIND_KEYS = {
    "cmd": frozenset({"run", "expect", "timeout"}),
    "file": frozenset({"path", "contains", "min_bytes"}),
    "links": frozenset({"path"}),
    "manual": frozenset({"evidence"}),
    "data": frozenset({"path", "assert"}),
}
ALL_KEYS = UNIVERSAL_KEYS.union(*KIND_KEYS.values())
DATA_CLAUSES = ("required", "forbidden", "compare", "sla")


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
    timeout: int = DEFAULT_TIMEOUT
    asserts: tuple[Mapping[str, Any], ...] = ()


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
    for k in raw:
        if k not in TOP_KEYS:
            errs.append(f"顶层有不认识的字段 `{k}` —— 写错的键会被静默忽略，所以这里直接拒绝")
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
        for k in req:
            if k not in REQ_KEYS:
                errs.append(f"{where} 有不认识的字段 `{k}` —— 写错的键会被静默忽略")
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
            errs.extend(_field_errors(c, kind, cwhere))
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
            if kind in ("file", "links", "data"):
                need(c, "path", cwhere)
            if kind == "manual":
                need(c, "evidence", cwhere)
            if kind == "data":
                errs.extend(_assert_errors(c.get("assert"), cwhere))

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

            to = c.get("timeout", DEFAULT_TIMEOUT)
            if isinstance(to, bool) or not isinstance(to, int) or not 1 <= to <= MAX_TIMEOUT:
                errs.append(f"{cwhere} 的 `timeout` 必须是 1..{MAX_TIMEOUT} 的整数，实际是 {to!r}")

            # 判据只许读仓库内的相对路径。放它读 `..` 或绝对路径，等于让一份契约
            # 顺手把仓库外面的东西（客户文件、密钥）读进报告。
            for field in ("path", "evidence"):
                reason = _escape_reason(c.get(field))
                if reason:
                    errs.append(f"{cwhere} 的 `{field}` {reason}")
            needs = c.get("requires")
            needs = [] if needs is None else ([needs] if isinstance(needs, str) else needs)
            if isinstance(needs, list):
                for n in needs:
                    reason = _escape_reason(n)
                    if reason:
                        errs.append(f"{cwhere} 的 `requires` 里的 {n!r} {reason}")
    return errs


def _field_errors(c: Mapping[str, Any], kind: str, where: str) -> list[str]:
    """字段白名单 + 字段归属：不认识的键、放错判据类型的键，一律拒绝。

    这两条是同一件事的两面 —— `blockng` 会被静默忽略，`run` 写在 `file` 判据上
    同样会被静默忽略。只要"写了但没生效"是可能的，报告就会替一个没跑过的判据说话。
    """
    errs: list[str] = []
    allowed = UNIVERSAL_KEYS | KIND_KEYS[kind]
    for k in c:
        if k not in ALL_KEYS:
            errs.append(f"{where} 有不认识的字段 `{k}` —— 写错的键会被静默忽略，"
                        "例如把 blocking 写成 blockng，那条判据就再也不阻断")
        elif k not in allowed:
            owner = next((x for x, ks in KIND_KEYS.items() if k in ks), "?")
            errs.append(f"{where} 的 `{k}` 只用于 {owner} 判据，这里 kind={kind}")
    return errs


def _assert_errors(blk: Any, where: str) -> list[str]:
    """`data` 判据的子句校验。子句是白名单的：四个形状，多一个都不认。"""
    if not isinstance(blk, list) or not blk:
        return [f"{where} 的 `assert` 必须是非空数组 —— 没有子句就等于没判"]
    errs: list[str] = []
    for i, a in enumerate(blk):
        w = f"{where} 的 assert[{i}]"
        if not isinstance(a, dict):
            errs.append(f"{w} 必须是对象")
            continue
        for k in a:
            if k not in DATA_CLAUSES and k != "when":
                errs.append(f"{w} 有不认识的键 `{k}`（子句只认 {'/'.join(DATA_CLAUSES)} + when）")
        clauses = [k for k in a if k in DATA_CLAUSES]
        if len(clauses) != 1:
            errs.append(f"{w} 必须恰好有一个子句（{'/'.join(DATA_CLAUSES)}），实际 {len(clauses)} 个")
            continue
        if "when" in a:
            errs.extend(_when_errors(a["when"], w))
        name, spec = clauses[0], a[clauses[0]]
        if name == "required":
            errs.extend(_str_list_errors(spec, f"{w}.required"))
        elif name == "forbidden":
            if not isinstance(spec, dict) or set(spec) != {"fields", "terms"}:
                errs.append(f"{w}.forbidden 必须是 {{fields, terms}} 两个键")
                continue
            errs.extend(_str_list_errors(spec["fields"], f"{w}.forbidden.fields"))
            errs.extend(_str_list_errors(spec["terms"], f"{w}.forbidden.terms"))
        elif name == "compare":
            errs.extend(_compare_errors(spec, w))
        elif name == "sla":
            errs.extend(_sla_errors(spec, w))
    return errs


def _str_list_errors(v: Any, where: str) -> list[str]:
    if not isinstance(v, list) or not v or not all(isinstance(x, str) and x.strip() for x in v):
        return [f"{where} 必须是非空字符串数组"]
    return []


def _when_errors(when: Any, where: str) -> list[str]:
    if not isinstance(when, dict):
        return [f"{where} 的 `when` 必须是对象"]
    errs: list[str] = []
    for k in when:
        if k not in ("field", "in", "nonempty"):
            errs.append(f"{where}.when 有不认识的键 `{k}`")
    if not isinstance(when.get("field"), str) or not when["field"].strip():
        errs.append(f"{where}.when 缺 `field`")
    if ("in" in when) == ("nonempty" in when):
        errs.append(f"{where}.when 的 `in` 与 `nonempty` 必须二选一")
    if "in" in when:
        vals = when["in"]
        if not isinstance(vals, list) or not vals:
            errs.append(f"{where}.when.in 必须是非空数组")
        elif any(isinstance(x, (list, dict)) or x is None for x in vals):
            errs.append(f"{where}.when.in 只接受字符串/数字/布尔，实际有 {vals!r}")
    if "nonempty" in when and when["nonempty"] is not True:
        errs.append(f"{where}.when.nonempty 只接受 true")
    return errs


def _compare_errors(spec: Any, where: str) -> list[str]:
    if not isinstance(spec, dict) or set(spec) != {"pairs", "expect"}:
        return [f"{where}.compare 必须是 {{pairs, expect}} 两个键"]
    errs: list[str] = []
    pairs = spec["pairs"]
    if not isinstance(pairs, list) or not pairs:
        errs.append(f"{where}.compare.pairs 必须是非空数组")
    else:
        for p in pairs:
            if (not isinstance(p, list) or len(p) != 2
                    or not all(isinstance(x, str) and x.strip() for x in p)):
                errs.append(f"{where}.compare.pairs 的每一项必须是两个字段名，实际 {p!r}")
            elif p[0] == p[1]:
                errs.append(f"{where}.compare.pairs 里 {p[0]!r} 和自己比 —— 永远相等，判不出东西")
    if spec["expect"] not in ("eq", "ne"):
        errs.append(f"{where}.compare.expect 只能是 eq / ne，实际 {spec['expect']!r}")
    return errs


def _sla_errors(spec: Any, where: str) -> list[str]:
    if not isinstance(spec, dict) or set(spec) != {"start", "end", "max_hours"}:
        return [f"{where}.sla 必须是 {{start, end, max_hours}} 三个键"]
    errs: list[str] = []
    for k in ("start", "end"):
        if not isinstance(spec[k], str) or not spec[k].strip():
            errs.append(f"{where}.sla.{k} 必须是字段名")
    mh = spec["max_hours"]
    if isinstance(mh, bool) or not isinstance(mh, (int, float)) or mh <= 0:
        errs.append(f"{where}.sla.max_hours 必须是正数，实际 {mh!r}")
    return errs


def _escape_reason(p: Any) -> str:
    """返回不合规的理由（空串 = 合规）。"""
    if not isinstance(p, str) or not p.strip():
        return ""
    norm = p.replace("\\", "/")
    if norm.startswith("/") or re.match(r"^[A-Za-z]:", norm):
        return "是绝对路径 —— 判据只许读仓库内的相对路径"
    if ".." in PurePosixPath(norm).parts:
        return "含 `..` —— 判据只许读仓库内的相对路径"
    return ""


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
                timeout=int(c.get("timeout", DEFAULT_TIMEOUT)),
                asserts=tuple(c.get("assert", ())),
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
