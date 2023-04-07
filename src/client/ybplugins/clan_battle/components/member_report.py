from ..typing import QQid
from ..util import atqq
from .shadow import ShadowQQ


class ClanMemberReport:

    def __init__(self, qqid: QQid, nickname: str):
        self.qqid = qqid
        self.nickname = nickname
        self.finished_count = 0
        self.tailing_count = 0
        self.holds_tailing = False
        self.challenges = []

    def add_challenge(self, cycle, boss, is_tailing, is_continue):
        challenge = f'{cycle}-{boss}'
        if is_tailing and is_continue:
            self.challenges.append(f'>{challenge}#')
            self.holds_tailing = False
            self.tailing_count -= 1
            self.finished_count += 1
        elif is_tailing:
            self.challenges.append(f'{challenge}+')
            self.tailing_count += 1
            self.holds_tailing = True
        elif is_continue:
            self.challenges.append(f'>{challenge}')
            self.holds_tailing = False
            self.finished_count += 1
            self.tailing_count -= 1
        else:
            self.challenges.append(challenge)
            self.finished_count += 1

    def atqq(self):
        if ShadowQQ.is_shadow(self.qqid):
            return atqq(ShadowQQ.get_delegate(self.qqid)) + ' ' + self.nickname
        else:
            return atqq(self.qqid)

    @property
    def finished(self):
        return self.finished_count == 3

    @property
    def unfinished(self):
        if self.holds_tailing:
            return 3 - self.finished_count - 1
        else:
            return 3 - self.finished_count

    @property
    def status(self):
        status = ''
        if self.finished_count == 3:
            status += '已下班'
        else:
            if self.holds_tailing and self.finished_count == 2:
                status += '剩补偿刀未出'
            elif self.holds_tailing:
                status += f'剩补偿刀和{3 - self.finished_count - 1}完整刀未出'
            else:
                status += f'剩{3 - self.finished_count}刀未出'
        return status