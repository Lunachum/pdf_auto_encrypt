# -*- coding: utf-8 -*-

import os
import time
import sys
import logging
import threading
from getpass import getpass
from pathlib import Path

import pypdf
from pypdf.constants import UserAccessPermissions
from pypdf.errors import PdfReadError, EmptyFileError

from watchdog.observers import Observer
from watchdog.events import LoggingEventHandler, FileCreatedEvent, FileModifiedEvent, FileMovedEvent


# === 設定 =========================

"""
BACKUP_ENABLED: 保護PDFの出力先に同じ名前のファイルがあった場合、バックアップするかどうか

デフォルト: True
よくわからなければ True のままにします

- True の場合: 自動的にバックアップします
- False の場合: バックアップせずに上書きします(危険)

上書き保存を検出する際に複数回 on_modified が呼ばれてしまうため、バックアップファイルが増える可能性があります
その場合は False のほうが容量を節約できますが、基本的には True のほうが安全です。
"""
BACKUP_ENABLED = True

"""
BACKUP_FOLDER: バックアップファイルをバックアップフォルダに移動します

デフォルト: True
よくわからなければ True のままにします

バックアップファイルをバックアップフォルダに作ります。
バックアップフォルダは 出力先\.backups フォルダです
"""
BACKUP_FOLDER = True

"""
HOOK_ON_CREATED: ファイル作成時に自動処理するかどうか

デフォルト: True
よくわからなければ True のままにします

別のフォルダから移動してきたPDFは on_modified が呼ばれないことがあるため、作成時も処理します。
作成と変更の両方で呼ばれても、SETTLE_SECONDS の待ち合わせでまとめて 1 回だけ処理します
"""
HOOK_ON_CREATED = True

"""
HOOK_ON_MODIFIED: ファイル変更時に自動処理するかどうか

デフォルト: True
よくわからなければ True のままにします

監視対象フォルダ内のファイル内容が変更されたときに保護処理を実行します
"""
HOOK_ON_MODIFIED = True

"""
HOOK_ON_MOVED: ファイルの移動・名前変更時に自動処理するかどうか

デフォルト: True
よくわからなければ True のままにします

一時ファイルに書き込んでから名前を変えて保存するソフトや、
別のフォルダから監視フォルダへ移動したPDFも処理できるようにします
"""
HOOK_ON_MOVED = True

"""
SETTLE_SECONDS: ファイルの変更が止まってから処理を始めるまでの秒数

デフォルト: 2.0
よくわからなければ 2.0 のままにします

保存中のファイル (書き込み途中) を処理しないよう、
ファイルのサイズと更新日時がこの秒数変わらなくなるまで待ってから処理します。
大きなファイルの保存やネットワークフォルダへの保存で途中のファイルが処理される場合は増やしてください
"""
SETTLE_SECONDS = 2.0

"""
SET_USER_PASSWORD: ユーザーパスワード設定機能を有効かするかどうか
このフラグが有効でも、ユーザーパスワード引数を指定しなければユーザーパスワードは設定されません。
このフラグが無効の場合、いかなる場合でもユーザーパスワードが設定されません。

デフォルト: True
よくわからなければ True のままにします

ユーザーパスワードを設定すると、出力された PDF ファイルを閲覧するためにパスワードが必要になります。
"""
SET_USER_PASSWORD = True

"""
SET_OWNER_PASSWORD: オーナーパスワードを設定するかどうか

デフォルト: True
よくわからなければ True のままにします

オーナーパスワードを設定すると、閲覧のみに制限された、保護されたPDFファイルを作成します。
ユーザーパスワードを設定しないことで、閲覧自体はパスワードなしでもできます。
"""
SET_OWNER_PASSWORD = True

"""
USER_PERMISSIONS: ユーザーの権限

デフォルト: 0

ユーザーの権限を指定します
UserAccessPermissionsの定数を使います
0 で閲覧のみ。

複数の権限を与える場合
例えば PRINT と PRINT_TO_REPRESENTATION を与えたい場合は | でつなぎます
例: USER_PERMISSIONS = UserAccessPermissions.PRINT | UserAccessPermissions.PRINT_TO_REPRESENTATION
"""
USER_PERMISSIONS = 0

