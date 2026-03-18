#!/usr/bin/env python3
"""
 目的: markdownファイルをpdfへ変換するソフト
 概略:
1. 指定されたフォルダを監視して、markdownファイル(.md)ファイルが更新されたら、pdfへ変換する
2. 変換されたPDFは、root_src PATHと同様のroot_destパスへコピーする
3. .mdファイルは中身を確認し、marp用であったらmarp-cliで変換し、
   slidev用であったらslidevで変換し、それ以外であればpandocでpdfへ変換する。

条件:
- 本プログラムを開始したら、root_srcフォルダ内の下記通り探索する。
--- root_src内の同一ファイル名の.mdと.pdfのタイムスタンプを確認し、10秒以上差があれば、 .mdを.pdfへ変換する。
- 起動後、探索をし終えたら、root_srcフォルダ内を監視し、監視対象の.mdファイルが更新された.pdfへ変換監視する。以後、プログラム終了まで監視処理を行う
- .md以外は変換しないが、指定された拡張子のファイルは、同フォルダ構成位置へコピーする

 手順:
 1. バンドルされたmarp-cliバイナリの存在確認
 2. slidev コマンドの存在確認
 3. 指定された監視対象のフォルダをroot_srcとする。root_srcフォルダ構成を、pdf保存先であるroot_destフォルダにも同階層構造を再現する
"""

import os
import sys
import platform
import time
import shutil
import subprocess
import argparse
import logging
from pathlib import Path
from typing import Protocol
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler


class _FSEvent(Protocol):
    is_directory: bool
    src_path: str


# ログ設定
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# -------------------------------------------------------
# パス設定
# -------------------------------------------------------
SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent

# pandoc 設定（md2pdf/md2pdf.py に準拠）
PANDOC: str = "/opt/homebrew/bin/pandoc"
HEADER_TEX: str = str(REPO_ROOT / "md2pdf" / "japanese.tex")
PANDOC_ARGS: list[str] = [
    "-t", "pdf",
    "--pdf-engine=lualatex",
    "-V", "mainfont=Hiragino Kaku Gothic ProN",
    "-V", "sansfont=Hiragino Kaku Gothic ProN",
    "-V", "monofont=Hiragino Kaku Gothic ProN",
    "-H", HEADER_TEX,
]

# marp-cli バンドルバイナリ


def _get_marp_binary() -> Path:
    system = platform.system()
    if system == "Windows":
        return REPO_ROOT / "marp-cli" / "win" / "marp.exe"
    elif system == "Darwin":
        return REPO_ROOT / "marp-cli" / "macos" / "marp"
    elif system == "Linux":
        return REPO_ROOT / "marp-cli" / "linux" / "marp"
    else:
        raise NotImplementedError(f"{system=}のmarp-cliはありません。")


MARP_BIN: Path = _get_marp_binary()


