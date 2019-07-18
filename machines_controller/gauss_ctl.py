import visa


class GaussMeter:
    def __init__(self):
        self.__gs = visa.ResourceManager().open_resource("ASRL3::INSTR")  # linux "ASRL/dev/ttyUSB0::INSTR"

    def __query(self, command: str) -> None:
        res = self.__gs.query(command)
        res.translate(str.maketrans('', '', ' \r\n'))
        return res

    def __write(self, command: str) -> None:
        self.__gs.write(command)

    def magnetic_field_fetch(self) -> int:
        """磁界の値を測定機器に問い合わせ,1Gauss単位で返す

        :return: 磁界の値(Gauss)
        :rtype int
        """

        res = self.__query("FIELD?")
        multiplier = self.__query("FIELDM?")
        if multiplier == "m":
            res = res * 10 ** (-3)
        elif multiplier == "k":
            res = res * 1000
        else:
            pass

        return round(res)

    def set_query(self, command):
        w = self.__query(command)
        print(w)

    def readable_magnetic_field_fetch(self) -> str:
        """磁界の値を測定機器に問い合わせ,人間が読みやすい形で返す

        :return: 磁界の値
        :rtype str
        """
        field_str = self.__query("FIELD?") + self.__query("FIELDM?") + self.__query("UNIT?")
        return field_str

    def range_set(self, range_index: int) -> None:
        if range_index < 0 or range_index > 3:
            range_index = 0
        self.__write("RANGE " + str(range_index))
        return
