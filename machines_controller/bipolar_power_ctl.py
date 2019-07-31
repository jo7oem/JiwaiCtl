import time
import typing

import visa


class Current(object):
    def __init__(self, current: typing.SupportsFloat = 0, unit: str = "mA"):

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
        return Current(current=self.mA() + int(other), unit="mA")

    def __sub__(self, other):
        return Current(current=self.mA() - int(other), unit="mA")

    def __mul__(self, other):
        return Current(current=round(self.mA() * float(other)), unit="mA")

    def __int__(self):
        return self.mA()

    def set_mA(self, current: int):
        self.__current = current

    def set_A(self, current: float):
        self.__current = float(current) * 1000

    def __str__(self) -> str:
        if abs(self.__current) >= 1000:
            return str(self.A()) + " A"
        else:
            return str(self.mA()) + " mA"

    def __lt__(self, other):
        return self.mA() < int(other)

    def __gt__(self, other):
        return self.mA() > int(other)

    def __le__(self, other):
        return self.mA() <= int(other)

    def __ge__(self, other):
        return self.mA() >= int(other)

    def __eq__(self, other):
        return self.mA() == int(other)

    def __abs__(self):
        return abs(self.mA())


class BipolarPower:
    def __init__(self):
        self.__gs = visa.ResourceManager().open_resource("GPIB0::4::INSTR")  # linux "ASRL/dev/ttyUSB0::INSTR"
        self.CURRENT_CHANGE_LIMIT = Current(500, "mA")
        self.CURRENT_CHANGE_DELAY = 0.5

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
        current, unit = self.__query("IOUT?").split(" ")
        return Current(current=current, unit=unit)

    def iset_fetch(self):
        current, unit = self.__query("ISET?").split(" ")
        return Current(current=current, unit=unit)

    def __set_iout(self, current):
        self.__query(str(current))

    def set_iout(self, current):
        now_iout = self.iout_fetch()
        if now_iout == current:
            return
        if current.mA() - now_iout.mA() > 0:
            current_list = range(now_iout.mA(), current.mA(), self.CURRENT_CHANGE_LIMIT.mA())
        else:
            current_list = range(now_iout.mA(), current.mA(), -self.CURRENT_CHANGE_LIMIT.mA())
        for i in current_list:
            self.__set_iout(Current(i, "mA"))
            time.sleep(self.CURRENT_CHANGE_DELAY)
        self.__set_iout(current)
        time.sleep(self.CURRENT_CHANGE_DELAY)

    def allow_output(self, operation: bool):
        now_output = self.check_allow_output()
        if now_output == operation:
            return
        iset = self.iset_fetch()
        if iset != 0:
            if not now_output:
                self.__set_iout(Current(0, "mA"))
            else:
                self.set_iout(Current(0, "mA"))
        time.sleep(0.1)
        if operation:
            self.__write("OUT 1")
        else:
            self.__write("OUT 0")
        time.sleep(0.1)
        if self.check_allow_output() == operation:
            return
        raise OSError
