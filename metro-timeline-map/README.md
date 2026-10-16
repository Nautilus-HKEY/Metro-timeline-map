# Metro timeline map skill

Asks for a topic title, a year range and two toggle views, then draws a Liniennetzplan-style timeline as one PNG per view plus an interactive page with a working toggle bar.

Install: copy this folder to `~/.claude/skills/metro-timeline-map/` (Claude Code) or zip it and add it under Settings, Capabilities, Skills (Claude app).

Run without Claude:

    pip install pillow
    python scripts/render_map.py --data examples/smfret-example.json --from 1990 --until 2026 --title "Live-Cell smFRET" --out demo --html

Optional credit line in every map: add `--credit "Your credit text"`.
