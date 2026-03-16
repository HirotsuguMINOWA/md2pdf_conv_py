T="/Users/hirots-m/Library/CloudStorage/GoogleDrive-researcher.and.educator@gmail.com/マイドライブ/EduMaterial/javascript入門" && watchexec \
  --watch ${T}\
  --exts md \
  --shell bash \
  -- marp --pdf ${T}
  

path="/Users/hirots-m/Library/CloudStorage/GoogleDrive-researcher.and.educator@gmail.com/マイドライブ/EduMaterial/javascript入門"
watchexec \
  --watch ="/Users/hirots-m/Library/CloudStorage/GoogleDrive-researcher.and.educator@gmail.com/マイドライブ/EduMaterial/javascript入門" \
  --exts md \
  --shell bash \
  -- 'pandoc "{}" -t beamer -o "${WATCHEXEC_COMMON_PATH%.md}.pdf"'


watchexec -w "/Users/hirots-m/Library/CloudStorage/GoogleDrive-researcher.and.educator@gmail.com/マイドライブ/EduMaterial/javascript入門" \
-e md \
  --shell bash \
-- pandoc "{}" -t beamer -o "{}.pdf"





path="/Users/hirots-m/Library/CloudStorage/GoogleDrive-researcher.and.educator@gmail.com/マイドライブ/EduMaterial/javascript入門" &&
  watchexec -e md -- pandoc "${path}" -t beamer -o "${path}.pdf"




path="/Users/hirots-m/Library/CloudStorage/GoogleDrive-researcher.and.educator@gmail.com/マイドライブ/EduMaterial/javascript入門"

watchexec --watch "{path}" --shell bash -e md \
  -- sh -c 'pandoc "$1" -t beamer -o "${1%.md}.pdf"' _ "{path}"


WATCHEXEC_WRITTEN_PATH="/Users/hirots-m/Library/CloudStorage/GoogleDrive-researcher.and.educator@gmail.com/マイドライブ/EduMaterial/javascript入門"
watchexec -e md --shell bash -- "pandoc \$WATCHEXEC_WRITTEN_PATH -t beamer -o \${WATCHEXEC_WRITTEN_PATH%.md}.pdf"



chokidar \
  "/Users/hirots-m/Library/CloudStorage/GoogleDrive-researcher.and.educator@gmail.com/マイドライブ/EduMaterial/javascript入門/**/*.md" \
  --use-polling \
  --interval 2000 \
  -c 'pandoc "{path}" -t beamer --pdf-engine=lualatex \
    -V mainfont="Hiragino Kaku Gothic ProN" \
    -V sansfont="Hiragino Kaku Gothic ProN" \
    -V monofont="Hiragino Kaku Gothic ProN" \
    -V mathfont="Hiragino Kaku Gothic ProN" \
    -H <(echo "\\usepackage{luatexja}\n\\usepackage{emoji}\n\\setemojifont{Apple Color Emoji}") \
    -o "$(dirname \"{path}\")/$(basename \"{path}\" .md).pdf"'



chokidar \
  "/Users/hirots-m/Library/CloudStorage/GoogleDrive-researcher.and.educator@gmail.com/マイドライブ/EduMaterial/javascript入門/**/*.md" \
  --use-polling \
  --interval 2000 \
    -- marp --pdf {path}