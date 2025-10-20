#!/usr/bin/env python3
"""
 目的: markdownファイルをpdfへ変換するソフト
 概略:
1. 指定されたフォルダを監視して、markdownファイル(.md)ファイルが更新されたら、pdfへ変換する
2. 変換されたPDFは、root_src PATHと同様のroot_destパスへコピーする
3. .mdファイルは中身を確認し、marp用であったらmarp-cliで変換し、  それ以外であればpandocでpdfへ変換する。

条件:
- 本プログラムを開始したら、root_srcフォルダ内の下記通り探索する。
--- root_src内の同一ファイル名の.mdと.pdfのタイムスタンプを確認し、10秒以上差があれば、 .mdを.pdfへ変換する。
- 起動後、探索をし終えたら、root_srcフォルダ内を監視し、監視対象の.mdファイルが更新された.pdfへ変換監視する。以後、プログラム終了まで監視処理を行う
- .md以外は変換しないが、指定された拡張子のファイルは、同フォルダ構成位置へコピーする


 手順:
 1. /usr/bin/marp-cliが存在するかチェック
 2. 指定された監視対象のフォルダをroot_srcとする。root_srcフォルダ構成を、pdf保存先であるroot_destフォルダにも同階層構造を再現する
"""

import os
import sys
import time
import shutil
import subprocess
import argparse
from pathlib import Path
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
import logging

# ログ設定
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class MarkdownConverter:
    def __init__(self, root_src, root_dest, copy_extensions=None):
        self.root_src = Path(root_src)
        self.root_dest = Path(root_dest)
        self.copy_extensions = copy_extensions or ['.png', '.jpg', '.jpeg', '.gif', '.svg']
        self.marp_available = self.check_marp_cli()
        
        # 出力フォルダを作成
        self.root_dest.mkdir(parents=True, exist_ok=True)
        
    def check_marp_cli(self):
        """marp-cliの存在確認"""
        try:
            result = subprocess.run(['which', 'marp'], capture_output=True, text=True)
            if result.returncode == 0:
                logger.info(f"marp-cli found at: {result.stdout.strip()}")
                return True
            else:
                # /usr/bin/marp-cliも確認
                if Path('/usr/bin/marp-cli').exists():
                    logger.info("marp-cli found at: /usr/bin/marp-cli")
                    return True
                logger.warning("marp-cli not found. Only pandoc conversion will be available.")
                return False
        except Exception as e:
            logger.error(f"Error checking marp-cli: {e}")
            return False
    
    def is_marp_file(self, md_file):
        """markdownファイルがmarp用かどうか判定"""
        try:
            with open(md_file, 'r', encoding='utf-8') as f:
                content = f.read()
                # marpの特徴的なキーワードを検索
                marp_keywords = ['marp:', 'theme:', 'paginate:', '---\nmarp']
                return any(keyword in content for keyword in marp_keywords)
        except Exception as e:
            logger.error(f"Error reading file {md_file}: {e}")
            return False
    
    def get_relative_path(self, file_path):
        """root_srcからの相対パスを取得"""
        return file_path.relative_to(self.root_src)
    
    def get_dest_path(self, src_path, new_extension=None):
        """変換先のパスを取得"""
        rel_path = self.get_relative_path(src_path)
        if new_extension:
            rel_path = rel_path.with_suffix(new_extension)
        return self.root_dest / rel_path
    
    def ensure_dest_dir(self, dest_path):
        """変換先ディレクトリを作成"""
        dest_path.parent.mkdir(parents=True, exist_ok=True)
    
    def convert_with_marp(self, md_file, pdf_file):
        """marp-cliでPDFに変換"""
        try:
            cmd = ['marp', '--pdf', str(md_file), '-o', str(pdf_file)]
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode == 0:
                logger.info(f"Successfully converted {md_file} to {pdf_file} using marp")
                return True
            else:
                logger.error(f"Marp conversion failed: {result.stderr}")
                return False
        except Exception as e:
            logger.error(f"Error during marp conversion: {e}")
            return False
    
    def convert_with_pandoc(self, md_file, pdf_file):
        """pandocでPDFに変換"""
        try:
            cmd = ['pandoc', str(md_file), '-o', str(pdf_file)]
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode == 0:
                logger.info(f"Successfully converted {md_file} to {pdf_file} using pandoc")
                return True
            else:
                logger.error(f"Pandoc conversion failed: {result.stderr}")
                return False
        except Exception as e:
            logger.error(f"Error during pandoc conversion: {e}")
            return False
    
    def convert_markdown_to_pdf(self, md_file):
        """markdownファイルをPDFに変換"""
        pdf_file = self.get_dest_path(md_file, '.pdf')
        self.ensure_dest_dir(pdf_file)
        
        # marp用かどうか判定
        if self.marp_available and self.is_marp_file(md_file):
            success = self.convert_with_marp(md_file, pdf_file)
        else:
            success = self.convert_with_pandoc(md_file, pdf_file)
        
        return success
    
    def copy_file(self, src_file):
        """指定された拡張子のファイルをコピー"""
        dest_file = self.get_dest_path(src_file)
        self.ensure_dest_dir(dest_file)
        
        try:
            shutil.copy2(src_file, dest_file)
            logger.info(f"Copied {src_file} to {dest_file}")
            return True
        except Exception as e:
            logger.error(f"Error copying file {src_file}: {e}")
            return False
    
    def should_convert(self, md_file):
        """変換が必要かどうか判定（タイムスタンプ比較）"""
        pdf_file = self.get_dest_path(md_file, '.pdf')
        
        if not pdf_file.exists():
            return True
        
        try:
            md_mtime = md_file.stat().st_mtime
            pdf_mtime = pdf_file.stat().st_mtime
            
            # 10秒以上の差があれば変換
            return (md_mtime - pdf_mtime) > 10
        except Exception as e:
            logger.error(f"Error comparing timestamps: {e}")
            return True
    
    def process_file(self, file_path):
        """ファイルを処理"""
        file_path = Path(file_path)
        
        if file_path.suffix == '.md':
            if self.should_convert(file_path):
                self.convert_markdown_to_pdf(file_path)
        elif file_path.suffix in self.copy_extensions:
            self.copy_file(file_path)
    
    def initial_scan(self):
        """初期スキャン"""
        logger.info(f"Starting initial scan of {self.root_src}")
        
        for file_path in self.root_src.rglob('*'):
            if file_path.is_file():
                self.process_file(file_path)
        
        logger.info("Initial scan completed")
    
    def replicate_folder_structure(self):
        """フォルダ構造を複製"""
        for dir_path in self.root_src.rglob('*'):
            if dir_path.is_dir():
                dest_dir = self.get_dest_path(dir_path)
                dest_dir.mkdir(parents=True, exist_ok=True)

