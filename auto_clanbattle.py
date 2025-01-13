import asyncio
import os
import re
import time
import base64
import random
import datetime
import aiocqhttp

from io import BytesIO
from hoshino import aiorequests as requests
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from hoshino.typing import CQEvent, HoshinoBot
from typing import Dict
from hoshino.modules.priconne import _pcr_data, chara
from hoshino.typing import MessageSegment
from hoshino import priv, R, util, log, config, Service
import numpy as np
from collections import Counter

try:	#怡宝的pcr账号管理模块，可以和怡宝的清日常插件用同一个
	from ..autopcr.query import query
except:
	from .query import query

from json import load, dump, loads
from nonebot import get_bot, on_command
from os.path import dirname, join, exists
from .secret import Secret


help_msg = '''需先完成以下操作才可用：
1、添加机器人为好友；
2、私聊机器人发送 [clan 群号 pcr账号 pcr密码] ，根据提示完成验证。验证成功后可在群内开启自动报刀
[初始化会战推送]: 会战前一天发送该命令，不发也可以
[切换会战推送]: 开启/关闭会战自动报刀推送
[开启会战推送]: 开启会战自动报刀推送
[关闭会战推送]: 关闭会战自动报刀推送
[出刀监控状态]: 查看当前群的自动报刀状态
[会战状态]: 当前所有boss血量和成员出刀情况（一图流）
[切换账号 账号编号]: 可私聊机器人发送多个pcr账号，当需要上其中一个号时可切换另一个账号，使自动报刀不会停止
[删除监控账号 账号编号]: 删除绑定的pcr账号，后续不能用该账号进行监控
[会战预约(1/2/3/4/5)]: 预约提醒
[预约表/会战表]: 查看所有预约
[清空预约表]: (仅管理员可用)
[抓人]: 栞栞谁今天没有出刀
[出刀时段统计]: 查看公会内出刀的时间范围
[查档线]: 若参数为空，则输出10000名内各档档线；若有多个参数，请使用英文逗号隔开。新增按照关键词查档线。结算期间数据为空
[sl + pcr名字]:为玩家打上SL标记
[更新boss数据]:仅超级管理员可用，更新boss头像和各种数据'''

sv = Service('自动报刀', enable_on_default = False, help_ = help_msg, bundle = 'pcr查询')
logger = log.new_logger(__name__, config.DEBUG)

current_folder = dirname(__file__)
img_folder = join(current_folder, 'img')
font_file = join(img_folder, 'pcrcnfont.ttf')

cqbot = get_bot()
secret = Secret()
event_cache = {}
chat_list = {}

setting = join(current_folder, 'setting.json')
def save_setting(dic):
	with open(setting, 'w', encoding="utf-8") as fp: dump(dic, fp, indent=4, ensure_ascii=False)
def get_setting() -> dict:
	dic = {}
	if exists(setting):
		try:
			with open(setting, "r", encoding="utf-8") as fp: dic = load(fp)
		except:
			with open(setting, "r", encoding="gb2312") as fp: dic = load(fp)
	return dic


boss_icon_list = get_setting()['boss_icon_list']	#boss头像列表
health_list = get_setting()['health_list']			#boss血量列表
phase = get_setting()['phase']						#阶段周目
side = get_setting()['side']						#阶段数
RANK_LIST = get_setting()['rank_list']				#查档线等待修改和上传图片
max_chat_list = get_setting()['max_chat_list']		#最多记录多少条留言
loop_interval = get_setting()['loop_interval']		#循环检测间隔

def get_new_account_number(account_list):
	if not account_list or len(account_list) == 0:
		return 0
	num_list = []
	for _, account_info in account_list.items():
		num_ = 'num' in account_info and account_info['num']
		num_list.append(num_)
	for num in range(30):
		if num not in num_list:
			return num

@sv.on_prefix(("clan"))
# clan <群号> <pcr账号> <密码>
async def upload_account(bot: HoshinoBot, ev: CQEvent):
	await bot.finish(ev, f"请加好友私聊使用，或使用#clan在群里上传账号密码")
@cqbot.on_message
async def upload_account(context):
	if context["message_type"] != 'private':return
	msg:list = context["raw_message"].split(' ')
	if msg[0] != 'clan': return
	msg.pop(0)
	await upload_account_all(cqbot, context, msg, True)

@sv.on_prefix(("#clan"))
async def upload_account_all(bot: HoshinoBot, ev: CQEvent, p_msg = None, is_private = False):
	if is_private: msg = p_msg
	else: msg = ev.message.extract_plain_text().strip().split()

	if len(msg) not in [2, 3]:
		return await bot.send(ev, "请输入\nclan 群号 pcr账号 pcr密码\n中间用空格分隔。如在群内使用不需要加上群号")
	group_id = ev.group_id and str(ev.group_id) or msg[0]
	try:
		group_info = await bot.get_group_info(group_id = group_id, self_id = ev.self_id)
	except aiocqhttp.exceptions.ActionFailed as e:
		return await bot.send(ev, e.result['message'])
	except Exception as e:
		return await bot.send(ev, "群号检测失败，请检查群号后重试")
	if group_info['member_count'] < 1:
		return await bot.send(ev, "该bot不在此群中，请检查群号是否有误")

	group_info = secret.get_sec(group_id)
	if not group_info:
		group_info = {
			'account_list':{},
			'now_monitor_account':'',		#现在正在监控出刀的账号
			'monitor_flag':0,				#监控状态，0为未开启监控
			'coin':0,						#会战币
			'renew_coin':0,					#会战币
			'tvid': 0,						#玩家id
			'pre_push':[[],[],[],[],[]],	#预约表
			'boss_status':[0,0,0,0,0],		#boss状态表
			'arrow':0,						#出刀id
			'in_game':[0,0,0,0,0],			#90s实战中人数
			'in_game_old':[0,0,0,0,0],		#实战中总人数
			'in_game_calc_mode':0,			#实战中显示模式，0为显示90秒内的，1为显示进入且报刀后的
			'text_mode':0,					#状态显示是否为文字模式，0为图片，1为文字
			'bot_qqid':ev.self_id,			#机器人自己的qq号
			'group_id':group_id,			#群号
			'execute_flag':False			#正在执行查询
		}
	account_list = group_info['account_list']
	if len(account_list) >= 30 : return await bot.send(ev, "超过最大可录入账号数量")

	for i in range(len(msg)):
		msg[i] = msg[i].replace('"', '')
		if msg[i][0] == '<' and msg[i][-1] == '>':
			msg[i] = msg[i][1:-1]

	account = ev.group_id and msg[0] or msg[1]
	password = ev.group_id and msg[1] or msg[2]
	qq_id = str(ev.user_id)
	st = "更新"
	if account not in account_list:
		num = get_new_account_number(account_list)
		account_list[account] = {
			'account':account,
			'password':password,
			'qqid':qq_id,
			'num': num
		}
		st = "获取"
	else:
		account_list[account]['password'] = password

	account_info = account_list[account]
	account_info["update_time"] = str(datetime.datetime.now())
	account_info["status"] = "1"

	try:
		accountInfo = {"account": account, "password": password, "access_key": '', "uid": '', "qqid": int(qq_id)}
		await clean_login(account_info, accountInfo)
		group_info['tvid'] = await query.get_pcrid(accountInfo)
		group_info['coin'] = await query.get_item_stock(accountInfo, 90006)
		group_info['now_monitor_account'] = account
		await bot.send(ev, f'{qq_id}的记录已{st}并校验通过\naccount={account}\npcrname={account_info["pcrname"]}\npcrid={account_info["pcrid"]}')
	except Exception as e:
		account_info["status"] = "2"
		await bot.send(ev, f'{qq_id}的记录已{st}\naccount={account}\n账号密码检验不通过：{e}，已置为错误。')
	secret.add_group_info(group_id, group_info)

async def clean_login(account_info, accountInfo):
    access_key, uid = await query.VerifyAccount(accountInfo, clean_cache = True)
    account_info["access_key"] = access_key
    account_info["uid"] = uid
    account_info["pcrname"] = await query.get_username(accountInfo)
    account_info["pcrid"] = await query.get_pcrid(accountInfo)

async def _account_verify(bot: HoshinoBot, ev: CQEvent, group_id, ret = 0):
	out_put = ""
	group_info = secret.get_sec(group_id)
	if not group_info: return bot.send('当前群未绑定账号，请发送私聊机器人发送 [clan 群号 pcr账号 pcr密码]')

	try:
		access_key, uid = '', ''
		now_monitor_account = group_info['now_monitor_account']
		if now_monitor_account == '' : raise f"当前群({group_id})未添加账号，请先加机器人好友私聊发 `clan 群号 pcr账号 密码` 以绑定账号"
		account_info = group_info['account_list'][now_monitor_account]
		if "access_key" in account_info: access_key = account_info["access_key"]
		if "uid" in account_info: uid = account_info["uid"]
		accountInfo = {"account": account_info["account"], "password": account_info["password"], "access_key":access_key, "uid":uid, "qqid": int(account_info['qqid'])}
		await query.VerifyAccount(accountInfo, b_check = False)
		account_info["update_time"] = str(datetime.datetime.now())
		account_info["status"] = "1"
		if ret == 0:pass
			# await bot.send(ev, f'pcrname = {account_info["pcrname"]} pcrid={account_info["pcrid"]} 验证通过')
		else: out_put = f'pcrname = {account_info["pcrname"]} pcrid={account_info["pcrid"]} 验证通过'
	except Exception as e:
		try:
			accountInfo = {"account": account_info["account"], "password": account_info["password"], "access_key": '', "uid": '', "qqid": ev.user_id}
			await clean_login(account_info, accountInfo)
		except Exception as e:
			if ret == 2:
				raise RuntimeError(f'群 {group_id} 的pcr账号 {account_info["account"]} 验证失败: {e}')
			elif ret == 0:
				await bot.send(ev, f'群 {group_id} 的pcr账号 {account_info["account"]} 验证失败: {e}')
			else:
				out_put = f'群 {group_id} 的pcr账号 {account_info["account"]} 验证失败: {e}'

	return out_put


