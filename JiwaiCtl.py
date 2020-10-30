import csv
import datetime
import json
import os
import sys
import time
from typing import List
from typing import Union

import pyvisa

import machines_controller.bipolar_power_ctl as visa_bp
import machines_controller.gauss_ctl as visa_gs
from machines_controller.bipolar_power_ctl import Current

HELM_Oe2CURRENT_CONST = 20.960 / 1000  # ヘルムホルツコイル用磁界電流変換係数 mA換算用
HELM_MAGNET_FIELD_LIMIT = 150
ELMG_MAGNET_FIELD_LIMIT = 4150


class MeasureSetting:  # 33#
    force_demag = False  # 測定前に消磁を強制するかどうか
    verified = False  # 測定シークエンスが検証済みか
    control_mode = "oectl"  # 制御モード "oectl":磁界制御, "current":電流制御

    measure_sequence = [[]]  # 測定シークエンス

    pre_lock_sec = 1.5  # 磁界設定後に状態を記録するまでの時間
    post_lock_sec = 1.5  # 状態を記録してから状態をロックする時間

    pre_block_sec = 10  # 測定シークエンスを開始する前に0番目の設定磁界でブロックする時間
    post_block_sec = 10  # 最後の測定条件で記録してからBG補正用に同じ測定条件でブロックする時間
    blocking_monitoring_sec = 5  # ブロック動作を行っているときにモニタリングを行う間隔

    # 以下状態管理変数
    is_cached = False
    cached_sequence = [[]]

    def __init__(self, seq_dict=None):
        if seq_dict is None:
            return
        # 必須項目
        if "seq" in seq_dict:
            self.measure_sequence = seq_dict["seq"]
        if "control" in seq_dict:
            mode = seq_dict["control"]
            if "oectl" in mode:
                self.control_mode = "oectl"
            elif "current" in mode:
                self.control_mode = "current"
            else:
                print("[control] の設定値が不正")

        # options
        if "verified" in seq_dict:
            self.verified = seq_dict["verified"]

        if "pre_lock_sec" in seq_dict:
            self.pre_lock_sec = seq_dict["pre_lock_sec"]
        if "post_lock_sec" in seq_dict:
            self.post_lock_sec = seq_dict["post_lock_sec"]

        if "pre_block_sec" in seq_dict:
            self.pre_block_sec = seq_dict["pre_block_sec"]
        if "post_block_sec" in seq_dict:
            self.post_block_sec = seq_dict["post_block_sec"]
        if "blocking_monitoring_sec" in seq_dict:
            self.blocking_monitoring_sec = seq_dict["blocking_monitoring_sec"]
        return

    def measure_lock_record(self, target: Union[float, int], pre_lock_time: float, post_lock_time: float,
                            start_time: datetime.datetime, save_file: str = None) -> Current:
        current = Current()
        if self.control_mode == "current":
            current = Current(target, "mA")
            power.set_iset(current)
        elif self.control_mode == "oectl":
            current = magnet_field_ctl(target, True)

        time.sleep(pre_lock_time)
        status = load_status()
        status.set_origin_time(start_time)
        status.target = target
        print(status)
        if save_file:
            save_status(save_file, status)
        time.sleep(post_lock_time)
        return current

    def measure_process(self, measure_seq: List[int], start_time: datetime.datetime,
                        save_file: str = None) -> None:
        """
        測定シークエンスに従って測定を実施する

        :param measure_seq: 測定シークエンス intのリスト
        :param start_time: 測定基準時刻
        :param save_file: ログファイル名
        """
        if self.control_mode == "current":
            power.set_iset(Current(measure_seq[0], "mA"))
        elif self.control_mode == "oectl":
            magnet_field_ctl(measure_seq[0], True)

        time.sleep(self.pre_lock_sec)
        status = load_status()
        status.set_origin_time(start_time)
        status.target = measure_seq[0]
        print(status)
        if save_file:
            save_status(save_file, status)

        if self.blocking_monitoring_sec <= 0.2:
            time.sleep(self.pre_block_sec)
        else:
            for _ in range(self.blocking_monitoring_sec, self.pre_block_sec, self.blocking_monitoring_sec):
                time.sleep(self.blocking_monitoring_sec - 0.2)
                status = load_status()
                status.set_origin_time(start_time)
                status.target = measure_seq[0]
                print(status)
                if save_file:
                    save_status(save_file, status)

            time.sleep(self.pre_block_sec % self.blocking_monitoring_sec)

        for target in measure_seq:
            self.measure_lock_record(target, self.pre_lock_sec, self.post_lock_sec, start_time, save_file)

        if self.blocking_monitoring_sec <= 0.2:
            time.sleep(self.post_block_sec)
        else:
            for _ in range(self.blocking_monitoring_sec, self.post_block_sec, self.blocking_monitoring_sec):
                time.sleep(self.blocking_monitoring_sec - 0.2)
                status = load_status()
                status.set_origin_time(start_time)
                status.target = measure_seq[-1]
                print(status)
                if save_file:
                    save_status(save_file, status)

            time.sleep(self.post_block_sec % self.blocking_monitoring_sec)

        status = load_status()
        status.set_origin_time(start_time)
        status.target = measure_seq[-1]
        print(status)
        if save_file:
            save_status(save_file, status)

        return

    def measure(self) -> None:
        """
        測定プログラム
        """
        if not self.verified:
            print("設定ファイルの検証を行ってください。")
            return
        if self.force_demag:
            print("消磁中")
            demag()
            print("消磁完了")
        loop = 0
        for seq in self.measure_sequence:
            loop += 1
            print("測定シーケンスに入ります Y/n s(kip)")
            r = input(">>>>>").lower()
            if r == "n":
                break
            if r == "s":
                continue
            file = datetime.datetime.now().strftime('%Y-%m-%d_%H-%M-%S') + ".log"
            file, start_time = gen_csv_header(file)
            self.measure_process(seq, start_time, save_file=file)
            print("測定完了")

        power.set_iset(Current(0, "mA"))
        return

    def measure_test(self) -> None:
        """
        測定設定ファイルを検証する
        """
        if self.force_demag:
            print("消磁中")
            demag()
            print("消磁完了")
        for seq in self.measure_sequence:
            start_time = datetime.datetime.now()
            print("測定開始:", start_time.strftime('%Y-%m-%d %H:%M:%S'))
            try:
                self.measure_process(seq, start_time)
            except ValueError:
                print("測定値指定が不正です")
                self.verified = False
                return
        print("測定設定は検証されました。")
        self.verified = True
        power.set_iset(Current(0, "mA"))
        return


