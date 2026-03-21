#!/usr/bin/env python3
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
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
    run(
        [
            chrome_path,
            "--headless=new",
            "--disable-gpu",
            "--allow-file-access-from-files",
            "--enable-local-file-accesses",
            f"--virtual-time-budget={timeout_ms}",
            f"--print-to-pdf={pdf_path}",
            html_uri,
        ]
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Convert Markdown to PDF via HTML + Chrome, closer to Markdown Preview Enhanced."
    )
    parser.add_argument("input", help="input markdown file")
    parser.add_argument("-o", "--output", help="output pdf path")
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
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    markdown_path = Path(args.input).expanduser().resolve()
    if not markdown_path.exists():
        print(f"input markdown not found: {markdown_path}", file=sys.stderr)
        return 2

    pdf_path = (
        Path(args.output).expanduser().resolve()
        if args.output
        else markdown_path.with_suffix(".pdf")
    )
    pdf_path.parent.mkdir(parents=True, exist_ok=True)

    mpe_crossnote_root = Path(args.mpe_crossnote_root).expanduser().resolve()
    if not mpe_crossnote_root.exists():
        print(f"MPE crossnote directory not found: {mpe_crossnote_root}", file=sys.stderr)
        return 3

    renderer_script = Path(args.renderer_script).expanduser().resolve()
    if not renderer_script.exists():
        print(f"renderer script not found: {renderer_script}", file=sys.stderr)
        return 4

    chrome_path = find_chrome(args.chrome_path)

    if args.keep_html:
        html_path = pdf_path.with_suffix(".html")
        render_html(markdown_path, html_path, renderer_script, mpe_crossnote_root)
    else:
        with tempfile.TemporaryDirectory(prefix="md2pdf-py2-") as tmp_dir:
            html_path = Path(tmp_dir) / f"{markdown_path.stem}.html"
            render_html(markdown_path, html_path, renderer_script, mpe_crossnote_root)
            print_pdf(html_path, pdf_path, chrome_path, args.timeout_ms)
            print(f"PDF written to: {pdf_path}")
            return 0

    print_pdf(html_path, pdf_path, chrome_path, args.timeout_ms)
    print(f"HTML written to: {html_path}")
    print(f"PDF written to: {pdf_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
