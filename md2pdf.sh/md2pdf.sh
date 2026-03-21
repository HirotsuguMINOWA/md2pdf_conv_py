#!/bin/bash
# MD -> PDF conversion script with watch mode
#
# Usage:
#   md2pdf.sh [--header file.tex] [--output file.pdf] <file.md>
#   md2pdf.sh [--header file.tex] [--output folder] --watch [folder]
#   md2pdf.sh [--header file.tex] [folder]

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DEFAULT_HEADER="$SCRIPT_DIR/japanese.tex"
HEADER_FILES=()
OUTPUT_PATH=""
WATCH_MODE=0
TARGET_PATH=""

usage() {
    echo "Usage:"
    echo "  md2pdf.sh [--header file.tex] [--output file.pdf] <file.md>"
    echo "  md2pdf.sh [--header file.tex] [--output folder] --watch [folder]"
    echo "  md2pdf.sh [--header file.tex] [folder]"
}

add_default_header_if_needed() {
    if [ ${#HEADER_FILES[@]} -eq 0 ]; then
        HEADER_FILES=("$DEFAULT_HEADER")
    fi
}

convert() {
    local input_path="$1"
    local output_path="${2:-${input_path%.md}.pdf}"
    local pandoc_args=(
        "$input_path"
        -t pdf
        --pdf-engine=lualatex
        -V mainfont="Hiragino Kaku Gothic ProN"
        -V sansfont="Hiragino Kaku Gothic ProN"
        -V monofont="Hiragino Kaku Gothic ProN"
    )
    local header

    add_default_header_if_needed

    for header in "${HEADER_FILES[@]}"; do
        pandoc_args+=( -H "$header" )
    done

    echo "Converting: $input_path"
    echo "Output: $output_path"
    /opt/homebrew/bin/pandoc "${pandoc_args[@]}" -o "$output_path"
}

shell_quote() {
    local value="${1//\'/\'\\\'\'}"
    printf "'%s'" "$value"
}

build_watch_command() {
    local command
    local header

    command="$(shell_quote "$0")"

    for header in "${HEADER_FILES[@]}"; do
        command+=" $(shell_quote --header) $(shell_quote "$header")"
    done

    if [ -n "$OUTPUT_PATH" ]; then
        command+=" $(shell_quote --output) $(shell_quote "$OUTPUT_PATH")"
    fi

    command+=" $(shell_quote '{path}')"

    printf '%s' "$command"
}

while [ $# -gt 0 ]; do
    case "$1" in
        --watch)
            WATCH_MODE=1
            shift
            ;;
        --output)
            if [ $# -lt 2 ]; then
                echo "Error: --output requires a path."
                usage
                exit 1
            fi
            OUTPUT_PATH="$2"
            shift 2
            ;;
        --header|-H)
            if [ $# -lt 2 ]; then
                echo "Error: --header requires a file path."
                usage
                exit 1
            fi
            HEADER_FILES+=("$2")
            shift 2
            ;;
        --help|-h)
            usage
            exit 0
            ;;
        --*)
            echo "Error: unknown option '$1'."
            usage
            exit 1
            ;;
        *)
            if [ -n "$TARGET_PATH" ]; then
                echo "Error: multiple input paths were provided."
                usage
                exit 1
            fi
            TARGET_PATH="$1"
            shift
            ;;
    esac
done

if [ "$WATCH_MODE" -eq 1 ]; then
    WATCH_DIR="${TARGET_PATH:-$SCRIPT_DIR}"

    if [ ! -d "$WATCH_DIR" ]; then
        echo "Error: '$WATCH_DIR' is not a directory."
        exit 1
    fi
else
    if [ -z "$TARGET_PATH" ]; then
        WATCH_DIR="$SCRIPT_DIR"
        WATCH_MODE=1
    elif [ -d "$TARGET_PATH" ]; then
        WATCH_DIR="$TARGET_PATH"
        WATCH_MODE=1
    elif [ -f "$TARGET_PATH" ]; then
        if [ -n "$OUTPUT_PATH" ] && [ -d "$OUTPUT_PATH" ]; then
            convert "$TARGET_PATH" "$OUTPUT_PATH/$(basename "${TARGET_PATH%.md}").pdf"
        else
            convert "$TARGET_PATH" "$OUTPUT_PATH"
        fi
        exit $?
    else
        echo "Error: '$TARGET_PATH' is not a file or directory."
        usage
        exit 1
    fi
fi

add_default_header_if_needed

if [ "$WATCH_MODE" -eq 1 ] && [ -n "$OUTPUT_PATH" ]; then
    mkdir -p "$OUTPUT_PATH"
fi

echo "Watching: $WATCH_DIR"
echo "Headers: ${HEADER_FILES[*]}"
if [ -n "$OUTPUT_PATH" ]; then
    echo "Watch output dir: $OUTPUT_PATH"
fi
echo "Press Ctrl+C to stop."

/opt/homebrew/bin/chokidar \
    "$WATCH_DIR/**/*.md" \
    --use-polling \
    --interval 2000 \
    --shell bash \
    -c "$(build_watch_command)"
