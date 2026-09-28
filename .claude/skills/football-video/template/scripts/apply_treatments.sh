#!/bin/bash
# Run after build_index.py: HyperFrames media treatments on scene photos.
set -e
cd "$(dirname "$0")/.."
INK='{"intensity":1,"adjust":{"contrast":0.08},"effects":{"monoScreen":1,"monoScreenSize":0.28,"monoScreenAngle":0.25,"monoScreenSpread":0.3},"palette":["#0f1a11","#e1fe67"]}'
GREY='{"intensity":1,"adjust":{"saturation":-1,"exposure":-0.15,"contrast":-0.05}}'
t() { npx hyperframes media-treatment --file "$1" --selector "$2" --grading "$3" --apply --json >/dev/null && echo "ok $1 $2"; }
for s in "#mane-img" "#felix-img" "#t1-img" "#t2-img"; do t compositions/hook.html "$s" "$INK"; done
t compositions/grind.html "#gt-img" "$GREY"
t compositions/theline.html "#gt-img" "$GREY"
