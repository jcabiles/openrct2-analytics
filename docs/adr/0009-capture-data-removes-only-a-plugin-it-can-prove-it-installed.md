# ADR 0009: capture-data removes only a plugin file it can prove it installed

- Date: 2026-09-30
- Status: Accepted

## Bottom line

`make capture-data` writes an install record before it installs the plugin, publishes the file with a
hard link that cannot overwrite anything, and removes the file only when its path equals the recorded
path and its SHA-256 equals the recorded one. Any other file at the install path is left alone and the
command refuses to start. The price is that a file with the same bytes put there by someone else counts as
the command's own, and that a force-killed run leaves the plugin in the player's folder until the next
start removes it.

## Context

The command writes into the player's own OpenRCT2 plugin folder, which the repo does not own. The
roadmap's no-go for this work is that it deletes only the plugin file it installed. The engine loads every
`.js` file in that folder as its own plugin, so a leftover file keeps recording the next time the game
starts. The harness that proved the real-play flow overwrote its named file blindly and removed it with a
missing-is-fine delete, which is safe for a probe and wrong for a command other players run.

## Decision

| Decision | Choice |
|---|---|
| Ownership proof | The install record `installed-plugin.json` in the capture folder holds the install path, the SHA-256 of the installed bytes and the time. A file is the command's own only when the recorded path equals the current install path and the file's SHA-256 equals the recorded one. |
| Order | Record first, then a copy under the temporary name `.openrct2-analytics.js.capture-tmp` (no `.js` suffix, so the game never loads it), then a hard link to the final name, then removal of the temporary name. |
| Publish | A hard link, which fails when the final name exists, so a file that appeared after the checks is never replaced. The command then refuses, removes only its temporary file and keeps the other file. |
| Foreign files | A file at the install path that fails the proof, a symlink, a non-regular file or a file with an extra hard link (other than the command's own temporary name) makes the command exit 2 with "Nothing was changed." |
| Leftovers | At the next start, a file or temporary file that passes the proof is removed as the leftover of a killed run; a record whose files are gone is cleared. |
| Failed removal | The record is deleted only after the file is gone, so a failed removal keeps the record and exits 1 for the next run to finish. |
| Build | The plugin is rebuilt on every run and the output is deleted before and after a failed build. |

## Rejected alternatives

- **Overwrite the named file, as the harness did.** It destroys a player's own file of the same name.
- **Publish with a rename.** `os.rename` replaced an existing file in a re-run on 2026-09-30, so a file
  that appeared between the checks and the publish would have been destroyed.
- **Prove identity by inode as well as bytes.** Not adopted: a file at the install path with the recorded
  bytes is the command's own plugin in every way that matters, so removing it loses nothing the command did
  not create.
- **Rebuild only when the output is older than its sources.** The TypeScript compiler writes its output even
  on a type error, so a failed `make check` build left a file newer than its sources, and the time check
  would have installed it.

## Consequences

- **Same bytes, other hands.** A file with identical bytes put at the install path by someone else is
  treated as the command's own and removed. Accepted: it would be the same plugin.
- **A force-kill leaves the plugin until the next start.** SIGKILL cannot be handled; the next run removes
  the file under the same proof. A kill in the middle of writing the temporary file leaves a file that
  matches no record, so every later run refuses until it is moved away; the refusal names the file.
- **A few seconds per run** for the rebuild.
- **The record holds a private home path,** so `data/capture/` is git-ignored and a test guards the rule.
- **Hard links need file-system support.** Only macOS has run against the real game; a file system with no
  hard links would make the install fail on Windows or Linux, which stay untested.

## How we would know this is wrong

- A real session leaves the plugin behind, or removes a file the command did not install.
- A player on Windows or Linux cannot install because their file system lacks hard links, which would
  mean the publish step needs a fallback.
