#!/usr/bin/env node

const fs = require("fs");
const path = require("path");

function usage() {
  console.error(
    "Usage: node render_markdown.js <input.md> <output.html> [mpe_root]"
  );
}

const [, , inputPath, outputPath, mpeRootArg] = process.argv;

if (!inputPath || !outputPath) {
  usage();
  process.exit(2);
}

const mpeRoot =
  mpeRootArg ||
  path.join(
    process.env.HOME || "",
    ".vscode",
    "extensions",
    "shd101wyy.markdown-preview-enhanced-0.8.21",
    "crossnote"
  );

const remarkablePath = path.join(
  mpeRoot,
  "dependencies",
  "remarkable",
  "remarkable.js"
);
const mermaidJsPath = path.join(
  mpeRoot,
  "dependencies",
  "mermaid",
  "mermaid.min.js"
);

if (!fs.existsSync(remarkablePath)) {
  console.error(`remarkable.js not found: ${remarkablePath}`);
  process.exit(3);
}
if (!fs.existsSync(mermaidJsPath)) {
  console.error(`mermaid.min.js not found: ${mermaidJsPath}`);
  process.exit(4);
}

const Remarkable = require(remarkablePath);

function escapeHtml(text) {
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function fileUrl(absPath) {
  return `file://${absPath}`;
}

const markdown = fs.readFileSync(inputPath, "utf8");
const md = new Remarkable({
  html: true,
  breaks: true,
  linkify: true,
  typographer: false,
  langPrefix: "language-",
  highlight: (str, lang) => {
    const className = lang ? ` class="language-${escapeHtml(lang)}"` : "";
    return `<pre class="md2pdf-pre"><code${className}>${escapeHtml(str)}</code></pre>`;
  },
});

let bodyHtml = md.render(markdown);

bodyHtml = bodyHtml.replace(
  /<pre class="md2pdf-pre"><code class="language-mermaid">([\s\S]*?)<\/code><\/pre>/g,
  (_, code) => `<pre class="mermaid">${code}</pre>`
);

const html = `<!doctype html>
<html lang="ja">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>${escapeHtml(path.basename(inputPath))}</title>
  <script src="${fileUrl(mermaidJsPath)}"></script>
  <style>
    :root {
      --page-width: 920px;
      --text: #1d2433;
      --muted: #51607a;
      --border: #d5dbe7;
      --code-bg: #f6f8fb;
      --paper: #ffffff;
      --accent: #1e5eff;
    }
    html, body {
      margin: 0;
      padding: 0;
      background: #f3f5f9;
      color: var(--text);
      font-family: "Hiragino Sans", "Yu Gothic", "Meiryo", sans-serif;
      line-height: 1.7;
    }
    body {
      padding: 24px;
      box-sizing: border-box;
    }
    main {
      width: min(100%, var(--page-width));
      margin: 0 auto;
      background: var(--paper);
      padding: 32px 40px 48px;
      box-sizing: border-box;
    }
    h1, h2, h3, h4, h5, h6 {
      line-height: 1.3;
      break-after: avoid-page;
      page-break-after: avoid;
    }
    p, li, blockquote {
      orphans: 3;
      widows: 3;
    }
    img, svg, table, blockquote, pre, .mermaid {
      max-width: 100%;
      break-inside: avoid-page;
      page-break-inside: avoid;
    }
    pre {
      background: var(--code-bg);
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 14px 16px;
      overflow: visible;
      white-space: pre-wrap;
      overflow-wrap: anywhere;
    }
    code {
      font-family: "SFMono-Regular", "Menlo", "Monaco", "Consolas", monospace;
      font-size: 0.92em;
      white-space: pre-wrap;
      overflow-wrap: anywhere;
    }
    :not(pre) > code {
      background: var(--code-bg);
      border: 1px solid var(--border);
      border-radius: 6px;
      padding: 0.1em 0.35em;
    }
    table {
      width: 100%;
      border-collapse: collapse;
      display: block;
      overflow-x: auto;
    }
    th, td {
      border: 1px solid var(--border);
      padding: 8px 10px;
      vertical-align: top;
    }
    th {
      background: #eef3ff;
    }
    blockquote {
      margin-left: 0;
      padding-left: 1em;
      border-left: 4px solid #b9c7e6;
      color: var(--muted);
    }
    hr {
      border: 0;
      border-top: 1px solid var(--border);
      margin: 2em 0;
    }
    .pagebreak, .newpage {
      page-break-before: always;
      break-before: page;
    }
    .mermaid {
      text-align: center;
      background: #fff;
    }
    @page {
      size: A4;
      margin: 14mm 12mm 14mm 12mm;
    }
    @media print {
      html, body {
        background: #fff;
      }
      body {
        padding: 0;
      }
      main {
        width: auto;
        margin: 0;
        padding: 0;
        box-shadow: none;
      }
      a, a:visited {
        color: inherit;
        text-decoration: none;
      }
    }
  </style>
</head>
<body>
  <main class="markdown-body">
${bodyHtml}
  </main>
  <script>
    window.__MD2PDF_READY__ = false;
    async function renderMermaid() {
      const blocks = Array.from(document.querySelectorAll("pre.mermaid"));
      if (!blocks.length) {
        window.__MD2PDF_READY__ = true;
        return;
      }
      mermaid.initialize({ startOnLoad: false, securityLevel: "loose" });
      for (const block of blocks) {
        const source = block.textContent || "";
        const id = "mermaid-" + Math.random().toString(36).slice(2);
        try {
          const result = await mermaid.render(id, source);
          const wrapper = document.createElement("div");
          wrapper.className = "mermaid";
          wrapper.innerHTML = result.svg;
          block.replaceWith(wrapper);
        } catch (error) {
          const fallback = document.createElement("pre");
          fallback.className = "md2pdf-pre";
          fallback.textContent = source;
          block.replaceWith(fallback);
          console.error("Mermaid render failed:", error);
        }
      }
      window.__MD2PDF_READY__ = true;
    }
    renderMermaid();
  </script>
</body>
</html>
`;

fs.writeFileSync(outputPath, html, "utf8");
