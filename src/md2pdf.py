#!/usr/bin/env python3
"""
 目的: markdownファイルをPDFまたはHTMLへ変換するソフト
 注意事項: ソースフォルダにCloudStorage(例:GDrive)があるため、ファイルの変更は『pollingで要取得』
 概略:
1. 指定されたフォルダを監視して、markdownファイル(.md)ファイルが更新されたら、pdfへ変換する
2. 変換されたPDFは、root_src PATHと同様のroot_destパスへコピーする
3. .mdファイルは中身を確認し、marp用であったらmarp-cliで変換し、
   slidev用であったらslidevで変換し、それ以外であればpandocで指定形式へ変換する。

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

from abc import ABC
import json
import os
import re
import sys
import platform
import time
import shutil
import subprocess
import argparse
import tempfile
from pathlib import Path
from loguru import logger


class CommonInterface(ABC):
    def get_path(self) -> str | Path:
        raise NotImplementedError

    def convert(
        self,
        src_md: Path,
        outdir: Path,
        header_tex_p: Path | None
    ) -> None:
        raise NotImplementedError


DEFAULT_LOG_LEVEL = "DEBUG"
DEFAULT_OUTPUT_FORMAT = "pdf"
DEFAULT_INPUT_EXTENSIONS: list[str] = [".md"]
OUTPUT_EXTENSIONS: dict[str, str] = {
    "pdf": ".pdf",
    "html": ".html",
}
SUPPORTED_INPUT_EXTENSIONS: set[str] = {".md", ".html"}

PANDOC_TEXT_REPLACEMENTS: dict[int, str] = {
    ord("\uFE0F"): "",        # Variation Selector-16: emoji presentation
    ord("✅"): "[OK]",
    ord("❌"): "[NG]",
    ord("⭕"): "[OK]",
    ord("⚠"): "[WARN]",
    ord("☕"): "[BREAK]",
    ord("🎉"): "[CELEBRATE]",
    ord("📝"): "[NOTE]",
    ord("💡"): "[IDEA]",
    ord("🚀"): "[START]",
    ord("📌"): "[PIN]",
    ord("🔧"): "[FIX]",
    ord("🎯"): "[GOAL]",
    ord("📁"): "[FILE]",
    ord("🌟"): "[STAR]",
    ord("▶"): "[PLAY]",
    ord("🔴"): "[RED]",
    ord("🟢"): "[GREEN]",
}


MERMAID_BLOCK_RE = re.compile(r'```mermaid\n(.*?)```', re.DOTALL)
PLANTUML_BLOCK_RE = re.compile(r'```plantuml\n(.*?)```', re.DOTALL)


def has_diagram_blocks(text: str) -> bool:
    return bool(MERMAID_BLOCK_RE.search(text) or PLANTUML_BLOCK_RE.search(text))


def sanitize_markdown_for_pandoc(markdown_text: str) -> tuple[str, bool]:
    """Replace Unicode sequences that are known to crash LuaLaTeX emoji shaping."""
    sanitized = markdown_text.translate(PANDOC_TEXT_REPLACEMENTS)
    return sanitized, sanitized != markdown_text


def configure_logger(log_level: str) -> None:
    logger.remove()
    _ = logger.add(
        sys.stderr,
        level=log_level.upper(),
        format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level:<8} | {message}",
    )


# -------------------------------------------------------
# パス設定
# -------------------------------------------------------
SCRIPT_DIR = Path(__file__).resolve().parent


def _resolve_repo_root() -> Path:
    """Nuitka/PyInstaller ビルド済みバイナリ実行時は __file__ が一時展開ディレクトリを
    指すため、sys.executable の親ディレクトリを REPO_ROOT として使う。"""
    # Nuitka one-file: runtime extraction dir ≠ 実際のバイナリ置き場
    try:
        import __compiled__  # type: ignore[import]  # noqa: F401
        return Path(sys.executable).resolve().parent
    except ImportError:
        pass
    # PyInstaller
    if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
        return Path(sys.executable).resolve().parent
    # 通常の Python 実行
    return SCRIPT_DIR.parent


REPO_ROOT = _resolve_repo_root()

# pandoc 設定（md2pdf/md2pdf.py に準拠）
PANDOC: str = "/opt/homebrew/bin/pandoc"
DEFAULT_HEADER_TEX: str = str(REPO_ROOT / "md2pdf.sh" / "japanese.tex")
BASE_PANDOC_PDF_ARGS: list[str] = [
    "-t", "pdf",
    "--pdf-engine=lualatex",
    "-V", "mainfont=Hiragino Kaku Gothic ProN",
    "-V", "sansfont=Hiragino Kaku Gothic ProN",
    "-V", "monofont=Hiragino Kaku Gothic ProN",
    "--verbose"
]
DEFAULT_CHROME_CANDIDATES: list[Path] = [
    Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
    Path("/Applications/Chromium.app/Contents/MacOS/Chromium"),
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
    input_extensions: list[str]
    copy_extensions: list[str]
    header_files: list[str]
    marp_header_files: list[str]
    marp_available: bool
    slidev_available: bool
    output_formats: list[str]
    output_format: str  # 変換中の現在フォーマット（convert_markdown内でセット）

    def __init__(self, root_src: str, root_dest: str,
                 input_extensions: list[str] | None = None,
                 copy_extensions: list[str] | None = None,
                 header_files: list[str] | None = None,
                 marp_header_files: list[str] | None = None,
                 output_formats: list[str] | None = None,
                 engine: str = 'auto') -> None:
        self.root_src = Path(root_src)
        self.root_dest = Path(root_dest)
        self.input_extensions = normalize_input_extensions(input_extensions)
        self.copy_extensions = copy_extensions or ['.png', '.jpg', '.jpeg', '.gif', '.svg']
        self.header_files = header_files or [DEFAULT_HEADER_TEX]
        self.marp_header_files = marp_header_files or []
        self.output_formats = normalize_output_formats(output_formats or [DEFAULT_OUTPUT_FORMAT])
        self.output_format = self.output_formats[0]  # 内部処理用の現在値
        self.engine = engine
        logger.debug(
            "Initializing MarkdownConverter: root_src={}, root_dest={}, input_extensions={}, copy_extensions={}, header_files={}, marp_header_files={}, output_formats={}, engine={}",
            self.root_src,
            self.root_dest,
            self.input_extensions,
            self.copy_extensions,
            self.header_files,
            self.marp_header_files,
            self.output_formats,
            self.engine,
        )
        self.marp_available = self._check_marp()
        self.slidev_available = self._check_slidev()
        self.playwright_available = self._check_playwright()
        self.plantuml_cli_available = self._check_plantuml_cli()

        # 出力フォルダを作成
        self.root_dest.mkdir(parents=True, exist_ok=True)
        logger.debug("Ensured destination directory exists: {}", self.root_dest)

    # -------------------------------------------------------
    # ツール存在確認
    # -------------------------------------------------------
    def _check_marp(self) -> bool:
        """バンドルされた marp-cli バイナリの確認"""
        logger.debug("Checking marp-cli binary: {}", MARP_BIN)
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
            logger.debug("Checking slidev with `which slidev`")
            result = subprocess.run(['which', 'slidev'], capture_output=True, text=True)
            if result.returncode == 0:
                logger.info(f"slidev found at: {result.stdout.strip()}")
                return True
            # npx 経由で使えるか確認
            logger.debug("Checking slidev with `npx @slidev/cli --version`")
            result2 = subprocess.run(['npx', '@slidev/cli', '--version'],
                                     capture_output=True, text=True, timeout=10)
            if result2.returncode == 0:
                logger.info("slidev available via npx @slidev/cli")
                return True
        except Exception as exc:
            logger.debug("Slidev availability check raised an exception: {}", exc)
        logger.warning("slidev not found. Slidev conversion unavailable.")
        return False

    def _check_playwright(self) -> bool:
        # playwright パッケージ確認・自動インストール
        try:
            import playwright  # noqa: F401
        except ImportError:
            logger.info("playwright not installed. Installing via pip...")
            result = subprocess.run(
                [sys.executable, '-m', 'pip', 'install', 'playwright'],
                capture_output=True, text=True
            )
            if result.returncode != 0:
                logger.error(
                    f"Failed to install playwright:\n{result.stderr}\n"
                    "  Fix: pip install playwright"
                )
                return False
            logger.info("playwright installed successfully.")

        # Chromium ブラウザバイナリ確認・自動インストール
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                browser = p.chromium.launch(timeout=10000)
                browser.close()
            logger.info("Playwright chromium browser is available.")
            return True
        except Exception:
            logger.info("Playwright chromium not found. Installing via `playwright install chromium`...")
            result = subprocess.run(
                [sys.executable, '-m', 'playwright', 'install', 'chromium'],
                capture_output=True, text=True
            )
            if result.returncode != 0:
                logger.error(
                    f"Failed to install Playwright chromium:\n{result.stderr}\n"
                    "  Fix: playwright install chromium"
                )
                return False
            logger.info("Playwright chromium installed successfully.")
            return True

    def _check_plantuml_cli(self) -> bool:
        found = shutil.which('plantuml')
        if found:
            logger.info(f"plantuml CLI found: {found}")
            return True
        logger.warning("plantuml CLI not found. PlantUML blocks will not be converted to diagrams.")
        return False

    def _replace_plantuml_with_svg(self, md_text: str) -> str:
        """plantuml コードブロックを inline SVG に置換する"""
        def replace(m: re.Match) -> str:
            code = m.group(1)
            puml_path = ''
            svg_path = ''
            try:
                with tempfile.NamedTemporaryFile(
                    suffix='.puml', mode='w', encoding='utf-8', delete=False
                ) as f:
                    f.write('@startuml\n' + code + '\n@enduml')
                    puml_path = f.name
                svg_path = puml_path.replace('.puml', '.svg')
                subprocess.run(
                    ['plantuml', '-tsvg', puml_path],
                    capture_output=True, check=True
                )
                svg_content = Path(svg_path).read_text(encoding='utf-8')
                svg_clean = re.sub(r'<\?xml[^>]+\?>', '', svg_content).strip()
                return f'\n\n<div class="plantuml-diagram">{svg_clean}</div>\n\n'
            except Exception as e:
                logger.warning(f"PlantUML conversion failed: {e}")
                return m.group(0)
            finally:
                for p in [puml_path, svg_path]:
                    try:
                        if p:
                            Path(p).unlink(missing_ok=True)
                    except Exception:
                        pass
        return PLANTUML_BLOCK_RE.sub(replace, md_text)

    def _build_html_for_playwright(self, md_text: str) -> str:
        """marked.js + mermaid.js を埋め込んだ HTML 文字列を生成する"""
        if self.plantuml_cli_available:
            md_text = self._replace_plantuml_with_svg(md_text)
        md_json = json.dumps(md_text)
        return f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<style>
  body {{ font-family: "Hiragino Kaku Gothic ProN", sans-serif;
          max-width: 900px; margin: 0 auto; padding: 2em; }}
  pre code {{ background: #f4f4f4; display: block; padding: 1em; }}
  .mermaid {{ text-align: center; }}
</style>
</head>
<body>
<div id="content"></div>
<script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/mermaid/dist/mermaid.min.js"></script>
<script>
  // mermaid コードブロックを <div class="mermaid"> に変換するカスタムレンダラー
  // marked.js は ```mermaid を <code class="language-mermaid"> に変換するが、
  // mermaid.js v10+ は <div class="mermaid"> を期待するため変換が必要
  marked.use({{
    renderer: {{
      code({{ text, lang }}) {{
        if (lang === 'mermaid') {{
          return '<div class="mermaid">' + text + '</div>';
        }}
        return false;
      }}
    }}
  }});

  const md = {md_json};
  document.getElementById('content').innerHTML = marked.parse(md);

  mermaid.initialize({{ startOnLoad: false }});
  mermaid.run({{ querySelector: '.mermaid' }}).then(() => {{
    document.body.setAttribute('data-ready', 'true');
  }}).catch((e) => {{
    console.error('mermaid rendering error:', e);
    document.body.setAttribute('data-ready', 'true');
  }});
</script>
</body>
</html>"""

    def convert_with_playwright(self, md_file: Path, output_file: Path) -> bool:
        """Playwright で MD（mermaid/plantuml 含む）→ PDF 変換"""
        try:
            from playwright.sync_api import sync_playwright
            md_text = md_file.read_text(encoding='utf-8')
            html = self._build_html_for_playwright(md_text)

            with tempfile.NamedTemporaryFile(
                suffix='.html', mode='w', encoding='utf-8', delete=False
            ) as f:
                f.write(html)
                html_path = Path(f.name)

            try:
                with sync_playwright() as p:
                    browser = p.chromium.launch()
                    page = browser.new_page()
                    page.goto(html_path.resolve().as_uri())
                    page.wait_for_selector('[data-ready="true"]', timeout=30000)
                    page.pdf(
                        path=str(output_file),
                        print_background=True,
                        format='A4',
                    )
                    browser.close()
            finally:
                html_path.unlink(missing_ok=True)

            logger.info(f"[playwright] {md_file} -> {output_file}")
            return True
        except Exception as e:
            logger.error(f"Playwright conversion failed: {e}")
            return False

    def _find_chrome_binary(self) -> str | None:
        for candidate in DEFAULT_CHROME_CANDIDATES:
            if candidate.exists():
                logger.debug("Using Chrome/Chromium binary: {}", candidate)
                return str(candidate)

        for name in ["google-chrome", "chromium", "chromium-browser"]:
            found = shutil.which(name)
            if found:
                logger.debug("Using Chrome/Chromium from PATH: {}", found)
                return found

        logger.warning("Chrome/Chromium not found. HTML to PDF conversion is unavailable.")
        return None

    # -------------------------------------------------------
    # ファイル種別判定
    # -------------------------------------------------------
    def _read_frontmatter(self, md_file: Path) -> str:
        """ファイル先頭のフロントマター部分（最大 50 行）を返す"""
        try:
            logger.debug("Reading frontmatter: {}", md_file)
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
        is_marp = any(kw in head for kw in marp_keywords)
        logger.debug("Detected marp markdown={} for file={}", is_marp, md_file)
        return is_marp

    def is_slidev_file(self, md_file: Path) -> bool:
        """slidev 用 Markdown か判定"""
        head = self._read_frontmatter(md_file)
        slidev_keywords = ['slidev:', 'theme:', 'layout:']
        # slidev ファイルは通常 --- で始まるフロントマターを持ち、
        # かつ slidev 特有のキーワードが含まれる
        has_frontmatter = head.startswith('---')
        has_keyword = any(kw in head for kw in slidev_keywords)
        is_slidev = has_frontmatter and has_keyword and not self.is_marp_file(md_file)
        logger.debug("Detected slidev markdown={} for file={}", is_slidev, md_file)
        return is_slidev

    # -------------------------------------------------------
    # 変換処理
    # -------------------------------------------------------
    def _normalize_marp_header_fragment(self, text: str) -> str:
        """Marp に挿入する frontmatter 断片を正規化する。"""
        stripped = text.lstrip('\ufeff').strip()
        if not stripped:
            return ''

        lines = stripped.splitlines()
        if len(lines) >= 2 and lines[0].strip() == '---':
            for idx in range(1, len(lines)):
                if lines[idx].strip() in {'---', '...'}:
                    stripped = '\n'.join(lines[1:idx]).strip()
                    break
        return stripped

    def _load_marp_header_text(self) -> str:
        fragments: list[str] = []
        for header_file in self.marp_header_files:
            header_path = Path(header_file)
            try:
                fragment = self._normalize_marp_header_fragment(
                    header_path.read_text(encoding='utf-8')
                )
            except Exception as exc:
                logger.error("Error reading marp header file {}: {}", header_path, exc)
                continue
            if fragment:
                fragments.append(fragment)
        combined = '\n'.join(fragments).strip()
        logger.debug("Loaded marp header fragments from {} file(s)", len(fragments))
        return combined

    def _inject_marp_header(self, markdown_text: str, header_text: str) -> str:
        if not header_text.strip():
            return markdown_text

        lines = markdown_text.splitlines(keepends=True)
        if lines and lines[0].strip() == '---':
            return ''.join([lines[0], f"{header_text.rstrip()}\n", *lines[1:]])

        stripped_body = markdown_text.lstrip('\ufeff')
        return f"---\n{header_text.rstrip()}\n---\n\n{stripped_body}"

    def _prepare_marp_source(self, md_file: Path) -> tuple[Path, Path | None]:
        """Marp 用に必要なら先頭ヘッダーを注入した一時 Markdown を作る。"""
        header_text = self._load_marp_header_text()
        if not header_text:
            return md_file, None

        markdown_text = md_file.read_text(encoding='utf-8')
        merged_text = self._inject_marp_header(markdown_text, header_text)
        if merged_text == markdown_text:
            return md_file, None

        with tempfile.NamedTemporaryFile(
            mode='w',
            encoding='utf-8',
            suffix='.md',
            prefix=f"{md_file.stem}.marp.",
            dir=str(md_file.parent),
            delete=False,
        ) as tmp_file:
            tmp_file.write(merged_text)
            tmp_path = Path(tmp_file.name)

        logger.debug("Prepared temporary marp source: {}", tmp_path)
        return tmp_path, tmp_path

    def convert_with_marp(self, md_file: Path, output_file: Path) -> bool:
        """バンドルされた marp-cli で指定形式に変換"""
        temp_md_file: Path | None = None
        try:
            marp_input, temp_md_file = self._prepare_marp_source(md_file)
            cmd = [str(MARP_BIN)]
            if self.output_format == 'pdf':
                cmd.append('--pdf')
            cmd.extend([
                '--allow-local-files',
                str(marp_input.name if marp_input.parent == md_file.parent else marp_input),
                '-o',
                str(output_file),
            ])
            logger.debug("Running marp command: {} (cwd={})", cmd, md_file.parent)
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                cwd=str(md_file.parent),
            )
            if result.returncode == 0:
                logger.info(f"[marp] {md_file} -> {output_file}")
                return True
            else:
                logger.error(f"Marp conversion failed: {result.stderr}")
                return False
        except Exception as e:
            logger.error(f"Error during marp conversion: {e}")
            return False
        finally:
            if temp_md_file and temp_md_file.exists():
                try:
                    temp_md_file.unlink()
                    logger.debug("Removed temporary marp source: {}", temp_md_file)
                except Exception as exc:
                    logger.warning("Could not remove temporary marp source {}: {}", temp_md_file, exc)

    def convert_with_slidev(self, md_file: Path, output_file: Path) -> bool:
        """slidev でPDFに変換。HTML指定時は pandoc にフォールバックする。"""
        if self.output_format != 'pdf':
            logger.warning(
                "slidev markdown HTML export is not directly supported; falling back to pandoc: {}",
                md_file,
            )
            return self.convert_with_pandoc(md_file, output_file)

        try:
            # slidev export はカレントディレクトリを基準に動作するため cd する
            if shutil.which('slidev'):
                cmd = ['slidev', 'export', str(md_file), '--format', 'pdf', '--output', str(output_file)]
            else:
                cmd = ['npx', '@slidev/cli', 'export', str(md_file),
                       '--format', 'pdf', '--output', str(output_file)]
            logger.debug("Running slidev command: {} (cwd={})", cmd, md_file.parent)
            result = subprocess.run(cmd, capture_output=True, text=True,
                                    cwd=str(md_file.parent))
            if result.returncode == 0:
                logger.info(f"[slidev] {md_file} -> {output_file}")
                return True
            else:
                logger.error(f"Slidev conversion failed: {result.stderr}")
                return False
        except Exception as e:
            logger.error(f"Error during slidev conversion: {e}")
            return False

    def convert_with_pandoc(self, md_file: Path, output_file: Path) -> bool:
        """pandoc で指定形式に変換する。PDFは emoji を含んでも落ちにくくする。"""
        try:
            markdown_text = md_file.read_text(encoding='utf-8')
            markdown_input = markdown_text
            cmd = [PANDOC, '-']

            if self.output_format == 'pdf':
                sanitized_text, was_sanitized = sanitize_markdown_for_pandoc(markdown_text)
                markdown_input = sanitized_text
                cmd.extend(BASE_PANDOC_PDF_ARGS)
                cmd.extend([
                    '--no-highlight',
                    '--resource-path', str(md_file.parent),
                ])
                for header_file in self.header_files:
                    cmd.extend(['-H', header_file])
                if was_sanitized:
                    logger.warning(
                        'Replaced problematic Unicode emoji sequences before pandoc conversion: {}',
                        md_file,
                    )
            else:
                cmd.extend([
                    '-t', 'html5',
                    '--standalone',
                    '--resource-path', str(md_file.parent),
                ])

            cmd.extend(['-o', str(output_file)])

            logger.debug("Running pandoc command: {}", cmd)
            result = subprocess.run(
                cmd,
                input=markdown_input,
                capture_output=True,
                text=True,
                encoding='utf-8',
                cwd=str(md_file.parent),
            )
            if result.stdout:
                print(result.stdout, end='')
            if result.stderr:
                print(result.stderr, end='', file=sys.stderr)
            if result.returncode == 0:
                logger.info(f"[pandoc] {md_file} -> {output_file}")
                return True
            else:
                logger.error(f"Pandoc conversion failed (exit {result.returncode})")
                return False
        except Exception as e:
            logger.error(f"Error during pandoc conversion: {e}")
            return False

    def convert_html_with_pandoc(self, html_file: Path, output_file: Path) -> bool:
        """HTML は Chrome/Chromium の headless print で PDF に変換する。"""
        if self.output_format != 'pdf':
            logger.error("HTML input only supports PDF output: {}", html_file)
            return False

        try:
            chrome_path = self._find_chrome_binary()
            if not chrome_path:
                logger.error("HTML to PDF requires Chrome or Chromium: {}", html_file)
                return False

            html_uri = html_file.resolve().as_uri()
            with tempfile.TemporaryDirectory(prefix='md2pdf-html-') as user_data_dir:
                cmd = [
                    chrome_path,
                    "--headless",
                    "--disable-gpu",
                    "--no-first-run",
                    "--no-default-browser-check",
                    f"--user-data-dir={user_data_dir}",
                    "--allow-file-access-from-files",
                    "--enable-local-file-accesses",
                    "--print-to-pdf-no-header",
                    f"--print-to-pdf={output_file}",
                    html_uri,
                ]

                logger.debug("Running Chrome/Chromium for HTML input: {}", cmd)
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    encoding='utf-8',
                    cwd=str(html_file.parent),
                    timeout=50  # !これが無いと新しい変換されない
                )
            if result.stdout:
                print(result.stdout, end='')
            if result.stderr:
                print(result.stderr, end='', file=sys.stderr)
            if result.returncode == 0:
                logger.info(f"[html-pdf] {html_file} -> {output_file}")
                return True

            logger.error(f"HTML to PDF conversion failed (exit {result.returncode})")
            return False
        except Exception as e:
            logger.error(f"Error during HTML conversion: {e}")
            return False

    def convert_file_to_path(self, src_file: Path, output_file: Path) -> bool:
        """入力種別に応じて変換ツールを自動選択して指定パスへ変換する。"""
        self.ensure_dest_dir(output_file)
        logger.debug("Converting file {} -> {}", src_file, output_file)

        if src_file.suffix == '.html':
            return self.convert_html_with_pandoc(src_file, output_file)

        if self.engine == 'marp':
            return self.convert_with_marp(src_file, output_file)
        if self.engine == 'slidev':
            return self.convert_with_slidev(src_file, output_file)
        if self.engine == 'playwright':
            # playwright は PDF のみ対応。html フォーマット時は pandoc にフォールバック
            if self.output_format == 'pdf':
                return self.convert_with_playwright(src_file, output_file)
            return self.convert_with_pandoc(src_file, output_file)
        if self.engine == 'pandoc':
            return self.convert_with_pandoc(src_file, output_file)
        # engine == 'auto': 自動判定
        if self.marp_available and self.is_marp_file(src_file):
            return self.convert_with_marp(src_file, output_file)
        if self.slidev_available and self.is_slidev_file(src_file):
            return self.convert_with_slidev(src_file, output_file)
        if self.playwright_available and self.output_format == 'pdf':
            md_text = src_file.read_text(encoding='utf-8')
            if has_diagram_blocks(md_text):
                return self.convert_with_playwright(src_file, output_file)
        return self.convert_with_pandoc(src_file, output_file)

    def get_output_extension(self) -> str:
        extension = OUTPUT_EXTENSIONS[self.output_format]
        logger.debug("Resolved output extension for format {}: {}", self.output_format, extension)
        return extension

    def convert_markdown(self, md_file: Path) -> bool:
        """変換ツールを自動選択して指定形式に変換（marp > slidev > pandoc）。複数フォーマット対応。"""
        all_ok = True
        for fmt in self.output_formats:
            self.output_format = fmt
            output_file = self.get_dest_path(md_file, self.get_output_extension())
            ok = self.convert_file_to_path(md_file, output_file)
            if not ok:
                all_ok = False
        return all_ok

    def convert_markdown_to_pdf(self, md_file: Path) -> bool:
        """後方互換用。現在の output_formats に従って変換する。"""
        return self.convert_markdown(md_file)

    # -------------------------------------------------------
    # パス・ディレクトリ操作
    # -------------------------------------------------------
    def get_relative_path(self, file_path: Path) -> Path:
        relative_path = file_path.relative_to(self.root_src)
        logger.debug("Resolved relative path {} -> {}", file_path, relative_path)
        return relative_path

    def get_dest_path(self, src_path: Path, new_extension: str | None = None) -> Path:
        rel_path = self.get_relative_path(src_path)
        if new_extension is not None:
            rel_path = rel_path.with_suffix(new_extension)
        dest_path = self.root_dest / rel_path
        logger.debug("Resolved destination path {} -> {}", src_path, dest_path)
        return dest_path

    def ensure_dest_dir(self, dest_path: Path) -> None:
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        logger.debug("Ensured parent directory exists: {}", dest_path.parent)

    def replicate_folder_structure(self) -> None:
        """フォルダ構造を複製"""
        logger.debug("Replicating folder structure from {} to {}", self.root_src, self.root_dest)
        for dir_path in self.root_src.rglob('*'):
            if dir_path.is_dir():
                dest_dir = self.get_dest_path(dir_path)
                dest_dir.mkdir(parents=True, exist_ok=True)
                logger.debug("Ensured mirrored directory exists: {}", dest_dir)

    # -------------------------------------------------------
    # ファイルコピー・タイムスタンプ
    # -------------------------------------------------------
    def copy_file(self, src_file: Path) -> bool:
        """指定された拡張子のファイルをコピー"""
        dest_file = self.get_dest_path(src_file)
        self.ensure_dest_dir(dest_file)
        try:
            logger.debug("Copying asset file {} -> {}", src_file, dest_file)
            _ = shutil.copy2(src_file, dest_file)
            logger.info(f"Copied {src_file} to {dest_file}")
            return True
        except Exception as e:
            logger.error(f"Error copying file {src_file}: {e}")
            return False

    def should_convert(self, src_file: Path) -> bool:
        """変換が必要かどうか判定（タイムスタンプ比較）"""
        output_file = self.get_dest_path(src_file, self.get_output_extension())
        if not output_file.exists():
            logger.debug("Destination output does not exist yet, converting: {}", output_file)
            return True
        try:
            md_mtime = src_file.stat().st_mtime
            output_mtime = output_file.stat().st_mtime
            should_rebuild = (md_mtime - output_mtime) > 10
            logger.debug(
                "Timestamp comparison for {}: src_mtime={}, output_mtime={}, should_convert={}",
                src_file,
                md_mtime,
                output_mtime,
                should_rebuild,
            )
            return should_rebuild
        except Exception as e:
            logger.error(f"Error comparing timestamps: {e}")
            return True

    def process_file(self, file_path: str | Path) -> None:
        """ファイルを処理"""
        p = Path(file_path)
        logger.debug("Processing filesystem path: {}", p)
        if p.suffix in self.input_extensions:
            if self.should_convert(p):
                _ = self.convert_file_to_path(p, self.get_dest_path(p, self.get_output_extension()))
            else:
                logger.debug("Skipping source file because output is up-to-date: {}", p)
        elif p.suffix in self.copy_extensions:
            _ = self.copy_file(p)
        else:
            logger.debug("Skipping unsupported file type: {}", p)

    def initial_scan(self) -> None:
        """初期スキャン"""
        logger.info(f"Starting initial scan of {self.root_src}")
        for file_path in self.root_src.rglob('*'):
            if file_path.is_file():
                logger.debug("Initial scan visiting file: {}", file_path)
                self.process_file(file_path)
        logger.info("Initial scan completed")


