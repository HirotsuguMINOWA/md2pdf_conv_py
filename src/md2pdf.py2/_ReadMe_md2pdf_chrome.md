# MD → PDF 変換 備忘録（chokidar + pandoc + lualatex）

最終更新: 2026-03-15

---

## 概要

Markdownファイルを監視し、変更があれば自動的に pandoc 経由でBeamer PDF（日本語スライド）に変換する仕組み。

- **監視:** chokidar（Node.js製CLIツール）
- **変換:** `md2pdf.sh`（bash ラッパースクリプト）経由で pandoc + lualatex を呼び出す
- **出力:** mdファイルと同名・同フォルダに `.pdf` を生成

---

## 必要なツール・モジュール

### Homebrew 系

```sh
brew install pandoc
npm install -g chokidar-cli
```

### TeX Live（lualatex + 日本語対応）

```sh
# macOS: MacTeX または TeX Live 2024以降を推奨
# 以下のパッケージが必要（tlmgr で確認・追加）
tlmgr install luatexja
tlmgr install luatexja-fontspec
tlmgr install emoji
tlmgr install beamer
```

インストール確認コマンド：

```sh
kpsewhich emoji.sty       # emoji パッケージ確認
kpsewhich luatexja.sty    # luatexja 確認
which pandoc              # pandoc パス確認（→ /opt/homebrew/bin/pandoc）
which chokidar            # chokidar パス確認
```

---

## 外部ファイル（同フォルダに配置）

### `md2pdf.sh`（pandoc 変換ラッパー）

**fish shell は `p="$1"` 構文をサポートしないため**、bash スクリプトとして分離。
chokidar の `-c` から呼び出す。

```bash
#!/bin/bash
if [ -z "$1" ]; then
    echo "Usage: md2pdf.sh <file.md>"
    exit 1
fi
p="$1"
/opt/homebrew/bin/pandoc "$p" -t beamer --pdf-engine=lualatex \
    -V mainfont="Hiragino Kaku Gothic ProN" \
    -V sansfont="Hiragino Kaku Gothic ProN" \
    -V monofont="Hiragino Kaku Gothic ProN" \
    -H "/Users/hirots-m/Library/CloudStorage/GoogleDrive-researcher.and.educator@gmail.com/マイドライブ/EduMaterial/javascript入門/japanese.tex" \
    -o "${p%.md}.pdf"
```

作成後、実行権限を付与：

```sh
chmod +x md2pdf.sh
```

### `japanese.tex`（`-H` で読み込む LaTeX ヘッダ）

```latex
\usepackage{luatexja}
\usepackage{luatexja-fontspec}
\usepackage{emoji}
\setemojifont{Apple Color Emoji}
```

> **注意:** このファイルは純粋な LaTeX コードのみ記述すること。
> シェルスクリプト（`cat > ... << 'EOF'` 等）を混入させないこと（過去に混入して壊れた経緯あり）。

### `header.tex`（追加設定が必要な場合の代替ヘッダ）

```latex
\usepackage{luatexja-fontspec}
\usepackage{emoji}
\setemojifont{Apple Color Emoji}
\ltjsetparameter{jacharrange={6}}
```

---

## 監視 + 変換コマンド（chokidar）

```sh
chokidar \
  "/Users/hirots-m/Library/CloudStorage/GoogleDrive-researcher.and.educator@gmail.com/マイドライブ/EduMaterial/javascript入門/**/*.md" \
  --use-polling \
  --interval 2000 \
  -c '"/Users/hirots-m/Library/CloudStorage/GoogleDrive-researcher.and.educator@gmail.com/マイドライブ/EduMaterial/javascript入門/md2pdf.sh" "{path}"'
```

**ポイント:**
- `-c` には `md2pdf.sh` を絶対パスで指定し、`{path}` を引数として渡す
- `--use-polling` は Google Drive マウント環境での inotify 非対応を回避するため必須
- `--interval 2000` は2秒ごとのポーリング（頻度は状況に応じて調整）
- 出力先は **mdファイルと同フォルダ・同名の `.pdf`**（`${p%.md}.pdf` による拡張子置換）

---

## トラブルシューティング

### `fish: Unsupported use of '='` エラー

**症状:** chokidar の `-c` 内で `p="..."` を直接書くと fish が構文エラーを出す

**原因:** fish shell は `VAR=value` 構文をサポートしない（`set VAR value` が正式構文）

**対処:** `md2pdf.sh`（bash スクリプト）に分離し、chokidar からはそれを呼び出す

### `md2pdf.sh` を引数なしで実行するとエラー

**症状:** `pandoc: withBinaryFile: does not exist (No such file or directory)`

**原因:** `$1` が空のまま pandoc に渡される

**対処:** スクリプト先頭の引数チェック（`if [ -z "$1" ]`）で検出・メッセージ表示

### ✅ 等の絵文字が PDF に出ない

**症状:** `[WARNING] Missing character: There is no ✅ (U+2705) in font file:HaranoAjiMincho-Regular`

**原因:**
1. `japanese.tex` の内容が壊れている（シェルスクリプトが混入している等）
2. `emoji` パッケージが未インストール
3. `-H` に相対パスを指定しており `japanese.tex` が読み込まれていない

**対処:**
- `kpsewhich emoji.sty` で emoji パッケージの存在確認
- `japanese.tex` の中身がLaTeXのみであることを確認
- `md2pdf.sh` 内の `-H` が絶対パスになっているか確認

### `dyld: Library not loaded: libsimdjson.*.dylib` エラー

**症状:** chokidar 実行時に node が起動しない

**原因:** Homebrew で simdjson が更新され、node がリンクしている `.dylib` が消えた

**対処:** `brew reinstall node`

### HaranoAjiMincho が使われてしまう

`-V mainfont` の指定が beamer テンプレートに適用されない場合がある。
`japanese.tex` 内で明示的に設定する方法：

```latex
\setmainfont{Hiragino Kaku Gothic ProN}
\setsansfont{Hiragino Kaku Gothic ProN}
\setmonofont{Hiragino Kaku Gothic ProN}
```

---

## 環境情報（確認済み）

| ツール | パス / バージョン |
| ------ | --------------- |
| pandoc | `/opt/homebrew/bin/pandoc` (3.9) |
| chokidar | `/opt/homebrew/bin/chokidar` |
| lualatex | TeX Live 2026 |
| emoji.sty | `/usr/local/texlive/2026/texmf-dist/tex/latex/emoji/emoji.sty` |
