import asyncio
import logging
import os
import re
import sys
from typing import Any, Dict, List
from urllib.parse import urljoin

from aiocqhttp.api import Api
from apscheduler.triggers.cron import CronTrigger

from ..typing import Groupid
from ...ybdata import Clan_group, Clan_member, User
from ..exception import ClanBattleError, InputError
from ..util import atqq
from .define import Commands, Server

_logger = logging.getLogger(__name__)


def match_patterns(patterns: List[str], cmd: str):
	for pattern in patterns:
		match = re.match(pattern, cmd)
		if match:
			return match
	return None

#初始化
def init(self,
		 glo_setting:Dict[str, Any],
		 bot_api:Api,
		 boss_id_name:Dict[str, Any],
		 *args, **kwargs):
	self.setting = glo_setting
	self.boss_id_name = boss_id_name
	self.bossinfo = glo_setting['boss']
	self.level_by_cycle = glo_setting['level_by_cycle']
	self.api = bot_api
	self.group_data_list = {}

	# log
	if not os.path.exists(os.path.join(glo_setting['dirname'], 'log')):
		os.mkdir(os.path.join(glo_setting['dirname'], 'log'))

	formater = logging.Formatter('[%(asctime)s] %(levelname)s: %(message)s')
	filehandler = logging.FileHandler(
		os.path.join(glo_setting['dirname'], 'log', '公会战日志.log'),
		encoding='utf-8',
	)
	filehandler.setFormatter(formater)
	consolehandler = logging.StreamHandler(stream=sys.stdout)
	consolehandler.setFormatter(formater)
	_logger.addHandler(filehandler)
	_logger.addHandler(consolehandler)
	_logger.setLevel(logging.INFO)

	for group in Clan_group.select().where(Clan_group.deleted == False):
		self._boss_status[group.group_id] = asyncio.get_event_loop().create_future()

	# super-admin initialize
	User.update({User.authority_group: 100}).where(
		User.authority_group == 1
	).execute()
	User.update({User.authority_group: 1}).where(
		User.qqid.in_(self.setting['super-admin'])
	).execute()

	from pathlib import Path
	inipath = Path(os.path.dirname(__file__)).parents[2] / 'yobot_data' / 'groups.ini'
	if not inipath.exists():
		if not (Path(os.path.dirname(__file__)).parents[2] / 'yobot_data').exists():
			os.mkdir(str(Path(os.path.dirname(__file__)).parents[2] / 'yobot_data'))
		inipath.touch()
		with open(inipath,'w') as f:
			f.write('[GROUPS]\n11111 = 22222')

#定时任务
def jobs(self):
	trigger = CronTrigger(hour=5)

	def ensure_future_update_all_group_members():
		asyncio.ensure_future(self._update_group_list_async())

	return ((trigger, ensure_future_update_all_group_members),)

#匹配
def match(self, cmd):
	if self.setting['clan_battle_mode'] != 'web':
		return 0
	if len(cmd) < 2:
		return 0
	return Commands.get(cmd[0:2], 0)


