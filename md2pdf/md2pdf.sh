#!/bin/bash
# MD → PDF 変換スクリプト（監視モード付き）
#
# 使い方:
#   md2pdf.sh <file.md>            # 単一ファイルを変換
#   md2pdf.sh --watch [フォルダ]   # フォルダを監視して自動変換（省略時は自フォルダ）

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# -------------------------------------------------------
# 変換関数
# -------------------------------------------------------
convert() {
    local p="$1"
    echo "Converting: $p"
    /opt/homebrew/bin/pandoc "$p" -t pdf --pdf-engine=lualatex \
        -V mainfont="Hiragino Kaku Gothic ProN" \
        -V sansfont="Hiragino Kaku Gothic ProN" \
        -V monofont="Hiragino Kaku Gothic ProN" \
        -H "$SCRIPT_DIR/japanese.tex" \
        -o "${p%.md}.pdf"
}

# -------------------------------------------------------
# 引数の振り分け
# -------------------------------------------------------
if [ "$1" = "--watch" ]; then
    # 監視モード（--watch フォルダ）
    WATCH_DIR="${2:-$SCRIPT_DIR}"
elif [ -d "$1" ]; then
    # 引数がディレクトリ → 監視モード
    WATCH_DIR="$1"
elif [ -f "$1" ]; then
    # 引数がファイル → 単一変換モード
    convert "$1"
    exit $?
elif [ -z "$1" ]; then
    # 引数なし → 自フォルダを監視
    WATCH_DIR="$SCRIPT_DIR"
else
    echo "Error: '$1' is not a file or directory."
    echo "Usage:"
    echo "  md2pdf.sh <file.md>            # 単一ファイルを変換"
    echo "  md2pdf.sh [フォルダ]           # フォルダを監視して自動変換"
    exit 1
fi

echo "Watching: $WATCH_DIR"
echo "Press Ctrl+C to stop."

/opt/homebrew/bin/chokidar \
    "$WATCH_DIR/**/*.md" \
    --use-polling \
    --interval 2000 \
    --shell bash \
    -c "$0 '{path}'"
