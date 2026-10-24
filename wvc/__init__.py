# -*- coding: utf-8 -*-
"""WorkCovenant —— 职业契约框架的参考实现（框架层）。

这一层只认三件事：**契约怎么写、判据怎么跑、分数怎么算**。
它不知道"凭证""错题""工单"是什么 —— 那些是各个职业契约里的判据内容。

    from wvc import contract, score
    c = contract.load("contracts/仓库交付.json")
    print(score.render(score.evaluate(c, ".")))
"""
from . import checks, contract, score

__all__ = ["checks", "contract", "score"]
#: 框架版本。**判断框架新旧以 CHANGELOG 为准**（发版行形态 `## 日期 · vX.Y.Z`）——
#: 这个值是给外部消费的元数据，不是尺子；但它停在旧版本，读它的人就会漏掉中间的
#: 改动。两条腿必须同时动，`tests/test_docs.py` 盯着。
__version__ = "1.2.1"
