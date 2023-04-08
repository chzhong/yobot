import asyncio
import logging
from typing import Dict, Optional, Union

from .shadow import  ShadowQQ
from .member_report import ClanMemberReport

from ..typing import Groupid, Pcr_date, QQid
from ..util import pcr_datetime

from ...ybdata import Clan_challenge, Clan_delegate, Clan_group, Clan_member, User
from ..exception import GroupNotExist, NickNameAmbigous, NickNameNotFound

_logger = logging.getLogger(__name__)



def bind_group_principal(self, group_id: Groupid, principal_group_id: Groupid):
	"""
	set group's principal to
	Args:
		group_id: delegate group id
		principal_group_id: principal group id. 0 to cancel delegation
	"""
	delegate = Clan_delegate.get_or_none(group_id=group_id)
	if delegate is None and principal_group_id > 0:
		delegate = Clan_delegate.create(group_id=group_id, principal_group_id=principal_group_id)
	else:
		if principal_group_id > 0:
			delegate.principal_group_id = principal_group_id
			delegate.save()
		else:
			principal_group_id = delegate.principal_group_id
			delegate.delete_instance()
	return delegate


def get_group_principal(self, group_id: Groupid):
	"""
	get group's principal
	Args:
		group_id: delegate group id
	"""
	delegate = Clan_delegate.get_or_none(group_id=group_id)
	if delegate is None:
		# No delegation
		return group_id
	else:
		return delegate.principal_group_id


async def bind_group_for_shadow(self, group_id: Groupid, qqid: QQid, nickname: str):
	"""
	set user's default group
	Args:
		group_id: group id
		qqid: qqid
		nickname: displayed name
	"""
	_logger.info(f'绑定小号 group: {group_id}, onwer: {qqid}, nickname: {nickname}')
	min_shadow = ShadowQQ.min_shadow(qqid)
	max_shadow = ShadowQQ.max_shadow(qqid)
	shadows = Clan_member.select().where(Clan_member.qqid.between(min_shadow.qqid, max_shadow.qqid))
	if not shadows:
		shadow_num = 1
	else:
		shadow_num = len(shadows) + 1
	shadow = ShadowQQ(qqid, shadow_num)
	_logger.info(f'绑定小号 group: {group_id}, onwer: {qqid}, nickname: {nickname}, qqid={shadow.qqid}')
	return await self.bind_group(group_id, shadow.qqid, nickname)

def unbind_group_for_shadow(self, group_id: Groupid, qqid: QQid, nickname: str):
	"""
    set user's default group
    Args:
        group_id: group id
        qqid: qqid
        nickname: displayed name
    """
	min_shadow = ShadowQQ.min_shadow(qqid)
	max_shadow = ShadowQQ.max_shadow(qqid)
	shadows = User.select().where(User.qqid.between(min_shadow.qqid, max_shadow.qqid)
								  and User.nickname == nickname)
	if not shadows:
		return
	shadow = shadows[0]
	self.drop_member(group_id, [shadow.qqid])


def resolve_behalf(self, group_id: Groupid, behalf: Union[str, None]):
	"""
	resolve behalf
	Args:
		group_id: group id
		behalf: qqid or nickname
	"""
	if not behalf:
		return None
	try:
		return QQid(int(behalf))
	except ValueError:
		# Search by nick name
		members = Clan_member.select(Clan_member, User).join(User, on=(Clan_member.qqid == User.qqid).alias('usr')) \
			.where((Clan_member.group_id == group_id) & (User.nickname.contains(behalf)))
		if not members:
			raise NickNameNotFound(behalf)
		elif len(members) > 1:
			raise NickNameAmbigous(behalf, [item.usr.nickname for item in members])
		_logger.info(f'昵称查找 {behalf} -> {members[0].qqid}')
		return QQid(members[0].qqid)


def get_clan_daily_challenge_report(self,
									group_id: Groupid,
									pcrdate: Optional[Pcr_date] = None,
									battle_id: Union[int, None] = None,
									):
	"""
	get the unfinished challanges
	Args:
		group_id: group id
		battle_id: battle id
		pcrdate: pcrdate of report
	"""
	group = Clan_group.get_or_none(group_id=group_id)
	if group is None:
		raise GroupNotExist
	if pcrdate is None:
		pcrdate = pcr_datetime(group.game_server)[0]
	if battle_id is None:
		battle_id = group.battle_id
	member_list = self.get_member_list(group_id)
	member_reports = {}  # type: Dict[QQid, ClanMemberReport]
	for member in member_list:
		member_reports[member['qqid']] = ClanMemberReport(member['qqid'], member['nickname'])
	for item in Clan_challenge.select().where(
			Clan_challenge.gid == group_id,
			Clan_challenge.bid == battle_id,
			Clan_challenge.challenge_pcrdate == pcrdate,
	):
		report = member_reports[str(item.qqid)]
		report.add_challenge(item.boss_cycle, item.boss_num, item.boss_health_ramain == 0, item.is_continue)
	return member_reports