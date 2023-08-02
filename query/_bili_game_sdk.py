from traceback import print_exc
import httpx
import json
import time
import hashlib
import urllib
from hoshino.aiorequests import post, get
from ._captcha_verifier import CaptchaVerifier, autoCaptchaVerifier, gs_otto, gs_token
import httpx

bililogin = "https://line1-sdk-center-login-sh.biligame.net/"
header = {"User-Agent": "Mozilla/5.0 BSGameSDK", "Content-Type": "application/x-www-form-urlencoded",
          "Host": "line1-sdk-center-login-sh.biligame.net"}

from Crypto.PublicKey import RSA
from Crypto.Cipher import PKCS1_v1_5 as Cipher_pkcs1_v1_5
import base64


# 加密
class RsaCr:
    @staticmethod
    def RsaCreate(message, public_key) -> str:
        rsakey = RSA.importKey(public_key)
        cipher = Cipher_pkcs1_v1_5.new(rsakey)  # 创建用于执行pkcs1_v1_5加密或解密的密码
        cipher_text = base64.b64encode(cipher.encrypt(message.encode('utf-8')))
        text = cipher_text.decode('utf-8')
        return text


async def SendPost(url, data) -> dict:
    async with httpx.AsyncClient() as client:
        return (await client.post(url=url, data=data, headers=header, timeout=20)).json()


def SetSign(data) -> str:
    data["timestamp"] = int(time.time())
    data["client_timestamp"] = int(time.time())
    sign = ""
    data2 = ""
    for key in data:
        if key == "pwd":
            pwd = urllib.parse.quote(data["pwd"])
            data2 += f"{key}={pwd}&"
        data2 += f"{key}={data[key]}&"
    for key in sorted(data):
        sign += f"{data[key]}"
    data = sign
    sign = sign + "fe8aac4e02f845b8ad67c427d48bfaf1"
    sign = hashlib.md5(sign.encode()).hexdigest()
    data2 += "sign=" + sign
    return data2


gs_modolRsa = '{"operators":"5","merchant_id":"1","isRoot":"0","domain_switch_count":"0","sdk_type":"1","sdk_log_type":"1","timestamp":"1613035485639","support_abis":"x86,armeabi-v7a,armeabi","access_key":"","sdk_ver":"3.4.2","oaid":"","dp":"1280*720","original_domain":"","imei":"227656364311444","version":"1","udid":"KREhESMUIhUjFnJKNko2TDQFYlZkB3cdeQ==","apk_sign":"e89b158e4bcf988ebd09eb83f5378e87","platform_type":"3","old_buvid":"XZA2FA4AC240F665E2F27F603ABF98C615C29","android_id":"84567e2dda72d1d4","fingerprint":"","mac":"08:00:27:53:DD:12","server_id":"1592","domain":"line1-sdk-center-login-sh.biligame.net","app_id":"1370","version_code":"90","net":"4","pf_ver":"6.0.1","cur_buvid":"XZA2FA4AC240F665E2F27F603ABF98C615C29","c":"1","brand":"Android","client_timestamp":"1613035486888","channel_id":"1","uid":"","game_id":"1370","ver":"2.4.10","model":"MuMu"}'
gs_modolLogin = '{"operators":"5","merchant_id":"1","isRoot":"0","domain_switch_count":"0","sdk_type":"1","sdk_log_type":"1","timestamp":"1613035508188","support_abis":"x86,armeabi-v7a,armeabi","access_key":"","sdk_ver":"3.4.2","oaid":"","dp":"1280*720","original_domain":"","imei":"227656364311444","gt_user_id":"fac83ce4326d47e1ac277a4d552bd2af","seccode":"","version":"1","udid":"KREhESMUIhUjFnJKNko2TDQFYlZkB3cdeQ==","apk_sign":"e89b158e4bcf988ebd09eb83f5378e87","platform_type":"3","old_buvid":"XZA2FA4AC240F665E2F27F603ABF98C615C29","android_id":"84567e2dda72d1d4","fingerprint":"","validate":"84ec07cff0d9c30acb9fe46b8745e8df","mac":"08:00:27:53:DD:12","server_id":"1592","domain":"line1-sdk-center-login-sh.biligame.net","app_id":"1370","pwd":"rxwA8J+GcVdqa3qlvXFppusRg4Ss83tH6HqxcciVsTdwxSpsoz2WuAFFGgQKWM1+GtFovrLkpeMieEwOmQdzvDiLTtHeQNBOiqHDfJEKtLj7h1nvKZ1Op6vOgs6hxM6fPqFGQC2ncbAR5NNkESpSWeYTO4IT58ZIJcC0DdWQqh4=","version_code":"90","net":"4","pf_ver":"6.0.1","cur_buvid":"XZA2FA4AC240F665E2F27F603ABF98C615C29","c":"1","brand":"Android","client_timestamp":"1613035509437","channel_id":"1","uid":"","captcha_type":"1","game_id":"1370","challenge":"efc825eaaef2405c954a91ad9faf29a2","user_id":"doo349","ver":"2.4.10","model":"MuMu"}'
gs_modolCaptch = '{"operators":"5","merchant_id":"1","isRoot":"0","domain_switch_count":"0","sdk_type":"1","sdk_log_type":"1","timestamp":"1613035486182","support_abis":"x86,armeabi-v7a,armeabi","access_key":"","sdk_ver":"3.4.2","oaid":"","dp":"1280*720","original_domain":"","imei":"227656364311444","version":"1","udid":"KREhESMUIhUjFnJKNko2TDQFYlZkB3cdeQ==","apk_sign":"e89b158e4bcf988ebd09eb83f5378e87","platform_type":"3","old_buvid":"XZA2FA4AC240F665E2F27F603ABF98C615C29","android_id":"84567e2dda72d1d4","fingerprint":"","mac":"08:00:27:53:DD:12","server_id":"1592","domain":"line1-sdk-center-login-sh.biligame.net","app_id":"1370","version_code":"90","net":"4","pf_ver":"6.0.1","cur_buvid":"XZA2FA4AC240F665E2F27F603ABF98C615C29","c":"1","brand":"Android","client_timestamp":"1613035487431","channel_id":"1","uid":"","game_id":"1370","ver":"2.4.10","model":"MuMu"}'


