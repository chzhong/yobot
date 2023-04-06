from typing import List


class ClanBattleError(ValueError):...
class UserError(ClanBattleError):...
class GroupError(ClanBattleError):...
class InputError(ClanBattleError):...
class UserNotInGroup(UserError):
    def __init__(self, msg='未加入公会，请先发送“加入公会”', *args):
        super().__init__(msg, *args)
class GroupNotExist(GroupError):
    def __init__(self, msg='本群未初始化，请发送“创建X服公会”', *args):
        super().__init__(msg, *args)

class NickNameNotFound(UserError):
    def __init__(self, nickname, *args):
        super.__init__(msg=f'找不到昵称为“{nickname}”的会员', *args)

class NickNameAmbigous(UserError):
    def __init__(self, nickname:str, candidates: List[str], *args):
        name_list = '\n- '.join(candidates)
        super.__init__(msg=f'会员昵称“{nickname}”不明确，可能是如下会员:\n- {name_list}', *args)