class MarkdownFileHandler(FileSystemEventHandler):
    def __init__(self, converter):
        self.converter = converter
    
    def on_modified(self, event):
        if not event.is_directory:
            self.converter.process_file(event.src_path)
    
    def on_created(self, event):
        if not event.is_directory:
            self.converter.process_file(event.src_path)

def main():
    parser = argparse.ArgumentParser(description='Markdown to PDF converter with folder monitoring')
    parser.add_argument('root_src', help='Source folder to monitor')
    parser.add_argument('root_dest', help='Destination folder for PDFs')
    parser.add_argument('--copy-extensions', nargs='+', 
                       default=['.png', '.jpg', '.jpeg', '.gif', '.svg'],
                       help='File extensions to copy (default: .png .jpg .jpeg .gif .svg)')
    
    args = parser.parse_args()
    
    # パスの存在確認
    if not Path(args.root_src).exists():
        logger.error(f"Source folder does not exist: {args.root_src}")
        sys.exit(1)
    
    # コンバーターを初期化
    converter = MarkdownConverter(args.root_src, args.root_dest, args.copy_extensions)
    
    # フォルダ構造を複製
    converter.replicate_folder_structure()
    
    # 初期スキャン
    converter.initial_scan()
    
    # ファイル監視を開始
    event_handler = MarkdownFileHandler(converter)
    observer = Observer()
    observer.schedule(event_handler, args.root_src, recursive=True)
    
    logger.info(f"Starting file monitoring for {args.root_src}")
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