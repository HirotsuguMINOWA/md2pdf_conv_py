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
EXCEPTION_LOG_MODE: bool = False
DEFAULT_OUTPUT_FORMAT = "pdf"
DEFAULT_INPUT_EXTENSIONS: list[str] = [".md"]
OUTPUT_EXTENSIONS: dict[str, str] = {
    "pdf": ".pdf",
    "html": ".html",
    "docx": ".docx",
    "html_pdf": ".pdf",   # md→html（中間）→pdf
    "html_docx": ".docx", # md→html + docx
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
    global EXCEPTION_LOG_MODE
    requested = (log_level or DEFAULT_LOG_LEVEL).strip().upper()
    EXCEPTION_LOG_MODE = requested == "EXCEPTION"
    sink_level = "ERROR" if EXCEPTION_LOG_MODE else requested

    logger.remove()
    try:
        _ = logger.add(
            sys.stderr,
            level=sink_level,
            format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level:<8} | {message}",
        )
    except ValueError:
        # 不正なログレベルでも実行継続できるようフォールバックする
        _ = logger.add(
            sys.stderr,
            level=DEFAULT_LOG_LEVEL,
            format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level:<8} | {message}",
        )
        logger.warning(
            "Invalid log level '{}'. Falling back to {}.",
            log_level,
            DEFAULT_LOG_LEVEL,
        )
        EXCEPTION_LOG_MODE = False


def log_exception_or_error(message: str, exc: Exception) -> None:
    if EXCEPTION_LOG_MODE:
        logger.exception("{}: {}", message, exc)
    else:
        logger.error("{}: {}", message, exc)


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
        md_json = json.dumps(md_text).replace('</', '<\\/')
        return f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/highlight.js@11/styles/github.min.css">
