# -*- coding: utf-8 -*-
"""反证 —— 故意把东西改坏，看引擎会不会红。

一个永远报绿的引擎，比没有引擎更能骗人：它给出一张漂亮的表，让所有人放心。
所以这里不问"引擎算得对不对"，只问一件事：**它咬不咬得住。**

八条反证，每条都改一处、必须当场变红；改不红就说明那一类错误会漏过去，
漏过去的错误最后会以"验收通过了但线上是坏的"的形式出现在用户面前。

后两条专门盯**敏感信息扫描器**：规则被改瞎、真密钥被植入，
两种都必须当场说破 —— 扫描器失灵时给出的"干净"，是最贵的假报告。

    python tools/mutation_check.py           # 逐条说话
    python tools/mutation_check.py --quiet   # 只留结论（给契约判据调用）

退出码：0 八条全咬住 / 1 有漏网的。
"""
from __future__ import annotations

import copy
import json
import sys
import tempfile
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from wvc import contract as C      # noqa: E402
from wvc import privacy as P       # noqa: E402
from wvc import score as S         # noqa: E402

BASE = {
    "format": C.FORMAT,
    "id": "mutation-fixture",
    "name": "反证用最小契约",
    "profession": "测试",
    "version": "1.0.0",
    "owner": "反证脚本",
    "requirements": [
        {
            "id": "R1", "title": "交付物在且不是空壳",
            "verbatim": "反证用", "loop": ["跑一次", "看结果"],
            "criteria": [
                {"id": "R1-a", "title": "文件够大", "why": "空壳等于没交",
                 "kind": "file", "path": "doc.md", "min_bytes": 400, "blocking": True},
                {"id": "R1-b", "title": "有一级标题", "why": "没有标题读者不知道在看什么",
                 "kind": "file", "path": "doc.md", "contains": "^# 标题"},
            ],
        },
        {
            "id": "R2", "title": "证据链",
            "verbatim": "反证用", "loop": ["看链接", "看人工证据"],
            "criteria": [
                {"id": "R2-a", "title": "相对链接解析得到", "why": "断链假装有出处",
                 "kind": "links", "path": "doc.md"},
                {"id": "R2-b", "title": "人工项留了证据", "why": "没证据就是没验",
                 "kind": "manual", "evidence": "evidence.md"},
            ],
        },
        {
            "id": "R3", "title": "命令类判据",
            "verbatim": "反证用", "loop": ["跑命令", "看输出"],
            "criteria": [
                {"id": "R3-a", "title": "命令输出 OK", "why": "命令跑不通就是没做到",
                 "kind": "cmd", "run": "{python} -c \"print('OK')\"",
                 "expect": {"stdout_contains": "OK"}},
            ],
        },
    ],
}

DOC = "# 标题\n\n" + ("这是一份够长的交付物。" * 40) + "\n\n[证据](evidence.md)\n"
EVIDENCE = "✅ 看过了：首屏三问都答得出来。\n"


class Workspace:
    """一次性的工作目录：产物写在这里，绝不碰仓库里的真文件。"""

    def __init__(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="wvc_mut_")
        self.root = Path(self._tmp.name)
        (self.root / "doc.md").write_text(DOC, encoding="utf-8")
        (self.root / "evidence.md").write_text(EVIDENCE, encoding="utf-8")

    def cleanup(self) -> None:
        self._tmp.cleanup()

    def run(self, raw: dict) -> S.Report:
        p = self.root / "_contract.json"
        p.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
        return S.evaluate(C.load(p), self.root)


def crit(report: S.Report, cid: str) -> str:
    for row in report.rows:
        for c, r in row.results:
            if c.id == cid:
                return r.state
    return "missing"


# ------------------------------------------------------------------ 六条反证
def m1_expectation(ws: Workspace) -> str:
    """把期望输出改坏 —— 引擎必须红。"""
    raw = copy.deepcopy(BASE)
    raw["requirements"][2]["criteria"][0]["expect"]["stdout_contains"] = "绝不会出现的词"
    rep = ws.run(raw)
    assert rep.exit_code == 1, f"退出码 {rep.exit_code}，期望 1"
    assert crit(rep, "R3-a") == "fail", "R3-a 没红"
    return "期望改坏 → R3-a 红，退出码 1"


def m2_missing_deliverable(ws: Workspace) -> str:
    """删掉交付物 —— 必须是 fail，不是 skip。"""
    (ws.root / "doc.md").unlink()
    rep = ws.run(BASE)
    assert crit(rep, "R1-a") == "fail", f"交付物没了却记成 {crit(rep, 'R1-a')}"
    assert rep.exit_code == 1, f"退出码 {rep.exit_code}，期望 1"
    return "删交付物 → fail（不是「未验」），退出码 1"


