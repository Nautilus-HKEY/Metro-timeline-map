---
name: metro-timeline-map
description: Builds a German-style metro line map (Liniennetzplan) timeline for any topic, with a toggle bar inside the figure that switches between two ways of grouping the lines. Asks for the topic title, the year range and the two toggle views, then researches, draws two PNGs and an interactive page.
---

# Metro timeline map

Draws the history of a topic like a transit network: each line is a group, each station is a dated paper, event or milestone, time runs left to right. A toggle bar in the figure switches between two groupings of the same stations (for example Biological / Methodological, Application / Technique, Region / Era). A PNG cannot toggle, so the skill makes one PNG per view with the bar drawn, plus an interactive HTML page where the bar works.

Bundled:
- `scripts/render_map.py`: renderer. Python 3 and Pillow only (`pip install pillow`).
- `examples/smfret-example.json`: a complete data file (live-cell smFRET) showing the schema.

## Step 1: ask the questions

Ask all in one go with AskUserQuestion; if that tool is missing, ask in plain text and wait.

1. **Title.** What topic is the map for? (free text, e.g. "Live-Cell smFRET", "CRISPR", "Cryo-EM")
2. **Year range.** From which year and until which year? Offer the current year as the default end. Reject an end year before the start year.
3. **Toggle.** What two views should the toggle switch between? Offer: "Where / How" (the topic split by setting or system versus by method or technique), "Application / Technique", "Region / Era", and Other (the person names the two views). Each view needs 3 to 5 lines, so ask what the lines in each view should be, or propose them from the topic and let the person confirm.
4. **Model for the research pass.** Sonnet (recommended), Opus, Haiku or Fable.

## Step 2: research with the chosen model

Start one subagent with the Agent tool, setting `model` to the choice. Brief it to: search the web (WebSearch, WebFetch) for the landmark papers and reviews on the topic dated FROM to UNTIL; verify each year and citation against a source (publisher page, PubMed, PMC, DOI); aim for 12 to 30 stations; and return only JSON in the schema below. It must never invent a reference. If it cannot find a source, it leaves the paper out. If authors or year come from memory, set `"checked": false` (the map prints a †).

Data file schema (see `examples/smfret-example.json`):

```json
{"meta":{"title":"TOPIC","verified_through":"YYYY-MM-DD","note":"Selected milestones, not exhaustive."},
 "views":{
  "a":{"name":"View A name","subtitle":"short phrase","lines":[
     {"id":"L1","badge":"1","name":"Line name","desc":"one line","color":"#224F86"},
     {"id":"OTH","badge":"4","name":"Delivery and standards","desc":"...","color":"#8C6DAB","style":"dashed"},
     {"id":"R","badge":"R","name":"Reviews","desc":"Overviews of the field","color":"#6B7680"}]},
  "b":{"name":"View B name","subtitle":"...","lines":[ ... ]}},
 "stations":[{"id":"short-id","year":2014.4,"lines":{"a":["L1"],"b":["M2"]},
   "label":["Short name","First author et al."],"title":"Plain headline",
   "cite":"Authors, Journal volume, pages, year","text":"One or two sentences.",
   "url":"https://...","checked":true,"delivery":"optional third label line"}],
 "links":[{"from":"id1","to":"id2","checked":true,"note":"what the link is","url":"https://..."}]}
```

Rules for the data:
- View keys are always `a` and `b`. Every station lists its line ids in both views (one or two ids; two makes an interchange).
- A line with `"style":"dashed"` is drawn as a straight dashed lane at the top. Use it for stations that fit no main line in that view, so the main lines are not forced to carry them. Keep it to one such lane per view.
- `year` may carry a fraction for the month. `label` has two or three short lines, 16 characters each at most.
- Line colours: pick distinct hues with enough contrast on white and avoid red-green pairs only.
- `links` draw dashed arrows (source to target). Add one only when a paper states the connection, with a source. Start a link from the last station of a line so the dashed path leaves the line instead of running along it. Links are straight; where one crosses another line it hops over with a small arc.

Save the research as `data.json` in the working directory.

## Step 3: render

```bash
python scripts/render_map.py --data data.json --from FROM --until UNTIL \
  --title "TITLE" --out map-FROM-UNTIL --html
```

Writes `<out>-<view a name>.png`, `<out>-<view b name>.png` (names slugged), `<out>-references.md` and `<out>.html`. Options: `--view both|a|b`, `--html-fragment` (page body only, for publishing as an artifact), `--dark`, `--scale 3`, `--credit "TEXT"` (a credit line printed in the footer of each PNG and in the page note; leave it out for none).

Open both PNGs and check them before delivering: no overlapping labels, no line running through a label, pills at line ends, each station on the right lines. If a label collides, shorten its `label` text or move the station to another line, then re-render.

## Step 4: deliver

Send both PNGs and the references file. If an artifact tool is available, publish the `--html-fragment` output so the person gets the working toggle (keep the same file path to update the same page). In two sentences say what the map covers and how the toggle groups the lines. Always state how many stations carry a † (from memory, not re-checked) and any link whose source is not confirmed.

## Rules

- Never add a station without a source the research pass actually found.
- The map is a selection, not a census. Say so if asked about completeness.
- Keep the person's year range exactly; do not widen it.
- Do not claim a paper belongs to a line unless that line's description fits it.
