import visa


class GaussMeter:
    def __init__(self):
        self._gs = visa.ResourceManager().open_resource("ASRL3::INSTR")

    def _query(self, command):
        print(command)
        res = self._gs.query(command + "\r\n")
        return res

    def magnetic_field_fetch(self):
        res = self._query("FIELD?")
        return res

    def set_query(self, command):
        w = self._query(command)
        print(w)
