<!--
Maintainer notes (hidden on GitHub). This file holds the words of the player guide's play part. The site page
site/guide.njk renders each named passage of it in place, after the setup part from install-by-hand.md and
before the help part from fix-a-problem.md: a passage starts at its HTML-comment marker and runs to the next
marker. Edit the words here, never in site/guide.njk; a passage added, removed or renamed here needs the
matching change there.

- Text before the first marker is not rendered on the site. The first marker sits inside the page's heading
  line, so GitHub shows a heading while the site takes only its text.
- Passages whose names end in -github are for GitHub only; they hold the links to the other two guide files.
- Each topic passage starts with its own heading. The section ids in site/guide.njk equal GitHub's anchors
  for those headings, so the in-page links work in both places.
- Every code span on the built page, including each screen block, is pinned to the code that prints it in
  tests/guide_strings.toml. Screen text is quoted exactly as the code prints it.
-->

# <!-- passage: how-h -->How to play Theme Park Enterprise

<!-- passage: how-contents -->
This page takes about 10 minutes to read. Read the first three parts before you play; come back to the others when you need them.

1. [What Theme Park Enterprise is](#what-theme-park-enterprise-is)
2. [Three words the app uses](#three-words-the-app-uses)
3. [Your first play](#your-first-play)
4. [Continue a park](#continue-a-park)
5. [Try things in a Sandbox park](#try-things-in-a-sandbox-park)
6. [Open Park 2](#open-park-2)
7. [Run a finished park on autopilot](#run-a-finished-park-on-autopilot)
8. [Read your dashboard](#read-your-dashboard)

<!-- passage: how-help-github -->
Something on screen this page doesn't explain? Look it up in [Fix a problem](fix-a-problem.md).

<!-- passage: how-what -->
## What Theme Park Enterprise is

You run one theme park company in OpenRCT2. Every park you open belongs to it.

- **One calendar.** Your company starts on 1 March 2000. Each OpenRCT2 season, March to October, is one **company year**.
- **One park at a time.** You open parks one after another. The app works out which company year each new park starts in.
- **Every play is recorded.** You start the game from the app **OpenRCT2 Enterprise**. It records what happens in your park and adds it to your company when you quit.
- **A dashboard on your Mac** shows how your company is doing, month by month.
- **Autopilot** lets an older park play a company year by itself, with no game window, while you aren't playing. It plays a year that another company park has already played by hand, so your older parks keep earning.

<!-- passage: how-words -->
## Three words the app uses

- **A play** is one sitting: from opening the app until you quit the game. The app asks `Where should this play count?` at the start of each one.
- **Filing** a play adds what was recorded to your company. The app files each play for you after you quit. Saving keeps your park in OpenRCT2; filing puts the play on your dashboard.
- **Company or Sandbox.** A Company play counts in your company's results. A Sandbox play is recorded but left out of them. A park keeps the choice it was first filed under: a company park stays a company park, and a Sandbox park stays a Sandbox park.

<!-- passage: how-first-play -->
## Your first play

1. Quit OpenRCT2 if it's open, then double-click **OpenRCT2 Enterprise**. A Terminal window opens and asks:

   ```
   Where should this play count?
   1. Company — counts toward the company's results
   2. Sandbox — saved, but kept out of the company's results (a company park stays company)
   3. Run autopilot on a finished park — the game plays one company year by itself (up to about two hours), then it is filed
   ```

2. Type 1 and press Return. Terminal prints `Opening OpenRCT2.` and the game opens by itself.
3. Start a new game and pick any scenario. Don't load a save: a new company park starts fresh.
4. Once your park is open, Terminal prints `events arriving`. That means the app is recording. If it never appears, or Terminal says `NOT recording`, quit the game and look up what Terminal says in Fix a problem, under "When you start a play".
5. Play until the month in the game's bottom bar shows **April**. Your dashboard shows a month only after the game closes it, on the 1st of the next month.
6. Save your park, then quit OpenRCT2.
7. Watch Terminal. It prints a report of your play, then a line that starts with `Backup:`. Note the file name after `copied to save/` on that line: it's the file you load next time. Then the app files the play and welcomes your park:

   ```
   <park name> joins the company as Park <number>, starting in company year <year>
   ```

   Your first park is Park 1, starting in company year 2000.
8. Your browser opens your dashboard on its **Executive** page. Check that your play is there: the sentence at the top of the page starts `By the end of March 2000`. If the page says `No monthly statement is in the working copy yet.`, your play didn't get into April. Continue the park and play into April.
9. Back in Terminal, press Return when it says `Press Return to close this window.` Keep the window open until then.

<!-- passage: how-first-play-github -->
Something else on screen? Look it up in [Fix a problem](fix-a-problem.md#when-you-start-a-play).

<!-- passage: how-continue -->
## Continue a park

1. Quit OpenRCT2 and double-click **OpenRCT2 Enterprise**. Type the park's own choice: 1 for a company park, 2 for a Sandbox park.
2. In the game, load the file named after `copied to save/` on the park's last `Backup:` line (after an autopilot year, the save named on its `To refurbish the park, load save/` line). Its name looks like this:

   ```
   <park name>-last-plugin-save-YYYY-MM-DD.park
   ```

3. Play, save and quit, as in your first play.

That file is exactly where your company's record of the park stops, and autopilot starts from it later.

Before the game opens, Terminal may warn that a save `was saved over while nothing was recording` or `changed after the last recorded save`. This happens when you played with the plain OpenRCT2 icon. Load the file the warning names instead.

The window may also start with `Play waiting to be filed:` and ask `File the waiting play now, before this play?` That's an earlier play that wasn't filed, for example because the window was closed too early. Type 1 to file it first, and answer any question about the parks it names.

<!-- passage: how-sandbox -->
## Try things in a Sandbox park

Type 2 at the first question and start a new game. That park becomes a Sandbox park: recorded and saved, but left out of your company's results. To continue it later, type 2 again and load its backup file.

You can't practise on a company park. If you type 2 and then load a company park, the app asks after you quit: the park `is saved as Company, but this play was started as Sandbox.` Type 1 to file the play as Company. To experiment freely, start a separate Sandbox park.

<!-- passage: how-park-2 -->
## Open Park 2

Close your current park's company year first, then start the new park. The order matters.

1. **Stop your current park exactly on 1 March.** Near the end of October, set the game to normal speed. Watch the month in the bottom bar, and pause the moment it changes from October to March. That change is 1 March. Save while paused, then quit. Reach 1 March in the same sitting that plays the park's last days of October. 1 March closes the company year; even one day past it counts as the next company year, which pushes Park 2's start a year later.
2. **Let the app file that play.** Wait for the `Backup:` line and `Press Return to close this window.`
3. **Start the new park.** Open the app, type 1, and start a new game. Don't load a save.
4. **Play, save and quit as usual.** Terminal welcomes the new park, with its number and the company year it starts in.

For example: your first park played company years 2000, 2001 and 2002, and you stopped it on 1 March. Your next park joins as Park 2, starting in company year 2003. You never type the year. The game itself still shows Park 2's own dates, starting from its year 1; the company year is your dashboard's calendar.

From now on you play Park 2 by hand. Each time Park 2 plays and files a new company year, Park 1 can play that year on autopilot.

<!-- passage: how-autopilot -->
## Run a finished park on autopilot

Autopilot plays one park by itself, with no game window, from its last backup to the next 1 March. It only plays a company year that another park has already played by hand.

### A park can run autopilot when

- It's a company park, not a Sandbox park.
- Its last play ended with a `Backup:` line for it. Autopilot starts from that backup.
- Another company park has played that company year by hand, saved, and been filed. For example: Park 1 stopped on 1 March, at the start of 2003. Once Park 2 has played into 2003, saved and been filed, Park 1 can play 2003.
- You haven't played the park itself by hand in that company year.
- OpenRCT2 is in your Mac's main Applications folder, the game is closed, and its newest autosave is at least 10 minutes old. Autopilot won't start while the game might still be running.
- First run only: the park makes a profit and you've completed its scenario challenge (the goal the scenario gave you). You confirm this by typing a sentence.

### Run it

1. Double-click **OpenRCT2 Enterprise** and type 3. Type the number next to the park's name in this menu:

   ```
   Which park should autopilot run?
   1. <park>
   Not ready: <park>: <reason>
   0. Back to the first question
   ```

   A park listed as `Not ready:` can't run yet; the reason follows its name. The app checks the company year only after you pick a park, so a numbered park can still be refused.
2. On a park's first run, the window says `To confirm that it is ready, type this sentence exactly:` and prints it. The sentence is the park's ID followed by `is profitable and its scenario challenge is complete`. Copy the whole sentence from the window, paste it, and press Return.
3. Leave the Terminal window open and your Mac's lid open. The window says `This can take up to about two hours. Keep this window open until it says it finished.` Most runs take a few minutes: the app stops the game if it runs longer than about 17 minutes, and before it starts it may wait up to 5 minutes for your Mac to be less busy.
4. When the year is done, Terminal prints a line with `played company year`, files the year and opens your dashboard. To continue the park by hand, load the save named on the line that starts `To refurbish the park, load save/`.

If the window says `Autopilot did not finish every step`, read the lines above it. If one of them ends with `Nothing was written.` or says `Company data was not touched`, nothing changed: press Return to close the window, fix what the message names, open the app again and type 3. For any other ending, don't try again; the year may already be in your company's records.

<!-- passage: how-autopilot-github -->
Every autopilot message, and what to do about it, is in [Fix a problem](fix-a-problem.md#autopilot-problems).

<!-- passage: how-dashboard -->
## Read your dashboard

Your dashboard runs on this Mac at http://127.0.0.1:8780/. It keeps running until you restart your Mac. After a restart, open the app and choose a play: the app starts the dashboard each time you choose 1, 2 or 3.

- **Start on Executive.** It opens first. Its top sentence describes the company up to the latest month the game has closed, so it doesn't change while you play inside a month.
- **Filters are on the left:** the park, the **Company year**, and **Season to date through** (the last month to count). Sandbox parks are left out of **All parks** at first; to count them, choose **Included** under **Sandbox parks**.
- **The yellow bar at the top of every page** shows when the figures were last updated, and also says when a park has play that isn't filed yet and what to do.
- **New play shows after a reload.** Once a play is filed, press Command-R. A month appears only once the game has closed it, on the 1st of the next month.

Each page answers one question:

| Page | The question it answers |
| --- | --- |
| **Executive** | Is this season ahead of last season at the same point? |
| **Finance** | What made a month good or bad, ride by ride? |
| **Attractions** | Which rides pull their weight? |
| **Pricing** | Did a ride's price change pay off? It shows a change once the ride kept each price for at least 5 open days. |
| **Operations** | When do guests come, and how often is each ride open? |

<!-- passage: how-next-github -->
**Next:** if something goes wrong, see [Fix a problem](fix-a-problem.md). To set up again, see [Set up your Mac](install-by-hand.md).