async def verify(bot:HoshinoBot = None, ev:CQEvent = None, check_login = False):
	group_id = ev.group_id
	group_info = secret.get_sec(group_id)
	if not group_info: 
		await bot.send(ev, f"当前群({group_id})未添加账号，请先加机器人好友私聊发 `clan 群号 pcr账号 密码` 以绑定账号")
		raise f'当前群({group_id})未添加账号，请先加机器人好友私聊发 `clan 群号 pcr账号 密码` 以绑定账号'
	if check_login:
		await _account_verify(bot, ev, group_id)


@sv.on_fullmatch('更新boss数据')
async def init_monitor(bot:HoshinoBot, ev:CQEvent):
	if not priv.check_priv(ev, priv.SUPERUSER):
		return await bot.send(ev,'权限不足，当前指令仅超级管理员可用!如发现头像不对请通知机器人管理员')
	global boss_icon_list, health_list, phase, side
	setting_dic = get_setting()
	url = 'https://pcr.satroki.tech/api/Quest/GetClanBattleInfos?s=cn'
	base = 'https://redive.estertion.win/icon/unit/'
	date = datetime.date.today()
	d_year = date.year
	d_month = date.month
	title = None
	try:
		res = await requests.get(url)
		content = res.raw_response.content.decode()
		infos = loads(content)
		for info in infos:
			if info["year"] == d_year and info["month"] == d_month:
				boss_icon_list, health_list, phase, side, title = [], [], {}, {}, info["title"]
				boss_phase = info["phases"][0]["bosses"]
				for bp in boss_phase: boss_icon_list.append(bp["unitId"])
				stage = 0
				for stage_info in info["phases"]:
					health_list.append([])
					phase[stage_info['lapFrom']] = stage + 1
					side[stage_info['lapFrom']] = chr(65 + stage)
					for boss_info in stage_info["bosses"]:
						health_list[stage].append(boss_info['hp'])
					stage += 1
				break
		for i in boss_icon_list:
			if not exists(current_folder + '/img' + f'/{i}.png'):
				res = await requests.get(base + str(i) + '.webp')
				res = res.raw_response
				with open(current_folder + '/img' + f'/{i}.png', 'wb') as img:
					img.write(res.content)
		setting_dic['boss_icon_list'], setting_dic['health_list'], setting_dic['phase'], setting_dic['side'] = boss_icon_list, health_list, phase, side
		save_setting(setting_dic)
	except Exception as e:
		logger.exception(str(e))
		return await bot.send(ev, f'获取当期BOSS数据失败，请重试')
	await bot.send(ev, f'更新完成，当期会战为 {title}')


@sv.scheduled_job('interval', seconds=loop_interval)
async def monitor_loop():
	try:
		tasks = []
		for group_id, group_info in secret.get_group_infos().items():
			if group_info['monitor_flag'] == 0 : continue	#跳过不开启出刀监控或正在执行的群
			tasks.append(monitor_task(group_id))
		if len(tasks) > 0: await asyncio.gather(*tasks)
	except Exception as e:
		logger.exception(e)

async def monitor_task(group_id):
	group_info = secret.get_sec(group_id)
	group_info['execute_flag'] = True

	try:
		now_monitor_account = group_info['now_monitor_account']			#当前监控的账号
		account_info = group_info['account_list'][now_monitor_account]	#当前监控的账号信息

		load_index = await query.get_load_index(account_info)			#获取玩家数据
		group_info['tvid'] = await query.get_pcrid(account_info)		#更新正在监控的玩家id
		if group_info['coin'] == 0 or group_info['renew_coin'] > 0:		#初始化获取硬币数/检测到boss状态发生变化后更新会战币
			group_info['coin'] = await query.get_item_stock(account_info, 90006)	#获取会战币

		msg, clan_battle_info, clan_info = [], 0, 0
		while(True):
			try:
				clan_info = await query.get_clan_info(account_info)
				clan_id = clan_info['clan']['detail']['clan_id']
				clan_battle_info = await query.get_clan_battle_info(account_info, clan_id)
				if group_info['renew_coin'] > 0: group_info['renew_coin'] -= 1
				break
			except Exception as e:
				if ('连接中断' or '发生了错误(E)') in str(e):
					msg = f'发生错误：{str(e)}\n账号 {load_index["user_info"]["user_name"]} 可能被顶号，已自动关闭推送。如需上号请`切换账号`或`切换会战推送`'
					if group_id in event_cache: return await cqbot.send(event_cache[group_id], msg)
					else: await cqbot.send_group_msg(group_id = int(group_id), self_id = group_info['bot_qqid'], message = msg)
					group_info['monitor_flag'] = 0
					group_info['execute_flag'] = False
					return
				load_index = await query.get_load_index(account_info)    #击败BOSS时会战币会变动
				group_info['coin'] = await query.get_item_stock(account_info, 90006)

		#判定是否处于会战期间
		is_interval = load_index['clan_battle']['is_interval']
		if is_interval == 1:
			mode_change_open = load_index['clan_battle']['mode_change_limit_start_time']
			mode_change_open = time.strftime("%Y-%m-%d %H:%M:%S",time.localtime(mode_change_open))
			mode_change_limit = load_index['clan_battle']['mode_change_limit_time']
			mode_change_limit = time.strftime("%Y-%m-%d %H:%M:%S",time.localtime(mode_change_limit))
			msg = f'当前会战未开放，请在会战前一天发送 初始化会战推送\n会战模式可切换时间{mode_change_open}-{mode_change_limit}'
			group_info['monitor_flag'] = 0
			group_info['execute_flag'] = False
			if group_id in event_cache: return await cqbot.send(event_cache[group_id], msg)
			else: return await cqbot.send_group_msg(group_id = int(group_id), self_id = group_info['bot_qqid'], message = msg)

		#判断各BOSS圈数并获取预约表推送
		boss_num = 0
		boss_hp_msg = ['剩余血量：']
		for boss_info in clan_battle_info['boss_info']:
			lap_num = boss_info['lap_num']
			max_hp = boss_info['max_hp']
			current_hp = boss_info['current_hp']
			hp_percent = '{:.2f}'.format(current_hp/max_hp*100)
			boss_hp_msg.append(f'{lap_num}周目{boss_num+1}王：{current_hp}/{max_hp}({hp_percent}%)')
			if lap_num != group_info['boss_status'][boss_num]:
				group_info['boss_status'][boss_num] = lap_num
				push_list = group_info['pre_push'][boss_num]
				if len(push_list) > 0:     #预约后群内和行会内提醒
					at_msg = []
					for qqid in push_list:
						at_msg.append(f'提醒：已到{lap_num}周目 {boss_num+1} 王！\n[CQ:at,qq={qqid}]')
					if group_id in event_cache: await cqbot.send(event_cache[group_id], '\n'.join(at_msg))
					else: await cqbot.send_group_msg(group_id = int(group_id), self_id = group_info['bot_qqid'], message = at_msg)
					group_info['pre_push'][boss_num] = []
			boss_num += 1

		#获取出刀记录并推送最新的出刀
		history = reversed(clan_battle_info['damage_history'])   #从返回的出刀记录刀的状态
		clan_id = clan_info['clan']['detail']['clan_id']

		if group_info['arrow'] == 0:
			output_file = os.path.join(current_folder, 'output', f'{group_id}.txt')
			if not exists(output_file):open(output_file, 'w')
			with open(output_file, encoding='utf-8') as file:
				for line in file:
					if line == '':continue
					line = line.split(',')
					if line[0] != 'SL': group_info['arrow'] = int(line[4])
		clan_battle_id = clan_battle_info['clan_battle_id']
		in_battle = []
		for hst in history:
			# logger.info(f"history_id = {hst['history_id']}, arrow = {group_info['arrow']}")
			if ((group_info['arrow'] != 0) and (int(hst['history_id']) > int(group_info['arrow']))) or (group_info['arrow'] == 0):   #记录刀ID防止重复
				name = hst['name']					#名字
				vid = hst['viewer_id']				#13位ID
				kill = hst['kill']					#是否击杀
				damage = hst['damage']				#伤害
				lap = hst['lap_num']				#圈数
				boss = int(hst['order_num'])		#几号boss
				ctime = hst['create_time']			#出刀时间
				real_time = time.localtime(ctime)
				day = real_time[2]
				hour = real_time[3]
				min = real_time[4]
				seconds = real_time[5]
				arrow = hst['history_id']			#记录指针
				enemy_id = hst['enemy_id']			#BOSS_ID，暂时没找到用处
				is_auto = hst['is_auto']
				if is_auto == 1: is_auto_r = '自动刀'
				else: is_auto_r = '手动刀'

				if_kill = ''
				if kill == 1:
					if_kill = '并击破'
					group_info['in_game_old'][boss-1] = 0
					group_info['renew_coin'] = 2	#第二次获取时顺带刷新会战币数量

				for st in phase:
					if lap >= int(st): phases = st
				phases = phase[phases]
				timeline = await query.query(account_info, '/clan_battle/battle_log_list', {'clan_battle_id': clan_battle_id, 'order_num': boss, 'phases': [phases], 'report_types': [1], 'hide_same_units': 0, 'favorite_ids': [], 'sort_type': 3, 'page': 1})
				timeline_list = timeline['battle_list']
				start_time, used_time = 0, 0
				for tl in timeline_list:
					if tl['battle_end_time'] == ctime:
						battle_log_id = tl['battle_log_id']
						group_info['tvid'] = tl['target_viewer_id']
						timeline_report = await query.query(account_info, '/clan_battle/timeline_report', {'target_viewer_id': group_info['tvid'], 'clan_battle_id': clan_battle_id, 'battle_log_id': int(battle_log_id)})
						start_time = timeline_report['start_remain_time']
						used_time = timeline_report['battle_time']
						break
				if start_time == 90:
					battle_type = f'初始刀{used_time}s'
				else:
					battle_type = f'补偿刀{used_time}s'
				for st in side:
					if lap >= int(st): cur_side = st
				cur_side = side[cur_side]
				msg.append(f'[{cur_side}-{battle_type}]{name} 对 {lap} 周目 {boss} 王造成了 {damage} 伤害{if_kill}({is_auto_r})')
				in_battle.append([boss, kill])
				output = f'{day},{hour},{min},{seconds},{arrow},{name},{vid},{lap},{boss},{damage},{kill},{enemy_id},{clan_battle_id},{is_auto},{start_time},{used_time},'  #记录出刀，后面要用
				with open(current_folder + "/output" + f'/{group_id}.txt', 'a+', encoding='utf-8') as file: file.write(str(output)+'\n')
				group_info['arrow'] = arrow

		#记录实战人数变动并推送
		change = False
		for num in range(0,5):
			boss_info2 = await query.query(account_info, '/clan_battle/boss_info', {
				'clan_id': clan_id,
				'clan_battle_id': clan_battle_id,
				'lap_num': group_info['boss_status'][num],
				'order_num': num+1
			})
			fighter_num = boss_info2['fighter_num']
			if group_info['in_game'][num] != fighter_num:
				if fighter_num > group_info['in_game'][num]:
					diff = fighter_num - group_info['in_game'][num]
					group_info['in_game_old'][num] += diff
				group_info['in_game'][num] = fighter_num
				change = True
			if in_battle != []:
				change = True
				for ib in in_battle:
					if group_info['in_game_old'][ib[0]-1] > 0:
						group_info['in_game_old'][ib[0]-1] -= 1
					if ib[1] == 1:
						group_info['in_game_old'][ib[0]-1] = 0

		push_hp = True
		if change == True:
			group_info['renew_coin'] = 15
			if group_info['in_game_calc_mode'] == 1:
				msg.append(f"当前实战人数发生变化:\n[{group_info['in_game_old'][0]}][{group_info['in_game_old'][1]}][{group_info['in_game_old'][2]}][{group_info['in_game_old'][3]}][{group_info['in_game_old'][4]}]")
			else:
				msg.append(f"当前90s内实战人数发生变化:\n[{group_info['in_game'][0]}][{group_info['in_game'][1]}][{group_info['in_game'][2]}][{group_info['in_game'][3]}][{group_info['in_game'][4]}]")
			if len(msg) == 1: push_hp = False

		if len(msg) != 0:
			msg = '\n'.join(msg)
			if len(msg) > 200: msg = '...\n' + msg[-200:]
			if push_hp:
				boss_hp_msg = '\n'.join(boss_hp_msg)
				back_msg = f'{msg}\n{boss_hp_msg}'
			else:
				back_msg = msg
			if group_id in event_cache: await cqbot.send(event_cache[group_id], back_msg)
			else: await cqbot.send_group_msg(group_id = int(group_id), self_id = group_info['bot_qqid'], message = back_msg)
	except Exception as e:
		group_info['monitor_flag'] = 0
		back_msg = f'监控出现错误，已取消监控：{str(e)}'
		if group_id in event_cache: await cqbot.send(event_cache[group_id], back_msg)
		else: await cqbot.send_group_msg(group_id = int(group_id), self_id = group_info['bot_qqid'], message = back_msg)
	group_info['execute_flag'] = False


