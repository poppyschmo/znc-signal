import traceback  # noqa: F401
from enum import Enum

CONTINUE = None


class ModuleNV(dict):
    def __setitem__(self, key, value):
        if not isinstance(value, str) or not isinstance(key, str):
            raise NotImplementedError(
                "Wrong number or type of arguments for "
                "overloaded function 'CModule_SetNV'"
            )
        super().__setitem__(key, value)


class Module:

    def GetClient(self):
        return CClient()

    def GetSavePath(self):
        raise NotImplementedError

    def GetModName(self):
        return self.__class__.__name__


class Socket: pass  # noqa: E701


class CClient:
    def GetFullName(self):
        pass


def fake_getmoddirs():
    return [".", ".."]


class CModules:
    GetModDirs = fake_getmoddirs


class String:
    def __init__(self, s):
        self.s = s


def CZNC_GetVersion():
    return "1.6.6"


class CModInfo(Enum):
    GlobalModule = 0
    UserModule = 1
    NetworkModule = 2


def CModInfo_ModuleTypeToString(t):
    return CModInfo(t).name.replace("Module", "")
