# -*- coding: utf-8 -*-
"""敏感信息扫描 —— 公开仓库的发布前门。

    python tools/privacy_scan.py                # 工作树 + 规则自测（默认）
    python tools/privacy_scan.py --history      # 同时扫**所有提交**（历史删不干净）
    python tools/privacy_scan.py --selftest     # 只验规则本身：正例咬不咬得住、反例误不误报
    python tools/privacy_scan.py --json         # 给机器看

退出码
------
    0  干净（工作树 0 命中，规则自测全过）
    1  有命中 —— 不准发布
    3  规则自测不过 —— 扫描器自己坏了，这时"干净"两个字毫无意义

`3` 单独一个码是刻意的：**扫描器坏掉**和**仓库脏了**必须分得开。
混在一起就会出现"扫描通过"其实是因为规则失灵。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from wvc import privacy as P      # noqa: E402

USAGE = """用法：python tools/privacy_scan.py [选项]

  --tree       扫工作树（默认）
  --history    扫 git 历史（所有提交的新增行）
  --selftest   只跑规则自测
  --json       输出 JSON
  -h, --help   看这段

规则共 {n} 条，见 wvc/privacy.py；每条都带正例与反例。"""


def main(argv: list[str]) -> int:
    if {"-h", "--help"} & set(argv):
        print(USAGE.format(n=len(P.RULES)))
        return 0
    want_tree = "--tree" in argv or "--history" not in argv
    want_hist = "--history" in argv
    want_self = "--selftest" in argv or want_tree
    as_json = "--json" in argv

    payload: dict = {"rules": len(P.RULES), "units": [], "hits": [], "skipped": []}
    code = 0

    bad_rules = P.selftest() if want_self else []
    if bad_rules:
        payload["selftest"] = bad_rules
        code = 3
        if not as_json:
            print(f"❌ 规则自测 {len(bad_rules)} 条不过 —— 扫描器的结论不可信：")
            for b in bad_rules:
                print(f"   · {b}")
            print("   先修规则，再看仓库干不干净。")
            return code
    elif want_self and not as_json:
        payload["selftest"] = []

    if want_tree:
        res = P.scan_tree(ROOT)
        payload["units"].append({"scope": "工作树", "files": res.files, "hits": len(res.hits),
                                 "skipped": res.skipped})
        payload["hits"] += [{"rule": h.rule_id, "name": h.rule_name, "path": h.path,
                             "line": h.line_no, "value": h.value} for h in res.hits]
        payload["skipped"] += res.skipped
        if not as_json:
            print(f"工作树 · {res.files} 个文件 · 命中 {len(res.hits)} · 跳过 {len(res.skipped)}")
            for h in res.hits:
                print(f"   ❌ {h.line()}")
            for s in res.skipped:
                print(f"   · 跳过 {s}")
            print("   ✅ 干净" if res.ok else "   ❌ 有命中 —— 不准发布")
        code = max(code, 0 if res.ok else 1)

    if want_hist:
        res = P.scan_history(ROOT)
        payload["units"].append({"scope": "历史", "commits": res.commits, "hits": len(res.hits)})
        payload["hits"] += [{"rule": h.rule_id, "name": h.rule_name, "path": h.path,
                             "line": h.line_no, "value": h.value} for h in res.hits]
        payload["skipped"] += res.skipped
        if not as_json:
            print(f"历史 · {res.commits} 个提交 · 命中 {len(res.hits)}")
            for h in res.hits:
                print(f"   ❌ {h.line()}")
            for s in res.skipped:
                print(f"   · 跳过 {s}")
            print("   ✅ 全部提交干净（历史删不干净，只能证明它从来是干净的）"
                  if res.ok else "   ❌ 历史里就有 —— 改工作树没用")
        code = max(code, 0 if res.ok else 1)

    if want_self and not bad_rules and not as_json:
        print(f"规则自测 · {len(P.RULES)} 条全过（正例咬得住、反例不误报）")

    if as_json:
        payload["ok"] = code == 0 and not payload["hits"]
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv))