def resolve_pandoc_header_files(header_files: list[str]) -> list[str]:
    resolved = header_files or [DEFAULT_HEADER_TEX]
    logger.debug("Resolved pandoc header files: {}", resolved)
    return resolved


def resolve_marp_header_files(header_files: list[str] | None) -> list[str]:
    resolved = header_files or []
    logger.debug("Resolved marp header files: {}", resolved)
    return resolved


def normalize_output_format(output_format: str) -> str:
    normalized = output_format.lower()
    if normalized not in OUTPUT_EXTENSIONS:
        supported = ', '.join(sorted(OUTPUT_EXTENSIONS))
        raise ValueError(f"Unsupported output format: {output_format}. Supported formats: {supported}")
    return normalized


def normalize_output_formats(output_formats: list[str]) -> list[str]:
    seen: list[str] = []
    for fmt in output_formats:
        normalized = normalize_output_format(fmt)
        if normalized not in seen:
            seen.append(normalized)
    if not seen:
        raise ValueError("At least one output format must be specified")
    return seen


def normalize_input_extensions(input_extensions: list[str] | None) -> list[str]:
    normalized = input_extensions or DEFAULT_INPUT_EXTENSIONS
    resolved: list[str] = []
    for extension in normalized:
        ext = extension.strip().lower()
        if not ext:
            continue
        if not ext.startswith('.'):
            ext = f'.{ext}'
        if ext not in SUPPORTED_INPUT_EXTENSIONS:
            supported = ', '.join(sorted(SUPPORTED_INPUT_EXTENSIONS))
            raise ValueError(f"Unsupported input format: {extension}. Supported formats: {supported}")
        if ext not in resolved:
            resolved.append(ext)
    if not resolved:
        raise ValueError("At least one input format must be specified")
    return resolved