@sv.on_rex(r'^(切换|开启|打开|关闭)(?:会战|自动报刀)(?:推送|监控)?')
async def switch_monitor(bot:HoshinoBot, ev:CQEvent):
	match = ev['match']
	if not match : return
	if not priv.check_priv(ev, priv.ADMIN): return await bot.send(ev,'权限不足，当前指令仅管理员可用!')
	await verify(bot, ev, True)

	text, flag = match.group(1), -1
	if text and (text == '开启' or text == '打开'): flag = 1
	elif text and text == '关闭': flag = 0

	group_id = ev.group_id
	event_cache[str(group_id)] = ev
	group_info = secret.get_sec(group_id)

	if flag > -1:
		group_info['monitor_flag'] = flag
		await bot.send(ev, f'已{text}会战推送')
	else:
		if group_info['monitor_flag'] == 0:
			group_info['monitor_flag'] = 1
			await bot.send(ev,'已开启会战推送')
		else:
			group_info['monitor_flag'] = 0
			await bot.send(ev, '已关闭会战推送')


@sv.on_fullmatch('更新账号数据')
async def update_account(bot:HoshinoBot, ev:CQEvent):
	infos = secret.get_group_infos()
	for _, group_info in infos.items():
		account_list = group_info["account_list"]
		for _, account_info in account_list.items():
			account_info["num"] = get_new_account_number(account_list)
	await bot.send(ev, '更新成功')


@sv.on_fullmatch('出刀监控状态','报刀监控状态')
async def monitor_statu(bot:HoshinoBot, ev:CQEvent):
	group_id = ev.group_id
	group_info = secret.get_sec(group_id)
	if not group_info: return await bot.send(ev, '当前群未绑定任何账号')
	account_list:Dict = group_info["account_list"]
	msg = ['当前群绑定的报刀账号有：']
	for _, account_info in account_list.items():
		status = account_info["status"]
		text = f'---编号{account_info["num"]}，状态：{"已激活" if status == "1" else "未激活"}'
		if status == "1" and "pcrname" in account_info:
			text += f'，游戏名：{account_info["pcrname"]}'
		msg.append(text)
	if len(msg) == 1: return await bot.send(ev, '当前群未绑定任何账号，无任何状态')
	account = group_info["now_monitor_account"]
	account_name = account_list[account]["pcrname"]
	account_num = account_list[account]["num"]
	msg.append(f'当前监控的账号编号：{account_num}，游戏名：{account_name}')
	msg.append(f'是否开启监控：{"已开启" if group_info["monitor_flag"] else "未开启"}')
	msg.append('已激活状态下的账号可以通过 切换账号 来切换出刀监控')
	msg.append('输入 删除监控账号 + 账号编号 可以删除绑定的账号')
	await bot.send(ev, '\n'.join(msg))


@sv.on_rex(r'^删除监控账号(?: |)([\s\S]*)')
async def delete_account(bot:HoshinoBot, ev:CQEvent):
	match = ev['match']
	if not match : return
	group_id = ev.group_id
	group_info = secret.get_sec(group_id)
	if not group_info: return await bot.send(ev, '当前群未绑定任何账号')
	account_list:Dict = group_info["account_list"]
	num = int(match.group(1))
	for account, account_info in account_list.items():
		if num == account_info['num']:
			msg = ['删除成功']
			account_list.pop(account)
			if account == group_info['now_monitor_account']:
				group_info['now_monitor_account'] = ''
				group_info['monitor_flag'] = 0
				msg.append('删除的账号是当前正在监控的账号，已自动退出出刀监控')
			return await bot.send(ev, '\n'.join(msg))
	await bot.send(ev, '不存在的编号')