MEASURE_SEQUENCE = MeasureSetting()  # 設定ファイル格納先


class StatusList:
    iset = 0.0
    iout = 0.0
    field = 0.0
    vout = 0.0
    target = 0.0
    loadtime = datetime.datetime
    diff_second = 0

    def __str__(self):
        return "{:03} sec ISET= {:+.3f} A\tIOUT= {:+.3f}A\tField= {:+.1f} G\tVOUT= {:+.3f} \tTarget= {:+03}".format(
            self.diff_second, self.iset, self.iout,
            self.field, self.vout, self.target)

    def set_origin_time(self, start_time: datetime.datetime) -> None:
        """
        経過時間表示のための基準時刻を設定する

        :param start_time: 基準時刻
        """
        self.loadtime = datetime.datetime.now()
        self.diff_second = (self.loadtime - start_time).seconds

    def out_tuple(self) -> tuple:
        return self.diff_second, self.iset, self.iout, self.field, self.vout, self.target


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
    """
    磁界制御を行う
    電磁石の場合は1 Oe -> 1 mA換算で電流を変化させる
    ヘルムホルツコイルの場合は磁界-電流変換式を用いる

    目標磁界に対応した電流値を最後に返す

    :param target: ターゲット磁界(Oe)
    :param auto_range: オートレンジを使用するか(電磁石のみ有効)
    :return: 最終電流

    :raise ValueError: 目標磁界が出力制限を超過する場合は命令を発行せずに例外を投げる
    """
    next_range = 0
    if CONNECT_MAGNET == "ELMG":  # 電磁石制御部
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
        loop_limit = 8
        if diff_field > 0:
            is_diff_field_up = True
        else:
            is_diff_field_up = False
        elmg_const = 1.0 - 0.16 * now_range
        next_current = Current(now_current.mA() + diff_field * elmg_const, "mA")
        while (is_diff_field_up and diff_field >= 1) or (
                not is_diff_field_up and diff_field <= -1):  # 目標磁界の1 Oe手前か超えたら制御成功とみなす
            loop_limit -= 1
            if now_current == next_current:
                return next_current
            power.set_iset(next_current)
            time.sleep(0.1)
            now_field = gauss.magnetic_field_fetch()

            if loop_limit == 0:
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
            next_current = Current(now_current.mA() + diff_field * elmg_const, "mA")
            continue
        last_current = power.iset_fetch()
        return last_current
    elif CONNECT_MAGNET == "HELM":  # ヘルムホルツコイル制御部
        if target > HELM_MAGNET_FIELD_LIMIT:
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
    print("""
    quit\t通常終了
    load FileName \t ./measure_sequence以下のFileNameの測定定義ファイルを読み込む
    test\t読み込んだ測定定義ファイルを検証する
    measure\t測定動作を行う
    demag\t消磁動作
    
    status\t電源,磁界の状態を表示
    gaussctl\tガウスメーター制御コマンド群
    powerctl\tバイポーラ電源制御コマンド群
    oectl 目標値 (単位)\t磁界制御
    """)