def resolve_single_output_path(input_path: Path, output_arg: str | None, output_format: str) -> Path:
    extension = OUTPUT_EXTENSIONS[normalize_output_format(output_format)]
    if not output_arg:
        output_path = input_path.with_suffix(extension)
        logger.debug("Using default single-file output path: {}", output_path)
        return output_path

    output_path = Path(output_arg)
    if output_path.exists() and output_path.is_dir():
        resolved = output_path / f"{input_path.stem}{extension}"
        logger.debug("Resolved directory output path for single file: {}", resolved)
        return resolved
    logger.debug("Resolved explicit single-file output path: {}", output_path)
    return output_path


def run_single_file_mode(input_path: Path, output_arg: str | None,
                         input_extensions: list[str], copy_extensions: list[str], header_files: list[str],
                         marp_header_files: list[str], output_formats: list[str], engine: str = 'auto') -> int:
    logger.debug(
        "Running single file mode: input_path={}, output_arg={}, input_extensions={}, copy_extensions={}, header_files={}, marp_header_files={}, output_formats={}, engine={}",
        input_path,
        output_arg,
        input_extensions,
        copy_extensions,
        header_files,
        marp_header_files,
        output_formats,
        engine,
    )
    # single file mode: 最初のフォーマットで出力先パスを決定、複数フォーマットは converter 内でループ
    output_path = resolve_single_output_path(input_path, output_arg, output_formats[0])
    converter = MarkdownConverter(
        str(input_path.parent),
        str(output_path.parent),
        input_extensions=input_extensions,
        copy_extensions=copy_extensions,
        header_files=header_files,
        marp_header_files=marp_header_files,
        output_formats=output_formats,
        engine=engine,
    )
    succeeded = converter.convert_markdown(input_path)
    return 0 if succeeded else 1


