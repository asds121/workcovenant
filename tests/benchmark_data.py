# -*- coding: utf-8 -*-
"""基准集 · data 组 —— 一批记录的失败模式。

单独一册的理由很实在：单个 `.py` 不许超过 20KB（仓库治理 G1-d）。
这里只放 `data` 判据的用例，骨架和另外六组在 `bench_support.py` /
`benchmark_cases.py`。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tests.bench_support import Case, criterion as _c, doc as _doc, write as _write  # noqa: E402


# ------------------------------------------------------------------ data（10）
def _d(cid: str, clause: dict, title: str = "", **kw) -> dict:
    """data 判据：`assert` 是关键字，不能当参数名传，所以单独包一层。"""
    d = _c(cid, "data", title, path="d.json", **kw)
    d["assert"] = [clause]
    return d


def _recs(*recs: dict) -> str:
    return json.dumps({"items": list(recs)}, ensure_ascii=False)


BASE_REC = {"id": "A-1", "order": "O-1", "risk": "low", "text": "正常回复"}


def data_cases() -> list[Case]:
    def good(root: Path) -> dict:
        _write(root, "d.json", _recs(BASE_REC))
        return _doc(_d("C1", {"required": ["order", "text"]}))

    def missing(root: Path) -> dict:
        _write(root, "d.json", _recs({**BASE_REC, "order": ""}))
        return _doc(_d("C1", {"required": ["order", "text"]}))

    def term(root: Path) -> dict:
        _write(root, "d.json", _recs({**BASE_REC, "text": "可以保证退款"}))
        return _doc(_d("C1", {"forbidden": {"fields": ["text"], "terms": ["保证退款"]}}))

    def late(root: Path) -> dict:
        _write(root, "d.json", _recs({**BASE_REC, "t0": "2026-10-20T09:00:00",
                                      "t1": "2026-10-21T10:00:00"}))
        return _doc(_d("C1", {"sla": {"start": "t0", "end": "t1", "max_hours": 24}}))

    def when_pass(root: Path) -> dict:
        """风险不高时，就不该要求升级路径 —— 判据不能扩大打击面。"""
        _write(root, "d.json", _recs(BASE_REC))
        return _doc(_d("C1", {"when": {"field": "risk", "in": ["high"]},
                              "required": ["escalation"]}))

    def when_fail(root: Path) -> dict:
        _write(root, "d.json", _recs({**BASE_REC, "risk": "high"}))
        return _doc(_d("C1", {"when": {"field": "risk", "in": ["high"]},
                              "required": ["escalation"]}))

    def same_source(root: Path) -> dict:
        _write(root, "d.json", _recs({**BASE_REC, "a": "proxy", "b": "proxy"}))
        return _doc(_d("C1", {"compare": {"pairs": [["a", "b"]], "expect": "ne"}}))

    def overwritten(root: Path) -> dict:
        _write(root, "d.json", _recs({**BASE_REC, "v": "机器值", "v_human": "人工值"}))
        return _doc(_d("C1", {"when": {"field": "v_human", "nonempty": True},
                              "compare": {"pairs": [["v", "v_human"]], "expect": "eq"}}))

    def broken_json(root: Path) -> dict:
        _write(root, "d.json", "{ 这不是 JSON")
        return _doc(_d("C1", {"required": ["order"]}))

    def not_list(root: Path) -> dict:
        _write(root, "d.json", '{"rows": []}')
        return _doc(_d("C1", {"required": ["order"]}))

    return [
        Case("B-data-01", "data", "全部合规 → 过", "基线：子句全成立时不许误报",
             good, {"C1": "pass"}, 0),
        Case("B-data-02", "data", "必填为空 → 红", "空串不算有值，这是最常见的脏数据",
             missing, {"C1": "fail"}, 1),
        Case("B-data-03", "data", "出现禁词 → 红", "禁词表要盯住的是内容，不是文件名",
             term, {"C1": "fail"}, 1),
        Case("B-data-04", "data", "超时 → 红", "时间戳能证明的违约，必须机器判",
             late, {"C1": "fail"}, 1),
        Case("B-data-05", "data", "when 不成立 → 不判", "条件不满足时不许无辜变红",
             when_pass, {"C1": "pass"}, 0),
        Case("B-data-06", "data", "when 成立但缺字段 → 红", "条件成立就得有，少一个都不行",
             when_fail, {"C1": "fail"}, 1),
        Case("B-data-07", "data", "两个来源相同 → 红", "同源不能当独立复核（协议 §2.5）",
             same_source, {"C1": "fail"}, 1),
        Case("B-data-08", "data", "人工值被覆盖 → 红", "补空只填空字段，已有值一个字不动",
             overwritten, {"C1": "fail"}, 1),
        Case("B-data-09", "data", "JSON 坏了 → 红不是崩", "一个判据写坏，不能让整次评分挂掉",
             broken_json, {"C1": "fail"}, 1),
        Case("B-data-10", "data", "没有记录数组 → 红", "数据文件结构不对，等于没交",
             not_list, {"C1": "fail"}, 1),
        *_real_cases(),
    ]


def _real_cases() -> list[Case]:
    """拿真样板间（工单质检）的契约去跑好样本与坏样本。

    这两条是"判据不是摆设"的最短证明：坏样本每一条只犯一个错，
    对应判据必须各自红；好样本必须全绿 —— 只红不绿说明判据在乱咬。
    """
    contract = ROOT / "contracts" / "工单质检.json"
    sample = ROOT / "examples" / "工单质检"

    def build(name: str):
        def _build(root: Path) -> dict:
            _write(root, "d.json", (sample / name).read_text(encoding="utf-8"))
            raw = json.loads(contract.read_text(encoding="utf-8"))
            for req in raw["requirements"]:
                for c in req["criteria"]:
                    c["path"] = "d.json"
            return raw
        return _build

    red = {"T1-a": "fail", "T2-a": "fail", "T3-a": "fail", "T4-a": "fail",
           "T5-a": "pass", "T6-a": "fail", "T7-a": "fail"}
    green = {f"T{i}-a": "pass" for i in range(1, 8)}
    return [
        Case("B-data-11", "data", "真样板间 × 坏样本 → 六条各自红",
             "每条坏记录只犯一个错；T5 不该被误伤", build("tickets-broken.json"), red, 1),
        Case("B-data-12", "data", "真样板间 × 好样本 → 全绿",
             "判据只红不绿，说明它在乱咬", build("tickets.json"), green, 0),
    ]
