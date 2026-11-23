<!--
Maintainer notes (hidden on GitHub). This file holds the words of the player guide's setup part. The site
page site/guide.njk renders each named passage of it in place: a passage starts at its HTML-comment marker
and runs to the next marker. Edit the words here, never in site/guide.njk; a passage added, removed or
renamed here needs the matching change there.

- Text before the first marker is not rendered on the site. The first marker sits inside the page's heading
  line, so GitHub shows a heading while the site takes only its text.
- Passages whose names end in -github are for GitHub only; the site never renders them. They hold the links
  to the other two guide files, which sit on the same page on the site.
- Site-only labels (page title, skip link, home link) live in guide-site-labels.md.
- Each step's command is one fenced zsh block, so GitHub shows a copy button. tests/test_guide_strings.py
  reads the commands from those blocks and pins them in order.
- Bare https addresses become links on GitHub and stay plain text on the site, whose page check allows only
  relative links.
- Every code span on the built page is pinned to the code or tool that prints it in tests/guide_strings.toml.
-->

# <!-- passage: install-h -->Set up Theme Park Enterprise on your Mac

<!-- passage: guide-bottom-line -->
Theme Park Enterprise lets you play OpenRCT2 as one company that owns several theme parks. An app records each time you play, and a dashboard on your own Mac shows how your company is doing. You set it up once, in about an hour, by copying commands into Terminal. You don't write any code.

<!-- passage: install-help-github -->
If a step shows a message this page doesn't explain, look it up in [Fix a problem](fix-a-problem.md#while-you-set-up).

<!-- passage: install-before -->
## What you need

- **A Mac**, and the password of an account that can install apps on it (an administrator account).
- **OpenRCT2 0.5.6**, dragged into your Mac's main Applications folder (not Downloads, and not an Applications folder inside your home folder), then opened once. Autopilot only finds the game there.
- **Your own RollerCoaster Tycoon 2 game files.** OpenRCT2 asks where they are the first time it starts.
- **Access to the project page**, https://github.com/jcabiles/openrct2-analytics. Open it. If GitHub says "Page not found", ask the person who shared the project to give your GitHub account access. If it shows **Private** next to the project's name, you need a GitHub account and you'll sign in at Step 8.
- **An internet connection, and about an hour.** Most of that time is waiting for downloads. The hour is an estimate; a slow connection takes longer.

## Know your Mac's chip

Steps 3 and 5 differ between the two kinds of Mac. Click the Apple menu, choose **About This Mac**, and look at the first lines.

- A **Chip** line that says Apple (for example Apple M1) means an **Apple chip**.
- A **Processor** line that says Intel means an **Intel chip**.

## Terminal basics

Terminal is the Mac app where you type commands.

1. **Open it.** Press Command-Space, type Terminal, and press Return. The line ending in % is the **prompt**: Terminal is waiting for you.
2. **Copy a command.** On GitHub, point at the grey box and click the copy button in its top-right corner. Or select the whole command and press Command-C.
3. **Paste and run it.** Click in Terminal, press Command-V, then press Return.
4. **Wait for a fresh prompt.** When a new line ending in % appears and no error is shown, the command has finished. Step 1 is the one exception, and it says so.
5. **Type your password when asked.** Nothing appears while you type, not even dots. Type it and press Return.

If Terminal seems stuck, hold Control and press C. That stops the command and gives you a fresh prompt.

<!-- passage: step-dev-tools-title -->
## Step 1: Install Apple's developer tools

<!-- passage: step-dev-tools-do -->
These tools let your Mac download the project and run its commands.

<!-- passage: step-dev-tools-command -->
```zsh
xcode-select --install
```

<!-- passage: step-dev-tools-see -->
**You should see:** a window asking to install the command line developer tools. Click **Install** and agree to the terms. Terminal shows a fresh prompt straight away, but the install is not finished yet: wait until the window says the software was installed, then go to Step 2.

<!-- passage: step-dev-tools-fix-1 -->
If Terminal says `already installed`, the tools are already on your Mac. Go to Step 2.

<!-- passage: step-homebrew-title -->
## Step 2: Install Homebrew

<!-- passage: step-homebrew-do -->
Homebrew installs the other tools for you. This command comes from Homebrew's own website, https://brew.sh. Terminal asks for your Mac password, then asks you to press Return to go on.