def m3_missing_prereq(ws: Workspace) -> str:
    """缺前置料 —— 必须 skip 且退出码 2，不能当成过。"""
    raw = copy.deepcopy(BASE)
    raw["requirements"][0]["criteria"][1]["requires"] = ["never.txt"]
    rep = ws.run(raw)
    assert crit(rep, "R1-b") == "skip", f"缺料却记成 {crit(rep, 'R1-b')}"
    assert rep.exit_code == 2, f"退出码 {rep.exit_code}，期望 2"
    assert "R1-b" not in [c.id for c, _ in rep.blocked], "缺料被算成阻断红"
    return "缺前置料 → skip，退出码 2（2 ≠ 通过）"


def m4_blocking_veto(ws: Workspace) -> str:
    """阻断项红了，别的全绿 —— 结论必须是不通过。"""
    raw = copy.deepcopy(BASE)
    raw["requirements"][0]["criteria"][0]["min_bytes"] = 10 ** 6
    rep = ws.run(raw)
    assert [c.id for c, _ in rep.blocked] == ["R1-a"], "阻断项没被单独指出来"
    assert rep.verdict.startswith("不通过"), f"结论是 {rep.verdict!r}"
    assert rep.overall > 0, "总分被抹成 0 —— 那会掩盖别的进展"
    return f"阻断项红 → 结论「{rep.verdict}」，总分仍显示 {rep.overall:.0f}"


def m5_manual_evidence(ws: Workspace) -> str:
    """人工项：没证据 → skip；证据判红 → fail。两种都不是 pass。"""
    ev = ws.root / "evidence.md"
    ev.unlink()
    assert crit(ws.run(BASE), "R2-b") == "skip", "没证据却记成过"
    ev.write_text("❌ 首屏读不懂。\n", encoding="utf-8")
    rep = ws.run(BASE)
    assert crit(rep, "R2-b") == "fail", "证据判红却记成过"
    return "人工项 无证据→skip / 判红→fail"


def m6_broken_contract(ws: Workspace) -> str:
    """契约缺字段、id 重复 —— 必须拒绝加载，不许静默补默认值。"""
    raw = copy.deepcopy(BASE)
    del raw["requirements"][0]["criteria"][0]["why"]
    try:
        C.load(_write(ws, raw))
    except C.ContractError as exc:
        assert "why" in str(exc), "报错里没说清缺哪个字段"
    else:
        raise AssertionError("缺 `why` 竟然加载成功了")

    raw = copy.deepcopy(BASE)
    raw["requirements"][0]["criteria"][1]["id"] = "R1-a"
    try:
        C.load(_write(ws, raw))
    except C.ContractError as exc:
        assert "重复" in str(exc), "报错里没说清是 id 重复"
    else:
        raise AssertionError("id 重复竟然加载成功了")
    return "缺字段 / id 重复 → 拒绝加载并说清位置"


def _write(ws: Workspace, raw: dict) -> Path:
    p = ws.root / "_broken.json"
    p.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    return p


def m7_blind_rule(ws: Workspace) -> str:
    """把一条敏感规则改瞎（永远不命中）—— 自测必须当场抓住。"""
    blind = [replace(P.RULES[0], pattern="(?!)")]
    bad = P.selftest(blind)
    assert bad, "规则退化成永不命中，自测居然一句话没说"
    assert "没咬住正例" in bad[0], f"自测说错了：{bad[0]}"
    assert P.selftest() == [], "真规则表自己也过不了自测"
    return "规则改瞎 → 自测红；真规则表自测全过"


def m8_planted_secret(ws: Workspace) -> str:
    """往工作树植入一条假密钥 —— 扫描器必须命中（漏报比误报严重得多）。"""
    secret = "gh" "p_" + "Q" * 36
    (ws.root / "config.py").write_text(f'TOKEN = "{secret}"\n', encoding="utf-8")
    hits = P.scan_tree(ws.root).hits
    assert any(h.rule_id == "P5" for h in hits), "植入的密钥没被抓住 —— 扫描器在漏"
    assert all("***" in h.value for h in hits), "报告里出现了明文"
    return "植入假密钥 → P5 命中，且报告已打码"


MUTATIONS = [
    ("M1 期望改坏", m1_expectation),
    ("M2 删交付物", m2_missing_deliverable),
    ("M3 缺前置料", m3_missing_prereq),
    ("M4 阻断项红", m4_blocking_veto),
    ("M5 人工证据", m5_manual_evidence),
    ("M6 契约坏了", m6_broken_contract),
    ("M7 规则改瞎", m7_blind_rule),
    ("M8 植入密钥", m8_planted_secret),
]


def main(argv: list[str]) -> int:
    quiet = "--quiet" in argv
    caught, missed = 0, []
    for name, fn in MUTATIONS:
        ws = Workspace()
        try:
            note = fn(ws)
            caught += 1
            if not quiet:
                print(f"✅ {name}：咬住了 —— {note}")
        except AssertionError as exc:
            missed.append(f"{name}：漏了 —— {exc}")
            if not quiet:
                print(f"❌ {name}：漏了 —— {exc}")
        finally:
            ws.cleanup()
    total = len(MUTATIONS)
    print(f"反证 {caught}/{total} 咬住" + ("· 全部咬住" if caught == total else ""))
    for m in missed:
        print("  ❌ " + m)
    return 0 if caught == total else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
