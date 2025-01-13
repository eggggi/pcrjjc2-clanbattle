import httpx
from hoshino import config, get_bot, log
from hoshino.aiorequests import get
from hoshino.typing import CommandSession
from nonebot import on_command
from json import loads
from typing import Dict
import asyncio
logger = log.new_logger(__name__, config.DEBUG)

gs_commandPrefix = 'cv'
g_bot = get_bot()
gs_otto = True
gs_token = None
gs_waitTime = 90

try:
    gs_token = config.priconne.arena.CAPTCHA_AUTH_KEY
except:
    gs_otto = False
    # logger.warning(f'自动过码需CAPTCHA_AUTH_KEY，请前往hoshino/config/priconne.py/class arena:下添加后重启bot。')

g_manualResult:Dict[int, str] = {}
captcha_header = {"Content-Type": "application/json",
                  "User-Agent": "pcrjjc2/1.0.0"}

async def autoCaptchaVerifier(*args):
    gt = args[0]
    challenge = args[1]
    userid = args[2]
    async with httpx.AsyncClient(timeout=30) as AsyncClient:
        try:
            res = await AsyncClient.get(url=f"https://pcrd.tencentbot.top/geetest_renew?captcha_type=1&challenge={challenge}&gt={gt}&userid={userid}&gs=1", headers=captcha_header)
            res = res.json()
            uuid = res["uuid"]
            ccnt = 0
            while (ccnt := ccnt + 1) < 10:
                res = await AsyncClient.get(url=f"https://pcrd.tencentbot.top/check/{uuid}", headers=captcha_header)
                res = res.json()

                if "queue_num" in res:
                    tim = min(int(res['queue_num']), 3) * 10
                    logger.info(f"过码排队，当前有{res['queue_num']}个在前面，等待{tim}s")
                    await asyncio.sleep(tim)
                    continue

                info = res["info"]
                if 'validate' in info:
                    return info["challenge"], info["gt_user_id"], info["validate"]

                if res["info"] in ["fail", "url invalid"]:
                    raise Exception(f"自动过码失败")

                if res["info"] == "in running":
                    logger.info(f"正在过码。等待5s")
                    await asyncio.sleep(5)

            raise Exception(f"自动过码多次失败")

        except Exception as e:
            raise Exception(f"自动过码异常，{e}")

async def CaptchaVerifier(challenge:str, gt:str, userId:str, qqid:int=None) -> str:
    """
    过码模块

    Args:
        challenge (str): 程序生成
        gt (str): 程序生成
        userId (str): 程序生成
        qqid (int, optional): 发送验证链接。仅当手动过码模式时需要。 Defaults to None.

    Raises:
        Exception: 手动过码模式但没有传入qqid
        Exception: 自动过码时返回结果res中code不为-1时的res
        Exception: 自动过码时其它异常

    Returns:
        str: 过码结果字符串
    """
    if gs_otto == False:
        url = f"https://help.tencentbot.top/geetest_/?captcha_type=1&challenge={challenge}&gt={gt}&userid={userId}&gs=1"
        if qqid is None:
            raise Exception("当前为手动过码模式，但没有传入消息接受者qqid。")
        try:
            await g_bot.send_private_msg(
                user_id=qqid,
                message=f'pcr账号登录触发验证码，请在{gs_waitTime}秒内完成以下链接中的验证内容，随后将第1个方框的内容点击复制，并加上"{gs_commandPrefix} "前缀发送给机器人完成验证\n验证链接：{url}\n示例：{gs_commandPrefix} 123456789')
        except Exception as e:
            raise Exception(f'向{qqid}私发过码验证消息失败，可能尚未添加好友。')
        g_manualResult[qqid] = None
        await asyncio.sleep(gs_waitTime)
        if g_manualResult.get(qqid, None) is not None:
            return g_manualResult.pop(qqid)
        g_manualResult.pop(qqid, None)
        await g_bot.send_private_msg(user_id=qqid, message="获取结果超时，操作中止")
        raise Exception("手动过码获取结果超时")

    # otto == True
    try:
        res = await (await get(url=f"https://api.fuckmys.tk/geetest?token={gs_token}&gt={gt}&challenge={challenge}")).content
        try:
            res = loads(res)
        except Exception as e:
            raise Exception(f'{res}')
        if res.get("code", -1) != 0:
            raise Exception(f'{res}')
        return res["data"]["validate"]
    except Exception as e:
        raise Exception(f"自动过码异常：{e}")
    

@on_command(f'{gs_commandPrefix}')
async def TryGetToken(session: CommandSession):
    qqid = int(session.ctx.user_id)
    if qqid not in g_manualResult:
        return
    token = session.ctx['message'].extract_plain_text().replace(f"{gs_commandPrefix}", "").strip().replace("|", "").replace("jordan", "")
    outPut = "获取" if g_manualResult[qqid] is None else "更新"
    g_manualResult[qqid] = token
    # await g_bot.send_private_msg(user_id=qqid, message=f'Token {token[:4]}...{token[-4:]} {outp}. Verifying...')
    await g_bot.send_private_msg(user_id=qqid, message=f'Token {token[:4]}...{token[-4:]} {outPut}成功，验证中...')