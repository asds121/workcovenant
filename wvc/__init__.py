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
__version__ = "1.0.0"
