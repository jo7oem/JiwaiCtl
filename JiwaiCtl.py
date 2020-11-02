import csv
import datetime
import hashlib
import json
import os
import sys
import time
from logging import DEBUG, ERROR, WARNING, INFO
from logging import getLogger, StreamHandler, Formatter, FileHandler
from typing import Union, List, Dict, Final

import pyvisa

import machines_controller.bipolar_power_ctl as visa_bp
import machines_controller.gauss_ctl as visa_gs
from machines_controller.bipolar_power_ctl import Current

LOGLEVEL = INFO
LOGFILE = "JiwaiCtl.log"
PRINT_LOGLEVEL = WARNING
# PRINT_LOGLEVEL = DEBUG

HELM_Oe2CURRENT_CONST: float = 20.960 / 1000  # ヘルムホルツコイル用磁界電流変換係数 mA換算用
HELM_MAGNET_FIELD_LIMIT: Final = 150
ELMG_MAGNET_FIELD_LIMIT: Final = 4150

OECTL_LOOP_LIMIT: int = 12
OECTL_BASE_COEFFICIENT: float = 0.96
OECTL_RANGE_COEFFICIENT: float = 0.12

DB_NAME: Final = "setting.db"


class MeasureSetting:  #
    force_demag: bool = False  # 測定前に消磁を強制するかどうか
    demag_step: int = 15
    control_mode: str = "oectl"  # 制御モード "oectl":磁界制御, "current":電流制御

    measure_sequence: List[List[Union[int, float]]] = [[]]  # 測定シークエンス

    pre_lock_sec: float = 1.5  # 磁界設定後に状態を記録するまでの時間
    post_lock_sec: float = 1.5  # 状態を記録してから状態をロックする時間

    pre_block_sec: float = 10  # 測定シークエンスを開始する前に0番目の設定磁界でブロックする時間
    pre_block_td: datetime.timedelta = datetime.timedelta(seconds=10)
    post_block_sec: float = 10  # 最後の測定条件で記録してからBG補正用に同じ測定条件でブロックする時間
    post_block_td: datetime.timedelta = datetime.timedelta(seconds=10)
    blocking_monitoring_sec: float = 5  # ブロック動作を行っているときにモニタリングを行う間隔
    blocking_monitoring_td: datetime.timedelta = datetime.timedelta(seconds=5)

    autorange: bool = False
    use_cache: bool = False

    # 以下状態管理変数
    verified: bool = False  # 測定シークエンスが検証済みか
    have_error: bool = False
    filepath: str = None

    is_cached: bool = False
    cached_sequence: List[List[int]] = []
    cached_range: List[List[int]] = []

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

    def __init__(self, seq_dict: Dict[str, any] = None, filepath: str = None):
        if seq_dict is None:
            return
        if filepath:
            self.filepath = filepath

        # 必須項目
        if (key := "connect_to") in seq_dict:
            mode = seq_dict[key]
            if not (mode in CONNECT_MAGNET):
                logger.error("設定ファイルと現在の接続先磁石が不一致")
                self.have_error = True
        else:
            self.log_key_notfound(key, ERROR)
            self.have_error = True

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
        if (key := "use_cache") in seq_dict:
            try:
                self.use_cache = bool(seq_dict[key])
            except ValueError:
                self.log_invalid_value(key, seq_dict[key], WARNING)

        if (key := "autorange") in seq_dict:
            try:
                self.autorange = bool(seq_dict[key])
            except ValueError:
                self.log_invalid_value(key, seq_dict[key], WARNING)
        else:
            if self.control_mode == "oectl":
                self.log_use_default(key, self.pre_lock_sec)
                self.verified = False

        if (key := "demag") in seq_dict:
            try:
                self.force_demag = bool(seq_dict[key])
            except ValueError:
                self.log_invalid_value(key, seq_dict[key], WARNING)
        else:
            self.log_use_default(key, self.force_demag)
            self.verified = False

        if (key := "demag_step") in seq_dict:
            try:
                self.demag_step = int(seq_dict[key])
            except ValueError:
                self.log_invalid_value(key, seq_dict[key], WARNING)

            if self.demag_step < 1:
                self.log_invalid_value(key, seq_dict[key], ERROR)
                self.have_error = True

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
                            start_time: datetime.datetime, save_file: str = None, mes_range: int = None) -> Current:
        current = None
        cange_range = False
        if not (mes_range is None):
            cange_range = True
            now_range = gauss.range_fetch()
            if mes_range < now_range:
                gauss.range_set(mes_range)
                cange_range = False
        if self.control_mode == "current" or (self.is_cached and self.use_cache):
            current = Current(target, "mA")
            power.set_iset(current)
        elif self.control_mode == "oectl":
            current = magnet_field_ctl(target, self.autorange)

        if cange_range:
            gauss.range_set(mes_range)

        time.sleep(pre_lock_time)
        status = load_status()
        status.set_origin_time(start_time)
        status.target = target
        print(status)
        if save_file:
            save_status(save_file, status)
        time.sleep(post_lock_time)
        return current

    def measure_process(self, measure_seq: List[Union[int, float]], start_time: datetime.datetime,
                        save_file: str = None, chached_range: Union[List[int]] = None) -> (List[int], List[int]):
        """
        測定シークエンスに従って測定を実施する

        :param chached_range:
        :param measure_seq: 測定シークエンス intのリスト
        :param start_time: 測定基準時刻
        :param save_file: ログファイル名
        """

        res_current: List[int] = []
        res_range: List[int] = []
        pre_block_range = None
        if chached_range is None:
            pass
        else:
            pre_block_range = chached_range[0]
        self.measure_lock_record(measure_seq[0], self.pre_lock_sec, 0, start_time, save_file=save_file,
                                 mes_range=pre_block_range)
        origin_time = datetime.datetime.now()
        next_time = origin_time + self.blocking_monitoring_td
        pre_block_end_time = origin_time + self.pre_block_td
        last_time = pre_block_end_time - self.blocking_monitoring_td

        logger.debug("pre_block_end_time = {0}".format(pre_block_end_time))
        logger.debug("last_time = {0}".format(last_time))
        logger.debug("next_time = {0}".format(next_time))
        while next_time < last_time:
            logger.debug("next_time = {0}".format(next_time))
            while datetime.datetime.now() < next_time:
                time.sleep(0.2)
            self.measure_lock_record(measure_seq[0], 0, 0, start_time, save_file=save_file, mes_range=pre_block_range)
            next_time = next_time + self.blocking_monitoring_td
        else:
            while datetime.datetime.now() < pre_block_end_time:
                time.sleep(0.2)
            self.measure_lock_record(measure_seq[0], 0, 0, start_time, save_file)

        lx = len(measure_seq)
        loop = 0
        for target in measure_seq:
            if chached_range is None:
                mes_range = None
            else:
                mes_range = chached_range[loop]
            c: Current
            loop += 1
            if loop == 1:
                c = self.measure_lock_record(target, 0, self.post_lock_sec, start_time, save_file, mes_range)
            elif loop == lx:
                c = self.measure_lock_record(target, self.pre_lock_sec, 0, start_time, save_file, mes_range)
            else:
                c = self.measure_lock_record(target, self.pre_lock_sec, self.post_lock_sec, start_time, save_file,
                                             mes_range)
            res_current.append(c.mA())
            res_range.append(gauss.range_fetch())

        origin_time = datetime.datetime.now()
        next_time = origin_time + self.blocking_monitoring_td
        post_block_end_time = origin_time + self.post_block_td
        last_time = post_block_end_time - self.blocking_monitoring_td

        post_block_range = None
        if chached_range is None:
            pass
        else:
            post_block_range = chached_range[-1]
        while next_time < last_time:
            while datetime.datetime.now() < next_time:
                time.sleep(0.2)
            self.measure_lock_record(measure_seq[-1], 0, 0, start_time, save_file, post_block_range)
            next_time = next_time + self.blocking_monitoring_td
        else:
            while datetime.datetime.now() < post_block_end_time:
                time.sleep(0.2)
            self.measure_lock_record(measure_seq[-1], 0, 0, start_time, save_file, post_block_range)

        return res_current, res_range

    def measure(self) -> None:
        """
        測定プログラム
        """
        if not self.verified:
            print("設定ファイルの検証を行ってください。")
            return
        if self.force_demag:
            oe_mode = True
            if self.control_mode == "current":
                oe_mode = False
            print("消磁中")
            demag(self.demag_step, oe_mode)
            print("消磁完了")
        if self.use_cache and self.is_cached:
            sequence = self.cached_sequence
        else:
            sequence = self.measure_sequence
        i = 0
        for seq in sequence:
            print("測定シーケンスに入ります Y/n s(kip)")
            r = input(">>>>>").lower()
            if r == "n":
                break
            if r == "s":
                continue
            file = datetime.datetime.now().strftime('%Y-%m-%d_%H-%M-%S') + ".log"
            file, start_time = gen_csv_header(file)
            if self.use_cache and self.is_cached and self.autorange:
                self.measure_process(seq, start_time, save_file=file, chached_range=self.cached_range[i])

            else:
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
            oe_mode = True
            if self.control_mode == "current":
                oe_mode = False
            print("消磁中")
            demag(self.demag_step, oe_mode)
            print("消磁完了")
        sequence: List[List[Union[int, float, Current]]]
        cache_lr: List[List[int]] = []
        cache_lc: List[List[int]] = []
        if self.is_cached and self.use_cache:
            print("cached")
            sequence = self.cached_sequence
        else:
            sequence = self.measure_sequence
        i = 0
        for seq in sequence:
            start_time = datetime.datetime.now()
            print("測定開始:", start_time.strftime('%Y-%m-%d %H:%M:%S'))
            try:
                if self.use_cache and self.is_cached and self.autorange:
                    cache_c, cache_r = self.measure_process(seq, start_time, chached_range=self.cached_range[i])
                else:
                    cache_c, cache_r = self.measure_process(seq, start_time)
            except ValueError:
                logger.error("測定値指定が不正です")
                self.verified = False
                return
            i += 1
            if self.use_cache and (not self.is_cached):
                cache_lc.append(cache_c)
                cache_lr.append(cache_r)

        self.verified = True
        if self.use_cache and (not self.is_cached):
            self.is_cached = True
            self.cached_sequence = cache_lc
            self.cached_range = cache_lr

        print("測定設定は検証されました。")
        power.set_iset(Current(0, "mA"))
        return


