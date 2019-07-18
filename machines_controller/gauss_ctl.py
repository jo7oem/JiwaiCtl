import visa


class GaussMeter:
    def __init__(self):
        self._gs = visa.ResourceManager().open_resource("ASRL3::INSTR")  # linux "ASRL/dev/ttyUSB0::INSTR"

    def _query(self, command):
        res = self._gs.query(command)
        res.translate(str.maketrans('', '', ' \r\n'))
        return res

    def magnetic_field_fetch(self) -> int:
        """磁界の値を測定機器に問い合わせ,1Gauss単位で返す

        :return: 磁界の値(Gauss)
        :rtype int
        """

        res = self._query("FIELD?")
        multiplier = self._query("FIELDM?")
        if multiplier == "m":
            res = res * 10 ** (-3)
        elif multiplier == "k":
            res = res * 1000
        else:
            pass

        return round(res)

    def set_query(self, command):
        w = self._query(command)
        print(w)
