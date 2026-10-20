# -*- coding: utf-8 -*-
"""打分 —— 把跑完的判据汇总成"哪条做到、哪条没做、哪条没验"。

口径（与核心文档 §5 一致，写死在代码里，不靠自觉）
-------------------------------------------------
1. 每条需求的得分 = 通过判据数 ÷ 判据总数。`skip` 进分母、不进分子 —— **没验不算过**。
2. 总分 = 各需求得分的平均（需求之间等权，避免"判据多的那条"绑架总分）。
3. 状态只有四种：做到 / 部分 / 未做 / （整条未验时归到"未做"）。
4. **阻断项一票否决**：任何 `blocking` 判据红了，结论直接"不通过"，分数照常显示 ——
   既不许把分数抹成 0（那会掩盖别的进展），也不许让分数把它盖过去。
5. 退出码：0 全过 / 1 有未过（含阻断）/ 2 没有未过但有未验。
   未过比未验严重，所以 1 优先 —— 否则一条红会被一条灰盖掉。
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import checks
from .contract import Contract, Criterion, Requirement


@dataclass
class Row:
    req: Requirement
    results: list[tuple[Criterion, checks.Result]] = field(default_factory=list)

    @property
    def passed(self) -> int:
        return sum(1 for _, r in self.results if r.state == checks.PASS)

    @property
    def failed(self) -> int:
        return sum(1 for _, r in self.results if r.state == checks.FAIL)

    @property
    def skipped(self) -> int:
        return sum(1 for _, r in self.results if r.state == checks.SKIP)

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def ratio(self) -> float:
        return self.passed / self.total if self.total else 0.0

    @property
    def status(self) -> str:
        if self.failed == 0 and self.skipped == 0:
            return "做到"
        if self.passed == 0:
            return "未做"
        return "部分"


@dataclass
class Report:
    contract: Contract
    rows: list[Row]
    seconds: float = 0.0

    @property
    def passed(self) -> int:
        return sum(r.passed for r in self.rows)

    @property
    def failed(self) -> int:
        return sum(r.failed for r in self.rows)

    @property
    def skipped(self) -> int:
        return sum(r.skipped for r in self.rows)

    @property
    def total(self) -> int:
        return sum(r.total for r in self.rows)

    @property
    def overall(self) -> float:
        return sum(r.ratio for r in self.rows) / len(self.rows) * 100 if self.rows else 0.0

    @property
    def blocked(self) -> list[tuple[Criterion, checks.Result]]:
        """红掉的阻断项 —— 一票否决的那几张票。"""
        return [(c, r) for row in self.rows for c, r in row.results if c.blocking and r.state == checks.FAIL]

    @property
    def verdict(self) -> str:
        if self.blocked:
            return f"不通过（阻断项 {', '.join(c.id for c, _ in self.blocked)} 未过）"
        if self.failed:
            return f"未通过（{self.failed} 条判据未过）"
        if self.skipped:
            return f"没验完（{self.skipped} 条缺料/没证据 —— 不算过）"
        return "通过"

    @property
    def exit_code(self) -> int:
        if self.failed:
            return 1
        if self.skipped:
            return 2
        return 0


def evaluate(contract: Contract, root: str | Path, only: set[str] | None = None) -> Report:
    root = Path(root).resolve()
    t0 = time.perf_counter()
    rows: list[Row] = []
    for req in contract.requirements:
        if only and req.id.upper() not in only:
            continue
        row = Row(req)
        for c in req.criteria:
            row.results.append((c, checks.execute(c, root)))
        rows.append(row)
    return Report(contract, rows, time.perf_counter() - t0)


def render(report: Report) -> str:
    c = report.contract
    out = [
        f"WorkCovenant 契约打分 · {c.name} {c.version} · {c.profession}",
        f"{len(report.rows)} 条需求 · {report.total} 条判据 · {report.passed} 过 / "
        f"{report.failed} 没过 / {report.skipped} 没验 · {report.seconds:.2f}s",
        "=" * 78,
    ]
    for row in report.rows:
        out.append(f"{row.req.id:<4} {row.req.title}　{row.passed}/{row.total}　{row.status}")
        for crit, res in row.results:
            flag = f"阻断·{crit.id}" if crit.blocking else crit.id
            out.append(f"   {checks.MARKS[res.state]} {flag:<10} {crit.title}")
            out.append(f"              {res.evidence}")
    out.append("=" * 78)
    out.append("按需求：" + "　".join(f"{r.req.id} {r.ratio * 100:3.0f}%" for r in report.rows))
    out.append(f"总分 {report.overall:.0f} / 100")
    out.append(f"结论：{report.verdict}")
    if report.skipped:
        out.append(f"注意：{report.skipped} 条**没验完**，它们不算过（口径见 docs/契约规范.md §3）。")
    return "\n".join(out)


def to_dict(report: Report) -> dict:
    return {
        "contract": {"id": report.contract.id, "name": report.contract.name,
                     "version": report.contract.version, "profession": report.contract.profession,
                     "source": report.contract.source},
        "overall": round(report.overall, 1),
        "verdict": report.verdict,
        "exit_code": report.exit_code,
        "counts": {"passed": report.passed, "failed": report.failed, "skipped": report.skipped,
                   "total": report.total},
        "seconds": round(report.seconds, 3),
        "requirements": [
            {
                "id": row.req.id, "title": row.req.title, "status": row.status,
                "passed": row.passed, "failed": row.failed, "skipped": row.skipped,
                "total": row.total, "score": round(row.ratio * 100, 1),
                "criteria": [
                    {"id": crit.id, "title": crit.title, "blocking": crit.blocking,
                     "state": res.state, "evidence": res.evidence,
                     "seconds": round(res.seconds, 3)}
                    for crit, res in row.results
                ],
            }
            for row in report.rows
        ],
    }


def dumps(report: Report) -> str:
    return json.dumps(to_dict(report), ensure_ascii=False, indent=2)