<style>
  body {{ font-family: "Hiragino Kaku Gothic ProN", sans-serif;
          max-width: 900px; margin: 0 auto; padding: 2em; }}
  pre {{ background: #f6f8fa; border-radius: 6px; padding: 1em; overflow-x: auto; }}
  pre code.hljs {{ background: transparent; padding: 0; }}
  .mermaid {{ text-align: center; }}
  
  /* 表の罫線を表示するスタイル */
  table {{ border-collapse: collapse; border: 1px solid #000; }}
  th, td {{ border: 1px solid #000; padding: 0.5em; }}
  table caption {{ font-weight: bold; margin: 1em 0; }}
</style>
</head>
<body>
<div id="content"></div>
<script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/mermaid/dist/mermaid.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/highlight.js@11/lib/highlight.min.js"></script>
<script>
  // mermaid コードブロックを <div class="mermaid"> に変換するカスタムレンダラー
  marked.use({{
    gfm: true,
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

  // シンタックスハイライト（mermaid 以外のコードブロック）
  document.querySelectorAll('pre code').forEach(function(el) {{
    hljs.highlightElement(el);
  }});

  // スクリプト読み込みエラーや mermaid 描画エラー時でも必ず data-ready をセット
  function markReady() {{
    document.body.setAttribute('data-ready', 'true');
  }}

  // 最大 25 秒でフォールバック（wait_for_selector の 30 秒より短く設定）
  var _fallbackTimer = setTimeout(markReady, 25000);

  try {{
    mermaid.initialize({{ startOnLoad: false }});
    mermaid.run({{ querySelector: '.mermaid' }}).then(function() {{
      clearTimeout(_fallbackTimer);
      markReady();
    }}).catch(function(e) {{
      console.error('mermaid rendering error:', e);
      clearTimeout(_fallbackTimer);
      markReady();
    }});
  }} catch(e) {{
    console.error('mermaid init error:', e);
    clearTimeout(_fallbackTimer);
    markReady();
  }}
</script>
</body>
</html>"""

    def convert_to_html(self, md_file: Path, output_file: Path) -> bool:
        """MD → HTML（mermaid.js + highlight.js 対応のブラウザ向け HTML を直接書き出す）"""
        try:
            md_text = md_file.read_text(encoding='utf-8')
            html = self._build_html_for_playwright(md_text)
            output_file.write_text(html, encoding='utf-8')
            logger.info(f"[html-template] {md_file} -> {output_file}")
            return True
        except Exception as e:
            log_exception_or_error("HTML output failed", e)
            return False

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
                    # set_content() を使うことで file:// 制約なしに CDN スクリプトを読み込める
                    page = browser.new_page()
                    page.set_content(html, wait_until='domcontentloaded')
                    page.wait_for_selector('[data-ready="true"]', timeout=60000)
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
            log_exception_or_error("Playwright conversion failed", e)
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

    def get_output_extension(self) -> str:
        return OUTPUT_EXTENSIONS[self.output_format]

    def get_dest_path(self, src_file: Path, extension: str | None = None) -> Path:
        src_path = Path(src_file).resolve()
        try:
            relative_path = src_path.relative_to(self.root_src.resolve())
        except Exception:
            relative_path = Path(src_path.name)

        if extension is not None:
            relative_path = relative_path.with_suffix(extension)

        return self.root_dest / relative_path

    def ensure_dest_dir(self, output_file: Path) -> None:
        output_file.parent.mkdir(parents=True, exist_ok=True)

    def replicate_folder_structure(self) -> None:
        self.root_dest.mkdir(parents=True, exist_ok=True)
        for directory in self.root_src.rglob('*'):
            if directory.is_dir():
                try:
                    relative_dir = directory.resolve().relative_to(self.root_src.resolve())
                except Exception:
                    relative_dir = Path(directory.name)
                dest_dir = self.root_dest / relative_dir
                dest_dir.mkdir(parents=True, exist_ok=True)
        logger.debug("Replicated folder structure: {} -> {}", self.root_src, self.root_dest)

    def copy_file(self, src_file: Path) -> bool:
        try:
            dest_file = self.get_dest_path(src_file)
            self.ensure_dest_dir(dest_file)
            shutil.copy2(src_file, dest_file)
            logger.info("[copy] {} -> {}", src_file, dest_file)
            return True
        except Exception as e:
            log_exception_or_error("File copy failed", e)
            return False

    def convert_file_to_path(self, src_file: Path, output_file: Path) -> bool:
        self.ensure_dest_dir(output_file)
        suffix = src_file.suffix.lower()

        if suffix == '.html':
            if self.output_format == 'html':
                try:
                    shutil.copy2(src_file, output_file)
                    logger.info("[html-copy] {} -> {}", src_file, output_file)
                    return True
                except Exception as e:
                    log_exception_or_error("HTML copy failed", e)
                    return False
            return self.convert_html_with_pandoc(src_file, output_file)

        if suffix != '.md':
            logger.error("Unsupported source file: {}", src_file)
            return False

        if self.output_format == 'html':
            return self.convert_to_html(src_file, output_file)

        if self.engine == 'pandoc':
            return self.convert_with_pandoc(src_file, output_file)

        if self.engine == 'playwright':
            if self.output_format == 'pdf':
                return self.convert_with_playwright(src_file, output_file)
            return self.convert_with_pandoc(src_file, output_file)

        if self.engine == 'marp':
            if self.output_format in {'pdf', 'html'}:
                return self.convert_with_marp(src_file, output_file)
            logger.warning(
                "marp engine does not support {} directly; falling back to pandoc",
                self.output_format,
            )
            return self.convert_with_pandoc(src_file, output_file)

        if self.engine == 'slidev':
            if self.output_format == 'pdf':
                return self.convert_with_slidev(src_file, output_file)
            logger.warning(
                "slidev engine does not support {} directly; falling back to pandoc",
                self.output_format,
            )
            return self.convert_with_pandoc(src_file, output_file)

        # auto
        if self.is_marp_file(src_file) and self.marp_available and self.output_format in {'pdf', 'html'}:
            return self.convert_with_marp(src_file, output_file)

        if self.is_slidev_file(src_file) and self.slidev_available and self.output_format == 'pdf':
            return self.convert_with_slidev(src_file, output_file)

        if self.output_format == 'pdf' and self.playwright_available:
            try:
                md_text = src_file.read_text(encoding='utf-8')
                if has_diagram_blocks(md_text):
                    return self.convert_with_playwright(src_file, output_file)
            except Exception as e:
                log_exception_or_error("Error reading markdown before engine selection", e)

        return self.convert_with_pandoc(src_file, output_file)

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
            log_exception_or_error(f"Error reading file {md_file}", e)
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
        """Marp に挿入する frontmatter 斉断片を正規化する。"""
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
            log_exception_or_error("Error during marp conversion", e)
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
            log_exception_or_error("Error during slidev conversion", e)
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

            elif self.output_format == 'docx':
                cmd.extend([
                    '--resource-path', str(md_file.parent),
                ])

            else:
                # HTML出力時: PlantUML ブロックを inline SVG に変換してから pandoc へ渡す
                if self.plantuml_cli_available:
                    markdown_input = self._replace_plantuml_with_svg(markdown_input)
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
            log_exception_or_error("Error during pandoc conversion", e)
            return False

    def convert_html_with_pandoc(self, html_file: Path, output_file: Path) -> bool:
        """HTML 入力を PDF または DOCX に変換する。"""
        if self.output_format == 'docx':
            try:
                cmd = [
                    PANDOC,
                    str(html_file),
                    '--resource-path', str(html_file.parent),
                    '-o', str(output_file),
                ]
                logger.debug("Running pandoc for HTML -> DOCX: {}", cmd)
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    encoding='utf-8',
                    cwd=str(html_file.parent),
                )
                if result.stdout:
                    print(result.stdout, end='')
                if result.stderr:
                    print(result.stderr, end='', file=sys.stderr)
                if result.returncode == 0:
                    logger.info(f"[html-docx] {html_file} -> {output_file}")
                    return True

                logger.error(f"HTML to DOCX conversion failed (exit {result.returncode})")
                return False
            except Exception as e:
                log_exception_or_error("Error during HTML -> DOCX conversion", e)
                return False

        if self.output_format != 'pdf':
            logger.error("HTML input only supports PDF or DOCX output: {}", html_file)
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
                    timeout=50
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
            log_exception_or_error("Error during HTML conversion", e)
            return False

    def _get_output_paths_for_format(self, src_file: Path, fmt: str) -> list[Path]:
        if fmt == 'html_pdf':
            return [
                self.get_dest_path(src_file, '.html'),
                self.get_dest_path(src_file, '.pdf'),
            ]
        if fmt == 'html_docx':
            return [
                self.get_dest_path(src_file, '.html'),
                self.get_dest_path(src_file, '.docx'),
            ]
        return [self.get_dest_path(src_file, OUTPUT_EXTENSIONS[fmt])]

    def convert_markdown(self, md_file: Path) -> bool:
        """変換ツールを自動選択して指定形式に変換。"""
        all_ok = True
        for fmt in self.output_formats:
            if fmt == 'html_pdf':
                ok = self._convert_md_via_html_to_pdf(md_file)
            elif fmt == 'html_docx':
                ok = self._convert_md_to_html_and_docx(md_file)
            else:
                self.output_format = fmt
                output_file = self.get_dest_path(md_file, self.get_output_extension())
                ok = self.convert_file_to_path(md_file, output_file)
            if not ok:
                all_ok = False
        return all_ok

    def _convert_md_via_html_to_pdf(self, md_file: Path) -> bool:
        """md → html（中間ファイル）→ pdf の2段階変換。"""
        html_output = self.get_dest_path(md_file, '.html')
        pdf_output = self.get_dest_path(md_file, '.pdf')

        self.output_format = 'html'
        self.ensure_dest_dir(html_output)
        ok_html = self.convert_to_html(md_file, html_output)
        if not ok_html:
            logger.error(f"html_pdf mode: HTML generation failed: {md_file}")
            return False

        self.output_format = 'pdf'
        self.ensure_dest_dir(pdf_output)
        ok_pdf = self.convert_html_with_pandoc(html_output, pdf_output)
        if not ok_pdf:
            logger.error(f"html_pdf mode: PDF generation failed: {html_output}")
        return ok_pdf

    def _convert_md_to_html_and_docx(self, md_file: Path) -> bool:
        """md → html + docx の2出力。"""
        html_output = self.get_dest_path(md_file, '.html')
        docx_output = self.get_dest_path(md_file, '.docx')

        self.output_format = 'html'
        self.ensure_dest_dir(html_output)
        ok_html = self.convert_to_html(md_file, html_output)
        if not ok_html:
            logger.error(f"html_docx mode: HTML generation failed: {md_file}")
            return False

        self.output_format = 'docx'
        self.ensure_dest_dir(docx_output)
        ok_docx = self.convert_with_pandoc(md_file, docx_output)
        if not ok_docx:
            logger.error(f"html_docx mode: DOCX generation failed: {md_file}")
        return ok_docx

    def should_convert(self, src_file: Path) -> bool:
        """変換が必要かどうか判定。"""
        try:
            md_mtime = src_file.stat().st_mtime
        except Exception as e:
            log_exception_or_error("Error reading source file timestamp", e)
            return True

        for fmt in self.output_formats:
            for output_file in self._get_output_paths_for_format(src_file, fmt):
                if not output_file.exists():
                    logger.debug("Destination output does not exist yet, converting: {}", output_file)
                    return True
                try:
                    output_mtime = output_file.stat().st_mtime
                    should_rebuild = (md_mtime - output_mtime) > 10
                    logger.debug(
                        "Timestamp comparison for {} ({} -> {}): src_mtime={}, output_mtime={}, should_convert={}",
                        src_file, fmt, output_file, md_mtime, output_mtime, should_rebuild,
                    )
                    if should_rebuild:
                        return True
                except Exception as e:
                    log_exception_or_error(f"Error comparing timestamps for {output_file}", e)
                    return True
        return False

    def process_file(self, file_path: str | Path) -> None:
        """ファイルを処理"""
        p = Path(file_path)
        logger.debug("Processing filesystem path: {}", p)
        if p.suffix in self.input_extensions:
            if self.should_convert(p):
                _ = self.convert_markdown(p)
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
                        converter.convert_markdown(path)
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
    _ = parser.add_argument('--format-output', '--format_output',
                            action='append',
                            choices=sorted(OUTPUT_EXTENSIONS),
                            default=[],
                            help=f'Output format (repeatable). '
                            f'選択肢: pdf / html / docx '
                            f'例: --format-output=html --format-output=pdf で html と pdf の両方を出力')
    _ = parser.add_argument('--log-level', '--log', default=DEFAULT_LOG_LEVEL,
                            help=f'Loguru log level (default: {DEFAULT_LOG_LEVEL}). '
                            'Use EXCEPTION to print traceback with logger.exception')
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
    # format_output のデフォルト値を処理
    format_output_list = args.format_output if args.format_output else [DEFAULT_OUTPUT_FORMAT]
    output_formats = normalize_output_formats(format_output_list)
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
        logger.info("File target was provided; running single-file conversion: {}", target_path)
        sys.exit(run_single_file_mode(
            target_path,
            args.output,
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
    try:
        main()
    except Exception as exc:
        log_exception_or_error("Fatal error", exc)
        sys.exit(1)
