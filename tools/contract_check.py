# -*- coding: utf-8 -*-
"""契约体检 —— 只验"这份契约写全了没有"，不跑判据。

为什么单独一个门：一份跑出 100 分的契约，也可能是**判据没覆盖到关键动作**的契约。
分数只回答"做到没有"，回答不了"该验的验了没有"。所以体检要独立、要先跑。

    python tools/contract_check.py contracts/仓库交付.json
    python tools/contract_check.py contracts/*.json      # bash 会展开

查什么
------
- schema v1.0 的硬字段（`wvc/contract.py::validate`，全量列出，不做"碰到第一个错就停"）
- 每条需求有没有原话 / 最小闭环 / 判据（三段齐全才算数）
- 每条判据有没有 `why`（守的是哪根红线）—— 没有就是"为了测而测"
- 至少一条阻断项（没有一票否决的契约拦不住任何东西）

退出码：0 合格 / 3 不合格。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from wvc import contract as C      # noqa: E402


def check_one(path: str) -> tuple[bool, str]:
    try:
        c = C.load(path)
    except C.ContractError as exc:
        return False, str(exc)

    lines = [f"✅ {path}",
             f"   {c.name} {c.version} · {c.profession} · 负责人 {c.owner}"]
    for r in c.requirements:
        auto = sum(1 for x in r.criteria if x.kind != "manual")
        manual = len(r.criteria) - auto
        tag = f"{len(r.criteria)} 条判据（机检 {auto}" + (f" · 人工留证 {manual}" if manual else "") + "）"
        block = " · 含阻断" if any(x.blocking for x in r.criteria) else ""
        lines.append(f"   {r.id:<4} {r.title}　{tag}{block}")
        lines.append(f"        闭环 {len(r.loop)} 步：{r.loop[0]}" + ("…" if len(r.loop) > 1 else ""))
    n = len(c.criteria)
    lines.append(f"   合计 {len(c.requirements)} 条需求 / {n} 条判据 / "
                 f"阻断 {len(c.blocking)} 条 / 人工留证 {sum(1 for x in c.criteria if x.kind == 'manual')} 条")
    if not c.blocking:
        return False, "\n".join(lines + ["❌ 一条阻断项都没有 —— 这份契约拦不住任何东西"])
    return True, "\n".join(lines)


def main(argv: list[str]) -> int:
    paths = [a for a in argv[1:] if not a.startswith("-")]
    if not paths:
        print(__doc__)
        return 3
    ok_all = True
    for p in paths:
        ok, text = check_one(p)
        print(text)
        ok_all = ok_all and ok
    print("=" * 60)
    print("全部合格" if ok_all else "有不合格的契约 —— 先修契约，再看分数")
    return 0 if ok_all else 3


if __name__ == "__main__":
    sys.exit(main(sys.argv))