class MarkdownConverter:
    root_src: Path
    root_dest: Path
    copy_extensions: list[str]
    marp_available: bool
    slidev_available: bool

    def __init__(self, root_src: str, root_dest: str,
                 copy_extensions: list[str] | None = None) -> None:
        self.root_src = Path(root_src)
        self.root_dest = Path(root_dest)
        self.copy_extensions = copy_extensions or ['.png', '.jpg', '.jpeg', '.gif', '.svg']
        self.marp_available = self._check_marp()
        self.slidev_available = self._check_slidev()

        # 出力フォルダを作成
        self.root_dest.mkdir(parents=True, exist_ok=True)

    # -------------------------------------------------------
    # ツール存在確認
    # -------------------------------------------------------
    def _check_marp(self) -> bool:
        """バンドルされた marp-cli バイナリの確認"""
        if MARP_BIN.exists():
            logger.info(f"marp-cli found at: {MARP_BIN}")
            # 実行権限を確認・付与
            if not os.access(MARP_BIN, os.X_OK):
                try:
                    MARP_BIN.chmod(MARP_BIN.stat().st_mode | 0o111)
                    logger.info("Granted execute permission to marp binary.")
                except Exception as e:
                    logger.warning(f"Could not set execute permission on marp binary: {e}")
            return True
        logger.warning(f"marp-cli binary not found at {MARP_BIN}. Marp conversion unavailable.")
        return False

    def _check_slidev(self) -> bool:
        """slidev コマンドの確認"""
        try:
            result = subprocess.run(['which', 'slidev'], capture_output=True, text=True)
            if result.returncode == 0:
                logger.info(f"slidev found at: {result.stdout.strip()}")
                return True
            # npx 経由で使えるか確認
            result2 = subprocess.run(['npx', '@slidev/cli', '--version'],
                                     capture_output=True, text=True, timeout=10)
            if result2.returncode == 0:
                logger.info("slidev available via npx @slidev/cli")
                return True
        except Exception:
            pass
        logger.warning("slidev not found. Slidev conversion unavailable.")
        return False

    # -------------------------------------------------------
    # ファイル種別判定
    # -------------------------------------------------------
    def _read_frontmatter(self, md_file: Path) -> str:
        """ファイル先頭のフロントマター部分（最大 50 行）を返す"""
        try:
            lines: list[str] = []
            with open(md_file, 'r', encoding='utf-8') as f:
                for i, line in enumerate(f):
                    if i >= 50:
                        break
                    lines.append(line)
            return ''.join(lines)
        except Exception as e:
            logger.error(f"Error reading file {md_file}: {e}")
            return ''

    def is_marp_file(self, md_file: Path) -> bool:
        """marp 用 Markdown か判定"""
        head = self._read_frontmatter(md_file)
        marp_keywords = ['marp: true', 'marp:true']
        return any(kw in head for kw in marp_keywords)

    def is_slidev_file(self, md_file: Path) -> bool:
        """slidev 用 Markdown か判定"""
        head = self._read_frontmatter(md_file)
        slidev_keywords = ['slidev:', 'theme:', 'layout:']
        # slidev ファイルは通常 --- で始まるフロントマターを持ち、
        # かつ slidev 特有のキーワードが含まれる
        has_frontmatter = head.startswith('---')
        has_keyword = any(kw in head for kw in slidev_keywords)
        return has_frontmatter and has_keyword and not self.is_marp_file(md_file)

    # -------------------------------------------------------
    # 変換処理
    # -------------------------------------------------------
    def convert_with_marp(self, md_file: Path, pdf_file: Path) -> bool:
        """バンドルされた marp-cli でPDFに変換"""
        try:
            cmd = [str(MARP_BIN), '--pdf', str(md_file), '-o', str(pdf_file)]
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode == 0:
                logger.info(f"[marp] {md_file} -> {pdf_file}")
                return True
            else:
                logger.error(f"Marp conversion failed: {result.stderr}")
                return False
        except Exception as e:
            logger.error(f"Error during marp conversion: {e}")
            return False

    def convert_with_slidev(self, md_file: Path, pdf_file: Path) -> bool:
        """slidev でPDFに変換"""
        try:
            # slidev export はカレントディレクトリを基準に動作するため cd する
            if shutil.which('slidev'):
                cmd = ['slidev', 'export', str(md_file), '--format', 'pdf', '--output', str(pdf_file)]
            else:
                cmd = ['npx', '@slidev/cli', 'export', str(md_file),
                       '--format', 'pdf', '--output', str(pdf_file)]
            result = subprocess.run(cmd, capture_output=True, text=True,
                                    cwd=str(md_file.parent))
            if result.returncode == 0:
                logger.info(f"[slidev] {md_file} -> {pdf_file}")
                return True
            else:
                logger.error(f"Slidev conversion failed: {result.stderr}")
                return False
        except Exception as e:
            logger.error(f"Error during slidev conversion: {e}")
            return False

    def convert_with_pandoc(self, md_file: Path, pdf_file: Path) -> bool:
        """pandoc (lualatex) でPDFに変換（md2pdf/md2pdf.py に準拠）"""
        try:
            cmd = [PANDOC, str(md_file)] + PANDOC_ARGS + ['-o', str(pdf_file)]
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.stdout:
                print(result.stdout, end='')
            if result.stderr:
                print(result.stderr, end='', file=sys.stderr)
            if result.returncode == 0:
                logger.info(f"[pandoc] {md_file} -> {pdf_file}")
                return True
            else:
                logger.error(f"Pandoc conversion failed (exit {result.returncode})")
                return False
        except Exception as e:
            logger.error(f"Error during pandoc conversion: {e}")
            return False

    def convert_markdown_to_pdf(self, md_file: Path) -> bool:
        """変換ツールを自動選択してPDFに変換（marp > slidev > pandoc）"""
        pdf_file = self.get_dest_path(md_file, '.pdf')
        self.ensure_dest_dir(pdf_file)

        if self.marp_available and self.is_marp_file(md_file):
            return self.convert_with_marp(md_file, pdf_file)
        elif self.slidev_available and self.is_slidev_file(md_file):
            return self.convert_with_slidev(md_file, pdf_file)
        else:
            return self.convert_with_pandoc(md_file, pdf_file)

    # -------------------------------------------------------
    # パス・ディレクトリ操作
    # -------------------------------------------------------
    def get_relative_path(self, file_path: Path) -> Path:
        return file_path.relative_to(self.root_src)

    def get_dest_path(self, src_path: Path, new_extension: str | None = None) -> Path:
        rel_path = self.get_relative_path(src_path)
        if new_extension is not None:
            rel_path = rel_path.with_suffix(new_extension)
        return self.root_dest / rel_path

    def ensure_dest_dir(self, dest_path: Path) -> None:
        dest_path.parent.mkdir(parents=True, exist_ok=True)

    def replicate_folder_structure(self) -> None:
        """フォルダ構造を複製"""
        for dir_path in self.root_src.rglob('*'):
            if dir_path.is_dir():
                dest_dir = self.get_dest_path(dir_path)
                dest_dir.mkdir(parents=True, exist_ok=True)

    # -------------------------------------------------------
    # ファイルコピー・タイムスタンプ
    # -------------------------------------------------------
    def copy_file(self, src_file: Path) -> bool:
        """指定された拡張子のファイルをコピー"""
        dest_file = self.get_dest_path(src_file)
        self.ensure_dest_dir(dest_file)
        try:
            _ = shutil.copy2(src_file, dest_file)
            logger.info(f"Copied {src_file} to {dest_file}")
            return True
        except Exception as e:
            logger.error(f"Error copying file {src_file}: {e}")
            return False

    def should_convert(self, md_file: Path) -> bool:
        """変換が必要かどうか判定（タイムスタンプ比較）"""
        pdf_file = self.get_dest_path(md_file, '.pdf')
        if not pdf_file.exists():
            return True
        try:
            md_mtime = md_file.stat().st_mtime
            pdf_mtime = pdf_file.stat().st_mtime
            return (md_mtime - pdf_mtime) > 10
        except Exception as e:
            logger.error(f"Error comparing timestamps: {e}")
            return True

    def process_file(self, file_path: str | Path) -> None:
        """ファイルを処理"""
        p = Path(file_path)
        if p.suffix == '.md':
            if self.should_convert(p):
                _ = self.convert_markdown_to_pdf(p)
        elif p.suffix in self.copy_extensions:
            _ = self.copy_file(p)

    def initial_scan(self) -> None:
        """初期スキャン"""
        logger.info(f"Starting initial scan of {self.root_src}")
        for file_path in self.root_src.rglob('*'):
            if file_path.is_file():
                self.process_file(file_path)
        logger.info("Initial scan completed")