@sv.on_rex(r'^切换账号(?: |)([\s\S]*)')
async def switch_account(bot:HoshinoBot, ev:CQEvent):
	match = ev['match']
	if not match : return
	if not priv.check_priv(ev, priv.ADMIN): return await bot.send(ev,'权限不足，当前指令仅管理员可用!')

	await verify(bot, ev)
	group_id = ev.group_id
	group_info = secret.get_sec(group_id)
	account_list = group_info['account_list']
	num = int(match.group(1))
	account_info = None
	account = 0
	for account_, account_info_ in account_list.items():
		if num == account_info_['num']:
			account_info = account_info_
			account = account_
			break
	if not account_info:
		return await bot.send(ev, "该账号不存在，请先加机器人好友私聊发 `clan 群号 pcr账号 密码` 以绑定账号")
	if account_info["status"] != '1':
		return await bot.send(ev, "该账号未验证通过，请先加机器人好友私聊发 `clan 群号 pcr账号 密码` 重新绑定并验证")
	if group_info['now_monitor_account'] == account:
		return await bot.send(ev, "当前正在监控这个账号，不需要切换")
	group_info['now_monitor_account'] = account

	try:
		await verify(bot, ev, True)
		group_info['tvid'] = await query.get_pcrid(account_info)
		group_info['coin'] = await query.get_item_stock(account_info, 90006)
		await bot.send(ev, f'切换成功，当前监控的账号为 {account_info["pcrname"]}')
	except Exception as e:
		await bot.send(ev, f'切换失败，请重试:\n{str(e)}')


@sv.on_fullmatch('初始化会战推送','初始化会战监控','初始化自动报刀')
async def init_monitor(bot:HoshinoBot, ev:CQEvent):
	group_id = ev.group_id
	group_info = secret.get_sec(group_id)
	group_info['arrow'] = 0
	output_file = current_folder + "/output" + f'/{group_id}.txt'
	if exists(output_file): os.remove(output_file)
	await bot.send(ev, '初始化成功')


@sv.on_rex(r'^(会战|取消|)预约([1-5])$')
async def preload(bot:HoshinoBot, ev:CQEvent):
	match = ev['match']
	if not match : return

	await verify(bot, ev)
	group_id = ev.group_id
	group_info = secret.get_sec(group_id)
	if group_info['monitor_flag'] == 0: return await bot.send(ev, '未开启会战推送，不能预约')

	try:
		text = match.group(1)
		boss_num = int(match.group(2))
		qqid = str(ev.user_id)
		push_list = group_info['pre_push'][boss_num-1]
		warn = ''
		if len(push_list) != 0: warn = f'注意：多于1人同时预约了{boss_num}王，请注意出刀情况!'
		if text == '取消':
			if qqid not in push_list: await bot.send(ev, '未预约该boss', at_sender=True)
			else:
				push_list.remove(qqid)
				await bot.send(ev, f'取消预约{boss_num}王成功！', at_sender=True)
		else:
			if qqid not in push_list:
				push_list.append(qqid)
				await bot.send(ev, f'预约{boss_num}王成功!\n{warn}', at_sender=True)
			else: await bot.send(ev, f'你已预约了{boss_num}王！', at_sender=True)
	except Exception as e:
		await bot.send(ev, f'出现错误：\n{str(e)}')


@sv.on_fullmatch('会战表', '预约表')  #预约列表
async def preload_list(bot:HoshinoBot, ev:CQEvent):
	await verify(bot, ev)
	group_id = ev.group_id
	group_info = secret.get_sec(group_id)
	if group_info['monitor_flag'] == 0: return await bot.send(ev, f'未开启会战推送，不能查询{ev.raw_message}')

	boss_num = 0
	msg = []
	for pre_lists in group_info['pre_push']:
		boss_num += 1
		msg.append(f'{boss_num}王预约列表:\n')
		for qqid in pre_lists:
			try:
				info = await bot.get_group_member_info(group_id=group_id, user_id=qqid)
				name = info['card'] or qqid
			except Exception as e: await bot.send(ev, f'出现错误:\n{str(e)}')
			msg.append(f'++{name}')
		msg.append('\n')
	await bot.send(ev, '\n'.join(msg))


@sv.on_fullmatch('清空预约表')
async def clean_preload_list(bot:HoshinoBot, ev:CQEvent):
	if not priv.check_priv(ev, priv.ADMIN): return await bot.send(ev,'权限不足，当前指令仅管理员可用!')
	await verify(bot, ev)

	group_id = ev.group_id
	group_info = secret.get_sec(group_id)
	group_info['pre_push'] = [[],[],[],[],[]]
	await bot.send(ev,'已全部清空')


@sv.on_fullmatch('会战帮助', '自动报刀', '自动报刀帮助')
async def help(bot:HoshinoBot, ev:CQEvent):
	await bot.send(ev, help_msg)


def rounded_rectangle(size, radius, color):     #ChatGPT帮我写的，我也不会
	width, height = size
	rectangle = Image.new("RGBA", size, color)
	corner = Image.new("RGBA", (radius, radius), (0, 0, 0, 0))
	filled_corner = Image.new("RGBA", (radius, radius), (0, 0, 0, 255))
	mask = Image.new("L", (radius, radius), 0)
	mask_draw = ImageDraw.Draw(mask)
	mask_draw.ellipse((0, 0, radius * 2, radius * 2), fill=255)
	corner.paste(filled_corner, (0, 0), mask)
	rectangle.paste(corner, (0, 0))
	rectangle.paste(corner.rotate(90), (0, height - radius))
	rectangle.paste(corner.rotate(180), (width - radius, height - radius))
	rectangle.paste(corner.rotate(270), (width - radius, 0))
	return rectangle


@sv.on_rex(r'^切换(文字|图片)模式$')
async def switch_status_mode(bot:HoshinoBot, ev:CQEvent):
	match = ev['match']
	if not match : return
	group_id = ev.group_id
	group_info = secret.get_sec(group_id)
	group_info['text_mode'] = match.group(1) == '文字' and 1 or 0
	await bot.send(ev,'切换成功')


