# md2pdf.py2 Plan

## 要実装

1. 指定フォルダを監視し、変更が変更があった.mdファイルを「Goal」の節の通りhtml,pdfファイルを書き出す機能、を実装して下さい。


## 次の要実装

- 「/Users/hirots-m/Library/CloudStorage/GoogleDrive-lab.crux.ore@gmail.com/マイドライブ/projects0/md2pdf.py/src/md2pdf.py」との統合


## Goal

`pandoc + lualatex` ベースではなく、`HTML -> Chrome/Chromium -> PDF` ベースで Markdown を PDF 化する。

狙いは次の 3 点です。

- スライド途中での不自然な分割を減らす
- 長いコードブロックが途中で切れにくいようにする
- `mermaid` をブラウザ側で描画してから PDF 化する

## Why this approach

VSCode の Markdown Preview Enhanced は、最終的にはブラウザ描画にかなり依存した見た目になります。
そのため、Python 側でも以下の流れに寄せるのが自然です。

1. Markdown を HTML に変換
2. HTML 内で `mermaid` を描画
3. Chrome の印刷エンジンで PDF 化

これなら LaTeX 系の改ページ制約や Unicode 周りの崩れを避けやすいです。

## Files

- `chrome_md_to_pdf.py`
  Python エントリポイント。Markdown から HTML を作り、Chrome headless で PDF 出力する。
- `render_markdown.js`
  HTML 生成担当。Markdown を HTML に変換し、`mermaid` 初期化を埋め込む。

## Design notes

- Python 依存は極力増やさない
- Node は既存環境のものを使う
- `remarkable.js` と `mermaid.min.js` は、ローカルの Markdown Preview Enhanced 拡張から再利用する
- 出力 HTML は一時ファイルとして生成し、必要なら `--keep-html` で残せるようにする
- `pre`, `code`, `table`, `img`, `svg` などに印刷向け CSS を入れて、ページ途中の切れを減らす

## Expected limitations

- MPE 完全互換ではない
- MPE 独自拡張のすべてを再現するわけではない
- `mermaid` の描画完了待ちは headless Chrome の待ち時間に依存する

## Next steps if needed

- フォルダ監視機能を追加する
- MPE の workspace CSS / custom CSS を読み込めるようにする
- `page.pdf()` を使う Puppeteer 版に発展させて、描画完了待ちをより厳密にする
