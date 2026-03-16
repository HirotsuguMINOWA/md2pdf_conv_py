# #!/bin/bash
# # 指定フォルダ（サブフォルダ含む）の .md ファイルを監視し、
# # 更新があれば pandoc で .pdf に変換する。
# #
# # 使い方:
# #   watch_md.sh [フォルダパス]
# #   フォルダパスを省略すると、このスクリプトと同じフォルダを監視する。

# SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# WATCH_DIR="${1:-$SCRIPT_DIR}"
# CONVERT_SCRIPT="$SCRIPT_DIR/md2pdf.sh"
# HEADER_TEX="$SCRIPT_DIR/japanese.tex"

# if [ ! -d "$WATCH_DIR" ]; then
#     echo "Error: '$WATCH_DIR' is not a directory."
#     exit 1
# fi

# if [ ! -f "$CONVERT_SCRIPT" ]; then
#     echo "Error: md2pdf.sh not found at '$CONVERT_SCRIPT'"
#     exit 1
# fi

# echo "Watching: $WATCH_DIR"
# echo "Press Ctrl+C to stop."

# /opt/homebrew/bin/chokidar \
#     "$WATCH_DIR/**/*.md" \
#     --use-polling \
#     --interval 2000 \
#     --shell bash \
#     -c "$CONVERT_SCRIPT '{path}'"
