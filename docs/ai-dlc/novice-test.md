# Blind novice test

**Bottom line:** this file is the repeatable test behind the roadmap block "Player-friendly game for strangers". An AI plays a non-technical teenage gamer who learns the game only by asking questions; its leftover "still hard" list is the measure. Run it after each batch of that block and compare with the baseline below.

## How to run it

1. Spawn one fresh agent on Claude Sonnet (`claude-sonnet-5-5`) with no tools, using the persona brief below unchanged.
2. Answer only the questions it asks, briefly and truthfully about the product as it is on that day. Never volunteer anything it did not ask.
3. After every answer, add: "Now tell me what is still unclear about these answers, then ask me what comes next."
4. Stop when it writes "I THINK I GET IT" with its numbered journey and its list of what still confuses it or seems scary or annoying.
5. Ask the split question below, then count the items in its "setup or rules themselves" group. That count is measure (b).
6. Record the date, the model, the count and the list in `docs/FINDINGS.md`.

Measure (a), Terminal commands typed from a fresh Mac with the game installed to a filed company play, is counted in the project owner's install dry run, not here; a role-play cannot observe a real Mac.

## Persona brief (send unchanged)

> Role-play. You are a high school student who loves tycoon games. You are not technical: you have never used Terminal, Git or Python. You just installed OpenRCT2 (a free remake of RollerCoaster Tycoon 2) on your Mac. A friend told you about a project called "Theme Park Enterprise": you run one company that owns several theme parks, play them, and watch your company grow on a dashboard website on your own computer. You want to go from "I just installed the game" all the way to "I am looking at my company's data on the dashboard", and understand how to play this enterprise version of the game.
>
> Rules: Do not use any tools; you know only what I tell you. Ask me questions, at most 4 per turn, in the order a real beginner would hit them, starting right after installing the game. Ask in your own words, as a teenager would, including about words you don't know. When I answer, first say what is still unclear, then ask what comes next. When you can describe the whole journey from install to the dashboard, including how a multi-park company grows over time, say "I THINK I GET IT" and write a short numbered summary of the journey in your own words, plus a list of anything that still confuses you or seemed scary or annoying.

## Split question (send after "I THINK I GET IT")

> Look back at every problem you had, from installing to the dashboard. For each one, say whether it was mainly because the explanation was missing (it would be fine if someone had just told you clearly) or because the setup or rules themselves are confusing or hard (even a perfect explanation would not fix it). Give a rough split and list which problems go in each group, one line each.

## Journey questions for the site section's check

A reader of only the "How a play works" section should answer these: what must be bought or installed first; how a play starts; what Company and Sandbox mean; how to tell a play was filed; how to continue a park; how a second park joins and in which company year; what autopilot does and how to start it; where the results show.

## Baseline (2026-11-15, Claude Sonnet, observational)

Split: about 45% explanation, 55% setup or rules. "Setup or rules themselves", 8 items:
1. Terminal, five pasted commands and four extra tools before any play.
2. Commands that delete data exist; fear of wiping the company.
3. Two new parks in one play stop the filing.
4. The strict year order for new parks.
5. Autopilot's first run needs an exact phrase, and how to start it is unclear.
6. Moving the project folder means rebuilding the app.
7. A failure shows only as text in a window that may be closed, so a play goes unfiled.
8. No company goal or score.

A second run on Codex Sol the same day gave 40% and 60%, with 5 such items (tools and Terminal; direnv's shell line and no checker; a Terminal window at launch; the two-new-parks stop; remembering the company rule, calendar and autopilot confirmation). Measure (a) baseline: about 10 typed commands (Apple's developer tools, Homebrew, Node and direnv, uv, direnv's shell line, `git clone`, `cd`, `make setup`, `direnv allow`, `make launcher`).