def run_watch_mode(root_src: Path, root_dest: Path,
                   input_extensions: list[str], copy_extensions: list[str], header_files: list[str],
                   marp_header_files: list[str], output_formats: list[str], engine: str = 'auto') -> int:
    logger.debug(
        "Running watch mode: root_src={}, root_dest={}, input_extensions={}, copy_extensions={}, header_files={}, marp_header_files={}, output_formats={}, engine={}",
        root_src,
        root_dest,
        input_extensions,
        copy_extensions,
        header_files,
        marp_header_files,
        output_formats,
        engine,
    )
    if not root_src.exists():
        logger.error(f"Source folder does not exist: {root_src}")
        return 1
    if not root_src.is_dir():
        logger.error(f"Source path is not a directory: {root_src}")
        return 1

    converter = MarkdownConverter(
        str(root_src),
        str(root_dest),
        input_extensions=input_extensions,
        copy_extensions=copy_extensions,
        header_files=header_files,
        marp_header_files=marp_header_files,
        output_formats=output_formats,
        engine=engine,
    )

    converter.replicate_folder_structure()
    converter.initial_scan()

    all_extensions = set(converter.input_extensions) | set(converter.copy_extensions)

    def _collect_mtimes() -> dict[Path, float]:
        result: dict[Path, float] = {}
        for p in root_src.rglob("*"):
            if p.is_file() and p.suffix in all_extensions:
                try:
                    result[p] = p.stat().st_mtime
                except OSError:
                    pass
        return result

    logger.info(f"\n Starting file monitoring (polling) for {root_src}")
    logger.info("Press Ctrl+C to stop.")
    prev = _collect_mtimes()

    try:
        while True:
            logger.debug("waiting....")
            time.sleep(2)
            curr = _collect_mtimes()
            for path, mtime in curr.items():
                if path not in prev or prev[path] != mtime:
                    logger.info("Detected change: {}", path)
                    # should_convert の10秒閾値チェックを飛ばして即変換
                    if path.suffix in converter.input_extensions:
                        out = converter.get_dest_path(path, converter.get_output_extension())
                        converter.convert_file_to_path(path, out)
                    elif path.suffix in converter.copy_extensions:
                        converter.copy_file(path)
            prev = curr
    except KeyboardInterrupt:
        logger.info("Stopping file monitoring...")

    logger.info("Program terminated")
    return 0