# PDF仕様で「1にしておく」と決められている予約ビット (7, 8, 13〜32ビット目)
# 権限0を指定しても、この予約ビットは立てたまま暗号化します
_PERMISSION_FLAGS = (
    UserAccessPermissions.PRINT
    | UserAccessPermissions.MODIFY
    | UserAccessPermissions.EXTRACT
    | UserAccessPermissions.ADD_OR_MODIFY
    | UserAccessPermissions.FILL_FORM_FIELDS
    | UserAccessPermissions.EXTRACT_TEXT_AND_GRAPHICS
    | UserAccessPermissions.ASSEMBLE_DOC
    | UserAccessPermissions.PRINT_TO_REPRESENTATION
)
_RESERVED_BITS = 0xFFFFFFFC & ~int(_PERMISSION_FLAGS)

"""
SAFE_DIRECTORY: 入力フォルダと出力フォルダが一致している場合にエラー終了するかどうか

デフォルト: True
よくわからなければ True のままにします

誤って入力と出力を同じにしてしまった場合、処理が無限ループするため
基本的に True のままにしてください
"""
SAFE_DIRECTORY = True

"""
LOCALIZE_LOGLEVEL: ログレベルを日本語化するかどうか
注意: ログメッセージは常に日本語です

デフォルト: True
よくわからなければ True のままにします

このスクリプトをさらにスクリプト処理する場合などで不都合がある場合は False にしてください
"""
LOCALIZE_LOGLEVEL = True

# ==================================

# パスワードを渡す環境変数の名前
ENV_OWNER_PASSWORD = "PDF_OWNER_PASSWORD"
ENV_USER_PASSWORD = "PDF_USER_PASSWORD"


logging.basicConfig(
    format="[%(asctime)s %(levelname)s]: %(message)s [%(filename)s:%(lineno)d]",
    level=logging.INFO,
    datefmt="%H:%M:%S"
)

if LOCALIZE_LOGLEVEL:
    logging.addLevelName(logging.DEBUG, "デバッグ")
    logging.addLevelName(logging.INFO, "情報")
    logging.addLevelName(logging.WARNING, "警告")
    logging.addLevelName(logging.ERROR, "エラー")
    logging.addLevelName(logging.CRITICAL, "重大")
else:
    logging.addLevelName(logging.WARNING, "WARN")
logger = logging.getLogger("PDF保護ツール")


def encrypt(source_pdf_file: Path, output_folder: Path, owner_password, user_password) -> None:
    """
    PDFの保護設定を行います

    @param source_pdf_file 入力PDFファイル
    """
    dest_pdf_file: Path = Path(output_folder) / Path(source_pdf_file).name
    with source_pdf_file.open("rb") as source:
        pdf_writer = pypdf.PdfWriter()

        try:
            pdf_writer.append(pypdf.PdfReader(source, strict=False))
            pdf_writer.encrypt(user_password=user_password if SET_USER_PASSWORD else "",
                               owner_password=owner_password if SET_OWNER_PASSWORD else "",
                               permissions_flag=int(USER_PERMISSIONS) | _RESERVED_BITS,
                               algorithm="AES-256")
        except EmptyFileError as err:
            # PDFの中身が壊れてる場合は処理しない
            logger.debug(err, exc_info=True, stack_info=True)
            logger.warning("スキップ/空のPDFファイル: %s", source_pdf_file)
            return
        except PdfReadError as err:
            # PDFの中身が壊れてる場合は処理しない
            logger.warning(err, exc_info=True, stack_info=True)
            logger.warning("スキップ/PDF解析失敗: %s", source_pdf_file)
            return

        bak_count = 0

        backup_folder = dest_pdf_file.parent
        if BACKUP_FOLDER:
            backup_folder = dest_pdf_file.with_name(".backups")
            backup_folder.mkdir(exist_ok=True)
        bak_dest = dest_pdf_file
        while bak_dest.exists():
            bak_dest = (backup_folder /
                        dest_pdf_file.name).with_suffix(f".{bak_count}.bak")
            bak_count += 1

        if BACKUP_ENABLED and dest_pdf_file.exists():
            logger.info("出力先に同じ名前のPDFファイルがあるため、バックアップします")
            dest_pdf_file.rename(bak_dest)
            logger.info("古いファイルをバックアップしました: %s -> %s",
                        dest_pdf_file, bak_dest)

        # 書き込み途中のPDFが出力先 (共有フォルダ) に見えないよう、
        # 一時ファイルに書き切ってから名前を変える
        tmp_file = dest_pdf_file.with_name(dest_pdf_file.name + ".tmp")
        try:
            with tmp_file.open(mode="wb") as dest:
                pdf_writer.write(dest)
            if BACKUP_ENABLED and dest_pdf_file.exists():
                raise FileExistsError(f"出力先にファイルが残っています: {dest_pdf_file}")
            os.replace(tmp_file, dest_pdf_file)
        finally:
            if tmp_file.exists():
                tmp_file.unlink()
        logger.info("パスワードロックしました: %s -> %s", source_pdf_file, dest_pdf_file)


