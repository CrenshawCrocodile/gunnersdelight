# Weekly routine

Runs weekly, Wednesdays. Exits without publishing unless a new gameweek has finalised.

Artifact: https://claude.ai/code/artifact/1dbdb62f-c2bc-45b2-8cc7-138c72d39d6f

## Prompt

You maintain the Fantasy Premier League tracker for "Rosner's Relegation Battle"
(league 184717), published as a Claude Artifact at:
https://claude.ai/code/artifact/1dbdb62f-c2bc-45b2-8cc7-138c72d39d6f

This repo contains everything needed. Work from its root. Do not modify
build_tracker.py, fetch_fpl.py or template.html.

Step 1. Read the current artifact with the Artifact tool, action "read", passing
that URL. You must do this before publishing; a publish without a prior read in
this session is refused. Extract the object literal assigned to DEFAULT_DATA in
its <script> and save it as out/previous.json (valid JSON, no trailing
semicolon). Note its "throughGW" value as PUBLISHED_GW.

Step 2. Run: python3 build_tracker.py --previous out/previous.json
It fetches the FPL API sequentially and takes a couple of minutes. If it exits
non-zero, STOP and report the exact error. Do not publish and do not work around
it. The script's checks exist to stop bad data reaching the league.

Step 3. Read out/data.json and note its "throughGW" as NEW_GW.
If NEW_GW is less than or equal to PUBLISHED_GW, no new gameweek has finalised.
STOP without publishing and report "no new gameweek, still through GW<N>".
This can happen in some weeks (for example an international break or a gameweek
not yet finalised) and is a success, not a failure.

Step 4. A new gameweek finalised. Read out/facts.json and write the recap for
NEW_GW: 6 to 8 short bullet points, the TL;DR a league member wants.

Rules for the bullets, which matter because the league reads this:
- Refer to entrants by TEAM NAME, never the manager's name. Use the exact team
  name as it appears in the data, including any emoji or curly apostrophe, so
  the page can auto-link it.
- No em dashes anywhere.
- Every number must come from facts.json. Never estimate or invent.
- Cover: who leads and any change at the top, the week's highest and lowest
  scores, the biggest riser and faller, the most captained player and what it
  returned, the highest scoring player owned in the league, and any chips played.
- Mention a chip only if chipsThisWeek is non-empty.
- Write plainly and specifically. No hype, no filler.

Save as recap.json in the form {"gw": NEW_GW, "bullets": ["...", "..."]} then
re-run: python3 build_tracker.py --previous out/previous.json --recap recap.json

Step 5. Publish out/tracker.html with the Artifact tool, passing the artifact
URL above as `url` so it updates in place and the league's link keeps working.
Set `label` to "Gameweek <NEW_GW>". Do not pass `favicon` and do not create a
new artifact. If the publish is rejected as a conflict, re-read the artifact,
re-run step 2 with the fresh previous.json, and publish once more.

Step 6. Report in three lines: the gameweek published, the leader and their
total, and the artifact URL.

Never invent standings, points or player data. Every number comes from the FPL
API via the script. If anything is unclear or fails, report it and stop.
