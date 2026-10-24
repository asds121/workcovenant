# -*- coding: utf-8 -*-
"""基准集的公共骨架 —— 用例怎么描述、怎么跑、怎么判"符合预期"。

拆出来只为一条：单个 `.py` 不许超过 20KB（仓库治理 G1-d）。
用例按判据类型分册：`benchmark_cases.py`（cmd/file/links/manual/contract/score）
与 `benchmark_data.py`（data）。**不是**为了多层抽象 —— 这里没有抽象。
"""
from __future__ import annotations

import json
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from wvc import contract as C      # noqa: E402
from wvc import score as S         # noqa: E402


@dataclass(frozen=True)
class Case:
    id: str
    group: str
    title: str
    why: str
    build: Callable[[Path], dict]
    states: dict[str, str] = field(default_factory=dict)   # 判据 id → 期望状态
    exit_code: int | None = None
    verdict: str = ""
    error: str = ""                                        # 期望 ContractError 片段
    contract: str = ""                                     # 跑的是哪份真契约（合成用例留空）


@dataclass
class Outcome:
    case: Case
    report: S.Report | None = None
    error: str = ""

    @property
    def ok(self) -> bool:
        return not self.detail

    @property
    def detail(self) -> str:
        """空串 = 符合预期；否则是"差在哪"。"""
        c = self.case
        if c.error:
            if not self.error:
                return f"{c.id} 期望契约被拒绝，实际加载成功"
            if c.error not in self.error:
                return f"{c.id} 报错里没有 {c.error!r}：{self.error}"
            return ""
        if self.error:
            return f"{c.id} 契约没加载成功：{self.error}"
        rep = self.report
        assert rep is not None
        for cid, want in c.states.items():
            got = state(rep, cid)
            if got != want:
                return f"{c.id} {cid} 期望 {want}，实际 {got}｜{evidence(rep, cid)}"
        if c.exit_code is not None and rep.exit_code != c.exit_code:
            return f"{c.id} 退出码期望 {c.exit_code}，实际 {rep.exit_code}"
        if c.verdict and c.verdict not in rep.verdict:
            return f"{c.id} 结论期望含 {c.verdict!r}，实际 {rep.verdict!r}"
        return ""


def state(rep: S.Report, cid: str) -> str:
    for row in rep.rows:
        for crit, res in row.results:
            if crit.id == cid:
                return res.state
    return "缺失"


def evidence(rep: S.Report, cid: str) -> str:
    for row in rep.rows:
        for crit, res in row.results:
            if crit.id == cid:
                return res.evidence
    return ""


def criterion(cid: str, kind: str, title: str = "", **kw) -> dict:
    d = {"id": cid, "title": title or cid, "kind": kind,
         "why": "基准集：这一类错了必须被认出来"}
    d.update(kw)
    return d


def doc(*crits: dict) -> dict:
    return {
        "format": C.FORMAT, "id": "bench", "name": "基准集用例", "profession": "基准",
        "version": "1.0.0", "owner": "benchmark",
        "requirements": [{"id": "R1", "title": "基准", "verbatim": "基准集用例",
                          "loop": ["跑一次"], "criteria": list(crits)}],
    }


def write(root: Path, name: str, data: str | bytes) -> None:
    p = root / name
    p.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, bytes):
        p.write_bytes(data)
    else:
        p.write_text(data, encoding="utf-8")


def run_case(case: Case) -> Outcome:
    with tempfile.TemporaryDirectory(prefix="wvc_bench_") as d:
        root = Path(d)
        raw = case.build(root)
        p = root / "_contract.json"
        p.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
        try:
            contract = C.load(p)
        except C.ContractError as exc:
            return Outcome(case, error=str(exc))
        return Outcome(case, report=S.evaluate(contract, root))
