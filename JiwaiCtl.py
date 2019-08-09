import csv
import datetime
import json
import sys
import time

import pyvisa

import machines_controller.bipolar_power_ctl as visa_bp
import machines_controller.gauss_ctl as visa_gs
from machines_controller.bipolar_power_ctl import Current

HELM_Oe2CURRENT_CONST = 20.960 / 1000  # ヘルムホルツコイル用磁界電流変換係数 mA換算用
HELM_MANGET_FIELD_LIMIT = 150
ELMG_MAGNET_FIELD_LIMIT = 4150
MESURE_SEQUENCE = {}
MESURE_SEQUENCE_VERIFY = False


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


def magnet_field_ctl(target: int, auto_range=False) -> Current:
    next_range = 0
    if CONNECT_MAGNET == "ELMG":
        if target > ELMG_MAGNET_FIELD_LIMIT:
            print("[Error]\t磁界制御入力値過大")
            print("最大磁界4.1kOe")
            raise ValueError
        now_range = gauss.range_fetch()
        if auto_range:
            if abs(target) >= 2500:
                next_range = 0
            elif abs(target) >= 250:
                next_range = 1
            else:
                next_range = 2
            if now_range == next_range:
                auto_range = False
                pass
            elif now_range < next_range:
                pass
            else:
                gauss.range_set(next_range)
                now_range = next_range
                time.sleep(0.5)
                auto_range = False
        now_field = gauss.magnetic_field_fetch()
        diff_field = target - now_field
        now_current = power.iset_fetch()
        looplimit = 8
        if diff_field > 0:
            is_diff_field_up = True
        else:
            is_diff_field_up = False
        elmg_const = 1.0 - 0.16 * now_range
        next_current = Current(now_current.mA() + (diff_field) * elmg_const, "mA")
        while (is_diff_field_up and diff_field >= 1) or (not is_diff_field_up and diff_field <= -1):
            looplimit -= 1
            if now_current == next_current:
                return next_current
            power.set_iset(next_current)
            time.sleep(0.1)
            now_field = gauss.magnetic_field_fetch()

            if looplimit == 0:
                break
            if auto_range:
                if abs(now_field) >= 3000 and next_range == 0:
                    pass
                elif abs(now_field) >= 300 and next_range >= 1:
                    gauss.range_set(1)
                    now_range = 1
                    now_field = gauss.magnetic_field_fetch()
                    if next_range == 1:
                        auto_range = False

                elif abs(now_field) < 300 and next_range == 2:
                    gauss.range_set(2)
                    now_range = 2
                    now_field = gauss.magnetic_field_fetch()
                    auto_range = False

                else:
                    pass

            while True:
                time.sleep(0.1)
                palfield = gauss.magnetic_field_fetch()
                if palfield == now_field:
                    break
                now_field = palfield
            diff_field = target - now_field
            elmg_const = 1.0 - 0.16 * now_range
            now_current = power.iset_fetch()
            next_current = Current(now_current.mA() + (diff_field) * elmg_const, "mA")
            continue
        last_current = power.iset_fetch()
        return last_current
    elif CONNECT_MAGNET == "HELM":
        if target > HELM_MANGET_FIELD_LIMIT:
            print("[Error]\t磁界制御入力値過大")
            print("最大磁界200Oe")
            raise ValueError
        target_current = Current(int(target / HELM_Oe2CURRENT_CONST), "mA")
        power.set_iset(target_current)
        return target_current
    else:
        raise ValueError


def print_status():
    print(load_status())
    return


def cmdlist():
    print("comandlist thi is mock")


def load_mesure_sequence(filename: str):
    try:
        with open("./mesure_sequence/" + filename, "r") as f:
            seq = json.load(f)
    except json.JSONDecodeError:
        print("設定ファイルの読み込み失敗"
              "ファイルの存在と構造を確認してください")
        return
    global MESURE_SEQUENCE
    global MESURE_SEQUENCE_VERIFY
    MESURE_SEQUENCE = seq
    MESURE_SEQUENCE_VERIFY = False
    return


def gen_csv_header(filename) -> datetime:
    print("測定条件等メモ記入欄")
    memo = input("memo :")
    start_time = datetime.datetime.now()
    with open(filename, mode='a', encoding="utf-8")as f:
        writer = csv.writer(f, lineterminator='\n')
        writer.writerow(["開始時刻", start_time.strftime('%Y-%m-%d_%H-%M-%S')])
        writer.writerow(["memo", memo])
        writer.writerow(["#####"])
        writer.writerow(["経過時間[sec]", "設定電流:ISET[A]", "出力電流:IOUT[A]", "磁界:H[Gauss]", "出力電圧:VOUT[V]", "IFINE"])
    return start_time


def save_status(filename: str, status: StatusList) -> None:
    """
    ファイルにステータスを追記する

    --------
    :type status: dict{"iset":float,"iout":float,"ifield"}
    :param filename: 書き込むファイル名
    :param status: 書き込むデー   タ
    :return:
    """
    result = status.out_tuple()

    with open(filename, mode='a', encoding="utf-8")as f:
        writer = csv.writer(f, lineterminator='\n')
        writer.writerow(result)
    return