@sv.on_prefix('会战状态', '状态')    #这个更是重量级
async def status(bot:HoshinoBot, ev:CQEvent):
	await verify(bot, ev)
	await bot.send(ev,'生成中...')
	group_id = ev.group_id
	group_info = secret.get_sec(group_id)
	account_list = group_info['account_list']
	account = group_info['now_monitor_account']
	account_info = account_list[account]

	status = ev.message.extract_plain_text().strip()
	if group_info['monitor_flag'] == 0 and status != '1':
		return await bot.send(ev,'现在会战推送状态为关闭，请确认是否有人上号，如果仍然需要查看状态，请输入 会战状态1 来确认\n（使用 会战状态1 查看状态的话，实战人数不正确）')

	try:
		clan_info = await query.get_clan_info(account_info)
		clan_id = clan_info['clan']['detail']['clan_id']
		battle_info = await query.get_clan_battle_info(account_info, clan_id)
		clan_battle_id = battle_info['clan_battle_id']

		if group_info['text_mode'] == 1:
			msg = ''
			clan_name = battle_info['user_clan']['clan_name']
			rank = battle_info['period_rank']
			lap = battle_info['lap_num']
			msg += f'{clan_name}[{rank}名]--{lap}周目\n※实战人数指90秒内人数\n'
			for boss in battle_info['boss_info']:
				boss_num = boss['order_num']
				boss_lap_num = boss['lap_num']
				mhp = boss['max_hp']
				hp = boss['current_hp']
				hp_percentage = int((hp / mhp)*100)  # 计算血量百分比
				boss_info = await query.query(account_info, '/clan_battle/boss_info', {
					'clan_id': clan_id,
					'clan_battle_id': clan_battle_id,
					'lap_num': boss_lap_num,
					'order_num': boss_num
				})
				fighter_num = boss_info['fighter_num']
				msg += f'{boss_lap_num}周目{boss_num}王 剩余{hp}血({hp_percentage}%)|{fighter_num}人实战\n'
			return await bot.send(ev,msg)


		# for root_, dirs_, files_ in os.walk(img_folder+'/bg'):	#自定义背景图
		#     bg = files_
		# bg_num = random.randint(0, len(bg)-1)
		# img = Image.open(img_folder+'/bg/'+bg[bg_num])
		# img = img.resize((1920,1080),Image.Resampling.LANCZOS)
		ids = list(_pcr_data.CHARA_NAME.keys())					#随机pcr卡面背景图（个人专用，因为改了hoshino的接口）
		role_id = random.choice(ids)
		while chara.is_npc(role_id): role_id = random.choice(ids)
		star = random.choice([3,6])
		c = chara.fromid(role_id, star)
		img:Image.Image = c.card.open()

		img = img.convert('RGBA')
		img = img.resize((1920,1080), Image.Resampling.LANCZOS)

		# front_img = Image.open(img_folder+'/cbt.png')
		# img.paste(front_img, (0,0),front_img)
		draw = ImageDraw.Draw(img)
		setFont_60 = ImageFont.truetype(font_file, 60)
		setFont_40 = ImageFont.truetype(font_file, 40)
		setFont_25 = ImageFont.truetype(font_file, 25)
		setFont_24 = ImageFont.truetype(font_file, 24)
		setFont_15 = ImageFont.truetype(font_file, 15)

		radius = 10 #圆角半径
		mask = Image.new("RGBA", img.size, (0, 0, 0, 0)) # 创建一个透明蒙版图像
		mask_draw = ImageDraw.Draw(mask)
		# rectangle_color = dominant_colors[0][0] + (100,)
		rectangle_color = (255, 255, 255, 100)  # 半透明白色
		for offset in range(5): #boss信息底框
			rectangle_coords = (70, 33 + offset * 145, 1275, 142 + offset * 145)
			mask_draw.rounded_rectangle(rectangle_coords, radius = radius, fill = rectangle_color)
		mask_draw.rounded_rectangle((70, 745, 1275, 1060), radius = radius, fill = rectangle_color) #玩家信息底框
		mask_draw.rounded_rectangle((1305, 35, 1840, 370), radius = radius, fill = rectangle_color) #公会信息底框
		mask_draw.rounded_rectangle((1305, 390, 1840, 720), radius = radius, fill = rectangle_color) #出刀信息底框
		mask_draw.rounded_rectangle((1305, 745, 1840, 1060), radius = radius, fill = rectangle_color) #留言板底框
		blurred_mask = mask.filter(ImageFilter.GaussianBlur(5))	#给画好的底框添加模糊效果
		img.paste(blurred_mask, (0, 0), blurred_mask)
		
		name_length = draw.textlength(c.name, font=setFont_15)
		draw.text((img.size[0] - name_length-10, img.size[1]-25), c.name, font=setFont_15, fill="#000000") #背景图角色名

		#boss信息部分
		lap = battle_info['lap_num']
		bg = Image.new('RGBA', (335, 35), (0, 0, 0, 128)) #boss血量半透明黑色背景
		for boss in battle_info['boss_info']:
			boss_num = boss['order_num']
			boss_lap_num = boss['lap_num']
			mhp = boss['max_hp']
			hp = boss['current_hp']
			hp_percentage = hp / mhp  # 计算血量百分比

			# 根据血量百分比设置血条颜色
			opacity = 200
			if hp_percentage > 0.5: hp_color = (144,238,144,opacity)
			elif 0.25 < hp_percentage <= 0.5: hp_color = (255,165,0,opacity)
			else: hp_color = (255,0,0,opacity)
			if boss_lap_num - lap == 2: hp_color = (160,32,240,opacity)
			elif boss_lap_num - lap == 1: hp_color = (255,192,203,opacity)

			point = 50+(boss_num-1)*145
			length = int((hp / mhp) * 1185)
			# (70, 35 + offset * 145, 1275, 140 + offset * 145)
			hp_bar = rounded_rectangle((length, 95), 10, hp_color)
			img.paste(hp_bar, (80, 40 + (boss_num - 1) * 145), hp_bar)
			try:
				boss_portrait = Image.open(current_folder+'/img'+f'/{boss_icon_list[boss_num - 1]}.png')
			except:
				boss_portrait = R.img(f'priconne/unit/icon_unit_100131.png').open()
			boss_portrait = boss_portrait.resize((70,70),Image.Resampling.LANCZOS)
			img.paste(boss_portrait, (93, point + 2))

			# boss血量和周目数
			img.paste(bg, (170, point), bg) #boss血量半透明黑色背景
			# draw.rounded_rectangle((165, point, 480, point + 35), radius = 5, fill = (0, 0, 0, 128)) #boss血量半透明黑色背景
			hp_text = f'{"{:,}".format(hp)}/{"{:,}".format(mhp)}'
			hp_text_length = draw.textlength(hp_text, font=setFont_25)
			draw.text((330 - hp_text_length / 2, point + 2), hp_text, font=setFont_25, fill="#FFFFFF") #血量
			stage_color = { #根据阶段不同修改背景颜色
				1: '#83C266',
				4: '#67A3E5',
				11: '#D56CB9',
				31: '#CF4F45',
				39: '#A465CC'
			}
			for st in side:
				if boss_lap_num >= int(st): cur_stage = st
			cur_stage = side[cur_stage]
			for st in stage_color:
				if boss_lap_num >= st: bg_color = st
			bg_color = stage_color[bg_color]
			draw.rounded_rectangle((530, point, 685, point + 35), radius = radius, fill = bg_color) #周目数纯色背景
			draw.text((540, point+2), f'{cur_stage}面 {boss_lap_num}周目', font=setFont_25, fill="#FFFFFF") #周目数

			if group_info['monitor_flag'] == 0: in_game_30, in_game_total = 0, 0
			else: in_game_30, in_game_total = {group_info['in_game'][boss_num-1]}, {group_info['in_game_old'][boss_num-1]}
			draw.rounded_rectangle((705, point, 905, point + 35), radius = radius, fill = bg_color) #实战人数纯色背景
			draw.text((715, point+2), f'实战人数: {in_game_30} ({in_game_total})', font=setFont_25, fill="#FFFFFF") #实战人数

			pre = group_info['pre_push'][boss_num-1]
			all_name = []
			if pre != []:
				for qqid in pre:
					try:
						info = await bot.get_stranger_info(self_id=ev.self_id, user_id=qqid)
						all_name.append(info['nickname'] or qqid)
					except Exception as e: logger.error(str(e))
			if len(all_name) != 0: draw.text((175, point + 42), f'{"、".join(all_name)}已预约', font=setFont_25, fill="#A020F0")
			else: draw.text((175, point + 42), f'无人预约', font=setFont_25, fill="#A020F0")

		#玩家信息部分
		row = 0
		width = 0
		all_battle_count = 0
		damage_rank = []
		for members in clan_info['clan']['members']:
			vid = members['viewer_id']
			name = members['name']
			favor = members['favorite_unit']
			favor_id = str(favor['id'])[:-2]
			stars = 3 if members['favorite_unit']['unit_rarity'] != 6 else 6
			damage_rank.append({"name":name,"damage":0})#random.randint(10000000,120000000)
			try:
				role = chara.fromid(favor_id, stars)
				icon = await role.get_icon()
				icon:Image.Image = icon.open()
				icon = icon.resize((48,48),Image.Resampling.LANCZOS)
				img.paste(icon, (82+int(149.5*width), 761+int(59.8*row)), icon)
			except Exception as e: logger.error(str(e))

			kill_acc = 0
			today_t = time.localtime()
			hour_h = today_t[3]
			today = 0
			if hour_h < 5:
				today = today_t[2]-1
			else:
				today = today_t[2]

			img3 = Image.new('RGB', (25, 17), "white")
			img4 = Image.new('RGB', (12, 17), "red")
			time_sign = 0
			half_sign = 0
			sl_sign = 0
			output_file = os.path.join(current_folder, 'output', f'{group_id}.txt')
			if not exists(output_file):open(output_file, 'w')
			for line in open(output_file, encoding='utf-8'):
				if line != '':
					line = line.split(',')
					if line[0] == 'SL':
						mode = 1
						re_vid = int(line[2])
						day = int(line[3])
						hour = int(line[4])
					else:#re_battle_id = int(line[4]);re_name = line[5];re_dmg = int(line[9]);re_boss_id = int(line[11]);re_is_auto = int(line[13]);re_lap = int(line[7]);re_boss = int(line[8]);
						mode = 2
						day = int(line[0])
						hour = int(line[1])
						re_vid = line[6]
						re_dmg = int(line[9])
						re_kill = int(line[10])
						re_clan_battle_id = int(line[12])
						re_start_time = int(line[14])
						re_battle_time = int(line[15])
					if_today = False
					if ((day == today and hour >= 5) or (day == today + 1 and hour < 5)) and (re_clan_battle_id == clan_battle_id) and mode == 2: if_today = True
					if ((day == today and hour >= 5) or (day == today + 1 and hour < 5)) and mode == 1: if_today = True
					if if_today == True and mode == 1 and int(vid) == int(re_vid): sl_sign = 1

					if int(vid) == int(re_vid) and if_today == True and mode == 2:
						damage_rank[-1]["damage"] += re_dmg
						if re_start_time == 90 and re_kill == 1:
							if time_sign >= 1:
								time_sign -= 1
								half_sign -= 0.5
								kill_acc += 0.5
								continue
							if re_battle_time <= 20 and re_battle_time != 0: time_sign += 1
							kill_acc += 0.5
							half_sign += 0.5
						elif re_start_time == 90 and re_kill == 0:
							if time_sign >= 1:
								kill_acc += 0.5
								time_sign -= 1
								half_sign -= 0.5
								continue
							kill_acc += 1
						else:
							kill_acc += 0.5
							half_sign -= 0.5
			if kill_acc > 3:    #对满补刀无从下手，先限定三刀补一下
				kill_acc = 3
			all_battle_count += kill_acc

			if kill_acc == 0: draw.text((132+149*width, 761+60*row), f'{name}', font=setFont_15, fill="#FF0000")		#未出刀
			elif 0< kill_acc < 3: draw.text((132+149*width, 761+60*row), f'{name}', font=setFont_15, fill="#FF00FF")	#已出刀未出完
			elif kill_acc == 3: draw.text((132+149*width, 761+60*row), f'{name}', font=setFont_15, fill="#FFFF00")		#出完刀
			width2 = 0
			kill_acc = kill_acc - half_sign

			while kill_acc-1 >=0:
				img.paste(img3, (130+int(149.5*width)+30*width2, 785+60*row))
				kill_acc -= 1
				width2 += 1
			while half_sign-0.5 >=0:
				img.paste(img4, (130+int(149.5*width)+30*width2, 785+60*row))
				half_sign -= 0.5
				width2 += 1
			if sl_sign == 1: draw.text((130+int(149.5*width), 785+60*row), f'SL', font=setFont_15, fill="black")
			width += 1
			if width == 6:
				width = 0
				row += 1
		damage_rank.sort(key=lambda x: x["damage"])
		draw.text((1000,760), '今日伤害排名：', font=setFont_15, fill="#A020F0")
		rank = 1
		for player_damage in damage_rank:
			draw.text((1000, 760 + 25 * rank), f'{rank} : {player_damage["damage"]}, {player_damage["name"]}', font=setFont_15, fill="#A020F0")
			rank += 1
			if rank > 10 :break

		#公会信息部分
		clan_name = battle_info['user_clan']['clan_name']
		clan_name_length = draw.textlength(clan_name, font=setFont_40)
		draw.text((1570 - int(clan_name_length / 2), 50), clan_name, font=setFont_40, fill="#A020F0") #公会名
		rank_text = f'当期排名：{battle_info["period_rank"]}   上期排名:{clan_info["last_total_ranking"]}'
		rank_length = draw.textlength(rank_text, font=setFont_25)
		draw.text((1570 - int(rank_length / 2), 110), rank_text, font=setFont_25, fill="#A020F0") #公会排名
		progress_color = all_battle_count >= 90 and '#ADFF2F' or (#绿
			all_battle_count >= 60 and '#EEEE00' or (#黄
				all_battle_count >= 30 and '#FFA500' or '#EE6363'))#橙，红
		offset = 32
		draw.line([(1620+offset, 210), (1525+offset, 345)], fill=progress_color, width=7)
		count_m = len(clan_info['clan']['members'])*3
		draw.text((1363+offset, 215), '今日已出', font=setFont_25, fill="#A020F0")
		draw.text((1688+offset, 305), '刀', font=setFont_25, fill="#A020F0")
		draw.text((1515+offset - draw.textlength(f'{all_battle_count}', font=setFont_60)/2, 205), f'{all_battle_count}', font=setFont_60, fill=progress_color)
		draw.text((1635+offset - draw.textlength(f'{count_m}', font=setFont_60)/2, 275), f'{count_m}', font=setFont_60, fill=progress_color)

		#出刀信息部分
		history = battle_info['damage_history']
		order = 0
		for hst in history:
			order += 1
			if order < 21:
				name = hst['name']
				vid = hst['viewer_id']
				kill = hst['kill']
				damage = hst['damage']
				lap = hst['lap_num']
				boss = int(hst['order_num'])
				ctime = hst['create_time']
				real_time = time.localtime(ctime)
				day = real_time[2]
				hour = real_time[3]
				minute = real_time[4]
				if_kill = ''
				if kill == 1: if_kill = '并击破'
				msg = f'[{day}日{hour:02}:{minute:02}]{name} 对 {lap} 周目 {boss} 王造成了 {damage} 伤害{if_kill}'
				if kill == 1: draw.text((1320, 385+(order*15)), f'{msg}', font=setFont_15, fill="black")
				else: draw.text((1320, 385+(order*15)), f'{msg}', font=setFont_15, fill="purple")

		#留言部分
		tital_length = draw.textlength('留言板', font=setFont_40)
		draw.text((1570 - int(tital_length / 2), 750), '留言板', font=setFont_40, fill="#A020F0") #公会名
		if group_id not in chat_list:
			text_length = draw.textlength('本群暂时没有留言！', font=setFont_24)
			draw.text((1570 - int(text_length / 2), 850), f'本群暂时没有留言！', font=setFont_24, fill="#A020F0")
		else:
			msg_list = []
			for i in range(0,len(chat_list[group_id]["uid"])):
				time_now = int(time.time())
				time_diff = time_now - chat_list[group_id]["time"][i]
				if time_diff <= 60:
					time_diff = '刚刚'
				else:
					time_diff = int(time_diff/60)
					time_diff = f'{time_diff}分钟前'
				nickname = chat_list[group_id]["uid"][i]
				try:
					nickname = await bot.get_group_member_info(group_id = group_id, user_id = (chat_list[group_id]["uid"][i]))
					nickname = nickname['nickname']
				except: pass
				chat = chat_list[group_id]["text"][i]
				msg_list.append(f'[{time_diff}]{nickname}:{chat}')
			draw.text((1320, 805), '\n'.join(msg_list), font=setFont_24, fill="#A020F0")


		width = img.size[0]		# 获取宽度
		height = img.size[1]	# 获取高度
		img = img.resize((int(width*1), int(height*1)), Image.Resampling.LANCZOS)
		img = p2ic2b64(img)
		img = MessageSegment.image(img)
		await bot.send(ev, img)
	except Exception as e:
		logger.exception(e)
		await bot.send(ev, f'出现错误, 请重试:\n{str(e)}')