class PendingFiles:
    """
    処理待ちのファイルを管理します

    ファイル保存中は on_modified が何度も呼ばれるため、すぐには処理せず
    「サイズと更新日時が SETTLE_SECONDS 秒変わらなくなったら 1 回だけ処理する」ようにします。
    また、一度処理したときと内容 (サイズと更新日時) が同じファイルは二重に処理しません。
    """

    def __init__(self, process):
        self._process = process
        self._lock = threading.Lock()
        # パス -> (最後に変化を見た時刻, 最後に見たファイルの状態)
        self._pending = {}
        # パス -> 処理したときのファイルの状態
        self._done = {}
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="pdf-worker", daemon=True)

    @staticmethod
    def _signature(path: str):
        """ファイルの状態 (サイズ, 更新日時)。ファイルがなければ None"""
        try:
            st = os.stat(path)
        except OSError:
            return None
        return (st.st_size, st.st_mtime_ns)

    def add(self, path: str):
        with self._lock:
            self._pending[path] = (time.monotonic(), self._signature(path))

    def start(self):
        self._thread.start()

    def stop(self):
        self._stop.set()
        self._thread.join()

    def _run(self):
        while not self._stop.wait(0.5):
            for path in self._ready_paths():
                self._process(path)

    def _ready_paths(self):
        """変化が止まって処理してよいファイルを取り出します"""
        ready = []
        now = time.monotonic()
        with self._lock:
            for path, (last_change, last_sig) in list(self._pending.items()):
                sig = self._signature(path)
                if sig is None:
                    # 一時ファイルなど、すでに消えたファイル
                    del self._pending[path]
                    continue
                if sig != last_sig:
                    # まだ書き込み中: 待ち時間をリセット
                    self._pending[path] = (now, sig)
                    continue
                if now - last_change < SETTLE_SECONDS or sig[0] == 0:
                    # 変化が止まってから時間が経っていない / 中身がまだ空
                    continue
                del self._pending[path]
                if self._done.get(path) == sig:
                    logger.debug("処理済みと同じ内容なのでスキップ: %s", path)
                    continue
                self._done[path] = sig
                ready.append(path)
        return ready


class FileEventHandler(LoggingEventHandler):

    def __init__(self, input_folder: Path, output_folder: Path, owner_password: str, user_password: str):
        super().__init__()
        self.input_folder = input_folder
        self.output_folder = output_folder
        self.owner_password = owner_password
        self.user_password = user_password
        self.pending = PendingFiles(self.run_encrypt)

    def enqueue(self, path):
        """
        PDFなら処理待ちに追加します (実際の処理は PendingFiles が行います)
        """
        if isinstance(path, bytes):
            path = os.fsdecode(path)
        if not path.lower().endswith(".pdf"):
            return
        if is_same_or_inside(Path(path).resolve(), Path(self.output_folder).resolve()):
            # SAFE_DIRECTORY = False で起動した場合でも、出力先のファイルは処理しない
            logger.debug("出力先のファイルなのでスキップ: %s", path)
            return
        self.pending.add(path)

    def run_encrypt(self, path: str):
        """
        保護スクリプトを実行します
        """
        try:
            logger.info("パスワードロックを行います: %s", path)
            encrypt(Path(path), Path(self.output_folder),
                    self.owner_password, self.user_password)
        except Exception as exception:
            logger.error("パスワードロック中にエラーが発生しました")
            logger.exception(exception, exc_info=True, stack_info=True)

    def on_created(self, event: FileCreatedEvent):
        """
        監視対象フォルダにファイルが作成された時の処理です
        """
        if not HOOK_ON_CREATED or event.is_directory:
            return
        path = event.src_path
        logger.info("ファイル作成: %s", path)
        self.enqueue(path)
        return super().on_created(event)

    def on_modified(self, event: FileModifiedEvent):
        """
        監視対象フォルダでファイルが変更された時の処理です
        (新規作成のファイルも含まれるようです)
        """
        if not HOOK_ON_MODIFIED or event.is_directory:
            return
        path = event.src_path
        logger.debug("ファイル変更: %s", path)
        self.enqueue(path)
        return super().on_modified(event)

    def on_moved(self, event: FileMovedEvent):
        """
        監視対象フォルダでファイルが移動・名前変更された時の処理です
        (移動先のパスを処理します)
        """
        if not HOOK_ON_MOVED or event.is_directory:
            return
        path = event.dest_path
        logger.info("ファイル移動: %s", path)
        self.enqueue(path)
        return super().on_moved(event)


