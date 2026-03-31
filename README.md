# Markdown to PDF Converter

フォルダ監視し、監視下のMarkdown/HTMLファイルに更新があれば、PDFまたはHTMLに自動変換するソフトウェアです。変換は、デフォルトはpandoc。Marp/Slidev の Markdown も扱えます。


# 依存インストール（初回のみ）

```bash
pip install playwright
playwright install chromium
brew install plantuml
```

# Plan for Development

## 要実装機能

- CLIパラメータで各モードを実施
- パラメータの
  - .htmlを.pdf化

## ToDo

<!-- - [ ] `--auto`  -->

### コード実施の流れ

- [x] 監視処理前にplaywrightやplantuml等必要なパッケージがインストールされているか確認、および、installの実施


# 問題

||Pandoc|Marp|Slidev|
|---|---|---|---|---|
|mermaild|N|**Y**|?||
|PG code|N|**Y**|?||

- MPE: Markdown 

## CLIパラメータ

|CLIパラメータ|内容|
|---|---|
|`--format-input`, `--format_input`|変換対象の入力拡張子を指定(例: `.md`, `.html`)|
|`--engine`|変換エンジンを指定(`auto` / `pandoc` / `playwright` / `marp` / `slidev`)。default=`auto`（mermaid/plantumlブロックがあれば自動的に`playwright`を使用）|
|`--format-output`, `--format_output`|出力形式を指定(`pdf`, `html`)。複数指定可: `--format-output pdf html`|
|`--watch`|変換するためフォルダ(サブフォルダ)を監視する|
|`--header`(任意)|pandocで PDF 変換の際に使う `header.tex`|
|`--marp-header`(任意)|Marp frontmatter に追加する YAML/Markdown 断片|



## 機能

- **自動変換**: 指定フォルダ内の`.md`や`.html`ファイルが更新されると自動的に変換
- **Marp対応**: Marp用のMarkdownファイルは`marp-cli`で変換、それ以外は`pandoc`で変換
- **HTML入力対応**: HTMLファイルをそのままPDFに変換
- **フォルダ構造保持**: ソースフォルダの階層構造を保持して変換先フォルダに複製
- **ファイルコピー**: 画像ファイルなど指定された拡張子のファイルを自動コピー
- **タイムスタンプ比較**: 10秒以上の差がある場合のみ変換を実行


## 変換機能

### html→PDF

html をそのまま PDF へ変換する

`.md` 入力とは異なり、`.html` 入力では `pandoc` の `--pdf-engine=lualatex` や `--header` は使いません。
`.html` は Chrome/Chromium の headless print を使って PDF 化します。

注意:
HTML 入力は現在 `pdf` 出力のみをサポートします。`--format html` と `.html` 入力の組み合わせは未対応です。


## 必要な環境

### Python依存関係

```bash
pip install -r requirements.txt
```

### 外部ツール
- **pandoc**: 通常のMarkdownファイルのPDF変換に使用
  ```bash
  # macOS
  brew install pandoc
  
  # Ubuntu/Debian
  sudo apt-get install pandoc
  ```

- **marp-cli** (オプション): Marp用MarkdownファイルのPDF変換に使用
  ```bash
  npm install -g @marp-team/marp-cli
  ```

- **Chrome / Chromium**: HTMLファイルのPDF変換に使用
  ```bash
  # macOS の例
  open -a "Google Chrome"
  ```

## 使用方法

### 基本的な使用方法
```bash
python src/md2pdf.py <監視フォルダ> <出力フォルダ>
```

### 例
```bash
python src/md2pdf.py ./markdown_files ./pdf_output
```

### オプション
- `--format-input`: 変換対象の入力拡張子を指定（デフォルト: `.md`）
- `--format`: 出力形式を指定（デフォルト: `pdf`）
- `--copy-extensions`: コピーするファイルの拡張子を指定（デフォルト: .png .jpg .jpeg .gif .svg）

```bash
python src/md2pdf.py ./markdown_files ./pdf_output --copy-extensions .png .jpg .svg .css
```

Markdown と HTML の両方を監視して PDF 化する例:

```bash
python src/md2pdf.py ./source ./pdf_output --format-input .md .html --format pdf
```

単一の HTML ファイルを PDF 化する例:

```bash
python src/md2pdf.py ./source/sample.html --output ./pdf_output/sample.pdf --format-input .html --format pdf
```

VS Code タスクやシェルから絶対パスで起動する場合は、次のいずれかを使ってください。

```bash
python /absolute/path/to/src/md2pdf.py --watch /path/to/source --output /path/to/output --format-input html --format pdf
```

または、`src/md2pdf.py` に実行権限を付けたうえで直接起動します。

```bash
chmod +x /absolute/path/to/src/md2pdf.py
/absolute/path/to/src/md2pdf.py --watch /path/to/source --output /path/to/output --format-input html --format pdf
```

## 動作の流れ

1. **初期化**: marp-cliの存在確認と出力フォルダの作成
2. **フォルダ構造複製**: ソースフォルダの階層構造を出力フォルダに複製
3. **初期スキャン**: 既存の対象ファイルをチェックし、必要に応じて変換
4. **監視開始**: ファイルの変更を監視し、リアルタイムで変換を実行

## Markdownファイルの判定

プログラムは以下のキーワードを含むファイルをMarp用として判定します：
- `marp:`
- `theme:`
- `paginate:`
- `---\nmarp`

## ログ

プログラムの実行状況はコンソールにログとして出力されます：
- 変換の成功/失敗
- ファイルのコピー状況
- エラーメッセージ

## 終了方法

`Ctrl+C`でプログラムを終了できます。

## トラブルシューティング

### marp-cliが見つからない場合
- marp-cliがインストールされていない場合、pandocのみで動作します
- `/usr/bin/marp-cli`または`which marp`で見つかるパスにmarp-cliがインストールされている必要があります

### pandocが見つからない場合
- pandocがインストールされていることを確認してください
- パスが通っていることを確認してください

### HTML の PDF 変換が失敗する場合
- `.html` 入力は LaTeX ではなく Chrome/Chromium の headless print で PDF 化します
- Google Chrome または Chromium がインストールされていることを確認してください
- `--header` は `.md` の PDF 変換時だけ有効で、`.html` では使われません

### 変換が実行されない場合
- ファイルのタイムスタンプを確認してください（10秒以上の差が必要）
- ログメッセージでエラーの詳細を確認してください

### `/path/to/src/md2pdf.py: Permission denied` が出る場合
- `src/md2pdf.py` を直接実行していて、実行権限が付いていない可能性があります
- 最も確実なのは `python /absolute/path/to/src/md2pdf.py ...` の形で起動する方法です
- 直接実行したい場合は `chmod +x /absolute/path/to/src/md2pdf.py` を一度実行してください
