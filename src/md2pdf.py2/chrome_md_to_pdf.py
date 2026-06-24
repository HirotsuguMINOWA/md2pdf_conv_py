#!/usr/bin/env python3
"""
markdown to pdf via HTML + Chrome converter

このスクリプトは、MarkdownファイルをHTMLに変換し、Headless Chromeを使用してPDFに変換します。
Markdown Preview Enhanced (MPE) のレンダリングスタイルに近づけるように設計されています。

CLI パラメータ:
    input                 入力Markdownファイルのパス
    -o, --output          出力PDFファイルのパス（省略時は入力ファイル名の.pdf）
    --watch               監視対象フォルダのパス
    --output-dir          watch モード時の出力先フォルダ
    --chrome-path         Chrome/Chromiumの実行ファイルの明示的なパス
    --mpe-crossnote-root  Markdown Preview Enhanced の crossnote ディレクトリパス
                          (デフォルト: ~/.vscode/extensions/...)
    --renderer-script     マークダウンレンダリング用JavaScriptファイルのパス
                          (デフォルト: スクリプトと同じディレクトリの render_markdown.js)
    --keep-html           HTMLファイルを出力PDFの隣に保持する（デフォルトは削除）
    --timeout-ms          Headless Chromeのレンダリング完了までの時間（ミリ秒）
                          (デフォルト: 15000)

使用例:
    python chrome_md_to_pdf.py README.md
    python chrome_md_to_pdf.py README.md -o output.pdf
    python chrome_md_to_pdf.py README.md --chrome-path /path/to/chrome --keep-html
    python chrome_md_to_pdf.py --watch ./docs --output-dir ./publish
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path


DEFAULT_MPE_CROSSNOTE = Path.home() / ".vscode" / "extensions" / "shd101wyy.markdown-preview-enhanced-0.8.21" / "crossnote"
DEFAULT_CHROME_CANDIDATES = [
    Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
    Path("/Applications/Chromium.app/Contents/MacOS/Chromium"),
]


def find_node() -> str:
    node = shutil.which("node")
    if node:
        return node
    raise FileNotFoundError("node was not found in PATH")


def find_chrome(explicit: str | None) -> str:
    if explicit:
        chrome_path = Path(explicit).expanduser()
        if chrome_path.exists():
            return str(chrome_path)
        raise FileNotFoundError(f"chrome not found: {chrome_path}")

    for candidate in DEFAULT_CHROME_CANDIDATES:
        if candidate.exists():
            return str(candidate)

    for name in ["google-chrome", "chromium", "chromium-browser"]:
        found = shutil.which(name)
        if found:
            return found

    raise FileNotFoundError("Chrome/Chromium was not found")


def run(command: list[str], cwd: Path | None = None) -> None:
    completed = subprocess.run(
        command,
        cwd=str(cwd) if cwd else None,
        text=True,
        capture_output=True,
    )
    if completed.stdout:
        print(completed.stdout, end="")
    if completed.stderr:
        print(completed.stderr, end="", file=sys.stderr)
    if completed.returncode != 0:
        raise RuntimeError(f"command failed ({completed.returncode}): {' '.join(command)}")


def render_html(
    markdown_path: Path,
    html_path: Path,
    renderer_script: Path,
    mpe_crossnote_root: Path,
) -> None:
    run(
        [
            find_node(),
            str(renderer_script),
            str(markdown_path),
            str(html_path),
            str(mpe_crossnote_root),
        ]
    )


def print_pdf(
    html_path: Path,
    pdf_path: Path,
    chrome_path: str,
    timeout_ms: int,
) -> None:
    html_uri = html_path.resolve().as_uri()
    with tempfile.TemporaryDirectory(prefix="md2pdf-py2-chrome-") as user_data_dir:
        run(
            [
                chrome_path,
                "--headless",
                "--disable-gpu",
                "--no-first-run",
                "--no-default-browser-check",
                f"--user-data-dir={user_data_dir}",
                "--allow-file-access-from-files",
                "--enable-local-file-accesses",
                f"--virtual-time-budget={timeout_ms}",
                "--print-to-pdf-no-header",
                f"--print-to-pdf={pdf_path}",
                html_uri,
            ]
        )


def convert_markdown_to_html_and_pdf(
    markdown_path: Path,
    html_path: Path,
    pdf_path: Path,
    renderer_script: Path,
    mpe_crossnote_root: Path,
    chrome_path: str,
    timeout_ms: int,
) -> None:
    html_path.parent.mkdir(parents=True, exist_ok=True)
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    render_html(markdown_path, html_path, renderer_script, mpe_crossnote_root)
    print_pdf(html_path, pdf_path, chrome_path, timeout_ms)


def iter_markdown_files(root: Path) -> list[Path]:
    return sorted(path for path in root.rglob("*.md") if path.is_file())


def resolve_watch_outputs(markdown_path: Path, watch_root: Path, output_root: Path) -> tuple[Path, Path]:
    relative_path = markdown_path.relative_to(watch_root)
    html_path = output_root / relative_path.with_suffix(".html")
    pdf_path = output_root / relative_path.with_suffix(".pdf")
    return html_path, pdf_path


def needs_rebuild(markdown_path: Path, html_path: Path, pdf_path: Path) -> bool:
    if not html_path.exists() or not pdf_path.exists():
        return True
    source_mtime = markdown_path.stat().st_mtime
    return source_mtime > html_path.stat().st_mtime or source_mtime > pdf_path.stat().st_mtime


def run_watch_mode(
    watch_root: Path,
    output_root: Path,
    renderer_script: Path,
    mpe_crossnote_root: Path,
    chrome_path: str,
    timeout_ms: int,
    poll_interval: float,
) -> int:
    if not watch_root.exists() or not watch_root.is_dir():
        print(f"watch directory not found: {watch_root}", file=sys.stderr)
        return 5

    output_root.mkdir(parents=True, exist_ok=True)
    known_mtimes: dict[Path, float] = {}

    print(f"Watching: {watch_root}")
    print(f"Output root: {output_root}")

    while True:
        try:
            current_files = iter_markdown_files(watch_root)
            current_set = set(current_files)

            for removed in set(known_mtimes) - current_set:
                known_mtimes.pop(removed, None)

            for markdown_path in current_files:
                current_mtime = markdown_path.stat().st_mtime
                previous_mtime = known_mtimes.get(markdown_path)
                html_path, pdf_path = resolve_watch_outputs(markdown_path, watch_root, output_root)

                should_process = False
                if previous_mtime is None:
                    should_process = needs_rebuild(markdown_path, html_path, pdf_path)
                elif current_mtime > previous_mtime:
                    should_process = True

                if should_process:
                    try:
                        convert_markdown_to_html_and_pdf(
                            markdown_path,
                            html_path,
                            pdf_path,
                            renderer_script,
                            mpe_crossnote_root,
                            chrome_path,
                            timeout_ms,
                        )
                        print(f"Updated: {markdown_path} -> {html_path}, {pdf_path}")
                    except Exception as exc:
                        print(f"Failed: {markdown_path}: {exc}", file=sys.stderr)

                known_mtimes[markdown_path] = current_mtime

            time.sleep(poll_interval)
        except KeyboardInterrupt:
            print("Stopping watch mode.")
            return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Convert Markdown to PDF via HTML + Chrome, closer to Markdown Preview Enhanced."
    )
    parser.add_argument("input", nargs="?", help="input markdown file")
    parser.add_argument("-o", "--output", help="output pdf path")
    parser.add_argument("--watch", help="watch a directory and rebuild changed markdown files")
    parser.add_argument(
        "--output-dir",
        help="output directory for watch mode (defaults to the watched directory)",
    )
    parser.add_argument("--chrome-path", help="explicit path to Chrome/Chromium")
    parser.add_argument(
        "--mpe-crossnote-root",
        default=str(DEFAULT_MPE_CROSSNOTE),
        help="path to Markdown Preview Enhanced crossnote directory",
    )
    parser.add_argument(
        "--renderer-script",
        default=str(Path(__file__).with_name("render_markdown.js")),
        help="path to render_markdown.js",
    )
    parser.add_argument(
        "--keep-html",
        action="store_true",
        help="keep the generated html next to the pdf",
    )
    parser.add_argument(
        "--timeout-ms",
        type=int,
        default=15000,
        help="time budget for headless chrome to finish rendering before printing",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=1.0,
        help="watch mode polling interval in seconds",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    pdf_path = (
        Path(args.output).expanduser().resolve()
        if args.output
        else None
    )

    mpe_crossnote_root = Path(args.mpe_crossnote_root).expanduser().resolve()
    if not mpe_crossnote_root.exists():
        print(f"MPE crossnote directory not found: {mpe_crossnote_root}", file=sys.stderr)
        return 3

    renderer_script = Path(args.renderer_script).expanduser().resolve()
    if not renderer_script.exists():
        print(f"renderer script not found: {renderer_script}", file=sys.stderr)
        return 4

    chrome_path = find_chrome(args.chrome_path)

    if args.watch:
        watch_root = Path(args.watch).expanduser().resolve()
        output_root = (
            Path(args.output_dir).expanduser().resolve()
            if args.output_dir
            else watch_root
        )
        return run_watch_mode(
            watch_root,
            output_root,
            renderer_script,
            mpe_crossnote_root,
            chrome_path,
            args.timeout_ms,
            args.poll_interval,
        )

    if not args.input:
        print("input markdown file is required when --watch is not used", file=sys.stderr)
        return 2

    markdown_path = Path(args.input).expanduser().resolve()
    if not markdown_path.exists():
        print(f"input markdown not found: {markdown_path}", file=sys.stderr)
        return 2

    if pdf_path is None:
        pdf_path = markdown_path.with_suffix(".pdf")
    pdf_path.parent.mkdir(parents=True, exist_ok=True)

    if args.keep_html:
        html_path = pdf_path.with_suffix(".html")
        convert_markdown_to_html_and_pdf(
            markdown_path,
            html_path,
            pdf_path,
            renderer_script,
            mpe_crossnote_root,
            chrome_path,
            args.timeout_ms,
        )
    else:
        with tempfile.TemporaryDirectory(prefix="md2pdf-py2-") as tmp_dir:
            html_path = Path(tmp_dir) / f"{markdown_path.stem}.html"
            convert_markdown_to_html_and_pdf(
                markdown_path,
                html_path,
                pdf_path,
                renderer_script,
                mpe_crossnote_root,
                chrome_path,
                args.timeout_ms,
            )
            print(f"PDF written to: {pdf_path}")
            return 0

    print(f"HTML written to: {html_path}")
    print(f"PDF written to: {pdf_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
