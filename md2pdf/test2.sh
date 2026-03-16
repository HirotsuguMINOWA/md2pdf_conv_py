#!/bin/bash
#!/usr/bin/env bash
#!/opt/homebrew/bin/bash

WATCHEXEC_WRITTEN_PATH="/Users/hirots-m/Library/CloudStorage/GoogleDrive-researcher.and.educator@gmail.com/マイドライブ/EduMaterial/javascript入門" && watchexec --shell bash -e md -- "pandoc \$WATCHEXEC_WRITTEN_PATH -t beamer -o \${WATCHEXEC_WRITTEN_PATH%.md}.pdf"



watchexec \
  -w "/Users/hirots-m/Library/CloudStorage/GoogleDrive-researcher.and.educator@gmail.com/マイドライブ/EduMaterial/javascript入門" \
  -e md \
  --shell bash \
  --poll 500ms \
  -- 'marp --pdf "$WATCHEXEC_COMMON_PATH"'
#   -- 'pandoc "$1" -t beamer -o "${1%.md}.pdf"' _ "{}"\

## fswatch

- GDriveだめ。--pollパラはないの？

#!/bin/bash

DIR="./slides"

fswatch -r -e ".*" -i "\\.md$" "$DIR" | while read file
do
  echo "update: $file"
  marp --pdf "$file"
done


fswatch -r -e ".*" -i "\\.md$" ./slides | while read file
do
  marp --pdf "$file"
done




cat > /tmp/japanese.tex << 'EOF'
\usepackage{luatexja}
\usepackage{luatexja-fontspec}
\usepackage{emoji}
\setemojifont{Apple Color Emoji}
EOF

chokidar \
  "/Users/hirots-m/Library/CloudStorage/GoogleDrive-researcher.and.educator@gmail.com/マイドライブ/EduMaterial/javascript入門/**/*.md" \
  --use-polling \
  --interval 2000 \
  -c 'pandoc "{path}" -t beamer --pdf-engine=lualatex \
    -V mainfont="Hiragino Kaku Gothic ProN" \
    -V sansfont="Hiragino Kaku Gothic ProN" \
    -V monofont="Hiragino Kaku Gothic ProN" \
    -H japanese.tex \
    -o "$(dirname \"{path}\")/$(basename \"{path}\" .md).pdf"'