@sv.on_prefix('抓人')
async def get_battle_status(bot:HoshinoBot, ev:CQEvent):
	if not priv.check_priv(ev, priv.ADMIN): return await bot.send(ev,'权限不足，当前指令仅管理员可用!')

	await verify(bot, ev)
	await bot.send(ev, '让我栞栞是谁还没有出刀...')
	group_id = ev.group_id
	group_info = secret.get_sec(group_id)
	account_list = group_info['account_list']
	account = group_info['now_monitor_account']
	account_info = account_list[account]
	msg = ev.message.extract_plain_text().strip()

	if msg != '': today = int(msg)
	else:
		today_t = time.localtime()
		hour_h = today_t[3]
		today = 0
		if hour_h < 5: today = today_t[2] - 1
		else: today = today_t[2]
	clan_info = await query.get_clan_info(account_info)
	clan_id = clan_info['clan']['detail']['clan_id']
	battle_info = await query.get_clan_battle_info(account_info, clan_id)
	clan_battle_id = battle_info['clan_battle_id']
	day_sign, num, max_page, battle_history_list = 0, 0, 0, []
	while(day_sign == 0):
		num += 1
		timeline = await query.query(account_info, '/clan_battle/battle_log_list', {
			'clan_battle_id': clan_battle_id,
			'order_num': 0, 'phases': [1,2,3,4,5],
			'report_types': [1],
			'hide_same_units': 0,
			'favorite_ids': [],
			'sort_type': 3,
			'page': num
		})
		if max_page == 0: max_page = timeline['max_page']
		max_page1 = timeline['max_page']
		if max_page1 < max_page: day_sign = 1
		for tl in timeline['battle_list']:
			tvid = tl['target_viewer_id']
			log_id = tl['battle_log_id']
			order_num = tl['order_num']
			lap_num = tl['lap_num']
			battle_end_time = tl['battle_end_time']
			damage = tl['total_damage']
			#目前暂时无法计算跨日残血boss合刀，对该部分玩家的计算会有偏差，应该可以从这里入手
			user_name = tl['user_name']
			hr = time.localtime(battle_end_time)
			day = hr[2]
			hour = hr[3]
			if (day == today and hour >= 5) or (day == today + 1 and hour < 5):
				battle_history_list.append([tvid, log_id, user_name, order_num, lap_num, damage])
			if (day < today): day_sign = 1

	for log in battle_history_list:
		extra_back = 0
		tvid = log[0]
		log_id = log[1]
		order_num = log[3]
		lap_num = log[4]
		damage = log[5]
		total_dmg = 0
		tvid3 = 0
		for log2 in battle_history_list:
			tvid2 = log2[0]
			order_num2 = log2[3]
			lap_num2 = log2[4]
			damage2 = log2[5]
			if order_num == order_num2 and lap_num == lap_num2:
				if tvid3 == 0: tvid3 = tvid2
				total_dmg += damage2
		for st in phase:
			if lap_num >= int(st): cur_side = st
		cur_side = phase[cur_side]
		if total_dmg > health_list[cur_side-1][order_num-1] and (int(tvid3) == int(tvid)): extra_back = 1


		timeline_report = await query.query(account_info, '/clan_battle/timeline_report', {
			'target_viewer_id': tvid,
			'clan_battle_id': clan_battle_id,
			'battle_log_id': int(log_id)
		})
		start_time = timeline_report['start_remain_time']
		used_time = timeline_report['battle_time']
		for tl in timeline_report['timeline']:
			if tl['is_battle_finish'] == 1:
				remain_time = tl['remain_time']
				if remain_time != 0: kill = 1
				else: kill = 0
		log.append(start_time)
		log.append(used_time)
		log.append(kill)
		log.append(extra_back)

	msg = []
	bladeDict = {}
	for members in clan_info['clan']['members']:
		vid = members['viewer_id']
		name = members['name']
		time_sign = 0
		half_sign = 0
		kill_acc = 0
		for log in battle_history_list:
			if log[0] == vid:
				start_time = log[6]
				used_time = log[7]
				kill = log[8]
				extra_back = log[9]
				if extra_back == 1:
					kill_acc += 0.5
					half_sign += 0.5
					continue
				if start_time == 90 and kill == 1:
					if time_sign >= 1:
						time_sign -= 1
						half_sign -= 0.5
						kill_acc += 0.5
						continue
					if used_time <= 20 and used_time != 0:
						time_sign += 1
					kill_acc += 0.5
					half_sign += 0.5
				elif start_time == 90 and kill == 0:
					if time_sign >= 1:
						kill_acc += 0.5
						time_sign -= 1
						half_sign -= 0.5
						continue
					kill_acc += 1
				else:
					kill_acc += 0.5
					half_sign -= 0.5
		if kill_acc < 3:
			blade = str(3-kill_acc)
			if blade not in bladeDict:
				bladeDict[blade] = [name]
			else:
				bladeDict[blade].append(name)
			# msg.append(f'【{name}】缺少{3-kill_acc}刀')
	for blade, players in bladeDict.items():
		msg.append(f'缺{blade}刀：{" ".join(players)}')
	if len(msg) > 0:
		msg.append('目前暂时无法计算跨日残血boss合刀，对该部分玩家的计算会有偏差')
		await bot.send(ev, '\n'.join(msg))
	else: await bot.send(ev, '所有人都出完刀辣！')


