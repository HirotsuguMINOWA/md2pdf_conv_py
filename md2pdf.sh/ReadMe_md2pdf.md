# md2pdf 備忘録

最終更新: 2026-03-15

---

## 概要

Markdown ファイルを監視し、更新があれば自動的に pandoc + lualatex 経由で PDF に変換する仕組み。
日本語・絵文字を含む Markdown を想定。

---

## フォルダ構成

```text
md2pdf/
├── md2pdf.py       # メインスクリプト（監視 + 変換）
├── japanese.tex    # pandoc に渡す LaTeX ヘッダ（日本語・絵文字設定）
└── ReadMe_md2pdf.md
```

> `md2pdf.py` と `japanese.tex` は **同じフォルダに置くこと**。
> スクリプトが自動的に同フォルダの `japanese.tex` を参照する。

---

## 必要なツール

### Python

標準ライブラリのみ使用。**pip インストール不要。**
使用モジュール: `os`, `sys`, `time`, `subprocess`, `pathlib`

```sh
python3 --version   # 3.6 以上を推奨
```

### pandoc

```sh
brew install pandoc
which pandoc        # → /opt/homebrew/bin/pandoc
pandoc --version    # 動作確認済み: pandoc 3.9
```

### TeX Live（lualatex + 日本語対応）

```sh
# MacTeX または TeX Live 2024 以降を推奨
tlmgr install luatexja
tlmgr install luatexja-fontspec
tlmgr install emoji
tlmgr install beamer

# インストール確認
kpsewhich emoji.sty      # → /usr/local/texlive/2026/.../emoji.sty
kpsewhich luatexja.sty
```

---

## 使い方

### 単一ファイルを変換

```sh
python md2pdf.py file.md
```

### フォルダを監視して自動変換

```sh
# md2pdf.py と同じフォルダを監視（引数省略）
python md2pdf.py

# フォルダを指定して監視
python md2pdf.py /path/to/folder
python md2pdf.py --watch /path/to/folder
```

変更を検知すると自動的に変換が走り、**md ファイルと同名・同フォルダに `.pdf` を生成**する。
停止は `Ctrl+C`。

---

## 外部ファイル：`japanese.tex`

pandoc の `-H` オプションで読み込む LaTeX ヘッダ。
日本語フォント設定と絵文字サポートを担う。

```latex
\usepackage{luatexja}
\usepackage{luatexja-fontspec}
\usepackage{emoji}
\setemojifont{Apple Color Emoji}

% Unicode絵文字 → \emoji{} コマンドへのマッピング
% HaranoAjiMincho が絵文字を処理しようとするのを防ぐ
\usepackage{newunicodechar}
\newunicodechar{✅}{\emoji{white-check-mark}}
\newunicodechar{❌}{\emoji{cross-mark}}
...（以下略）
```

> **注意:** このファイルは純粋な LaTeX コードのみ記述すること。
> シェルスクリプト（`cat > ... << 'EOF'` 等）を混入させないこと（過去に混入して壊れた経緯あり）。

---

## 内部動作

### 監視の仕組み（ポーリング方式）

`watchdog` 等の外部ライブラリを使わず、`Path.rglob("*.md")` で全 `.md` ファイルを列挙し、
`st_mtime`（最終更新時刻）を2秒ごとに比較して変更を検出する。

```text
起動時: 全 .md の mtime をスナップショット
  ↓
2秒待機
  ↓
再スキャン → mtime が変わっていれば convert() を呼び出す
  ↓（繰り返し）
```

Google Drive マウント環境では inotify が使えないため、ポーリング方式が安定して動作する。

### 変換コマンド（内部で実行される pandoc）

```sh
pandoc <file.md> \
    -t pdf \
    --pdf-engine=lualatex \
    -V mainfont="Hiragino Kaku Gothic ProN" \
    -V sansfont="Hiragino Kaku Gothic ProN" \
    -V monofont="Hiragino Kaku Gothic ProN" \
    -H /path/to/japanese.tex \
    -o <file.pdf>
```

---

## トラブルシューティング

### 絵文字が PDF に表示されない

**症状:** `[WARNING] Missing character: There is no ✅ (U+2705) in font file:HaranoAjiMincho-Regular`

**原因:** luatexja が絵文字を日本語フォント（HaranoAjiMincho）で処理しようとするが、そのフォントは絵文字に非対応。

**対処:** `japanese.tex` に `\newunicodechar` で該当絵文字をマッピングする。

```latex
\newunicodechar{🎉}{\emoji{party-popper}}
```

絵文字パッケージ名の調べ方:
```sh
texdoc emoji   # emoji パッケージのドキュメントを開く
```

### `japanese.tex` が読み込まれない

**原因:** `md2pdf.py` と `japanese.tex` が別フォルダにある。

**対処:** 両ファイルを同じフォルダに置く。スクリプトは `__file__` の親ディレクトリを自動参照する。

### `japanese.tex` の内容が壊れている

**症状:** LaTeX エラーが大量に出る / PDF が生成されない

**原因:** 過去に以下のようなシェルスクリプトが混入した経緯がある。

```sh
cat > /tmp/japanese.tex << 'EOF'   ← これが混入すると壊れる
\usepackage{luatexja}
...
EOF
```

**対処:** ファイルを開いて LaTeX コードのみになっているか確認する。

### `pandoc: inappropriate type (is a directory)` エラー

**症状:** ファイルではなくフォルダパスを単一変換として処理しようとした。

**対処:** `md2pdf.py` はフォルダが渡されると自動的に監視モードに切り替わる。
`.md` ファイルを直接渡すこと。

### `libsimdjson.*.dylib` エラーで node/chokidar が起動しない

**症状:** `dyld: Library not loaded: libsimdjson.30.dylib`

**原因:** Homebrew で simdjson が更新され、node がリンクしている `.dylib` が消えた。

**対処:** `brew reinstall node`（現在は chokidar を使わない Python 版に移行済みのため基本的に不要）

---

## 開発経緯

| 段階 | 内容 |
| ---- | ---- |
| 初期 | chokidar（Node.js）+ bash スクリプト（`md2pdf.sh` + `watch_md.sh`）で実装 |
| 問題① | fish shell が `p="$1"` 構文をサポートせずエラー → bash ラッパースクリプトに分離 |
| 問題② | chokidar の `-c` 引数のクォートネストが複雑で `-o` パスが正しく生成されなかった |
| 問題③ | `libsimdjson.dylib` の欠落で node ごと起動不可 → `brew reinstall node` で解決 |
| 問題④ | `japanese.tex` にシェルスクリプトが混入し LaTeX ヘッダが壊れた |
| 問題⑤ | 絵文字（✅ 等）が HaranoAjiMincho で処理されて警告 → `\newunicodechar` で対処 |
| 現在 | Python（標準ライブラリのみ）に全面移行。`md2pdf.py` 1ファイルで完結 |

---

## 環境情報（確認済み）

| ツール | パス / バージョン |
| ------ | --------------- |
| Python | `/usr/bin/python3` (3.x) |
| pandoc | `/opt/homebrew/bin/pandoc` (3.9) |
| lualatex | TeX Live 2026 |
| emoji.sty | `/usr/local/texlive/2026/texmf-dist/tex/latex/emoji/emoji.sty` |
| OS | macOS（Apple Silicon） |