# -------------------------------------------------------
# エントリポイント
# -------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser(
        description='Markdown/HTML converter with folder monitoring (pandoc / marp / slidev)')
    _ = parser.add_argument('target', nargs='?',
                            help='Source file to convert, or folder to monitor')
    _ = parser.add_argument('legacy_output', nargs='?',
                            help='Destination folder for legacy root_src root_dest usage')
    _ = parser.add_argument('--watch', nargs='?', const='.',
                            help='Watch a folder and convert changed source files')
    _ = parser.add_argument('--output',
                            help='Output file path for a single file, or destination folder for watch mode')
    _ = parser.add_argument('--format-input', '--format_input', nargs='+',
                            default=DEFAULT_INPUT_EXTENSIONS,
                            help='Input file extensions to convert (default: .md). Supports: .md .html')
    _ = parser.add_argument('--header', '-H', action='append', default=[],
                            help='Header TeX file to pass to pandoc (repeatable)')
    _ = parser.add_argument('--marp-header', action='append', default=[],
                            help='Markdown/YAML fragment file to inject into Marp frontmatter (repeatable)')
    _ = parser.add_argument('--format-output', '--format_output', nargs='+',
                            choices=sorted(OUTPUT_EXTENSIONS),
                            default=[DEFAULT_OUTPUT_FORMAT],
                            help=f'Output format(s) (default: {DEFAULT_OUTPUT_FORMAT}). '
                                 f'複数指定可: --format-output pdf html')
    _ = parser.add_argument('--log-level', default=DEFAULT_LOG_LEVEL,
                            help=f'Loguru log level (default: {DEFAULT_LOG_LEVEL})')
    _ = parser.add_argument('--copy-extensions', nargs='+',
                            default=['.png', '.jpg', '.jpeg', '.gif', '.svg'],
                            help='File extensions to copy (default: .png .jpg .jpeg .gif .svg)')
    _ = parser.add_argument('--engine',
                            choices=['auto', 'pandoc', 'playwright', 'marp', 'slidev'],
                            default='auto',
                            help='Conversion engine to use (default: auto). '
                                 'auto=自動判定, pandoc=強制pandoc, playwright=強制Playwright, '
                                 'marp=強制marp, slidev=強制slidev')

    args = parser.parse_args()
    configure_logger(args.log_level)
    logger.debug("CLI arguments: {}", args)

    copy_extensions: list[str] = args.copy_extensions
    input_extensions = normalize_input_extensions(args.format_input)
    header_files = resolve_pandoc_header_files(args.header)
    marp_header_files = resolve_marp_header_files(args.marp_header)
    output_formats = normalize_output_formats(args.format_output)
    engine: str = args.engine

    if args.watch is not None:
        watch_target = args.watch
        if watch_target == '.' and args.target:
            watch_target = args.target
        root_src = Path(watch_target).resolve()
        root_dest = Path(args.output).resolve() if args.output else root_src
        sys.exit(run_watch_mode(
            root_src,
            root_dest,
            input_extensions,
            copy_extensions,
            header_files,
            marp_header_files,
            output_formats,
            engine,
        ))

    if args.target and args.legacy_output and not args.output:
        root_src = Path(args.target).resolve()
        root_dest = Path(args.legacy_output).resolve()
        sys.exit(run_watch_mode(
            root_src,
            root_dest,
            input_extensions,
            copy_extensions,
            header_files,
            marp_header_files,
            output_formats,
            engine,
        ))

    if not args.target:
        root_src = Path.cwd()
        root_dest = Path(args.output).resolve() if args.output else root_src
        sys.exit(run_watch_mode(
            root_src,
            root_dest,
            input_extensions,
            copy_extensions,
            header_files,
            marp_header_files,
            output_formats,
            engine,
        ))

    target_path = Path(args.target).resolve()
    if not target_path.exists():
        logger.error(f"Target does not exist: {target_path}")
        sys.exit(1)

    if target_path.is_file():
        root_src = target_path.parent
        root_dest = Path(args.output).resolve() if args.output else root_src
        if root_dest.suffix:
            root_dest = root_dest.parent
        logger.info(
            "File target was provided; switching to watch mode for parent folder: {}",
            root_src,
        )
        sys.exit(run_watch_mode(
            root_src,
            root_dest,
            input_extensions,
            copy_extensions,
            header_files,
            marp_header_files,
            output_formats,
            engine,
        ))

    root_dest = Path(args.output).resolve() if args.output else target_path
    sys.exit(run_watch_mode(
        target_path,
        root_dest,
        input_extensions,
        copy_extensions,
        header_files,
        marp_header_files,
        output_formats,
        engine,
    ))


if __name__ == "__main__":
    main()
