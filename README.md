このソフトは
PDF ファイルが監視フォルダに作成されたとき (新規保存されたとき)
に自動的にパスワード付きのコピーを作るものです。

## 前提条件

### venv 環境を作る (必須ではない)

Windows の場合:

念のため venv 環境を作ってください
```
python -m venv .venv
.venv\Scripts\activate
```

### 必要なもののインストール

pip で必要なパッケージをインストールします。
```
pip install -r requirements.txt
```

pip コマンドがないと言われたら:
```
python -m pip install -r requirements.txt
```

requirements.txtがないと言われたら:
```
python -m pip install watchdog
python -m pip install cryptography
python -m pip install pypdf
```

## 使い方

pdf_auto_encrypt.py を起動します。

```
python pdf_auto_encrypt.py <元のPDFが保存されるフォルダ> <パスワード付きPDFの出力先> <オーナーパスワード> <ユーザーパスワード>
```
`<` と `>` の記号は何を入力するかわかりやすくしているだけなので、付けません。
オーナーパスワードは権限設定用のパスワードです。オーナーパスワードを知らない人は PDF を編集できなくなります。
ただし、仕様上確実に保護できるわけではありません。PyPDF のようなソフトを通すと改ざんされる可能性はあります。

ユーザーパスワードは閲覧制限のパスワードです (指定しなくてもよいです)

例:
```
python pdf_auto_encrypt.py C:\PDF作業用 C:\共有用 パスワード
```

相対パスも指定できます
```
python pdf_auto_encrypt.py PDF作業用 PDF共有用 パスワード
```

## 注意
「元のPDFが保存されるフォルダ」と「パスワード付きPDFの出力先」は絶対に同じにしないでください。
処理が無限ループします。
