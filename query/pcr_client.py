from ._pcr_client import PcrClient
from ..autopcr_db.typing import *
from typing import Dict, Union

_g_pcrClients: Dict[str, PcrClient] = {}

class PcrClientManager:
    @staticmethod
    def FromStr(account: str, password: str, qqid: int = None, access_key = '', uid = '', clean_cache = False) -> PcrClient:
        """
        若PCR账号名有记录，且密码相同：返回当前记录对象。
        若PCR账号名有记录，但密码不同：则重置对象并返回。
        若PCR账号名无记录：新建并返回一个PcrClient对象。

        Args:
            account (str): PCR账号
            password (str): PCR密码

        Raises:
            AssertionError: account或password为空

        Returns:
            PcrClient: PcrClient对象
        """
        assert len(account), "账号名为空"
        assert len(password), "密码为空"

        if account in _g_pcrClients and not clean_cache:
            if _g_pcrClients[account].biliSdkClient.password == password:
                return _g_pcrClients[account]

        _g_pcrClients[account] = PcrClient(account, password, qqid=qqid, access_key = access_key, uid = uid)
        return _g_pcrClients[account]
        
        
    @staticmethod        
    def FromDict(accountInfo: dict, clean_cache: bool = False) -> PcrClient:
        """
        若PCR账号名无记录：新建并返回一个PcrClient对象。
        若PCR账号名有记录，但密码不同：则重置对象并返回。
        若PCR账号名有记录，且密码相同：返回当前记录对象。

        Args:
            accountInfo (dict): PCR账号信息 {"account": str, "password": str, qqid: int = None}

        Raises:
            AssertionError: 未传入account或password字段或对应value为空

        Returns:
            PcrClient: PcrClient对象
        """
        
        assert "account" in accountInfo, "未传入account字段"
        assert "password" in accountInfo, "未传入password字段"
        
        return PcrClientManager.FromStr(accountInfo["account"], accountInfo["password"], accountInfo.get("qqid", None), accountInfo.get("access_key", ''), accountInfo.get("uid", ''), clean_cache)
    

    @staticmethod        
    def FromRecord(accountInfo: PcrAccountInfo) -> PcrClient:
        """
        若PCR账号名无记录：新建并返回一个PcrClient对象。
        若PCR账号名有记录，但密码不同：则重置对象并返回。
        若PCR账号名有记录，且密码相同：返回当前记录对象。

        Args:
            accountInfo (PcrAccountInfo): PCR账号数据库记录

        Raises:
            AssertionError: 该记录被标记为不合法

        Returns:
            PcrClient: PcrClient对象
        """
        
        assert accountInfo.is_valid, "该记录被标记为不合法"
        return PcrClientManager.FromStr(accountInfo.account, accountInfo.password)


    @staticmethod        
    def FromPcrid(pcrid: int) -> PcrClient:
        """
        在数据库中查找pcrid对应的账号密码记录
        若PCR账号名无记录：新建并返回一个PcrClient对象。
        若PCR账号名有记录，但密码不同：则重置对象并返回。
        若PCR账号名有记录，且密码相同：返回当前记录对象。

        Args:
            pcrid (int): PCRID

        Raises:
            AssertionError: 记录不存在或被标记为不合法

        Returns:
            PcrClient: PcrClient对象
        """
        
        pcrAccountInfo = PcrAccountInfo.get_or_none(PcrAccountInfo.pcrid == pcrid)
        assert pcrAccountInfo is not None, "记录不存在"
        return PcrClientManager.FromRecord(pcrAccountInfo)

    @staticmethod
    def Get(accountInfo: Union[dict, int, PcrAccountInfo]) -> PcrClient:
        if isinstance(accountInfo, dict):
            return PcrClientManager.FromDict(accountInfo)
        if isinstance(accountInfo, int):
            return PcrClientManager.FromPcrid(accountInfo)
        if isinstance(accountInfo, PcrAccountInfo):
            return PcrClientManager.FromRecord(accountInfo)
        raise TypeError(f'[PcrClientManager.Get]参数[accountInfo]类型[{type(accountInfo)}]不合法')