def mesure_process(mesure_setting, mesure_seq, start_time, save_file=None):
    pre_lock_time = mesure_setting["pre_lock_sec"]
    post_lock_time = mesure_setting["post_lock_sec"]
    for target in mesure_seq:
        if mesure_setting["control"] == "current":
            power.set_iset(Current(target, "mA"))
        elif mesure_setting["control"] == "oectl":
            magnet_field_ctl(target, True)
        else:
            print(mesure_setting["control"], "は不正な値")
            raise ValueError
        time.sleep(pre_lock_time)
        status = load_status()
        status.set_origine_time(start_time)
        print(status)
        if save_file:
            save_status(save_file, status)
        time.sleep(post_lock_time)
    return


def get_time_str() -> str:
    """
    現時刻を日本語に整形した文字列を返す
    ------------------------------
    :rtype: str
    :return: '2018-09-08 20:55:07'
    """
    return datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def mesure_test():
    operation = MESURE_SEQUENCE
    if "connect_to" not in operation:
        return
    if operation["connect_to"] != CONNECT_MAGNET:
        print("設定ファイルの種別が不一致")
        return
    if operation["demag"]:
        print("消磁中")
        demag()
        print("消磁完了")
    for seq in operation["seq"]:
        start_time = datetime.datetime.now()
        print("測定開始:", start_time.strftime('%Y-%m-%d %H:%M:%S'))
        try:
            mesure_process(operation, seq, start_time)
        except ValueError:
            print("測定値指定が不正です")
            return
    print("測定設定は検証されました。")
    global MESURE_SEQUENCE_VERIFY
    MESURE_SEQUENCE_VERIFY = True
    power.set_iset(Current(0, "mA"))
    return


def mesure():
    if not MESURE_SEQUENCE_VERIFY:
        print("設定ファイルの検証を行ってください。")
        return
    operation = MESURE_SEQUENCE
    if operation["demag"]:
        print("消磁中")
        demag()
        print("消磁完了")
    for seq in operation["seq"]:
        file = datetime.datetime.now().strftime('%Y-%m-%d_%H-%M-%S') + ".log"
        start_time = gen_csv_header(file)
        mesure_process(operation, seq, start_time, save_file=file)
    power.set_iset(Current(0, "mA"))


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
    if len(cmd) == 0:
        return
    target = cmd[0]
    unit = ""
    if len(cmd) >= 2:
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


def demag(step: int = 15):
    if CONNECT_MAGNET == "ELMG":
        max_current = magnet_field_ctl(4000, True)
    elif CONNECT_MAGNET == "HELM":
        max_current = magnet_field_ctl(100, True)
    else:
        raise ValueError
    diff_current = int(int(max_current) / step)
    current_seq = range(int(max_current), 0, -diff_current)
    flag = 1
    for i in current_seq:
        flag = flag * -1
        power.set_iset(Current(flag * i, "mA"))
        time.sleep(0.5)
    power.set_iset(Current(0, "mA"))
    return


def demag_cmd(cmd):
    if len(cmd) == 0:
        step = 15
    else:
        try:
            step = int(cmd[0])
        except ValueError:
            print("step数の指定が不正です。")
            return
    print("消磁開始")
    demag(step)
    print("消磁終了")
    return


def main():
    auto_range = False
    while True:
        request = input(">>>").lstrip(" ").lower().split(" ")
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

        elif cmd in {"demag"}:
            demag_cmd(request[1:])
            continue
        elif cmd in {"load"}:
            load_mesure_sequence(request[1])
            continue
        elif cmd in {"test"}:
            mesure_test()
            continue
        elif cmd in {"mesure"}:
            mesure()
            continue

        else:
            print("""invaild command\nPlease type "h" or "help" """)
            continue


def search_magnet():
    global CONNECT_MAGNET
    power.set_iset(Current(200, "mA"))
    time.sleep(0.2)
    resistance = power.vout_fetch() / power.iout_fetch().A()
    if resistance > 4:
        now = "ELMG"
    else:
        now = "HELM"
    power.allow_output(False)
    while True:
        print("接続先を入力してください。"
              "電磁石=>\"ELMG\"\tヘルムホルツ=>\"HELM\"")
        answer = input(">>>")
        if answer == now:
            break
        elif answer == "Force":
            print("強制接続先を入力してください。"
                  "電磁石=>\"ELMG\"\tヘルムホルツ=>\"HELM\"")
            force = input("###")
            if force == "ELMG":
                now = "ELMG"
                break
            elif force == "HELM":
                now = "HELM"
                break
            else:
                continue
        elif answer == "":
            continue
        else:
            print("接続先が不一致か入力内容が不正です。"
                  "接続先を強制するには\"Force\"と入力してください")
    power.allow_output(True)
    if now == "ELMG":
        print("Support Magnet Field is +-4kOe")
        power.CURRENT_CHANGE_LIMIT = Current(200, "mA")
        CONNECT_MAGNET = "ELMG"
        power.set_iset(Current(500, "mA"))
        time.sleep(0.5)
        resistance = power.vout_fetch() / power.iout_fetch().A()
        power.MAGNET_RESISTANCE = resistance
        return
    else:
        print("Support Magnet Field is +-200Oe")
        power.CURRENT_CHANGE_DELAY = 0.3
        CONNECT_MAGNET = "HELM"
        power.set_iset(Current(500, "mA"))
        time.sleep(0.2)
        resistance = power.vout_fetch() / power.iout_fetch().A()
        power.MAGNET_RESISTANCE = resistance
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
