import datetime
import sys
import time

import pyvisa

import machines_controller.bipolar_power_ctl as visa_bp
import machines_controller.gauss_ctl as visa_gs
from machines_controller.bipolar_power_ctl import Current

HELM_Oe2CURRENT_CONST = 20.960 / 1000  # ヘルムホルツコイル用磁界電流変換係数 mA換算用


class StatusList:
    iset = 0.0
    iout = 0.0
    field = 0.0
    vout = 0.0
    loadtime = datetime.datetime
    diff_second = 0

    def __str__(self):
        return "{:03} sec ISET= {:+.3f} A\tIOUT= {:+.3f}A\tField= {:+.1f} G\tVOUT= {:+.3f} ".format(
            self.diff_second, self.iset, self.iout,
            self.field, self.vout)

    def set_origine_time(self, start_time: datetime.datetime):
        self.loadtime = datetime.datetime.now()
        self.diff_second = (self.loadtime - start_time).seconds

    def out_tuple(self) -> tuple:
        return self.diff_second, self.iset, self.iout, self.field, self.vout


def load_status(iout=True, iset=True, vout=True, field=True) -> StatusList:
    """
    各ステータスをまとめて取得する

    --------
    :return: StatusList
    """
    result = StatusList()
    if iout:
        result.iout = power.iout_fetch().A()
    if iset:
        result.iset = power.iset_fetch().A()
    if vout:
        result.vout = power.vout_fetch()
    if field:
        result.field = gauss.magnetic_field_fetch()
    return result


def magnet_field_ctl(target: int, auto_range=False):
    global CONNECT_MAGNET
    next_range = 0
    if CONNECT_MAGNET == "ELMG":
        if auto_range:
            now_range = gauss.range_fetch()
            if abs(target) >= 2500:
                next_range = 0
            elif abs(target) >= 250:
                next_range = 1
            else:
                next_range = 2
            if now_range == next_range:
                pass
            elif now_range > next_range:
                pass
            else:
                gauss.range_set(next_range)
                auto_range = False
        now_field = gauss.magnetic_field_fetch()
        diff_field = target - now_field
        looplimit = 5
        if diff_field > 0:
            is_diff_field_up = True
        else:
            is_diff_field_up = False

        while (is_diff_field_up and diff_field >= 0) or (not is_diff_field_up and diff_field <= 0):
            looplimit -= 1
            now_current = power.iset_fetch()
            next_current = Current(now_current.mA() + (diff_field) * 1)
            power.set_iset(next_current)
            time.sleep(0.2)
            now_field = gauss.magnetic_field_fetch()
            diff_field = target - now_field
            if looplimit == 0:
                break
            if auto_range:
                gauss.range_set(next_range)
                auto_range = False
            continue
        return
    elif CONNECT_MAGNET == "HELM":
        global HELM_Oe2CURRENT_CONST
        if not target <= 110:
            target = 100
        target_current = Current(int(target / HELM_Oe2CURRENT_CONST), "mA")
        power.set_iset(target_current)
        return
    else:
        raise ValueError


def print_status():
    print(load_status())
    return


def cmdlist():
    print("comandlist thi is mock")


def power_ctl(cmd):
    if len(cmd) == 0:
        return
    req = cmd[0]
    if req == "status":
        print("ISET=" + str(power.iset_fetch()) + "\tIOUT=" + str(power.iout_fetch()) + "\tVOUT=" + str(
            power.vout_fetch()) + "V")
        return
    elif req == "iout":
        print("IOUT=" + str(power.iout_fetch()))
        return
    elif req == "iset":
        print("ISET=" + str(power.iset_fetch()))
        return
    elif req == "iout":
        print("IOUT=" + str(power.vout_fetch()) + "V")
        return
    elif req in {"iset", "set"}:
        if len(cmd) == 1:
            print("Missing paramator")
            return
        if len(cmd) >= 3:
            unit = cmd[2]
        else:
            unit = "mA"
        try:
            current = (Current(cmd[1], unit=unit))
        except ValueError:
            print("Command Value is Missing."
                  "ex) 400 mA or 4.2 A")
            return
        power.set_iset(current)
        return
    else:
        print("HELP Mock")
        return


def gauss_ctl(cmd):
    req = cmd[0]
    if req == "status":
        res = gauss.readable_magnetic_field_fetch()
        print(res)
        return
    elif req == "range":
        if len(cmd) >= 2:
            try:
                range_index = int(cmd[1])
            except ValueError:
                print("ValueError")
                return
            gauss.range_set(range_index)
        else:
            res = gauss.range_fetch()
            print("Gauss range is " + str(res))
            return
    else:
        print("HELP Mock")
        return


def Oe_ctl(cmd, auto_range):
    target = cmd[0]
    unit = ""
    if cmd[1]:
        unit = cmd[1]
    try:
        if unit == "k":
            target = int(float(target) * 1000)
        else:
            target = int(target)
    except ValueError:
        print("ValeError!")
        return
    magnet_field_ctl(target, auto_range=auto_range)
    return


def main():
    auto_range = False
    while True:
        request = input(">>>").lower().split(" ")
        cmd = request[0]
        if cmd in {"h", "help", "c", "cmd", "command"}:
            cmdlist()
            continue
        elif cmd in {"quit", "exit", "end"}:
            break
        elif cmd in {"status"}:
            print_status()
            continue
        elif cmd in {"powerctl"}:
            power_ctl(request[1:])
            continue
        elif cmd in {"gaussctl"}:
            gauss_ctl(request[1:])
            continue
        elif cmd in {"oectl"}:
            Oe_ctl(request[1:], auto_range)
            continue
        elif cmd in {"autorange"}:
            auto_range = not auto_range
            print("Auto Range is " + str(auto_range))

        else:
            print("""invaild command\nPlease type "h" or "help" """)
            continue


def search_magnet():
    global CONNECT_MAGNET
    power.set_iset(Current(200, "mA"))
    time.sleep(0.2)
    if power.vout_fetch() / power.iout_fetch().A() > 4:
        print("Support Magnet Field is +-4kOe")
        power.CURRENT_CHANGE_LIMIT = Current(300, "mA")
        CONNECT_MAGNET = "ELMG"
        return
    else:
        print("Support Magnet Field is +-200Oe")
        power.CURRENT_CHANGE_DELAY = 0.3
        CONNECT_MAGNET = "HELM"
        return


def init():
    gauss.range_set(0)
    power.set_iset(Current(0, "mA"))


CONNECT_MAGNET = ""

if __name__ == '__main__':
    while True:
        try:
            gauss = visa_gs.GaussMeter()
        except pyvisa.Error:
            print("[ERROR]\tガウスメーター接続失敗")
            ans = input("R:リトライ. f:無視. q:終了 >")
            if ans in {"f", "F"}:
                break
            elif ans in {"q", "Q"}:
                sys.exit(1)
            else:
                continue
        else:
            break
    while True:
        try:
            power = visa_bp.BipolarPower()
        except pyvisa.Error:
            print("[ERROR]\tバイポーラ電源接続失敗")
            ans = input("R:リトライ. f:無視. q:終了 >")
            if ans in {"f", "F"}:
                break
            elif ans in {"q", "Q"}:
                sys.exit(1)
            else:
                continue
        else:
            break
    gauss.range_set(0)
    power.allow_output(True)
    search_magnet()
    init()
    try:
        main()
    except Exception as e:
        import traceback

        print(traceback.format_exc())

    finally:
        init()
        power.allow_output(False)