def load_measure_sequence(filename: str):
    json_path = "./measure_sequence/" + filename
    if not os.path.exists(json_path):
        print("File not found! :", filename)
        return
    try:
        with open(json_path, "r") as f:
            seq = json.load(f)
    except json.JSONDecodeError:
        print("設定ファイルの読み込み失敗"
              "JSONファイルの構造を確認してください")
        return
    if seq.get("connect_to") != CONNECT_MAGNET:
        print("設定ファイルの種別が不一致")
        return

    global MEASURE_SEQUENCE
    MEASURE_SEQUENCE = MeasureSetting(seq)
    return


def gen_csv_header(filename: str) -> (str, datetime.datetime):
    """
    ログのヘッダを書き込む

    :param filename:
    :return: 基準時刻
    """
    if not os.path.exists('logs'):
        os.mkdir('logs')
    file_path = "logs/" + filename
    print("測定条件等メモ記入欄")
    memo = input("memo :")
    start_time = datetime.datetime.now()
    with open(file_path, mode='a', encoding="utf-8")as f:
        writer = csv.writer(f, lineterminator='\n')
        writer.writerow(["開始時刻", start_time.strftime('%Y-%m-%d_%H-%M-%S')])
        writer.writerow(["memo", memo])
        writer.writerow(["#####"])
        writer.writerow(["経過時間[sec]", "設定電流:ISET[A]", "出力電流:IOUT[A]", "磁界:H[Gauss]", "出力電圧:VOUT[V]", "設定値[G or I]"])
    return file_path, start_time


def save_status(filename: str, status: StatusList) -> None:
    """
    ファイルにステータスを追記する

    --------
    :type status: StatusList
    :param filename: 書き込むファイル名
    :param status: 書き込むデータ
    :return: None
    """
    result = status.out_tuple()

    with open(filename, mode='a', encoding="utf-8")as f:
        writer = csv.writer(f, lineterminator='\n')
        writer.writerow(result)
    return


