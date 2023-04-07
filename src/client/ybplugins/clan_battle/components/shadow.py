from typing import Optional

from ..typing import QQid


class ShadowQQ:

    PREFIX = 49
    SHADOW_GAP = 100
    MIN_SHADOW_NUM = 1
    MAX_SHADOW_NUM = SHADOW_GAP - 1
    BASE = QQid(PREFIX * 1_000_000_000_000)
    MIN = QQid(BASE * SHADOW_GAP)

    @staticmethod
    def is_shadow(qqid: QQid):
        return int(qqid) > ShadowQQ.MIN

    @staticmethod
    def get_delegate(qqid: QQid) -> QQid:
        return ShadowQQ(qqid).delegate

    @staticmethod
    def max_shadow(qqid: QQid):
        return ShadowQQ(qqid, ShadowQQ.SHADOW_GAP - 1)

    @staticmethod
    def min_shadow(qqid: QQid):
        return ShadowQQ(qqid, 1)

    def __init__(self, qqid: QQid, shadow_num: Optional[int]=None) -> None:
        if ShadowQQ.is_shadow(qqid):
            self.qqid = qqid
            self.delegate = QQid(int(qqid) // ShadowQQ.SHADOW_GAP - ShadowQQ.BASE)
            self.shadow_num = int(qqid) % ShadowQQ.SHADOW_GAP
        else:
            self.delegate = qqid
            self.shadow_num = shadow_num
            self.qqid = QQid((ShadowQQ.BASE + int(qqid)) * ShadowQQ.SHADOW_GAP + shadow_num)