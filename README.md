# Markdown to PDF Converter

フォルダ監視し、監視下のMarkdownファイルに更新があれば、PDFに自動変換するソフトウェアです。変換は、デフォルトはpandoc。今後はmarp,slidevで変換できるようにしたい

## 機能

- **自動変換**: 指定フォルダ内の`.md`ファイルが更新されると自動的にPDFに変換
- **Marp対応**: Marp用のMarkdownファイルは`marp-cli`で変換、それ以外は`pandoc`で変換
- **フォルダ構造保持**: ソースフォルダの階層構造を保持して変換先フォルダに複製
- **ファイルコピー**: 画像ファイルなど指定された拡張子のファイルを自動コピー
- **タイムスタンプ比較**: 10秒以上の差がある場合のみ変換を実行

## 必要な環境

### Python依存関係

```bash
pip install -r requirements.txt
```

### 外部ツール
- **pandoc**: 通常のMarkdownファイルのPDF変換に使用
  ```bash
  # macOS
  brew install pandoc
  
  # Ubuntu/Debian
  sudo apt-get install pandoc
  ```

- **marp-cli** (オプション): Marp用MarkdownファイルのPDF変換に使用
  ```bash
  npm install -g @marp-team/marp-cli
  ```

## 使用方法

### 基本的な使用方法
```bash
python src/main.py <監視フォルダ> <出力フォルダ>
```

### 例
```bash
python src/main.py ./markdown_files ./pdf_output
```

### オプション
- `--copy-extensions`: コピーするファイルの拡張子を指定（デフォルト: .png .jpg .jpeg .gif .svg）

```bash
python src/main.py ./markdown_files ./pdf_output --copy-extensions .png .jpg .svg .css
```

## 動作の流れ

1. **初期化**: marp-cliの存在確認と出力フォルダの作成
2. **フォルダ構造複製**: ソースフォルダの階層構造を出力フォルダに複製
3. **初期スキャン**: 既存のMarkdownファイルをチェックし、必要に応じて変換
4. **監視開始**: ファイルの変更を監視し、リアルタイムで変換を実行

## Markdownファイルの判定

プログラムは以下のキーワードを含むファイルをMarp用として判定します：
- `marp:`
- `theme:`
- `paginate:`
- `---\nmarp`

## ログ

プログラムの実行状況はコンソールにログとして出力されます：
- 変換の成功/失敗
- ファイルのコピー状況
- エラーメッセージ

## 終了方法

`Ctrl+C`でプログラムを終了できます。

## トラブルシューティング

### marp-cliが見つからない場合
- marp-cliがインストールされていない場合、pandocのみで動作します
- `/usr/bin/marp-cli`または`which marp`で見つかるパスにmarp-cliがインストールされている必要があります

### pandocが見つからない場合
- pandocがインストールされていることを確認してください
- パスが通っていることを確認してください

### 変換が実行されない場合
- ファイルのタイムスタンプを確認してください（10秒以上の差が必要）
- ログメッセージでエラーの詳細を確認してください