@sv.on_prefix('sl')
async def sl(bot:HoshinoBot, ev:CQEvent):
	await verify(bot, ev)
	group_id = ev.group_id
	group_info = secret.get_sec(group_id)
	account_list = group_info['account_list']
	account = group_info['now_monitor_account']
	account_info = account_list[account]

	if group_info['monitor_flag'] == 0: return await bot.send(ev,'未开启会战推送，无法sl')
	user_name = ev.message.extract_plain_text().strip()
	if user_name == '': return await bot.send(ev,'由于不进行绑定，请输入一个游戏内的ID')

	clan_info = await query.get_clan_info(account_info)
	search_sign = 0
	vid0 = 0
	for members in clan_info['clan']['members']:
		vid = members['viewer_id']
		name = str(members['name'])

		if user_name == name:
			user_name = name
			today_t = time.localtime()
			hour_h = today_t[3]
			today = 0
			if hour_h < 5: today = today_t[2]-1
			else: today = today_t[2]
			output_file = os.path.join(current_folder, 'output', f'{group_id}.txt')
			if not exists(output_file):open(output_file, 'w')
			for line in open(output_file, encoding='utf-8'):
				if line != '':
					line = line.split(',')
					if line[0] == 'SL':
						name2 = line[1]
						vid0 = int(line[2])
						day = int(line[3])
						hour = int(line[4])
						minute = int(line[5])
						seconds = int(line[6])
						mon = line[7]
						if (name2 == name) and (((day == today and hour >= 5) or (day == today + 1 and hour < 5))):
							await bot.send(ev,f'({name})已于{hour}:{minute}进行过SL操作！')
							return
			vid0 = vid
			search_sign = 1
			break
	if search_sign == 1:
		real_time = time.localtime()
		mon = real_time[1]
		day = real_time[2]  #垃圾代码
		hour = real_time[3]
		minute = real_time[4]
		seconds = real_time[5]
		output = f'SL,{user_name},{vid0},{day},{hour},{minute},{seconds},{mon},'
		with open(current_folder + "/output" + f'/{group_id}.txt', 'a+', encoding='utf-8') as file:
			file.write(str(output)+'\n')
		await bot.send(ev,f'{name}({vid0})已上报SL')
	else:
		return await bot.send(ev,'没有找到这个ID，请确认')


def p2ic2b64(img, quality=90):
	# 如果图像模式为RGBA，则将其转换为RGB模式
	if img.mode == 'RGBA':
		img_rgb = Image.new('RGB', img.size, (255, 255, 255))
		img_rgb.paste(img, mask=img.split()[3])  # 使用alpha通道作为mask
		img = img_rgb

	buf = BytesIO()
	img.save(buf, format='JPEG', quality=quality)
	base64_str = base64.b64encode(buf.getvalue()).decode('utf-8')
	return 'base64://' + base64_str

@sv.scheduled_job('cron', hour='5') #推送5点时的名次
async def rank_and_status():
	for group_id, group_info in secret.get_group_infos().items():
		if group_info['monitor_flag'] == 0:continue
		await _account_verify({}, {}, group_id, 2)
		account_list = group_info['account_list']
		account = group_info['now_monitor_account']
		account_info = account_list[account]
		clan_info = await query.get_clan_info(account_info)
		clan_id = clan_info['clan']['detail']['clan_id']
		battle_info = await query.get_clan_battle_info(account_info, clan_id)
		rank = battle_info['period_rank']
		msg = f'当前的排名为{rank}位'
		if group_id in event_cache: await cqbot.send(event_cache[group_id], msg)
		else: await cqbot.send_group_msg(group_id = int(group_id), self_id = group_info['bot_qqid'], message = msg)


@sv.on_prefix('查档线', '查公会', '查排名')     #从游戏内获取数据，无数据时返回空
async def query_line(bot:HoshinoBot, ev:CQEvent):
	if not priv.check_priv(ev, priv.ADMIN): return await bot.send(ev,'权限不足，当前指令仅管理员可用!')
	goal = ev.message.extract_plain_text().strip()
	await verify(bot, ev)
	group_id = ev.group_id
	group_info = secret.get_sec(group_id)
	account_list = group_info['account_list']
	account = group_info['now_monitor_account']
	account_info = account_list[account]
	try:
		goal_list = []
		if re.match("^[0-9,]+$", goal):
			if ',' in goal: goal_list = goal.split(',')
			else: goal_list.append(goal)
		elif goal == '':
			goal_list = [1,4,11,21,51,201,601,1201,2801,5001]
			await bot.send(ev,'获取数据时间较长，请稍候')
		else:
			goal_list = []
			await bot.send(ev,f'正在搜索行会关键词{goal}')
			clan_name_search = await query.query(account_info, '/clan/search_clan', {'clan_name': goal, 'join_condition': 1, 'member_condition_range': 0, 'activity': 0, 'clan_battle_mode': 0})
			clan_list = ''
			for search_clan in clan_name_search['list']:
				clan_name = search_clan['clan_name']
				clan_list += f'[{clan_name}]'
			clan_num = len(clan_name_search['list'])
			await bot.send(ev,f'找到{clan_num}个与关键词相关行会,超过5个的将不会查询，请精确化关键词\n{clan_list}')
			clan_num = 0
			for search_clan in clan_name_search['list']:
				if clan_num <= 4:
					search_clan_id = search_clan['clan_id']
					if search_clan_id == 0: break
					clan_most_info = await query.query(account_info, '/clan/others_info', {'clan_id': search_clan_id})
					clan_most_info = clan_most_info['clan']['detail']['current_period_ranking']
					if clan_most_info == 0: continue
					goal_list.append(clan_most_info)
					clan_num += 1
				else: break
		if goal_list == []: return await bot.send(ev,'无法获取排名，可能是官方正在结算，请等待结算后使用本功能')

		width2 = 500*len(goal_list)
		img4 = Image.new('RGB', (1000, width2), (255, 255, 255))
		all_num = 0
		clan_info = await query.get_clan_info(account_info)
		clan_id = clan_info['clan']['detail']['clan_id']
		battle_info = await query.get_clan_battle_info(account_info, clan_id)
		clan_battle_id = battle_info['clan_battle_id']
		for goal in goal_list:
			goal = int(goal)
			page = int((goal - 1) / 10)
			in_di = goal % 10
			if in_di == 0: in_di = 10

			page_info = await query.query(account_info, '/clan_battle/period_ranking', {
				'clan_id': clan_id,
				'clan_battle_id': clan_battle_id,
				'period': 1, 'month': 0, 'page': page, 'is_my_clan': 0, 'is_first': 1})
			if page_info['period_ranking'] == []:
				return await bot.send(ev,'当前会战排名正在结算，无法获取数据，请等待官方结算完成后再使用本功能~')
			num = 0
			lap = 0
			boss = 0
			stage = [207300000,859700000,4771700000,9017700000,999999999999]
			l1 = [  [7200000,9600000,13000000,16800000,22500000],
					[9600000,12800000,18000000,22800000,30000000],
					[24000000,28000000,40800000,45600000,57200000],
					[66500000,70000000,85100000,95000000,108000000],
					[297500000,315000000,351500000,380000000,440000000]]
			lp = [3,10,30,40,999]

			for rank in page_info['period_ranking']:
				num += 1
				if num == in_di:
					rank_num = rank['rank']
					dmg = rank['damage']
					mem = rank['member_num']
					name = rank['clan_name']
					l_vid = rank['leader_viewer_id']
					l_name = rank['leader_name']
					g_rank = rank['grade_rank']

					for stag in stage:
						lap += 1
						if dmg <= stag:
							dmg_left = dmg - stage[lap-2]
							break

					l_lps = 0
					while(dmg_left > 0):
						boss = 0
						for i in l1[lap-1]:
							if dmg_left - i > 0:
								boss += 1
								dmg_left -= i
							else:
								final_dmg = dmg_left
								dmg_left = -1
								break
						l_lps += 1
					final_lap = lp[lap-2] + l_lps
					progress = (float(final_dmg/i)*100)
					progress = round(progress, 2)
					msg = f'当前第 {lap} 阶段 | 第 {final_lap} 周目 {boss+1} 王 | 进度 {progress}%'

					R_n = 0
					for RA in RANK_LIST:
						if rank_num < RA:
							prev_r = RA
							next_r = RANK_LIST[R_n-1]
							break
						R_n += 1
					icon_unit = rank['leader_favorite_unit']['id']
					stars = rank['leader_favorite_unit']['unit_rarity']
					st = 1 if stars < 3 else 3
					st = st if st != 6 else 6
					chara_id = str(icon_unit)[:-2]
					clan_id_ = 0
					for n in range(0,6):
						clan_info = await query.query(account_info, '/clan/search_clan', {'clan_name': name, 'join_condition': 1, 'member_condition_range': 0, 'activity': 0, 'clan_battle_mode': 0})
						try:
							clan_ids = clan_info['list']
							for clan_id_info in clan_ids:
								clan_l_vid = clan_id_info['leader_viewer_id']
								if l_vid == clan_l_vid:
									clan_id_ = clan_id_info['clan_id']
									break
						except Exception as e:
							logger.exception(f'{str(e)}获取行会信息失败{n}')
					img = Image.open(img_folder + f'//bkg.png')
					draw = ImageDraw.Draw(img)
					if clan_id_ == 0:
						info_msg = f'获取行会信息失败(该行会未开放搜索或同名过多)'
						setFont = ImageFont.truetype(font_file, 15)
						draw.text((350,250), f'{info_msg}', font=setFont, fill="#4A515A")
					else:
						clan_most_info = await query.query(account_info, '/clan/others_info', {'clan_id': clan_id_})
						clan_member = clan_most_info['clan']['members']
						description = clan_most_info['clan']['detail']['description']

					wi, de = 0, 0
					setFont = ImageFont.truetype(font_file, 15)
					try:
						for member in clan_member:
							usr_name = member['name']
							draw.text((350 + wi * 120, 250 + de * 20), f'{usr_name}', font=setFont, fill="#4A515A")
							wi += 1
							if wi >= 5:
								wi = 0
								de += 1
					except Exception as e: logger.exception(str(e))
					setFont = ImageFont.truetype(font_file, 20)
					draw.text((20,220), f'当前位次: {rank_num}位', font=setFont, fill="#4A515A")
					draw.text((20,240), f'会长: {l_name}', font=setFont, fill="#4A515A")
					draw.text((20,260), f'VID: [{l_vid}]', font=setFont, fill="#4A515A")
					draw.text((20,280), f'上期位次: {g_rank}位', font=setFont, fill="#4A515A")
					try: draw.text((20,180), f'{description}', font=setFont, fill="#4A515A")
					except Exception as e: logger.exception(str(e))
					draw.text((350,220), msg, font=setFont, fill="#4A515A")

					setFont = ImageFont.truetype(font_file, 30)
					draw.text((750,75), f'{dmg}', font=setFont, fill="#4A515A")
					draw.text((850,135), f'{mem}/30', font=setFont, fill="#4A515A")
					draw.text((50,440), f'{prev_r}位', font=setFont, fill="#4A515A")
					draw.text((850,440), f'{next_r}位', font=setFont, fill="#4A515A")

					setFont = ImageFont.truetype(font_file, 40)
					draw.text((500,15), f'{name}', font=setFont, fill="#4A515A")

					try:
						img3 = R.img(f'priconne/unit/icon_unit_{chara_id}{st}1.png').open()
						img3 = img3.resize((160, 160))
						img.paste(img3, (17,17))
					except Exception as e: logger.exception(str(e))

					setFont = ImageFont.truetype(font_file, 50)

					if len(goal_list) != 1: img4.paste(img, (0,500*all_num))
					all_num+=1

		if len(goal_list) != 1:
			send_img = util.pic2b64(img4)
			send_img = MessageSegment.image(send_img)
		else:
			send_img = util.pic2b64(img)
			send_img = MessageSegment.image(send_img)
		await bot.send(ev, send_img)
	except Exception as e:
		logger.exception(str(e))
		await bot.send(ev, '获取数据时发生错误，请重试')


