import datetime
import time
from logging import DEBUG, ERROR, WARNING
from typing import Union, List

from JiwaiCtl import logger, power, magnet_field_ctl, load_status, save_status, demag, gen_csv_header
from machines_controller.bipolar_power_ctl import Current


class MeasureSetting:  # 33#
    force_demag: bool = False  # 測定前に消磁を強制するかどうか
    verified: bool = False  # 測定シークエンスが検証済みか
    control_mode: str = "oectl"  # 制御モード "oectl":磁界制御, "current":電流制御

    measure_sequence = [[]]  # 測定シークエンス

    pre_lock_sec: float = 1.5  # 磁界設定後に状態を記録するまでの時間
    post_lock_sec: float = 1.5  # 状態を記録してから状態をロックする時間

    pre_block_sec: float = 10  # 測定シークエンスを開始する前に0番目の設定磁界でブロックする時間
    pre_block_td: datetime.timedelta = datetime.timedelta(seconds=10)
    post_block_sec: float = 10  # 最後の測定条件で記録してからBG補正用に同じ測定条件でブロックする時間
    post_block_td: datetime.timedelta = datetime.timedelta(seconds=10)
    blocking_monitoring_sec: float = 5  # ブロック動作を行っているときにモニタリングを行う間隔
    blocking_monitoring_td: datetime.timedelta = datetime.timedelta(seconds=5)

    # 以下状態管理変数
    have_error: bool = False

    is_cached: bool = False
    cached_sequence = [[]]

    @staticmethod
    def log_key_notfound(key: str, level: int = DEBUG) -> None:
        logger.log(level, "[{0}] キーが見つかりません".format(key))
        return

    @staticmethod
    def log_invalid_value(key: str, val: str, level: int = DEBUG) -> None:
        logger.log(level, "[{0}] キーの設定値が不正 : 入力値 = {1}".format(key, val))
        return

    @staticmethod
    def log_2small_value(key: str, val: Union[int, float], minimum: Union[int, float], level: int = DEBUG) -> None:
        logger.log(level, "[{0}] キーの設定値が小さい : 最低値 = {2} ,入力値 = {1} = {1}".format(key, val, minimum))
        return

    @staticmethod
    def log_use_default(key: str, val: Union[int, float, str]) -> None:
        logger.warning("[{0}] キーが未定義 初期値を使用 : {1}".format(key, val))
        return

    def __init__(self, seq_dict=None):
        if seq_dict is None:
            return
        # 必須項目
        if (key := "seq") in seq_dict:
            self.measure_sequence = seq_dict[key]
        else:
            self.log_key_notfound(key, ERROR)
            self.have_error = True

        if (key := "control") in seq_dict:
            mode = seq_dict[key]
            if "oectl" in mode:
                self.control_mode = "oectl"
            elif "current" in mode:
                self.control_mode = "current"
            else:
                self.log_invalid_value(key, seq_dict[key], ERROR)
                self.have_error = True
        else:
            self.log_key_notfound(key, ERROR)
            self.have_error = True

        # options
        # 隠しキー TODO:HASH式に切り替える
        if (key := "verified") in seq_dict:
            try:
                self.verified = bool(seq_dict[key])
            except ValueError:
                self.log_invalid_value(key, seq_dict[key], WARNING)

        if (key := "pre_lock_sec") in seq_dict:
            minimum = 0.1
            try:
                val = float(seq_dict[key])
            except ValueError:
                self.log_invalid_value(key, seq_dict[key], WARNING)
                self.verified = False
            else:
                if val < minimum:
                    self.log_2small_value(key, val, minimum, WARNING)
                    self.verified = False
                else:
                    self.pre_lock_sec = val
        else:
            self.log_use_default(key, self.pre_lock_sec)

        if (key := "post_lock_sec") in seq_dict:
            minimum = 0.1
            try:
                val = float(seq_dict[key])
            except ValueError:
                self.log_invalid_value(key, seq_dict[key], WARNING)
                self.verified = False
            else:
                if val < minimum:
                    self.log_2small_value(key, val, minimum, WARNING)
                    self.verified = False
                else:
                    self.post_lock_sec = val
        else:
            self.log_use_default(key, self.post_lock_sec)

        if (key := "pre_block_sec") in seq_dict:
            minimum = 0.2
            try:
                val = float(seq_dict[key])
            except ValueError:
                self.log_invalid_value(key, seq_dict[key], WARNING)
                self.verified = False
            else:
                if val < minimum:
                    self.log_2small_value(key, val, minimum, WARNING)
                    self.verified = False
                else:
                    self.pre_block_sec = val
                    self.pre_block_td = datetime.timedelta(seconds=val)
        else:
            self.log_use_default(key, self.pre_block_sec)

        if (key := "post_block_sec") in seq_dict:
            minimum = 0.2
            try:
                val = float(seq_dict[key])
            except ValueError:
                self.log_invalid_value(key, seq_dict[key], WARNING)
                self.verified = False
            else:
                if val < minimum:
                    self.log_2small_value(key, val, minimum, WARNING)
                    self.verified = False
                else:
                    self.post_block_sec = val
                    self.post_block_td = datetime.timedelta(seconds=val)
        else:
            self.log_use_default(key, self.post_block_sec)

        if (key := "blocking_monitoring_sec") in seq_dict:
            minimum = 1
            try:
                val = float(seq_dict[key])
            except ValueError:
                self.log_invalid_value(key, seq_dict[key], WARNING)
                self.verified = False
            else:
                if val < minimum:
                    self.log_2small_value(key, val, minimum, WARNING)
                    self.verified = False
                else:
                    self.blocking_monitoring_sec = val
                    self.blocking_monitoring_td = datetime.timedelta(seconds=val)
        else:
            self.log_use_default(key, self.blocking_monitoring_sec)

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

        self.measure_lock_record(measure_seq[0], self.pre_lock_sec, 0, start_time, save_file)
        origin_time = datetime.datetime.now()
        next_time = origin_time + self.blocking_monitoring_td
        pre_block_end_time = origin_time + self.pre_block_td
        last_time = pre_block_end_time - self.blocking_monitoring_td

        while next_time > last_time:
            while datetime.datetime.now() < next_time:
                time.sleep(0.2)
            self.measure_lock_record(measure_seq[0], 0, 0, start_time, save_file)
            next_time = next_time + self.blocking_monitoring_td
        else:
            while datetime.datetime.now() < pre_block_end_time:
                time.sleep(0.2)
            self.measure_lock_record(measure_seq[0], 0, 0, start_time, save_file)

        for target in measure_seq:
            self.measure_lock_record(target, self.pre_lock_sec, self.post_lock_sec, start_time, save_file)

        origin_time = datetime.datetime.now()
        next_time = origin_time + self.blocking_monitoring_td
        post_block_end_time = origin_time + self.post_block_td
        last_time = post_block_end_time - self.blocking_monitoring_td

        while next_time > last_time:
            while datetime.datetime.now() < next_time:
                time.sleep(0.2)
            self.measure_lock_record(measure_seq[-1], 0, 0, start_time, save_file)
            next_time = next_time + self.blocking_monitoring_td
        else:
            while datetime.datetime.now() < post_block_end_time:
                time.sleep(0.2)
            self.measure_lock_record(measure_seq[-1], 0, 0, start_time, save_file)

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
        if self.have_error:
            logger.error("設定ファイルに致命的な問題あり")
            self.verified = False
            return
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