<!-- passage: step-homebrew-command -->
```zsh
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

<!-- passage: step-homebrew-see -->
**You should see:** `Installation successful!` near the end, then a list called **Next steps**.

<!-- passage: step-homebrew-fix-1 -->
If it says `Need sudo access on macOS`, your account can't install apps. Log in to an administrator account, then run this step again.

<!-- passage: step-homebrew-path-title -->
## Step 3: Tell Terminal where Homebrew is

<!-- passage: step-homebrew-path-do -->
**Intel chip:** skip this step and go to Step 4. Terminal already looks where Homebrew is.

**Apple chip:** run this command.

<!-- passage: step-homebrew-path-command -->
```zsh
echo 'eval "$(/opt/homebrew/bin/brew shellenv)"' >> ~/.zprofile && eval "$(/opt/homebrew/bin/brew shellenv)"
```

<!-- passage: step-homebrew-path-see -->
**You should see:** a fresh prompt. To check it, run `brew --version`: it prints Homebrew and a version number.

<!-- passage: step-homebrew-path-fix-1 -->
If `brew --version` says `command not found: brew`, open a new Terminal window (Command-N) and run it again there.

<!-- passage: step-tools-title -->
## Step 4: Install Node, direnv and uv

<!-- passage: step-tools-do -->
This installs the three tools the project runs on. It takes a few minutes.

<!-- passage: step-tools-command -->
```zsh
brew install node@24 direnv uv
```

<!-- passage: step-tools-see -->
**You should see:** many lines, then a fresh prompt, with no line starting with `Error:`. Near the end Homebrew prints a note about node@24; Step 5 takes care of it.

<!-- passage: step-tools-fix-1 -->
A line starting with `Error:` names the problem. Check your internet connection and run the command again.

<!-- passage: step-node-path-title -->
## Step 5: Tell Terminal where Node 24 is

<!-- passage: step-node-path-do -->
Homebrew keeps Node 24 in its own folder, so Terminal can't find it yet.

Run only the box for your Mac.

**Intel chip:**

```zsh
echo 'export PATH="/usr/local/opt/node@24/bin:$PATH"' >> ~/.zshrc
```

**Apple chip:**

<!-- passage: step-node-path-command -->
```zsh
echo 'export PATH="/opt/homebrew/opt/node@24/bin:$PATH"' >> ~/.zshrc
```

<!-- passage: step-node-path-see -->
**You should see:** a fresh prompt. Step 7 checks that Terminal finds Node 24.

<!-- passage: step-node-path-fix-1 -->
If Homebrew's note from Step 4 shows a different line, run the line from the note instead.

<!-- passage: step-direnv-hook-title -->
## Step 6: Turn on direnv

<!-- passage: step-direnv-hook-do -->
direnv switches on the project's settings whenever you go into its folder. This line starts it in every new Terminal window.

<!-- passage: step-direnv-hook-command -->
```zsh
echo 'eval "$(direnv hook zsh)"' >> ~/.zshrc
```

<!-- passage: step-direnv-hook-see -->
**You should see:** a fresh prompt. Step 7 checks it.

<!-- passage: step-direnv-hook-fix-1 -->
If the prompt changes to `dquote>`, a quote mark got lost when you pasted. Hold Control and press C, then paste the command again.

<!-- passage: step-check-tools-title -->
## Step 7: Check the tools

<!-- passage: step-check-tools-do -->
Open a **new** Terminal window (Command-N), so it reads the lines you just added. Use this new window for the rest of the setup.

<!-- passage: step-check-tools-command -->
```zsh
node --version && uv --version && direnv version
```

<!-- passage: step-check-tools-see -->
**You should see:** three lines, one per tool. The first starts with `v24`.

<!-- passage: step-check-tools-fix-1 -->
If a line says `command not found`, or the first line doesn't start with `v24`, look up the message in Fix a problem, under "While you set up".

<!-- passage: step-check-tools-fix-github -->
These messages are in [Fix a problem, under "While you set up"](fix-a-problem.md#while-you-set-up).

<!-- passage: step-sign-in-title -->
## Step 8: Sign in to GitHub (private project only)

<!-- passage: step-sign-in-do -->
Skip this step if the project page shows **Public** next to its name. A private project needs you to sign in before Terminal can download it. First install GitHub's sign-in tool:

<!-- passage: step-sign-in-command-1 -->
```zsh
brew install gh
```

<!-- passage: step-sign-in-between -->
Then start the sign-in:

<!-- passage: step-sign-in-command-2 -->
```zsh
gh auth login
```

<!-- passage: step-sign-in-answers -->
Terminal asks four questions. Use the arrow keys to pick an answer, then press Return:

1. Where you use GitHub: **GitHub.com**
2. Protocol for Git: **HTTPS**
3. Use your GitHub sign-in for Git: type **Y**
4. How to sign in: **Login with a web browser**

Terminal then shows a one-time code. Press Return, and your browser opens a GitHub page. Type the code there and approve the sign-in.

<!-- passage: step-sign-in-see -->
**You should see:** `Logged in as` followed by your GitHub name.

**If it fails:** if `brew install gh` says `command not found: brew`, open a new Terminal window (Command-N) and run it again there. If it shows a line starting with `Error:`, check your internet connection and run it again. If `gh auth login` cannot open your browser, copy the web address Terminal shows into your browser by hand. If GitHub says the code is wrong or has expired, run `gh auth login` again and use the new code.

<!-- passage: step-clone-title -->
## Step 9: Download the project

<!-- passage: step-clone-do -->
This copies the project into a new folder, openrct2-analytics, in your home folder. The address in it is the one under the project page's green Code button, on the HTTPS tab; if you were given a different project page, use the address from its Code button instead.

<!-- passage: step-clone-command -->
```zsh
git clone https://github.com/jcabiles/openrct2-analytics.git ~/openrct2-analytics
```

<!-- passage: step-clone-see -->
**You should see:** `Cloning into` and a few progress lines, then a fresh prompt.

<!-- passage: step-clone-fix-1 -->
If it says `Repository not found` or `Authentication failed`, your GitHub account can't reach the project yet: do Step 8, or ask for access. If it says `already exists and is not an empty directory`, a folder with that name is already there. Check that it is this project before you go on: look it up in Fix a problem, under "While you set up".

<!-- passage: step-cd-title -->
## Step 10: Go into the project folder

<!-- passage: step-cd-do -->
Every command from here on runs inside the project folder.

<!-- passage: step-cd-command -->
```zsh
cd ~/openrct2-analytics
```

<!-- passage: step-cd-see -->
**You should see:** `openrct2-analytics` just before the % in the prompt. A direnv line saying the `.envrc` file `is blocked` is expected: the folder's settings stay off until Step 12, after Step 11 has installed what they use.

<!-- passage: step-cd-fix-1 -->
If it says `no such file or directory`, the download in Step 9 didn't finish. Run Step 9 again.

<!-- passage: step-setup-title -->
## Step 11: Set up the project

<!-- passage: step-setup-do -->
This installs the project's own Python 3.12 and everything else it needs. It takes a few minutes.

<!-- passage: step-setup-command -->
```zsh
make setup
```

<!-- passage: step-setup-see -->
**You should see:** `doctor: the Python environment is whole.` near the end.

<!-- passage: step-setup-fix-1 -->
If it stops with an error, or says `doctor: the Python environment is damaged.`, look up the message in Fix a problem, under "While you set up".

<!-- passage: step-setup-fix-github -->
These messages are in [Fix a problem, under "While you set up"](fix-a-problem.md#while-you-set-up).

<!-- passage: step-direnv-allow-title -->
## Step 12: Switch on the folder's settings

<!-- passage: step-direnv-allow-do -->
direnv only switches on a folder's settings after you say you trust them.

<!-- passage: step-direnv-allow-command -->
```zsh
direnv allow
```

<!-- passage: step-direnv-allow-see -->
**You should see:** a few lines that start with `direnv:`. You never need this step again.

<!-- passage: step-direnv-allow-fix-1 -->
If it still says the `.envrc` file `is blocked`, check that the prompt shows `openrct2-analytics`. If not, run Step 10, then this step again.

<!-- passage: step-launcher-title -->
## Step 13: Build the app you play from

<!-- passage: step-launcher-do -->
This builds the app **OpenRCT2 Enterprise**. You start every play from it.

<!-- passage: step-launcher-command -->
```zsh
make launcher
```

<!-- passage: step-launcher-see -->
**You should see:** a line that starts with Built and ends with `Drag it to the Dock; double-click it to record and play the company park.`

<!-- passage: step-launcher-fix-1 -->
If it also says `OpenRCT2.app was not found in /Applications or ~/Applications`, the app is still built, but it keeps a plain script icon. To give it the game's icon, drag OpenRCT2 into your Mac's main Applications folder, then run this step again. You need OpenRCT2 there to play anyway.

<!-- passage: install-done -->
## You're ready when

1. Open Finder, choose **Go** then **Home** in the menu bar, and open the **Applications** folder there (`~/Applications`). Drag **OpenRCT2 Enterprise** to your Dock.
2. Double-click **OpenRCT2 Enterprise**. You're ready when a Terminal window asks `Where should this play count?`
3. Not playing yet? Close that window (click **Terminate** if Terminal asks). Nothing has changed.

From now on, always start the game from **OpenRCT2 Enterprise**. The plain OpenRCT2 icon starts the game without recording anything, so keep it out of your Dock.

<!-- passage: install-next-github -->
**Next: [Play your first park](how-the-game-works.md#your-first-play)**