class SettingDB:
    filepath: str = ""
    db: Dict[str, int] = dict()
    seq: MeasureSetting = MeasureSetting(None, None)
    now_hash: str = None
    loading_setting_path: str = None

    def __init__(self, filename: str):
        self.filepath = "./" + filename
        self.load_db()
        return

    def load_db(self) -> None:
        if not os.path.exists(self.filepath):
            return
        try:
            with open(self.filepath, "r") as f:
                self.db = json.load(f)
        except json.JSONDecodeError:
            os.remove(self.filepath)
            logger.warning("setting DB was broken!")
            return
        return

    def save_db(self):
        with open(self.filepath, mode='w', encoding="utf-8")as f:
            json.dump(self.db, f)

    def hash_check(self, filepath):
        m = hashlib.sha512()
        with open(filepath, 'rb') as f:
            m.update(f.read())
        self.now_hash = m.hexdigest()
        return self.now_hash

    def load_measure_sequence(self, filename: str, abspath: bool = False):
        if not abspath:
            json_path = os.path.abspath("./measure_sequence/" + filename)
            self.loading_setting_path = json_path
        else:
            json_path = filename

        if not os.path.exists(json_path):
            logger.error("File not found! : {0} ".format(filename))
            return

        try:
            with open(json_path, "r") as f:
                seq = json.load(f)
        except json.JSONDecodeError:
            logger.error("設定ファイルの読み込み失敗 JSONファイルの構造を確認 ")
            return
        self.seq = MeasureSetting(seq)
        self.hash_check(json_path)
        if (key := self.now_hash) in self.db:
            if self.db[key]:
                logger.info("検証済み設定ファイル {0}".format(json_path))
                self.seq.verified = True
            else:
                logger.info("設定ファイルの変更検知 {0}".format(json_path))
        else:
            logger.info("新しい設定ファイル {0}".format(json_path))
        if self.seq.verified:
            print("設定ファイルは検証済み")
        else:
            print("設定ファイルに未検証の要素有り. test 実行必須")
        return

    def reload_measure_sequence(self):
        self.load_measure_sequence(self.loading_setting_path, True)

    def seq_verified(self, b: bool):
        self.seq.verified = b
        self.db[self.now_hash] = b
        self.save_db()
        return