def get_time_str() -> str:
    """
    現時刻を日本語に整形した文字列を返す
    ------------------------------
    :rtype: str
    :return: '2018-09-08 20:55:07'
    """
    return datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def power_ctl(cmd: List[str]) -> None:
    """
    電源関連のコマンド

    :param cmd:入力コマンド文字列

    """
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

    elif req == "iout":
        print("IOUT=" + str(power.vout_fetch()) + "V")
        return
    elif req == "iset":
        print("ISET=" + str(power.iset_fetch()))
        if len(cmd) == 1:
            return
        if len(cmd) >= 4:
            unit = cmd[3]
        else:
            unit = "mA"
        try:
            current = (Current(float(cmd[1]), unit=unit))
        except ValueError:
            print("Command Value is Missing."
                  "ex) 400 mA or 4.2 A")
            return
        power.set_iset(current)
        return

    else:
        print("""
        status\t電源状態表示
        iset\t電流値設定[mA]表示
        iset set x mA 電流出力設定(強制 安全装置なし)
        
        """)
        return


def gauss_ctl(cmd: List[str]) -> None:
    """
    ガウスメーター関連のコマンド

    :param cmd:入力コマンド文字列
    """
    if len(cmd) == 0:
        return
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
        print("""
        status\t磁界表示
        range\t測定レンジ設定 indexの値はマニュアル参照
        ex) range -> 現在のレンジ表示
        ex) range 0 -> レンジを ~30kOeに設定
        """)
        return


def Oe_ctl(cmd: List[str], auto_range: bool = False) -> None:
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


def demag(step: int = 15, field_mode: bool = True):
    if CONNECT_MAGNET == "ELMG" and field_mode:
        max_current = magnet_field_ctl(4000, True)
    elif CONNECT_MAGNET == "ELMG" and (not field_mode):
        max_current = Current(4300, "mA")
    elif CONNECT_MAGNET == "HELM":
        max_current = magnet_field_ctl(100, True)
    else:
        raise ValueError
    flag = 1
    for i in range(0, step):
        print("Step: " + str(i + 1) + "/" + str(step))
        flag = flag * -1
        power.set_iset(Current(flag * (step - i) / step * max_current.mA(), "mA"))
        time.sleep(0.5)

    power.set_iset(Current(0, "mA"))
    return


def demag_cmd(cmd: List[str]) -> None:
    if len(cmd) == 0:
        step = 15
    else:
        try:
            step = int(cmd[0])
        except ValueError:
            print("step数の指定が不正です。")
            return
    print("消磁開始")
    demag(step, field_mode=True)
    print("消磁終了")
    return


def current_demag_cmd(cmd: List[str]) -> None:
    if len(cmd) == 0:
        step = 15
    else:
        try:
            step = int(cmd[0])
        except ValueError:
            print("step数の指定が不正です。")
            return
    print("消磁開始")
    demag(step, field_mode=False)
    print("消磁終了")
    return


def main() -> None:
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

        elif cmd in {"current_demag"}:
            current_demag_cmd(request[1:])
            continue
        elif cmd in {"demag"}:
            demag_cmd(request[1:])
            continue
        elif cmd in {"load"}:
            load_measure_sequence(request[1])
            continue
        elif cmd in {"test"}:
            MEASURE_SEQUENCE.measure_test()
            continue
        elif cmd in {"measure"}:
            MEASURE_SEQUENCE.measure()
            continue

        else:
            print("""invalid command\nPlease type "h" or "help" """)
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
        print("Support Magnet Field is +-100Oe")
        power.CURRENT_CHANGE_DELAY = 0.3
        CONNECT_MAGNET = "HELM"
        power.set_iset(Current(400, "mA"))
        time.sleep(0.2)
        resistance = power.vout_fetch() / power.iout_fetch().A()
        power.MAGNET_RESISTANCE = resistance
        gauss.range_set(2)
        return


def init() -> None:
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
        print(e)

    finally:
        init()
        power.allow_output(False)
