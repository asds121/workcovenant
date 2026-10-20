# -*- coding: utf-8 -*-
"""可重放校验 —— 同一个输入跑两次，判定必须逐格相同。

"跑通了"和"可重放"是两件事：前者只证明这次运气好。
用户的原话（总纲·稳）：**可重放（逐格相同，非"跑通"）**。

比什么、不比什么，写清楚比"差不多一致"重要：

| 比 | 不比 |
|---|---|
| 总分、结论、退出码 | 耗时（`seconds`） |
| 每条需求的 状态/得分/通过数 | 证据文本里的 "Ran 14 tests in 6.1s" |
| 每条判据的 state 与阻断标记 | 路径里的临时目录名 |

证据文本里允许出现耗时与绝对路径 —— 它们是给人看的现场记录，不是判定。
把判定和现场记录分开比，才不会为了"可重放"去伪造证据。

    python tools/replay_check.py contracts/教培-能力契约.json
    python tools/replay_check.py contracts/仓库交付.json --root .

退出码：0 两次一致 / 1 不一致 / 3 跑不起来。
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def snapshot(contract: str, root: str) -> dict:
    proc = subprocess.run([sys.executable, str(ROOT / "tools" / "score.py"), contract,
                           "--json", "--root", root],
                          cwd=str(ROOT), capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=600)
    if proc.returncode not in (0, 1, 2):
        raise RuntimeError(f"score 跑不起来（退出码 {proc.returncode}）：{proc.stderr.strip()[:300]}")
    rep = json.loads(proc.stdout)
    return {
        "overall": rep["overall"],
        "verdict": rep["verdict"],
        "exit_code": rep["exit_code"],
        "requirements": [
            {"id": r["id"], "status": r["status"], "score": r["score"],
             "passed": r["passed"], "failed": r["failed"], "skipped": r["skipped"],
             "criteria": [{"id": c["id"], "state": c["state"], "blocking": c["blocking"]}
                          for c in r["criteria"]]}
            for r in rep["requirements"]
        ],
    }


def main(argv: list[str]) -> int:
    args = [a for a in argv[1:] if not a.startswith("-")]
    if not args:
        print(__doc__)
        return 3
    contract = args[0]
    root = "."
    for i, a in enumerate(argv):
        if a == "--root" and i + 1 < len(argv):
            root = argv[i + 1]

    try:
        a = snapshot(contract, root)
        b = snapshot(contract, root)
    except Exception as exc:                      # noqa: BLE001
        print(f"可重放校验没跑起来：{type(exc).__name__}: {exc}")
        return 3

    if json.dumps(a, sort_keys=True, ensure_ascii=False) == json.dumps(b, sort_keys=True, ensure_ascii=False):
        print(f"✅ 可重放：两次跑判定逐格相同（{a['overall']:.0f} 分 · {a['verdict']}）")
        return 0

    print("❌ 不可重放 —— 同一个输入跑出了不同判定：")
    for x, y in zip(a["requirements"], b["requirements"]):
        if x != y:
            print(f"   {x['id']}：{x['status']} {x['score']}% → {y['status']} {y['score']}%")
            for c1, c2 in zip(x["criteria"], y["criteria"]):
                if c1 != c2:
                    print(f"      {c1['id']}: {c1['state']} → {c2['state']}")
    if a["overall"] != b["overall"]:
        print(f"   总分 {a['overall']} → {b['overall']}")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