DB = SettingDB(DB_NAME)


class StatusList:
    iset: float = 0.0
    iout: float = 0.0
    field: float = 0.0
    vout: float = 0.0
    target: float = 0.0
    diff_second: int = 0

    def __str__(self):
        return "{:03} sec ISET= {:+.3f} A\tIOUT= {:+.3f}A\tField= {:+.1f} G\tVOUT= {:+.3f} \tTarget= {:+03}".format(
            self.diff_second, self.iset, self.iout,
            self.field, self.vout, self.target)

    def set_origin_time(self, start_time: datetime.datetime) -> None:
        """
        経過時間表示のための基準時刻を設定する

        :param start_time: 基準時刻
        """
        loadtime = datetime.datetime.now()
        self.diff_second = (loadtime - start_time).seconds

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


def get_suitable_range(field: Union[int, float]) -> int:
    field = abs(field)
    if abs(field) >= 2700:
        return 0
    elif abs(field) >= 270:
        return 1
    elif abs(field) >= 27:
        return 2
    else:
        return 3


def magnet_field_ctl(target: int, auto_range: bool = False) -> Current:
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
    if CONNECT_MAGNET == "ELMG":  # 電磁石制御部
        if target > ELMG_MAGNET_FIELD_LIMIT:
            logger.error("磁界制御入力値過大")
            print("最大磁界4.1kOe")
            raise ValueError
        now_range = gauss.range_fetch()
        next_range = 0

        if auto_range:
            next_range = get_suitable_range(target)

            if now_range == next_range:  # レンジを変えないとき
                auto_range = False
                pass
            elif now_range < next_range:  # レンジを下げる方向
                pass
            else:  # レンジを上げる
                gauss.range_set(next_range)
                now_range = next_range
                auto_range = False
                time.sleep(0.1)
        now_field = gauss.magnetic_field_fetch()

        field_up: int
        if target - now_field > 0:
            field_up = 1
        else:
            field_up = -1

        loop_limit = OECTL_LOOP_LIMIT
        while True:
            while True:  # 磁界の一致を待つ
                palfield = gauss.magnetic_field_fetch()
                if palfield == now_field:
                    break
                now_field = palfield
                time.sleep(0.2)

            if auto_range:  # レンジを下げる処理
                r = get_suitable_range(now_field)

                if next_range == 0:
                    auto_range = False

                if r == now_range:
                    pass
                if r > now_range:
                    if r == next_range:
                        gauss.range_set(next_range)
                        now_range = r
                        auto_range = False
                    elif r < next_range:
                        gauss.range_set(r)
                        now_range = r
                    else:
                        pass
                else:
                    pass

            while True:  # 磁界の一致を待つ
                palfield = gauss.magnetic_field_fetch()
                if palfield == now_field:
                    break
                now_field = palfield
                time.sleep(0.2)

            if loop_limit == 0:
                break
            loop_limit -= 1

            diff_field = target - now_field

            if field_up == 1 and diff_field <= 1:
                break
            if field_up == -1 and diff_field >= -1:
                break

            elmg_const = OECTL_BASE_COEFFICIENT - OECTL_RANGE_COEFFICIENT * now_range

            # 次の設定値を算出
            now_current = power.iset_fetch()
            next_current = now_current + Current(diff_field * elmg_const, "mA")
            if abs(now_current - next_current) < 1:
                break
            power.set_iset(next_current)

            continue

        # 初期差分算出
        last_current = power.iset_fetch()
        now_field = gauss.magnetic_field_fetch()
        diff_field = target - now_field
        if abs(diff_field) >= 1:
            last_current = last_current + Current(diff_field * 0.9, "mA")
        last_current = last_current + Current(-(4 - now_range) * field_up, "mA")
        return last_current

    elif CONNECT_MAGNET == "HELM":  # ヘルムホルツコイル制御部
        return magnet_field_ctl_helmholtz(target)
    else:
        raise ValueError