# -------------------------------------------------------
# watchdog イベントハンドラ
# -------------------------------------------------------
class MarkdownFileHandler(FileSystemEventHandler):
    def __init__(self, converter: MarkdownConverter) -> None:
        self.converter = converter

    def on_modified(self, event: _FSEvent) -> None:
        if not event.is_directory:
            self.converter.process_file(event.src_path)

    def on_created(self, event: _FSEvent) -> None:
        if not event.is_directory:
            self.converter.process_file(event.src_path)


# -------------------------------------------------------
# エントリポイント
# -------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser(
        description='Markdown to PDF converter with folder monitoring (pandoc / marp / slidev)')
    _ = parser.add_argument('root_src', help='Source folder to monitor')
    _ = parser.add_argument('root_dest', help='Destination folder for PDFs')
    _ = parser.add_argument('--copy-extensions', nargs='+',
                            default=['.png', '.jpg', '.jpeg', '.gif', '.svg'],
                            help='File extensions to copy (default: .png .jpg .jpeg .gif .svg)')

    args = parser.parse_args()

    root_src: str = args.root_src
    root_dest: str = args.root_dest
    copy_extensions: list[str] = args.copy_extensions

    if not Path(root_src).exists():
        logger.error(f"Source folder does not exist: {root_src}")
        sys.exit(1)

    converter = MarkdownConverter(root_src, root_dest, copy_extensions)

    converter.replicate_folder_structure()
    converter.initial_scan()

    event_handler = MarkdownFileHandler(converter)
    observer = Observer()
    _ = observer.schedule(event_handler, root_src, recursive=True)

    logger.info(f"Starting file monitoring for {root_src}")
    observer.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Stopping file monitoring...")
        observer.stop()

    observer.join()
    logger.info("Program terminated")


if __name__ == "__main__":
    main()
