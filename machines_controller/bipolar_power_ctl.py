import typing

import visa


class Current(object):
    def __init__(self, current: typing.SupportsFloat, unit: str):
        if unit in ["mA", "ma", "MA", "Ma"]:
            self.__current = round(float(current))
        elif unit in ["A", "a"]:
            self.__current = round(float(current) * 1000)
        else:
            raise ValueError

    def mA(self) -> int:
        return self.__current

    def A(self) -> float:
        return float(self.__current) / 1000.0

    def __add__(self, other):
        return self.__current + int(other)

    def __sub__(self, other):
        return self.__add__(-int(other))

    def __mul__(self, other):
        return self.__current * other

    def __int__(self):
        return self.mA()

    def set_mA(self, current: int):
        self.__current = current

    def set_A(self, current: float):
        self.__current = float(current) * 1000



class BipolarPower:
    def __init__(self):
        self.__gs = visa.ResourceManager().open_resource("GPIB0::4::INSTR")  # linux "ASRL/dev/ttyUSB0::INSTR"

    def __query(self, command: str) -> str:
        res = self.__gs.query(command)
        res.translate(str.maketrans('', '', '\r\n'))
        return res

    def __write(self, command: str) -> None:
        self.__gs.write(command)

    def check_allow_output(self) -> bool:
        if self.__query("OUT?") == 'OUT 001\r\n':
            return True
        return False

    def __allow_output(self, allow: bool) -> None:
        if allow:
            self.__write("OUT 1")
        else:
            self.__write("OUT 0")
        return

    def iout_fetch(self):
        current, unit = self.__query("ISET?").split(" ")

    def allow_output(self, operation: bool):
        now_output = self.check_allow_output()
        if now_output == operation:
            return
        iset = FetchIset()
        if iset != 0:
            if not now_output:
                SetIset(0)
            else:
                ctl_iout_ma(0)
        time.sleep(0.1)
        if operation:
            power.write("OUT 1")
        else:
            power.write("OUT 0")
        time.sleep(0.1)
        if CanOutput() == operation:
            return
        raise ControlError("バイポーラ電源出力制御失敗")