@sv.on_fullmatch('出刀时段统计')
async def stats1(bot:HoshinoBot, ev:CQEvent):
	BTime = Image.new("RGBA",(1020,550),'#FFE4C4')
	draw = ImageDraw.Draw(BTime)
	setFont = ImageFont.truetype(font_file, 20)
	setFont2 = ImageFont.truetype(font_file, 15)

	time_array = []
	for i in range(0,24):
		draw.text((50 + 40*i ,520), f'{i}', font=setFont, fill="#4A515A")
		time_array.append(0)
	for i in range(1,6):
		draw.text((0, 520 - i*100), f'{i*2}0', font=setFont, fill="#4A515A")
		draw.line((33, 520 - i*100) + (1000, 520 - i*100), fill='#191970', width=1)

	output_file = os.path.join(current_folder, 'output', f'{ev.group_id}.txt')
	if not exists(output_file):open(output_file, 'w')
	for line in open(output_file, encoding='utf-8'):
		values = line.split(",")
		if values[0] == 'SL': continue
		battle_time = int(values[1])
		time_array[battle_time] += 1

	max_time = max(time_array)
	line_color = {
		0: '#808080',
		6: '#9CC5B0',
		12: '#C54730',
		18: '#384B5A'
	}
	for i in range(0,24):
		overline = False
		if time_array[i] >= 100:
			overline = True
		elif time_array[i] == 0:
			continue
		for color in line_color:
			if i >= color:
				color2 = line_color[color]
		y_axis = 520 - time_array[i]*5 if overline == False else 20
		font_color = 'black' if overline == False else 'purple'
		if time_array[i] == max_time:
			draw.line((60 + 40*i, 520) + (60 + 40*i, y_axis-5), fill='#00008B', width=30)
		draw.line((60 + 40*i, 520) + (60 + 40*i, y_axis), fill=color2, width=20)
		draw.text((50 + 40*i, y_axis - 22), f'{(time_array[i])}', font=setFont2, fill=font_color)
	draw.line((30, 520) + (1000, 520), fill=128, width=5)
	draw.line((30, 20) + (30, 520), fill=128, width=5)

	img = util.pic2b64(BTime)
	img = MessageSegment.image(img)
	await bot.send(ev, img)


#留言功能
@sv.on_prefix('会战留言')
async def chat(bot:HoshinoBot, ev:CQEvent):
	global chat_list
	msg = ev.message.extract_plain_text().strip()
	uid = ev.user_id
	group_id = ev.group_id
	if msg == '':
		await bot.send(ev,'你想说些什么呢^^')
	t = int(time.time())
	if group_id not in chat_list:
		chat_list[group_id] = {
			"uid": [],
			"text": [],
			"time": [],
			"extra": [],
		}

	if len(chat_list[group_id]["uid"]) > max_chat_list:
		del chat_list[group_id]["uid"][0]
		del chat_list[group_id]["text"][0]
		del chat_list[group_id]["time"][0]
	if len(chat_list[group_id]["uid"]) <= max_chat_list:
		chat_list[group_id]["uid"].append(int(uid))
		chat_list[group_id]["text"].append(str(msg))
		chat_list[group_id]["time"].append(int(t))

	await bot.send(ev,'已添加留言！')

@sv.on_prefix('会战留言板','留言板')
async def chat_board(bot:HoshinoBot, ev:CQEvent):
	group_id = ev.group_id
	if group_id not in chat_list:
		await bot.send(ev,'本群暂时没有留言！')
		return
	else:
		msg = '留言板：\n'
		for i in range(0,len(chat_list[group_id]["uid"])):
			time_now = int(time.time())
			time_diff = time_now - chat_list[group_id]["time"][i]
			if time_diff <= 60:
				time_diff = '刚刚'
			else:
				time_diff = int(time_diff/60)
				time_diff = f'{time_diff}分钟前'
			nickname = chat_list[group_id]["uid"][i]
			try:
				nickname = await bot.get_group_member_info(group_id = group_id,user_id = (chat_list[group_id]["uid"][i]))
				nickname = nickname['nickname']
			except: pass
			chat = chat_list[group_id]["text"][i]
			msg += f'[{time_diff}]{nickname}:{chat}\n'
		await bot.send(ev,msg)
		return

@sv.on_fullmatch('清空留言板')
async def clear_chat(bot:HoshinoBot, ev:CQEvent):
	group_id = ev.group_id
	u_priv = priv.get_user_priv(ev)
	if u_priv < sv.manage_priv:
		await bot.send(ev,'权限不足，当前指令仅管理员可用!')
		return
	del chat_list[group_id]
	await bot.send(ev,'已清空本群记录')



# async def pre():
# 	conn = sqlite3.connect('yobotdata_new.db')
# 	cursor = conn.cursor()
# 	for line in open("Output.txt",encoding='utf-8'):
# 		values = line.split(",")
# 		if values[0] == 'SL':
# 			continue
# 		cursor.execute("SELECT cid FROM clan_challenge ORDER BY cid DESC LIMIT 1")
# 		cid = (cursor.fetchone())[0] + 1
# 		boss_cycle = values[7]
# 		boss_num = values[8]
# 		if values[10] == 1:
# 			remain = 0
# 		else:
# 			remain = 1
# 		damage = values[9]
# 		is_continue = 0
# 		#row_data = (cid, bid, gid, qqid, 0, 0, boss_cycle, boss_num, remain, damage, is_continue)
# 		#cursor.execute("INSERT INTO clan_challenge (cid, bid, gid, qqid, challenge_pcrdate, challenge_pcrtime, boss_cycle, boss_num, boss_health_remain, challenge_damage, is_continue) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", row_data)
# 		conn.commit()
# 	conn.close()