def magnet_field_ctl_helmholtz(target: int) -> Current:
    if CONNECT_MAGNET == "HELM":  # ヘルムホルツコイル制御部
        if target > HELM_MAGNET_FIELD_LIMIT:
            logger.error("磁界制御入力値過大")
            print("最大磁界200Oe")
            raise ValueError
        target_current = Current(int(target / HELM_Oe2CURRENT_CONST), "mA")
        power.set_iset(target_current)
        return target_current
    else:
        raise ValueError


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


def print_status():
    print(load_status())
    return


def Oe_cmd(cmd: List[str], auto_range: bool = False) -> None:
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


def gauss_cmd(cmd: List[str]) -> None:
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


def cmdlist():
    print("""
    quit\t通常終了
    load FileName \t ./measure_sequence以下のFileNameの測定定義ファイルを読み込む
    reload\t最後に読み込んだ測定定義ファイルを読み込む
    test\t読み込んだ測定定義ファイルを検証する
    measure\t測定動作を行う
    demag\t消磁動作

    status\t電源,磁界の状態を表示
    gaussctl\tガウスメーター制御コマンド群
    powerctl\tバイポーラ電源制御コマンド群
    oectl 目標値 (単位)\t磁界制御
    """)


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
            gauss_cmd(request[1:])
            continue
        elif cmd in {"oectl"}:
            Oe_cmd(request[1:], auto_range)
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
            DB.load_measure_sequence(request[1])
            continue
        elif cmd in {"reload"}:
            DB.reload_measure_sequence()
            continue
        elif cmd in {"test"}:
            DB.seq.measure_test()
            if DB.seq.verified:
                DB.seq_verified(True)
            else:
                DB.seq_verified(False)
            continue
        elif cmd in {"measure"}:
            DB.seq.measure()
            continue

        else:
            print("""invalid command\nPlease type "h" or "help" """)
            continue


