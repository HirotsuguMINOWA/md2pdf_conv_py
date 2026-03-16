#!/usr/bin/env python3
"""
md2pdf.py  –  MD → PDF 変換スクリプト（監視モード付き）

使い方:
    python md2pdf.py <file.md>       # 単一ファイルを変換
    python md2pdf.py [フォルダ]      # フォルダを再帰的に監視して自動変換
    python md2pdf.py --watch [フォルダ]  # 同上（省略時はスクリプトと同じフォルダ）

依存: 標準ライブラリのみ（pip インストール不要）
      pandoc / lualatex が PATH または /opt/homebrew/bin に必要
"""

import os
import sys
import time
import subprocess
from pathlib import Path

# -------------------------------------------------------
# 設定
# -------------------------------------------------------
SCRIPT_DIR = Path(__file__).resolve().parent
PANDOC     = "/opt/homebrew/bin/pandoc"
HEADER_TEX = str(SCRIPT_DIR / "japanese.tex")
POLL_INTERVAL = 2.0   # 秒

PANDOC_ARGS = [
    "-t", "pdf",
    "--pdf-engine=lualatex",
    "-V", "mainfont=Hiragino Kaku Gothic ProN",
    "-V", "sansfont=Hiragino Kaku Gothic ProN",
    "-V", "monofont=Hiragino Kaku Gothic ProN",
    "-H", HEADER_TEX,
]

# -------------------------------------------------------
# 変換
# -------------------------------------------------------
def convert(md_path: Path) -> None:
    out_path = md_path.with_suffix(".pdf")
    print(f"Converting: {md_path}")
    result = subprocess.run(
        [PANDOC, str(md_path)] + PANDOC_ARGS + ["-o", str(out_path)],
        capture_output=True,
        text=True,
    )
    if result.stdout:
        print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, end="", file=sys.stderr)
    if result.returncode == 0:
        print(f"  -> {out_path}")
    else:
        print(f"  [ERROR] pandoc exited with code {result.returncode}", file=sys.stderr)

# -------------------------------------------------------
# ポーリング式ファイル監視（stdlib のみ）
# -------------------------------------------------------
def collect_mtimes(watch_dir: Path) -> dict:
    """watch_dir 以下の全 .md ファイルの {path: mtime} を返す"""
    return {
        p: p.stat().st_mtime
        for p in watch_dir.rglob("*.md")
        if p.is_file()
    }

def watch(watch_dir: Path) -> None:
    print(f"Watching: {watch_dir}")
    print("Press Ctrl+C to stop.")

    prev = collect_mtimes(watch_dir)

    try:
        while True:
            time.sleep(POLL_INTERVAL)
            curr = collect_mtimes(watch_dir)

            for path, mtime in curr.items():
                if path not in prev or prev[path] != mtime:
                    convert(path)

            prev = curr

    except KeyboardInterrupt:
        print("\nStopped.")

# -------------------------------------------------------
# エントリポイント
# -------------------------------------------------------
def main() -> None:
    args = sys.argv[1:]

    # --watch を除去してフォルダ引数だけ取り出す
    if args and args[0] == "--watch":
        args = args[1:]

    if not args:
        # 引数なし → スクリプトと同じフォルダを監視
        watch(SCRIPT_DIR)

    elif len(args) == 1:
        target = Path(args[0]).resolve()

        if target.is_dir():
            watch(target)

        elif target.is_file() and target.suffix == ".md":
            convert(target)
            sys.exit(0)

        else:
            print(f"Error: '{target}' is not a .md file or directory.", file=sys.stderr)
            print("Usage:")
            print("  python md2pdf.py <file.md>      # 単一ファイルを変換")
            print("  python md2pdf.py [フォルダ]     # フォルダを監視")
            sys.exit(1)

    else:
        print("Error: too many arguments.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
