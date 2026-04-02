python -m nuitka \
  --onefile \
  --standalone \
  --enable-plugin=playwright \
  --remove-output \
  --output-dir=built_nuitka \
  --output-filename=md2pdf \
  src/md2pdf.py