def search_magnet() -> None:
    global CONNECT_MAGNET
    while True:
        power.set_iset(Current(400, "mA"))
        time.sleep(0.3)
        resistance: float = power.vout_fetch() / power.iout_fetch().A()
        if resistance > 4:
            now = "ELMG"
        else:
            now = "HELM"
        power.allow_output(False)
        print("接続先を入力してください。"
              "電磁石=>\"ELMG\"\tヘルムホルツ=>\"HELM\"")
        answer = input(">>>")
        if now in answer:
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
            logger.error("接続先が不一致か入力内容が不正")
            print("接続先を強制するには\"Force\"と入力してください")
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


def setup_logger(log_folder, modname=__name__):
    lg = getLogger(modname)
    lg.setLevel(DEBUG)

    sh = StreamHandler()
    sh.setLevel(PRINT_LOGLEVEL)
    formatter = Formatter('%(name)s : %(levelname)s : %(message)s')
    sh.setFormatter(formatter)
    lg.addHandler(sh)

    fh = FileHandler(log_folder)  # fh = file handler
    fh.setLevel(LOGLEVEL)
    fh_formatter = Formatter('%(asctime)s : %(filename)s : %(name)s : %(lineno)d : %(levelname)s : %(message)s')
    fh.setFormatter(fh_formatter)
    lg.addHandler(fh)
    return lg


logger = setup_logger(LOGFILE)


def init() -> None:
    gauss.range_set(0)
    power.set_iset(Current(0, "mA"))


CONNECT_MAGNET = ""

if __name__ == '__main__':
    while True:
        try:
            gauss = visa_gs.GaussMeter()
        except pyvisa.Error:
            logger.error("ガウスメーター接続失敗")
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
            logger.error("バイポーラ電源接続失敗")
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
        logger.critical(e)

    finally:
        init()
        power.allow_output(False)
