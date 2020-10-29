import time

import visa


class GaussMeterOverRangeError(Exception):
    pass


class GaussMeter:
    def __init__(self) -> None:
        self.__gs = visa.ResourceManager().open_resource("ASRL3::INSTR")  # linux "ASRL/dev/ttyUSB0::INSTR"

    def __query(self, command: str) -> str:
        res = self.__gs.query(command)
        return res.strip("\r\n")

    def __write(self, command: str) -> None:
        self.__gs.write(command)

    def magnetic_field_fetch(self) -> float:
        """磁界の値を測定機器に問い合わせ,Gauss単位で返す

        :return: 磁界の値(Gauss)
        :rtype float
        """
        try:
            res = float(self.__query("FIELD?"))
        except ValueError:  # オーバーレンジ発生時の挙動
            range = self.range_fetch()
            if range == 0:  # 30kOe以上の挙動
                raise GaussMeterOverRangeError()
            self.range_set(range - 1)
            return self.magnetic_field_fetch()
        multiplier = self.__query("FIELDM?")
        if multiplier == "m":
            res = float(res) * 10 ** (-3)
        elif multiplier == "k":
            res = float(res) * 1000
        else:
            pass
        return res


def readable_magnetic_field_fetch(self) -> str:
    """磁界の値を測定機器に問い合わせ,人間が読みやすい形で返す

    :return: 磁界の値
    :rtype str
    """
    field_str = self.__query("FIELD?") + self.__query("FIELDM?") + self.__query("UNIT?")
    return field_str


def range_set(self, range_index: int) -> None:
    """
    レンジを切り替える
    0:~30.00 kOe
    1:~3.000 kOe
    2:~300.0 Oe
    3:~30.00 Oe
    :param range_index:
    :return:
    """
    if range_index < 0 or range_index > 3:
        range_index = 0
    self.__write("RANGE " + str(range_index))
    time.sleep(0.2)
    return


def range_fetch(self) -> int:
    return int(self.__query("RANGE?"))
