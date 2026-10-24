# -*- coding: utf-8 -*-
"""判据的行为覆盖 —— 按"有没有被弄红过"分类，不按"文档里有没有提过"。

为什么不用"字符串提及"：`R3-d` 在 README 里被提过很多次，但它的行为固定来自
它自己的 `run`（跑基准集）；而有些判据文档里一句没提，却真有坏样本把它弄红过。
两个轴混在一起，报告会同时漏报和误报。

四类（只看阻断项 —— 不阻断的判据红不红，不否决任何东西）：

- `坏样本`：`tests/benchmark_data.py` 里有真契约 × 坏样本的期望，它被真的弄红过。
- `自身即反证`：`run` 本身就是"把东西弄坏，看红不红"（unittest / benchmark / mutation）。
- `仅正向`：有 `run`，能红，但没人证明过它会红。
- `人工`：`manual` 判据。阻断项不许用它，出现即说明契约写错了。

这个工具**不是门**：它只出报告，永远退出码 0（除非契约读不进来）。
把它变成门，就会逼人去给"README 在"这种判据配一个"把 README 删了"的用例 ——
那测的是 README，不是引擎。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from wvc import contract as C           # noqa: E402
from tests.benchmark_cases import CASES  # noqa: E402

ADVERSARY = re.compile(r"unittest|benchmark\.py|mutation_check")
BAD = "fail"

LABELS = {
    "坏样本": "被坏样本弄红过 —— 它咬得住，有证据",
    "自身即反证": "run 本身就是把东西弄坏再看红",
    "仅正向": "有 run，能红，但没人证明过它会红",
    "人工": "manual 判据不许阻断 —— 这条是契约错误",
}


def red_ids() -> dict[str, set[str]]:
    """哪份真契约的哪些判据，被坏样本期望成 red。"""
    out: dict[str, set[str]] = defaultdict(set)
    for case in CASES:
        if not case.contract:
            continue
        for cid, want in case.states.items():
            if want == BAD:
                out[case.contract].add(cid)
    return out


def classify(crit, reds: set[str]) -> str:
    if crit.id in reds:
        return "坏样本"
    if crit.kind == "manual":
        return "人工"
    if ADVERSARY.search(crit.run or ""):
        return "自身即反证"
    return "仅正向"


def build_rows() -> list[dict]:
    reds = red_ids()
    rows: list[dict] = []
    for path in sorted((ROOT / "contracts").glob("*.json")):
        contract = C.load(path)
        for req in contract.requirements:
            for crit in req.criteria:
                if not crit.blocking:
                    continue
                rows.append({
                    "contract": path.stem,
                    "req": req.id,
                    "id": crit.id,
                    "kind": crit.kind,
                    "class": classify(crit, reds.get(path.stem, set())),
                })
    return rows


def summarize(rows: list[dict]) -> dict:
    counts = Counter(r["class"] for r in rows)
    by_contract: dict[str, Counter] = defaultdict(Counter)
    for r in rows:
        by_contract[r["contract"]][r["class"]] += 1
    groups = Counter(c.group for c in CASES)
    return {
        "blocking_total": len(rows),
        "counts": dict(counts),
        "by_contract": {k: dict(v) for k, v in by_contract.items()},
        "baseline_groups": dict(groups),
        "baseline_total": len(CASES),
        "gaps": [r["id"] for r in rows if r["class"] == "仅正向"],
    }


def render(rows: list[dict], s: dict) -> str:
    out = [
        f"判据行为覆盖 · {len(s['by_contract'])} 份契约 · {s['blocking_total']} 条阻断",
        "=" * 78,
    ]
    for label in ("坏样本", "自身即反证", "仅正向", "人工"):
        ids = [r["id"] for r in rows if r["class"] == label]
        if not ids:
            continue
        out.append(f"■ {label}（{len(ids)}）—— {LABELS[label]}")
        for contract in sorted({r["contract"] for r in rows if r["class"] == label}):
            part = [r["id"] for r in rows if r["class"] == label and r["contract"] == contract]
            out.append(f"    {contract}：{' '.join(part)}")
        out.append("")
    out.append("-" * 78)
    for contract, c in sorted(s["by_contract"].items()):
        detail = " · ".join(f"{k} {v}" for k, v in sorted(c.items()))
        out.append(f"{contract:<12}{sum(c.values()):>3} 条阻断　{detail}")
    out.append("-" * 78)
    out.append("总计 " + " · ".join(f"{k} {v}" for k, v in sorted(s["counts"].items())))
    out.append(f"基准集 {s['baseline_total']} 条，按失败模式组："
               + " · ".join(f"{k} {v}" for k, v in sorted(s["baseline_groups"].items())))
    if s["gaps"]:
        out.append("从未被弄红过（不是错误，是「还没证明」）：" + " ".join(s["gaps"]))
    return "\n".join(out)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="判据行为覆盖报告（只报告，不做门）")
    ap.add_argument("--json", action="store_true", help="机器可读")
    ap.add_argument("--quiet", action="store_true", help="只打总计与缺口")
    args = ap.parse_args(argv)
    rows = build_rows()
    s = summarize(rows)
    if args.json:
        print(json.dumps({"rows": rows, "summary": s}, ensure_ascii=False, indent=1))
    elif args.quiet:
        print("总计 " + " · ".join(f"{k} {v}" for k, v in sorted(s["counts"].items())))
        if s["gaps"]:
            print("从未被弄红过：" + " ".join(s["gaps"]))
    else:
        print(render(rows, s))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
