<!--
Maintainer notes (hidden on GitHub). This file holds the words of the player guide's help part. The site page
site/guide.njk renders each named passage of it in place, after the setup and play parts: a passage starts at
its HTML-comment marker and runs to the next marker. Edit the words here, never in site/guide.njk; a passage
added, removed or renamed here needs the matching change there.

- Text before the first marker is not rendered on the site. The first marker sits inside the page's heading
  line, so GitHub shows a heading while the site takes only its text.
- Passages whose names end in -github are for GitHub only; they hold the links to the other two guide files.
- Each group passage starts with its own heading. The section ids in site/guide.njk equal GitHub's anchors
  for those headings, so the in-page links work in both places.
- Every code span on the built page is pinned to the code or tool that prints it in tests/guide_strings.toml.
- make commands appear only in "For whoever helps you", apart from a command the app itself prints.
-->

# <!-- passage: fix-h -->Fix a problem

<!-- passage: fix-intro -->
Find the message you see on screen; each one says what it means and what to do. The groups follow the order things happen: [while you set up](#while-you-set-up), [when you start a play](#when-you-start-a-play), [after a play](#after-a-play) and [autopilot](#autopilot-problems). [Advanced](#advanced) covers backups, several new parks and moving the project folder.

**When to stop and ask for help.** If a message mentions seq, or you can't tell whether a play or an autopilot year was filed, don't try again. Keep the Terminal window open, or select all its text (Command-A), copy it (Command-C) and send it to whoever helps you. The commands they need are at the end, under [For whoever helps you](#for-whoever-helps-you).

<!-- passage: fix-pages-github -->
The setup steps are in [Set up your Mac](install-by-hand.md); playing is in [How to play](how-the-game-works.md).

<!-- passage: fix-setup -->
## While you set up

### Homebrew says your Mac account can't install apps

Terminal shows: `Need sudo access on macOS`

- **What it means:** your Mac account isn't allowed to install apps.
- **What to do:** log in to an administrator account, or ask whoever looks after the Mac. Then run Step 2 again.

### An error appears at the top of every new Terminal window

Terminal shows: `no such file or directory: /opt/homebrew/bin/brew`

- **What it means:** your Mac has an Intel chip and ran Step 3, which is for Apple chips.
- **What to do:** run `open -e ~/.zprofile`. TextEdit opens a file. Delete the line that mentions /opt/homebrew/bin/brew, save, and open a new Terminal window.

### Terminal can't find Homebrew

Terminal shows: `command not found: brew`

- **What it means:** Terminal can't find Homebrew yet.
- **What to do:** open a new Terminal window and try again. On an Apple chip, if it still fails, run Step 3 again.

### Step 7 can't find a tool

Terminal shows: `command not found`

- **What it means:** Terminal can't find the tool the line names.
- **What to do:** for node, run Step 5 again. For uv or direnv, run Step 4 again. Then open a new window and run Step 7 again.

### Step 7 shows a different Node version

Terminal shows: a first line that doesn't start with `v24`

- **What it means:** Terminal finds another copy of Node first.
- **What to do:** run Step 5 again, open a new window, and run Step 7 again.

### Terminal can't download the project

Terminal shows: `Repository not found` or `Authentication failed`, or it asks for a username

- **What it means:** your GitHub account can't reach the project from Terminal yet. Your normal GitHub password doesn't work there.
- **What to do:** do Step 8 (sign in to GitHub), then Step 9 again. If it still fails, ask the person who shared the project to give your account access.

### Terminal says the project folder already exists

Terminal shows: `already exists and is not an empty directory`

- **What it means:** a folder named openrct2-analytics is already in your home folder. It may be the project from an earlier download, or something else.
- **What to do:** check what it is: run `git -C ~/openrct2-analytics remote -v`. If the lines it prints hold the project's address, the one from Step 9, the folder is the project: go to Step 10. If it prints an error or a different address, don't set up there: in Finder, rename the folder (for example to openrct2-analytics-old), then run Step 9 again.

### Step 11 can't find a tool it needs

Terminal shows: `python3.12: command not found`, `make: npm: No such file or directory` or `command not found: make`

- **What it means:** a tool from an earlier step is missing: uv, Node or Apple's developer tools.
- **What to do:** run the earlier step again (Step 4 for uv, Steps 4 and 5 for Node, Step 1 for the developer tools). Then open a new window, run Step 10, and run Step 11 again.

### Setup says the project's Python is damaged

Terminal shows: `doctor: the Python environment is damaged.`

- **What it means:** the project's own copy of Python is broken. Your game, saves and parks are not affected.
- **What to do:** ask whoever helps you. The repair is under [For whoever helps you](#for-whoever-helps-you).

### Terminal says the project folder's settings are off

Terminal shows: the `.envrc` file `is blocked`

- **What it means:** the project folder's settings are off.
- **What to do:** check that the prompt shows `openrct2-analytics` (run Step 10 if not), then run Step 12.

<!-- passage: fix-start -->
## When you start a play

### The app can't find direnv

Terminal shows: `direnv is not on PATH`

- **What it means:** the app's Terminal window can't find direnv. It may be missing, or installed where Terminal doesn't look. Nothing was changed.
- **What to do:** on an Apple chip, run Step 3 again. Then run Step 4 again, open a new Terminal window, and open the app again.

### The app says the project folder isn't trusted yet

Terminal shows: `direnv does not trust this folder yet`

- **What it means:** the project folder's settings are off. Nothing was changed.
- **What to do:** go into the project folder: run Step 10, or, if you have moved the folder, type cd and a space, drag the folder from Finder into the Terminal window, and press Return. Then run Step 12, and open the app again.

### The app offers to file an earlier play

Terminal shows: `Play waiting to be filed:` and `File the waiting play now, before this play?`

- **What it means:** an earlier play was recorded but not filed, for example because its window was closed too early.
- **What to do:** type 1. The app files it first, then asks where this play should count. It may ask about a park by name; see [After a play](#after-a-play).

### The app says a recording failed its check

Terminal shows: `failed its seq audit`

- **What it means:** part of that recording is missing or appears twice, so it can't be filed. Until it is removed, no other play can be filed either.
- **What to do:** stop. Don't try to file it. Copy the Terminal text and send it to whoever helps you.

### The app says a recording is still being written

Terminal shows: `A recording is still being written`

- **What it means:** the game is still open, or a recording changed in the last 2 minutes, so the app can't offer to file it yet.
- **What to do:** quit OpenRCT2, wait 2 minutes, and open the app again.

### Terminal says the play is not being recorded

Terminal shows: `NOT recording`

- **What it means:** the game opened after the app had stopped waiting for it, so this play isn't being recorded.
- **What to do:** quit the game without saving, then open the app again.

### The game doesn't open

Terminal shows: `OpenRCT2 did not start; nothing was recorded.`

- **What it means:** the game didn't open, or didn't open within a minute.
- **What to do:** check that OpenRCT2 is in your Mac's main Applications folder and opens on its own. Then open the app again.

### A warning says a save changed while nothing was recording

Terminal shows: `was saved over while nothing was recording` or `changed after the last recorded save`

- **What it means:** a park's save changed while the app wasn't recording, usually after a play from the plain OpenRCT2 icon.
- **What to do:** load the file the warning names. If it tells you to copy a file into the game's save folder first, see [Advanced](#advanced).

### The recording never starts

Terminal never shows `events arriving` after your park opens.

- **What it means:** the app isn't receiving anything from the game.
- **What to do:** quit the game without saving, read what Terminal printed, and look it up on this page. If nothing here matches, ask for help.

<!-- passage: fix-after -->
## After a play

### No backup was made

Terminal shows: `Backup: no recorded save in this run, so no backup was made.`

- **What it means:** you didn't save during this play, so there is no new copy to continue from.
- **What to do:** next time, save before you quit. To continue the park, load its previous backup file.

### The backup copy failed

Terminal shows: `Backup FAILED` or `No backup made for`

- **What it means:** the copy of your save wasn't made. Your recorded play is safe, but it may not be filed yet.
- **What to do:** if the window also says `This play was not filed.`, follow that entry below. Next time, play the park from the app, save and quit, and check for a `Backup:` line. Autopilot can't run that park until it has one.

### The app asks about a Company park you played as Sandbox

Terminal shows: `is saved as Company, but this play was started as Sandbox.`

- **What it means:** you chose Sandbox but loaded a company park. (The same question appears the other way round for a Sandbox park.)
- **What to do:** type 1 to file the play the way the park was saved.

### The app asks about a park from an earlier play

Terminal shows: `from an earlier play is waiting. Where should it count?`

- **What it means:** a park from an earlier play was never filed.
- **What to do:** type a number: 1 for Company, 2 for Sandbox, or 3 for `Don't file now`. With 3, nothing is filed this time, and the app asks again next time.

### The app asks which of several new parks is which

Terminal shows: `is new in this play. Which is it?`

- **What it means:** you started more than one new park in one sitting.
- **What to do:** type the number next to `Opened first`, `Opened second` and so on, in the order you first played the parks, or the number next to Sandbox. See [Advanced](#advanced).

### The play was not filed

Terminal shows: `This play was not filed.`

- **What it means:** the recording step ended with a problem, so the play was not filed. Part or all of it may still be recorded.
- **What to do:** first read the capture report above it. If it says the game didn't start or nothing was recorded, there is nothing to file: fix what it names and open the app again. If a line there `names a seq problem`, stop and ask for help. Otherwise, press Return to close the window, wait 2 minutes, and open the app again. Only if the app then offers to file a waiting play, type 1. You can ignore the command the window prints; the app's offer does the same.

### One step of filing failed

Terminal shows: `Fix the cause, then rerun the whole chain:`

- **What it means:** one step of filing failed.
- **What to do:** read the lines just above it. If they mention seq, stop and ask for help. Otherwise, open the app again; it offers to file the waiting play. If the same message comes back, ask for help.

### Filing stopped after some parks were filed

Terminal shows: `To file the rest, run`

- **What it means:** the app filed some of the parks, then stopped. The line `already registered by this run:` names the parks that are done. The app has saved your answers about the others.
- **What to do:** read the lines above, fix the cause they name, then copy the command the window printed after `To file the rest, run`, only up to the opening bracket, and run it in the project folder (Step 10 takes you there). Don't open the app first: starting a play clears the saved answers, and the app would ask again about the parks that are not yet registered. If the same message comes back, ask for help.

### Nothing is waiting to be filed

Terminal shows: `auto-file: nothing is waiting to be filed.`

- **What it means:** every recorded play is already filed. Nothing is wrong and nothing was changed.
- **What to do:** nothing. If you expected a play to be there, check that you saved and quit the game, then open the app again.

### The dashboard doesn't open

Terminal shows: `The dashboard did not start`

- **What it means:** the dashboard didn't answer in time. Your play may still be filed.
- **What to do:** wait a minute, then go to http://127.0.0.1:8780/ in your browser. If it doesn't load, ask for help.

### The dashboard says no month has closed yet

The dashboard shows: `No monthly statement is in the working copy yet.`

- **What it means:** no game month has closed yet in your company parks.
- **What to do:** play a company park past the 1st of a month, save and quit.

<!-- passage: fix-autopilot -->
## Autopilot problems

### Autopilot lists a park as not ready

Terminal shows: `Not ready:`

- **What it means:** autopilot can't start this park; the reason follows its name.
- **What to do:** most often, play the park once from the app (type 1), save, quit, and check for a `Backup:` line.

### Autopilot can't find the game

Terminal shows: `OPENRCT2_BINARY does not name an executable file`

- **What it means:** autopilot can't find the game.
- **What to do:** drag OpenRCT2 into your Mac's main Applications folder. Then open the app again and type 3.

### Autopilot says the game was open a moment ago

Terminal shows: `The newest real OpenRCT2 autosave is`

- **What it means:** the game's newest autosave is less than 10 minutes old, so the game may still be running, and autopilot won't share your Mac with it.
- **What to do:** quit OpenRCT2, wait 10 minutes, then open the app again and type 3.

### Autopilot says you played that year by hand

Terminal shows: `is itself the managed park of company year`

- **What it means:** you played this park by hand in the year autopilot would play.
- **What to do:** play it by hand to 1 March of the next game year instead, then pause, save and quit.

### Autopilot says another park hasn't played that year yet

Terminal shows: `no other registered company park has a managed day in`

- **What it means:** no other company park has played that company year by hand yet.
- **What to do:** play another company park into that year by hand, save and quit. If the message also says `Waiting to register (they count once registered)`, that park's play isn't filed yet: open the app and type 1 when it offers to file it.

### Autopilot doesn't accept your sentence

Terminal shows: `Confirm it is ready with`

- **What it means:** the sentence you typed didn't match exactly. Nothing was played.
- **What to do:** press Return to close the window, open the app again, type 3, and paste the sentence again.

### Autopilot didn't start

Terminal shows: `Autopilot did not start`

- **What it means:** nothing was started.
- **What to do:** read the lines above it. Once the problem they name is fixed, open the app again and type 3.

### Autopilot stopped before it finished

Terminal shows: `Autopilot did not finish every step`

- **What it means:** the run stopped. It may have stopped before or after the year was added to your company.
- **What to do:** look at the lines above it. If one ends with `Nothing was written.` or says `Company data was not touched`, nothing changed: close the window, open the app again and type 3. Otherwise, stop and ask for help, even though the window says you may try again after a line that starts with three stars; that line can appear after the year was added.

### Autopilot's year finished but filing failed

Terminal shows: `Filing did not complete`

- **What it means:** the autopilot year finished, but filing it failed.
- **What to do:** if the lines above mention seq, stop and ask for help. Otherwise, wait 2 minutes, open the app again, and type 1 when it offers to file the waiting play.

<!-- passage: fix-advanced -->
## Advanced

### Your backups

- After each play you saved, the app keeps two copies of the park's last save: the dated copy in the game's save folder, which you load, and a second copy in the project's `local/park-backups/` folder, which autopilot uses. Never delete that folder.
- After a play by hand, a second play on the same day replaces that day's dated copy, but only while the copy still matches the project's own backup. If you saved into the dated copy yourself, the app leaves it alone and writes a new copy with the time added to its name. Autopilot never replaces a dated copy: when one already exists for that day, it writes a new copy with the time added. Older dated copies stay until you delete them.
- If a warning before a play tells you to copy a file from `local/park-backups/` into the game's save folder, copy it in Finder, then load it in the game.

### Several new parks in one sitting

If you start more than one new park in one play, the app asks about each one after you quit, with its name and the game days played. Type the number next to `Opened first`, `Opened second` and so on, in the order you first played them, or the number next to Sandbox. If the answers don't match that order, nothing is filed and the reason given is `order`. If filing stops, open the app again: it then asks the question for a park from an earlier play about each park that is not yet registered, and works out the start years again from the order of the parks' first recorded sessions.

### Moving the project folder

The app remembers where the project folder is. If you move the folder, open Terminal, type cd and a space, drag the folder from Finder into the Terminal window, and press Return. That puts Terminal in the folder's new place. Before you play again, ask whoever helps you to run the repair for a moved folder, which is under [For whoever helps you](#for-whoever-helps-you). The project's Python tools remember the old place, so until the repair is done a play can be recorded but not filed.

<!-- passage: fix-helper -->
## For whoever helps you

Run these in the project folder (`cd ~/openrct2-analytics`, or its new place after a move). The full command reference is the Commands section of AGENTS.md in the project.

- **Repair a damaged Python environment.** It deletes only the project's Python folder (named .venv) and builds it again; the game, saves and company data are not touched:

  ```zsh
  rm -rf .venv && make setup
  ```

- **After the project folder was moved.** First run the repair above in the folder's new place: every tool in the old Python folder (named .venv) still points at the old place, so filing fails until it is rebuilt. Then trust the folder again and rebuild the app so it opens the new place:

  ```zsh
  direnv allow
  ```

  ```zsh
  make launcher
  ```

- **Start the dashboard without a play.** It deletes nothing; keep its window open while the dashboard is in use:

  ```zsh
  make dashboard DATA_SET=company
  ```

- **File waiting play by hand.** It files every waiting park and may ask about others by name; it deletes nothing. Use `practice` instead of `company` for a Sandbox play:

  ```zsh
  make auto-file DATA_SET=company COUNT_AS=company
  ```

- **Remove a recording that failed its seq audit.** The message names the recording's ID. First put the ID in a variable: paste the line below, but before you press Return replace `EXAMPLE-SESSION-ID` with the ID from the message. (Left as it is, the commands below find no such recording.)

  ```zsh
  SESSION_ID='EXAMPLE-SESSION-ID'
  ```

  The next command is a preview: it deletes nothing and prints the plan and, on its `confirmation:` line, the exact phrase to confirm with. Read the plan before you go on:

  ```zsh
  make delete-company-data SESSION="$SESSION_ID"
  ```

  If the plan is right, run the confirmed command. It archives the affected files, then removes that recording from the company's data. It is refused once the company data has gone live (`raw captures are permanent since`):

  ```zsh
  make delete-company-data SESSION="$SESSION_ID" CONFIRM="delete company session $SESSION_ID"
  ```

  The preview ends by telling you to run `make pipeline DATA_SET=company` to rebuild. Do not run it while other play waits: it builds every recording but never registers a new park, so that park's play would be built and then never offered for filing. First run `make unfiled DATA_SET=company`. If it prints nothing, nothing waits, and you can run the rebuild command. If it prints a list, ask the player to open the app and type 1 when it offers to file the waiting play; the app converts, registers and builds in the right order.

- **After an autopilot run that stopped late.** Read the messages first. A year that landed is filed with the filing command above, unless a seq problem is named. A wrong run is removed with the delete commands above, by its session ID. A park's first autopilot run holds its readiness sentence, so the preview can refuse it with `holds the ready phrase of park` while later runs of that park exist. The default is to delete those later runs first, one at a time by their session IDs, then the first run. The whole-park delete is a last resort: deleting by park deletes every session of that park, hand play included, together with the park's registration and play-mode labels (archived first). To use it, put the park's ID in a `PARK_ID` variable as above and use `PARK="$PARK_ID"` in place of `SESSION="$SESSION_ID"` in both commands, with the phrase the preview prints on its `confirmation:` line. Before you confirm, read the preview's `scope: park=` line and its list of sessions, and check that every session listed is one you mean to lose. Then rebuild as the preview says, with the check for waiting play above. The Commands section of AGENTS.md, under make autopilot-year, explains what a delete keeps and what the next run needs.
