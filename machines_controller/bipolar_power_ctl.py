import visa


class BipolarPower:
    def __init__(self):
        self.__gs = visa.ResourceManager().open_resource("GPIB0::4::INSTR")  # linux "ASRL/dev/ttyUSB0::INSTR"

    def __query(self, command: str) -> str:
        res = self.__gs.query(command)
        res.translate(str.maketrans('', '', ' \r\n'))
        return res

    def __write(self, command: str) -> None:
        self.__gs.write(command)

    def check_allow_output(self) -> bool:
        if self.__query("OUT?") == 'OUT 001\r\n':
            return True
        return False