async def TryLoginWithCaptcha(account, password, challenge, gt_user, validate = '', access_key = '', uid = '') -> dict:
    rsa = await SendPost(bililogin + "api/client/rsa", SetSign(json.loads(gs_modolRsa)))
    data = json.loads(gs_modolLogin)
    public_key = rsa['rsa_key']
    data["access_key"] = access_key
    data["gt_user_id"] = gt_user
    data["uid"] = uid
    data["challenge"] = challenge
    data["user_id"] = account
    data["validate"] = validate
    data["seccode"] = ((validate + "|jordan") if len(validate) else "")
    data["pwd"] = RsaCr.RsaCreate(rsa['hash'] + password, public_key)
    data = SetSign(data)
    return await SendPost(bililogin + "api/client/login", data)


async def TryLoginWithoutCaptcha(account, password, access_key, uid) -> dict:
    return await TryLoginWithCaptcha(account, password, "", "", "", access_key, uid)


async def GetCaptchaQuiz() -> dict:
    data = json.loads(gs_modolCaptch)
    data = SetSign(data)
    return await SendPost(bililogin + "api/client/start_captcha", data)


async def TryLogin(biliAccount:str, biliPassword:str, qqid:int = None, access_key = '', uid = '') -> dict:
    """
    根据传入的账号和密码尝试登录。登录成功则返回登录信息，失败则抛出异常。

    Args:
        biliAccount (str): 账号。目前只支持ASCII字符。
        biliPassword (str): 密码。只支持ASCII字符。

    Raises:
        Exception: 用户名或密码错误
        CaptchaVerifier中可能抛出的异常

    Returns:
        dict: {"access_key": str, "code": int, "uid": int | str, ...}
    """
    
    loginSta = await TryLoginWithoutCaptcha(biliAccount, biliPassword, access_key, uid)
    if loginSta.get("message", "") == "用户名或密码错误":
        raise Exception("用户名或密码错误")

    if "access_key" in loginSta:
        return loginSta

    # if gs_otto:
    #     try:
    #         res = await GetValidate()
    #     except Exception as e:
    #         print_exc()
    #         print(f'Fail. 使用新过码API(token[{gs_token}])失败：{e}')
    #     else:
    #         return await TryLoginWithCaptcha(biliAccount, biliPassword, res["challenge"], res['gt_user'], res['validate'], access_key)

    try:
        cap = await SendPost(bililogin + "api/client/start_captcha", SetSign(json.loads(gs_modolCaptch)))
        challenge, gt_user_id, validate_key = await autoCaptchaVerifier(cap['gt'], cap['challenge'], cap['gt_user_id'])
        return await TryLoginWithCaptcha(biliAccount, biliPassword, challenge, gt_user_id, validate_key, access_key, uid)
    except:
        cap:dict = await GetCaptchaQuiz()  # start_captcha_input
        validateKey = await CaptchaVerifier(cap['challenge'], cap['gt'], cap['gt_user_id'], qqid)
        return await TryLoginWithCaptcha(biliAccount, biliPassword, cap["challenge"], cap['gt_user_id'], validateKey, access_key, uid)



async def GetValidate():
    async with httpx.AsyncClient() as client:
        url = f'https://:{gs_token}@pcr-bilibili-api.cn.linepro6.com:843/geetest-captcha/validate'
        response = await client.get(url, timeout=60)
        response.raise_for_status()
        res = json.loads(response.text)
        assert res.get("code", -1) == 0, f'访问/geetest-captcha/validate失败：{res}'
        return res["data"]