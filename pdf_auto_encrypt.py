# -*- coding: utf-8 -*-

import os
import time
import sys
import logging
from pathlib import Path

import pypdf
from pypdf.constants import UserAccessPermissions
from pypdf.errors import PdfReadError, EmptyFileError

from watchdog.observers import Observer
from watchdog.events import LoggingEventHandler, FileCreatedEvent, FileModifiedEvent


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

デフォルト: False
よくわからなければ False のままにします

新規作成時も on_modified が呼ばれるようなので、基本的には False のままで良いです
"""
HOOK_ON_CREATED = False

"""
HOOK_ON_MODIFIED: ファイル変更時に自動処理するかどうか

デフォルト: True
よくわからなければ True のままにします

監視対象フォルダ内のファイル内容が変更されたときに保護処理を実行します
"""
HOOK_ON_MODIFIED = True

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
                               permissions_flag=0,
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

        mode = "xb" if BACKUP_ENABLED else "wb"
        with dest_pdf_file.open(mode=mode) as dest:
            pdf_writer.write(dest)
        logger.info("パスワードロックしました: %s -> %s", source_pdf_file, dest_pdf_file)


class FileEventHandler(LoggingEventHandler):

    def __init__(self, input_folder: Path, output_folder: Path, owner_password: str, user_password: str):
        super().__init__()
        self.input_folder = input_folder
        self.output_folder = output_folder
        self.owner_password = owner_password
        self.user_password = user_password

    def run_encrypt(self, path: str):
        """
        保護スクリプトを実行します
        """
        if not path.lower().endswith(".pdf"):
            return
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
        if not HOOK_ON_CREATED:
            return
        path = event.src_path
        logger.info("ファイル作成: %s", path)
        self.run_encrypt(path)
        return super().on_created(event)

    def on_modified(self, event: FileModifiedEvent):
        """
        監視対象フォルダでファイルが変更された時の処理です
        (新規作成のファイルも含まれるようです)
        """
        if not HOOK_ON_MODIFIED:
            return
        path = event.src_path
        logger.info("ファイル変更: %s", path)
        self.run_encrypt(path)
        return super().on_modified(event)


def main():
    if len(sys.argv) - 1 < 3:  # argv[0] は自分のパス
        executable = Path(sys.argv[0]).name
        print("使用法:", executable,
              "<元のPDFを入れるフォルダ> <パスワードロックされたPDFの出力先> <オーナーパスワード> [ユーザーパスワード]")
        os._exit(-1)
        return

    input_folder = Path(sys.argv[1])
    output_folder = Path(sys.argv[2])
    owner_password = sys.argv[3]

    if input_folder == output_folder:
        logger.warning("入力フォルダと出力フォルダが同じフォルダです")
        if SAFE_DIRECTORY:
            logger.error("終了します")
            os._exit(1)
            return

    if owner_password.strip() == "":
        logger.warning("オーナーパスワードが空です")

    if len(sys.argv) - 1 >= 4:
        user_password = sys.argv[4]
        if not SET_USER_PASSWORD:
            logger.error("ユーザーパスワードが設定されていますが、SET_USER_PASSWORD フラグが False です")
            logger.error("SET_USER_PASSWORD フラグを True にした状態で再度実行してください")
            return
        logger.info("ユーザーパスワードが設定されました")
        if user_password.strip() == "":
            logger.warning("ユーザーパスワードが空の文字列です")
    else:
        user_password = ""
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

    logger.info("終了します")
    if interrupted:
        os._exit(0)


if __name__ == "__main__":
    main()