#执行
def execute(self, match_num, ctx):
	if ctx['message_type'] != 'group': return None
	cmd = ctx['raw_message']
	group_id = ctx['group_id']
	user_id = ctx['user_id']
	# 代理群转换
	sender_group_id = group_id	# 发指令的群
	group_id = self.get_group_principal(sender_group_id) # 公会群
	url = urljoin(
		self.setting['public_address'],
		'{}clan/{}/'.format(self.setting['public_basepath'],
		group_id))

	if match_num == 1:  # 创建
		match = re.match(r'^创建(?:([日台韩国])服)?[公工行]会$', cmd)
		if not match: return
		game_server = Server.get(match.group(1), 'cn')
		try:
			self.create_group(group_id, game_server)
		except ClanBattleError as e:
			_logger.info('群聊 失败 {} {} {}'.format(user_id, group_id, cmd))
			return str(e)
		_logger.info('群聊 成功 {} {} {}'.format(user_id, group_id, cmd))
		from pathlib import Path
		import configparser
		inipath = Path(os.path.dirname(__file__)).parents[2] / 'yobot_data' / 'groups.ini'
		config=configparser.RawConfigParser()
		config.read(str(inipath))
		config.set('GROUPS', str(ctx['group_id']), str(ctx['self_id']))
		with open(str(inipath),'w') as f:
			config.write(f)
		return ('公会创建成功，请登录后台查看，公会战成员请发送“加入公会”，'
				'或管理员发送“加入全部成员”'
				'如果无法正常使用网页催刀功能，请发送“手动添加群记录”')


	elif match_num == 2:  # 加入
		if cmd == '加入全部成员':
			if ctx['sender']['role'] == 'member':
				return '只有管理员才可以加入全部成员'
			_logger.info('群聊 成功 {} {} {}'.format(user_id, group_id, cmd))
			asyncio.ensure_future(self._update_all_group_members_async(group_id))
			return '本群所有成员已添加记录'
		match = re.match(r'^加入[公工行]会 *(?:\[CQ:at,qq=(\d+)\])? *$', cmd)
		if match:
			if match.group(1):
				if ctx['sender']['role'] == 'member':
					return '只有管理员才可以加入其他成员'
				user_id = int(match.group(1))
				nickname = None
			else:
				nickname = (ctx['sender'].get('card') or ctx['sender'].get('nickname'))
			asyncio.ensure_future(self.bind_group(group_id, user_id, nickname))
			_logger.info('群聊 成功 {} {} {}'.format(user_id, group_id, cmd))
			return '{}已加入本公会'.format(atqq(user_id))


	elif match_num == 3:  # 状态
		if cmd != '状态': return
		try: boss_summary = self.boss_status_summary(group_id)
		except ClanBattleError as e: return str(e)
		return boss_summary


	elif match_num == 4:  # 报刀
		# 1: boss_num, 2: damage, 3: unit?, 4: continue?, 5: behalf?, 6: yesterday?
		match = match_patterns((
			# 报刀 [-=]boss_num 伤害[单位] [补偿] @qq [昨日]
			r"^报刀 ?(?:[-=]?([1-5]))? +(\d+)?([Ww万Kk千])? *(补偿|补|b|bc)? *(?:\[CQ:at,qq=(\d+)\])? *(昨[日天])?$",
			# 报刀 [-=]boss_num 伤害[单位] [补偿] @昵称 [昨日]
			r"^报刀 ?(?:[-=]?([1-5]))? +(\d+)?([Ww万Kk千])? *(补偿|补|b|bc)? *(?:@(.+?))? *(昨[日天])?$",
		), cmd)
		if not match:
			return '''报刀帮助：
* 出整刀并击杀一王，发送：尾刀1
* 出补偿刀并击杀二王，发送：尾刀2b
* 出整刀打对三王造成1700万伤害，发送：报刀3 1700w
* 出补偿刀对四王造成250万伤害，发送：报刀4 250w 补

无需区分是第几刀的补偿，只需要区分好整刀和补偿。
伤害可以用具体伤害，也可以用带单位的伤害（支持的单位：wW万）
可以跟 @某人 代为报刀，@ 后面可以是 QQ 或者是昵称
可以跟 昨日 补报昨天的刀
如果报刀错误，可以发送：撤销  来取消前一次报刀。
'''
		unit = {
			'W': 10000,
			'w': 10000,
			'万': 10000,
			'k': 1000,
			'K': 1000,
			'千': 1000,
		}.get(match.group(3), 1)
		boss_num = match.group(1)
		damage = int(match.group(2) or 0) * unit
		is_continue = match.group(4) and True or False
		# behalf = match.group(5) and int(match.group(5))
		# 支持昵称代报刀
		try:
			behalf = self.resolve_behalf(group_id, match.group(5))
		except ClanBattleError as e:
			_logger.info('群聊 失败 {} {} {}'.format(user_id, group_id, cmd))
			return str(e)
		previous_day = bool(match.group(6))
		try:
			boss_status = self.challenge(group_id, user_id, False, damage, behalf, is_continue,
				boss_num = boss_num, previous_day = previous_day)
			# if behalf:
			# 	sender = self._get_nickname_by_qqid(user_id)
			# 	self.behelf_remind(behalf, f'{sender}使用您的账号打出{damage*unit}伤害')
		except ClanBattleError as e:
			_logger.info('群聊 失败 {} {} {}'.format(user_id, group_id, cmd))
			return str(e)
		_logger.info('群聊 成功 {} {} {}'.format(user_id, group_id, cmd))
		return boss_status


	elif match_num == 5:  # 尾刀
		# 1: boss_num, 2: continue?, 3: behalf?, 4: yesterday?
		match = match_patterns((
			# 尾刀 [boss_num] [补偿] @qq [昨日]
			r'^尾刀 ?(?:[-=]?([1-5]))? *(补偿|补|b|bc)? *(?:\[CQ:at,qq=(\d+)\])? *(昨[日天])?$',
			# 尾刀 [boss_num] [补偿] @昵称 [昨日]
			r'^尾刀 ?(?:[-=]?([1-5]))? *(补偿|补|b|bc)? *(?:@(.+?))? *(昨[日天])?$',
		), cmd)
		if not match: 
			return '''报刀帮助：
* 出整刀并击杀一王，发送：尾刀1
* 出补偿刀并击杀二王，发送：尾刀2b
* 出整刀打对三王造成1700万伤害，发送：报刀3 1700w
* 出补偿刀对四王造成250万伤害，发送：报刀4 250w 补

无需区分是第几刀的补偿，只需要区分好整刀和补偿。
伤害可以用具体伤害，也可以用带单位的伤害（支持的单位：wW万）
可以跟 @某人 代为报刀，@ 后面可以是 QQ 或者是昵称
可以跟 昨日 补报昨天的刀
如果报刀错误，可以发送：撤销  来取消前一次报刀。
'''
		#behalf = match.group(3) and int(match.group(3))
		# 支持昵称代报刀
		try:
			behalf = self.resolve_behalf(group_id, match.group(3))
		except ClanBattleError as e:
			_logger.info('群聊 失败 {} {} {}'.format(user_id, group_id, cmd))
			return str(e)
		is_continue = match.group(2) and True or False
		boss_num = match.group(1)

		previous_day = bool(match.group(4))
		try:
			boss_status = self.challenge(group_id, user_id, True, None, behalf, is_continue,
				boss_num = boss_num, previous_day = previous_day)
			# if behalf:
			# 	sender = self._get_nickname_by_qqid(user_id)
			# 	self.behelf_remind(behalf, f'{sender}使用您的账号收了个尾刀')
		except ClanBattleError as e:
			_logger.info('群聊 失败 {} {} {}'.format(user_id, group_id, cmd))
			return str(e)
		_logger.info('群聊 成功 {} {} {}'.format(user_id, group_id, cmd))
		return boss_status

	elif match_num == 6:  # 撤销
		if cmd != '撤销': return
		try:
			boss_status = self.undo(group_id, user_id)
		except ClanBattleError as e:
			_logger.info('群聊 失败 {} {} {}'.format(user_id, group_id, cmd))
			return str(e)
		_logger.info('群聊 成功 {} {} {}'.format(user_id, group_id, cmd))
		return boss_status

	elif match_num == 7:  # 预约
		# 1: boss_num, 2: message?, 3: behalf?
		match = match_patterns((
			# 预约表
			# 预约boos_num [：留言] [@qq]
			r'^预约([1-5]|表) *(?:[:：](.+))? *(?:\[CQ:at,qq=(\d+)\])? *$',
			# 预约boos_num [：留言] [@昵称]
			r'^预约([1-5]|表) *(?:[:：](.+))? *(?:@(.+?))? *$',
		), cmd)
		if not match: return
		msg = match.group(1)
		note = match.group(2) or ''
		#behalf = match.group(3) or None
		try:
			behalf = self.resolve_behalf(group_id, match.group(3))
		except ClanBattleError as e:
			_logger.info('群聊 失败 {} {} {}'.format(user_id, group_id, cmd))
			return str(e)
		if behalf : user_id = int(behalf)
		try:
			back_msg = self.subscribe(group_id, user_id, msg, note)
		except ClanBattleError as e:
			_logger.info('群聊 失败 {} {} {}'.format(user_id, group_id, cmd))
			return str(e)
		_logger.info('群聊 成功 {} {} {}'.format(user_id, group_id, cmd))
		return back_msg

	elif match_num == 8:  # 业绩
		match = re.match(r'^业绩表? *$', cmd)
		if not match: return
		try:
			back_msg = self.score_table(group_id)
		except ClanBattleError as e:
			_logger.info('群聊 失败 {} {} {}'.format(user_id, group_id, cmd))
			return str(e)
		_logger.info('群聊 成功 {} {} {}'.format(user_id, group_id, cmd))
		return back_msg

	elif match_num == 9:  # 出刀记录
		match = re.match(r'^出刀(记录|情况|状况|详情) *$', cmd)
		if not match: return
		try:
			back_msg = self.challenge_record(group_id)
		except ClanBattleError as e:
			_logger.info('群聊 失败 {} {} {}'.format(user_id, group_id, cmd))
			return str(e)
		_logger.info('群聊 成功 {} {} {}'.format(user_id, group_id, cmd))
		return back_msg

	elif match_num == 11:  # 挂树
		# 1: message?, 2: behalf?
		match = match_patterns((
			# 挂树[：留言] [@qq]
			r'^挂树 *(?:[\:：](.*))? *(?:\[CQ:at,qq=(\d+)\])? *$',
			# 挂树[：留言] [@昵称]
			r'^预约([1-5]|表) *(?:[:：](.+))? *(?:@(.+?))? *$',
		), cmd)
		if not match: return
		extra_msg = match.group(1)
		#behalf = match.group(2) and int(match.group(2))
		# 支持昵称代挂树
		try:
			behalf = self.resolve_behalf(group_id, match.group(2))
		except ClanBattleError as e:
			_logger.info('群聊 失败 {} {} {}'.format(user_id, group_id, cmd))
			return str(e)
		behalf = behalf or user_id
		if isinstance(extra_msg, str):
			extra_msg = extra_msg.strip()
			if not extra_msg: extra_msg = None
		try:
			msg = self.put_on_the_tree(group_id, behalf, extra_msg)
			# if behalf:
			# 	sender = self._get_nickname_by_qqid(user_id)
			# 	self.behelf_remind(behalf, f'您的号被{sender}挂树上了。')
		except ClanBattleError as e:
			_logger.info('群聊 失败 {} {} {}'.format(user_id, group_id, cmd))
			return str(e)
		_logger.info('群聊 成功 {} {} {}'.format(user_id, group_id, cmd))
		return msg

	elif match_num == 12:  # 申请
		# 1: (blank), 2: boss_num, 3: continue?,  4: behalf?
		match = match_patterns((
			# 进(1-5) [补] [@qq]
			# 申请出刀(1-5) [补]  [@qq]
			r'^(?:进|申请出刀)(| )([1-5]) *(补偿|补|b|bc)? *(?:\[CQ:at,qq=(\d+)\])? *$',
			# 挂树[：留言] [@昵称]
			r'^(?:进|申请出刀)(| )([1-5]) *(补偿|补|b|bc)? *(?:@(.+?))? *$',
		), cmd)
		if not match: return '申请出刀格式错误惹(っ °Д °;)っ\n如：申请出刀1 or 进1 or 申请出刀1补偿@xxx or 进1补偿@xxx'
		boss_num = match.group(2)
		is_continue = match.group(3) and True or False
		#behalf = match.group(4) and int(match.group(4))
		# 支持昵称代进刀
		try:
			behalf = self.resolve_behalf(group_id, match.group(4))
		except ClanBattleError as e:
			_logger.info('群聊 失败 {} {} {}'.format(user_id, group_id, cmd))
			return str(e)
		try:
			boss_info = self.apply_for_challenge(is_continue, group_id, user_id, boss_num, behalf)
			# if behalf:
			# 	sender = self._get_nickname_by_qqid(user_id)
			# 	self.behelf_remind(behalf, f'{sender}正在帮您代刀，请注意不要登录您的账号。')
		except ClanBattleError as e:
			_logger.info('群聊 失败 {} {} {}'.format(user_id, group_id, cmd))
			return str(e)
		_logger.info('群聊 成功 {} {} {}'.format(user_id, group_id, cmd))
		return boss_info

	elif match_num == 13:  # 取消
		# 1: boss_num or type, 2: boss_num?, 3: behalf?
		match = match_patterns((
			r'^取消 *(挂树|申请出刀|申请|出刀|出刀all|报伤害|sl|SL|预约) *([1-5])? *(?:\[CQ:at,qq=(\d+)\])? *$',
			r'^取消 *(挂树|申请出刀|申请|出刀|出刀all|报伤害|sl|SL|预约) *([1-5])? *(?:@(.+?))? *$',
		), cmd)
		if not match: return
		b = match.group(1)
		boss_num = match.group(2) and match.group(2)
		#behalf = match.group(3) and int(match.group(3))
		# 支持昵称代取消
		try:
			behalf = self.resolve_behalf(group_id, match.group(3))
		except ClanBattleError as e:
			_logger.info('群聊 失败 {} {} {}'.format(user_id, group_id, cmd))
			return str(e)
		if behalf:
			user_id = behalf
		try:
			if b == '挂树':
				msg = self.take_it_of_the_tree(group_id, user_id)
			elif b == '出刀' or b == '申请' or b == '申请出刀':
				msg =  self.cancel_blade(group_id, user_id)
			elif b == '出刀all':
				msg =  self.cancel_blade(group_id, user_id, cancel_type=0)
			elif b == '报伤害':
				msg =  self.report_hurt(0, 0, group_id, user_id, 1)
			elif b == 'sl' or b == 'SL':
				msg =  self.save_slot(group_id, user_id, clean_flag = True)
			elif b == '预约':
				msg = self.subscribe_cancel(group_id, boss_num, user_id)
			else:
				raise InputError("未能识别命令：{}。可能的命令：取消挂树/取消预约/取消申请/取消SL 等".format(b))
		except ClanBattleError as e:
			_logger.info('群聊 失败 {} {} {}'.format(user_id, group_id, cmd))
			return str(e)
		_logger.info('群聊 成功 {} {} {}'.format(user_id, group_id, cmd))
		return msg

	elif match_num == 15:  # 面板
		if len(cmd) != 2: return
		return f'公会战面板：\n{url}\n建议添加到浏览器收藏夹或桌面快捷方式'

	elif match_num == 16:  # SL
		# 1: chekc?, 2: behalf?
		match = match_patterns((
			r'^查?(?:SL|sl) *([\?？])? *(?:\[CQ:at,qq=(\d+)\])? *([\?？])? *$',
			r'^查?(?:SL|sl) *([\?？])? *(?:@(.+?))? *([\?？])? *$',
		), cmd)
		if not match: return
		#behalf = match.group(2) and int(match.group(2))
		# 支持昵称代SL
		try:
			behalf = self.resolve_behalf(group_id, match.group(2))
		except ClanBattleError as e:
			_logger.info('群聊 失败 {} {} {}'.format(user_id, group_id, cmd))
			return str(e)
		only_check = bool(match.group(1) or match.group(3))
		if behalf: user_id = behalf
		# if not self.check_blade(group_id, user_id) and not only_check:
		# 	return '你都没申请出刀，S啥子L啊 (╯‵□′)╯︵┻━┻'
		if only_check:
			sl_ed = self.save_slot(group_id, user_id, only_check=True)
			if sl_ed: return '今日已使用SL'
			else: return '今日未使用SL'
		else:
			back_msg = ''
			try: back_msg = self.save_slot(group_id, user_id)
			except ClanBattleError as e:
				_logger.info('群聊 失败 {} {} {}'.format(user_id, group_id, cmd))
				return str(e)
			_logger.info('群聊 成功 {} {} {}'.format(user_id, group_id, cmd))
			return back_msg

	elif match_num == 17:  # 报伤害
		match = re.match(r'^报伤害(?:剩| |)(?:(\d+(?:s|S|秒))?(?:打了| |)(\d+)(?:w|W|万))? *(?:\[CQ:at,qq=(\d+)\])? *$', cmd)
		if not match: return '格式出错(O×O)，如“报伤害 2s200w”或“报伤害 3s300w@xxx”'
		s = match.group(1) or 1
		if s != 1: s = re.sub(r'([a-z]|[A-Z]|秒)', '', s)
		hurt = match.group(2) and int(match.group(2))
		behalf = match.group(3) and int(match.group(3))
		if behalf: user_id = behalf
		if not self.check_blade(group_id, user_id):
			return '你都没申请出刀，报啥子伤害啊 (╯‵□′)╯︵┻━┻'
		return self.report_hurt(int(s), hurt, group_id, user_id)

	#TODO 权限申请封装func调用
	elif match_num == 18:  #权限，设置意外无权限用户有权限
		match = re.match(r'^更改权限 *(?:\[CQ:at,qq=(\d+)\])? *$', cmd)
		if match:
			if match.group(1):
				if ctx['sender']['role'] == 'member':
					return '只有管理员才可以申请权限'
				user_id = int(match.group(1))
				nickname = None
			else:
				nickname = (ctx['sender'].get('card') or ctx['sender'].get('nickname'))
			user = User.get_or_create(qqid=user_id)[0]
			membership = Clan_member.get_or_create(group_id = group_id, qqid = user_id)[0]
			user.nickname = nickname
			user.clan_group_id = group_id
			if user.authority_group >= 10:
				user.authority_group = (100 if ctx['sender']['role'] == 'member' else 10)
				membership.role = user.authority_group
			user.save()
			membership.save()
			_logger.info('群聊 成功 {} {} {}'.format(user_id, group_id, cmd))
			return '{}已成功申请权限'.format(atqq(user_id))

	elif match_num == 19:  #更改预约模式
	#TODO 19:更改预约模式
		print("完成度0%")

	elif match_num == 20:  #重置进度
		if cmd != "重置进度":
			return
		try:
			if (ctx['sender']['role'] not in ['owner', 'admin']) and (ctx['user_id'] not in self.setting['super-admin']):
				return '只有管理员或主人可使用重置进度功能'
			available_empty_battle_id = self._get_available_empty_battle_id(group_id)
			group = Clan_group.get_or_none(group_id=group_id)
			current_data_slot_record = group.battle_id
			self.switch_data_slot(group_id, available_empty_battle_id)
		except ClanBattleError as e:
			_logger.info('群聊 失败 {} {} {}'.format(user_id, group_id, cmd))
			return str(e)
		_logger.info('群聊 成功 {} {} {}'.format(user_id, group_id, cmd))
		return "进度已重置\n当前档案编号已从 {} 切换为 {}".format(current_data_slot_record, available_empty_battle_id)

	elif match_num == 990: # 催刀
		if ctx['sender']['role'] == 'member':
			return "只有管理员有权限催刀"
		report = self.get_clan_daily_challenge_report(group_id)
		unfinished_members = filter(lambda r: not r.finished, report.values())
		unfinished_members = sorted(unfinished_members, key=lambda m: -m.finished_count)
		unfinished_count = sum(map(lambda m: m.unfinished, unfinished_members))
		unfinished_continue = sum(map(lambda m: m.holds_tailing, unfinished_members))
		if '催刀报告' == cmd:
			if sender_group_id == group_id:
				return f'尚有 {unfinished_count} 完整刀和 {unfinished_continue} 补偿刀未出。请以下 {len(unfinished_members)} 名成员尽快出刀：\n' + '\n'.join([f'{member.atqq()} {member.status}' for member in unfinished_members])
			else:
				return '请以下成员尽快出刀：\n' + '\n'.join([f'{member.nickname}: {member.status}' for member in unfinished_members])
		elif cmd in ('催刀私聊', '催刀'):
			member_qq_list = [member.qqid for member in unfinished_members]
			self.send_remind(group_id, member_qq_list, user_id, '催刀私聊' == cmd)
			if '催刀私聊' == cmd:
				return f'已私信 {len(member_qq_list)} 人进行催刀'
		else:
			return
		_logger.info('群聊 成功 {} {} {}'.format(user_id, group_id, cmd))

	elif match_num == 970: #代理群设置
		if ctx['sender']['role'] == 'member':
			return
		if '代理帮助' == cmd:
			return '管理员设置本群（管理员小群等）代理公会群：\n代理 公会群号\n或者由下面命令取消代理其他公会：\n代理取消'
		match = re.match(r'^代理(取消)?\s+(\d+)\s*$', cmd)
		if not match:
			return
		is_cancel = match.group(1)
		if is_cancel:
			self.bind_group_principal(sender_group_id, Groupid(0))
			_logger.info('群聊 成功 {} {} {}'.format(user_id, sender_group_id, cmd))
			return '已取消对代理'
		else:
			principal_group_id = match.group(2)
			if not principal_group_id:
				return '请输入要代理的群号'
			principal_group_id = Groupid(int(principal_group_id))
			self.bind_group_principal(sender_group_id, principal_group_id)
			_logger.info('群聊 成功 {} {} {}'.format(user_id, sender_group_id, cmd))
			return '本群已设置为代理 {} 群'.format(principal_group_id)

	elif match_num == 980: #小号设置
		if ctx['sender']['role'] == 'member':
			return
		if '小号帮助' == cmd:
			return '管理员可以添加/删除小号：\n小号添加/删除 昵称 号主QQ\n- 或者 -\n小号添加/删除 昵称 号主QQ @号主'
		# 1: add/remove, 2: nickname, 3: owner
		match = match_patterns((
			r'^小号(添加|删除)\s+(.+?)\s*\[CQ:at,qq=(\d+)\]\s*$',
			r'^小号(添加|删除)\s+(.+?)\s+(\d+)\s*$',
			r'^小号(添加|删除)\s+(.+?)\s+@(.+?)\s*$',
		), cmd)
		if not match: return f'错误的格式：『{cmd}』'
		shadow_action = match.group(1)
		shadow_user_name = match.group(2)
		try:
			owner_user_id = self.resolve_behalf(group_id, match.group(3))
			if not owner_user_id:
				return f'无法找到： {shadow_user_name} 的大号 {match.group(3)}。他是否已经已经加入工会？'
			if '添加' == shadow_action:
				asyncio.ensure_future(self.bind_group_for_shadow(group_id, owner_user_id, shadow_user_name))
				_logger.info('群聊 成功 {} {} {}'.format(user_id, group_id, cmd))
				return '已设置小号 {}(号主：{})'.format(shadow_user_name, atqq(owner_user_id))
			elif '删除' == shadow_action:
				asyncio.ensure_future(self.unbind_group_for_shadow(group_id, owner_user_id, shadow_user_name))
				_logger.info('群聊 成功 {} {} {}'.format(user_id, group_id, cmd))
				return '已删除小号 {}(号主：{}) 群'.format(shadow_user_name, atqq(owner_user_id))
			else:
				return f'指令：{shadow_action} 不正确'
		except ClanBattleError as e:
			_logger.warning('群聊 失败 {} {} {}'.format(user_id, group_id, cmd))
			return str(e)
		except Exception as e:
			_logger.warning('群聊 失败 {} {} {}'.format(user_id, group_id, cmd), exc_info=1)
			return str(e)