def is_same_or_inside(path: Path, folder: Path) -> bool:
    """
    path が folder と同じか、folder の中 (サブフォルダ含む) にあれば True を返します
    """
    try:
        path.relative_to(folder)
        return True
    except ValueError:
        return False


def ask_password(prompt: str, allow_empty: bool) -> str:
    """
    画面にパスワードを表示せずに入力してもらいます (確認のため 2 回入力)
    """
    while True:
        password = getpass(prompt)
        if password == "" and allow_empty:
            return ""
        if password.strip() == "":
            print("空のパスワードは使えません。もう一度入力してください")
            continue
        if getpass("確認のため、もう一度入力してください: ") == password:
            return password
        print("パスワードが一致しません。もう一度入力してください")


def read_passwords():
    """
    オーナーパスワードとユーザーパスワードを読み込みます

    - 環境変数 PDF_OWNER_PASSWORD が設定されていれば環境変数から読み込む
      (ユーザーパスワードは PDF_USER_PASSWORD。設定されていなければユーザーパスワードなし)
    - 設定されていなければ画面から入力してもらう

    コマンド引数で渡すと、タスクマネージャーやコマンド履歴からパスワードが見えてしまうため使いません
    """
    owner_password = os.environ.get(ENV_OWNER_PASSWORD)
    if owner_password is not None:
        logger.info("環境変数 %s からパスワードを読み込みました", ENV_OWNER_PASSWORD)
        user_password = os.environ.get(ENV_USER_PASSWORD, "")
    else:
        owner_password = ask_password("オーナーパスワード: ", allow_empty=False)
        if SET_USER_PASSWORD:
            user_password = ask_password(
                "ユーザーパスワード (閲覧用。設定しない場合は空のまま Enter): ", allow_empty=True)
        else:
            user_password = ""
    return owner_password, user_password


def main():
    if len(sys.argv) - 1 != 2:  # argv[0] は自分のパス
        executable = Path(sys.argv[0]).name
        print("使用法:", executable,
              "<元のPDFを入れるフォルダ> <パスワードロックされたPDFの出力先>")
        print("パスワードは起動後に画面から入力するか、環境変数",
              ENV_OWNER_PASSWORD, "/", ENV_USER_PASSWORD, "で指定します")
        if len(sys.argv) - 1 > 2:
            print("※ パスワードをコマンド引数で渡す方法は、安全のため使えなくなりました")
        os._exit(-1)
        return

    input_folder = Path(sys.argv[1])
    output_folder = Path(sys.argv[2])

    if not input_folder.is_dir():
        logger.error("監視フォルダが見つかりません: %s", input_folder)
        os._exit(1)
        return

    # 相対パスや ".." を含むパスでも正しく比較できるよう、絶対パスに直してから比べる
    # (出力先はまだ存在しなくても resolve できる)
    input_resolved = input_folder.resolve()
    output_resolved = output_folder.resolve()
    if is_same_or_inside(output_resolved, input_resolved):
        # 出力先が監視フォルダと同じ、または監視フォルダの中にあると、
        # 出力したPDFを再び検知して処理し続ける (無限ループ) ため止める
        logger.warning("出力先が監視フォルダと同じか、監視フォルダの中にあります: %s", output_resolved)
        if SAFE_DIRECTORY:
            logger.error("終了します")
            os._exit(1)
            return

    owner_password, user_password = read_passwords()

    if owner_password.strip() == "":
        logger.warning("オーナーパスワードが空です")

    if user_password != "":
        if not SET_USER_PASSWORD:
            logger.error("ユーザーパスワードが設定されていますが、SET_USER_PASSWORD フラグが False です")
            logger.error("SET_USER_PASSWORD フラグを True にした状態で再度実行してください")
            return
        logger.info("ユーザーパスワードが設定されました")
        if user_password.strip() == "":
            logger.warning("ユーザーパスワードが空白だけです")
    else:
        logger.info("ユーザーパスワードは設定されていません")

    print("監視フォルダ:", input_folder.resolve())
    print("出力先:", output_folder.resolve())
    print("Ctrl+C で終了します")

    output_folder.mkdir(exist_ok=True)

    event_handler = FileEventHandler(
        input_folder, output_folder, owner_password, user_password)
    observer = Observer()
    observer.schedule(
        event_handler=event_handler,
        path=input_folder,
        recursive=True
    )
    event_handler.pending.start()
    observer.start()

    interrupted = False
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        interrupted = True
    finally:
        observer.stop()
        observer.join()
        event_handler.pending.stop()

    logger.info("終了します")
    if interrupted:
        os._exit(0)


if __name__ == "__main__":
    main()
