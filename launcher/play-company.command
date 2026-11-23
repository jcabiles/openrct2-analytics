#!/bin/zsh -l
# Opened in Terminal by the "OpenRCT2 Enterprise" app (make launcher): list play waiting to be
# filed and offer to file it before asking whether the play counts for the company or is a sandbox,
# start the company dashboard if it is not running, record one
# company play session, file it with make auto-file, then open the dashboard. A failed step stops
# the chain and leaves its message on screen. A third answer, "Run autopilot on a finished park",
# lists the parks that can run autopilot, asks the readiness sentence on a park's first run, records,
# runs the year under caffeinate, files it with make auto-file and opens the dashboard.
cd "${0:A:h}/.." || exit 1
dashboard_port=8780
dashboard_url="http://127.0.0.1:${dashboard_port}/"
dashboard_up() { curl -fsS --max-time 1 "${dashboard_url}_dashboard/ping" >/dev/null 2>&1 }
start_dashboard() {
  if ! dashboard_up; then
    mkdir -p local/dashboard
    # nohup keeps the server running after this Terminal window closes; &! detaches it from the shell.
    nohup direnv exec . make dashboard DATA_SET=company DASHBOARD_PORT=$dashboard_port DASHBOARD_DETACH=1 \
      </dev/null >>local/dashboard/server.log 2>&1 &!
  fi
}
# Opening the page never changes the window's exit status.
open_dashboard() {
  local _
  for _ in {1..20}; do dashboard_up && break; sleep 0.5; done
  if dashboard_up; then
    open "$dashboard_url"
  else
    print "The dashboard did not start; see $PWD/local/dashboard/server.log."
  fi
}
# Show the play that was recorded but never filed and offer to file it. Every name is local, so the
# global code that the last line exits with is never set here; end of input exits like the question.
offer_waiting_play() {
  local out rc answer first
  local -a lines
  out=$(direnv exec . make unfiled DATA_SET=company)
  rc=$?
  if (( rc != 0 )); then
    print "Waiting play could not be checked (see above)."
    return
  fi
  [[ -n $out ]] || return
  lines=("${(@f)out}")
  first=$lines[1]
  (( $#lines > 1 )) && print -rl -- "${(@)lines[2,-1]}"
  [[ $first == no-offer ]] && return
  answer=
  while [[ $answer != 1 && $answer != 2 ]]; do
    print "File the waiting play now, before this play?"
    print "1. Yes — file it first"
    print "2. No — go on"
    if ! read -r "answer?"; then
      print
      print "No answer was read. Nothing was changed."
      exit 130
    fi
  done
  [[ $answer == 1 ]] || return
  if [[ $first == offer-after-convert ]]; then
    # Convert exits non-zero whenever any session in the raw folder failed its audit, filed long ago
    # included, so its code is not used: the second list is the judge.
    direnv exec . make convert DATA_SET=company || true
    out=$(direnv exec . make unfiled DATA_SET=company)
    lines=("${(@f)out}")
    if [[ $lines[1] != offer ]]; then
      (( $#lines > 1 )) && print -rl -- "${(@)lines[2,-1]}"
      print "The waiting play was not filed."
      return
    fi
  fi
  # The record just written holds every session, so make auto-file asks about each unregistered park
  # by name and never applies COUNT_AS to a park; company is passed only because the mode needs a value.
  if ! { direnv exec . make auto-file DATA_SET=company RECORD=yes \
    && direnv exec . make auto-file DATA_SET=company COUNT_AS=company; }; then
    print "The waiting play was not filed (see above)."
    print "Any rerun command above is not needed: the waiting play is offered again the next time this app starts"
  fi
}
# The park menu behind answer 3. The list is read once; every reprint reuses that read. It sets
# autopilot_park, autopilot_label and autopilot_phrase (the helper's last field; "-" when no sentence
# is asked) for the chosen park, or leaves autopilot_park empty when the question is to be asked again.
# Every other name is local; end of input exits like the question.
choose_autopilot_park() {
  local raw menu line reply rc n
  local -a rows fields ready_ids ready_phrases ready_labels not_ready
  autopilot_park=
  raw=$(direnv exec . make autopilot-parks DATA_SET=company)
  rc=$?
  if (( rc == 0 )); then
    menu=$(print -r -- "$raw" | direnv exec . python -m openrct2_analytics.ingest.autopilot_menu)
    rc=$?
  fi
  if (( rc != 0 )); then
    print "The park list could not be read; see the messages above. To try again, choose 3 again, or run: make autopilot-parks DATA_SET=company"
    return
  fi
  if [[ -z $menu ]]; then
    print "No company park is registered yet, so autopilot has no park to run."
    return
  fi
  rows=("${(@f)menu}")
  for line in $rows; do
    fields=("${(@ps:\t:)line}")
    if [[ $fields[3] == - ]]; then
      ready_ids+=($fields[1])
      ready_phrases+=($fields[4])
      ready_labels+=($fields[2])
    else
      not_ready+=("Not ready: $fields[2]: $fields[3]")
    fi
  done
  if (( $#ready_ids == 0 )); then
    print "No park can run autopilot now:"
    print -rl -- "${(@)not_ready}"
    return
  fi
  while true; do
    print "Which park should autopilot run?"
    for n in {1..$#ready_ids}; do
      print -r -- "$n. $ready_labels[$n]"
    done
    (( $#not_ready )) && print -rl -- "${(@)not_ready}"
    print "0. Back to the first question"
    if ! read -r "reply?"; then
      print
      print "No answer was read. Nothing was changed."
      exit 130
    fi
    [[ $reply == 0 ]] && return
    # The answer is compared as text: arithmetic on a long digit string aborts zsh.
    for n in {1..$#ready_ids}; do
      if [[ $reply == "$n" ]]; then
        autopilot_park=$ready_ids[$n]
        autopilot_label=$ready_labels[$n]
        autopilot_phrase=$ready_phrases[$n]
        return
      fi
    done
  done
}
if ! command -v direnv >/dev/null 2>&1; then
  print "direnv is not on PATH. Install it with: brew install direnv; then run: direnv allow, in $PWD."
  code=2
elif ! direnv exec . true >/dev/null 2>&1; then
  print "direnv does not trust this folder yet. Run: direnv allow, in $PWD. Nothing was changed."
  code=2
else
  offer_waiting_play
  choice=
  while [[ -z $choice ]]; do
    print "Where should this play count?"
    print "1. Company — counts toward the company's results"
    print "2. Sandbox — saved, but kept out of the company's results (a company park stays company)"
    print "3. Run autopilot on a finished park — the game plays one company year by itself (up to about two hours), then it is filed"
    if ! read -r "answer?"; then
      print
      print "No answer was read. Nothing was changed."
      exit 130
    fi
    case $answer in
      1) choice=company ;;
      2) choice=practice ;;
      3)
        choose_autopilot_park
        [[ -z $autopilot_park ]] || choice=autopilot
        ;;
    esac
  done
  if [[ $choice == autopilot ]]; then
    ready_arg=()
    if [[ $autopilot_phrase != - ]]; then
      print -r -- "This is the first autopilot run for $autopilot_label. To confirm that it is ready, type this sentence exactly:"
      print -r -- "$autopilot_phrase"
      if ! read -r "typed?"; then
        print
        print "No answer was read. Nothing was changed."
        exit 130
      fi
      ready_arg=("READY=$typed")
    fi
    start_dashboard
    direnv exec . make auto-file DATA_SET=company RECORD=yes
    code=$?
    if (( code != 0 )); then
      print "Autopilot did not start; see the messages above. No autopilot run was started. Once the cause is fixed, open the launcher and choose 3 again."
    else
      print "This can take up to about two hours. Keep this window open until it says it finished. The Mac is kept from idle sleep while it runs; do not close the lid."
      direnv exec . caffeinate -i make autopilot-year DATA_SET=company PARK=$autopilot_park "${ready_arg[@]}"
      code=$?
      if (( code != 0 )); then
        # make reports every failure as 2, so the launcher cannot tell where the run stopped.
        print "Autopilot did not finish every step; see the messages above. If they say nothing was written or company data was not touched, or make stopped with a line starting with ***, nothing needs filing; fix the cause and choose 3 again. Otherwise, unless they name a seq problem, do not choose 3 again; file with: make auto-file DATA_SET=company COUNT_AS=company"
        print "That command files every waiting park, including an earlier registered park, and may ask about other waiting parks by name."
      else
        direnv exec . make auto-file DATA_SET=company COUNT_AS=company
        code=$?
        if (( code != 0 )); then
          print "Filing did not complete; see the messages above. To try again, run: make auto-file DATA_SET=company COUNT_AS=company"
          print "That command files every waiting park, including an earlier registered park, and may ask about other waiting parks by name."
          print "If the report above names a seq problem, do not file it."
        fi
      fi
    fi
    (( code == 0 )) && open_dashboard
  else
    start_dashboard
    direnv exec . make auto-file DATA_SET=company RECORD=yes
    code=$?
    if (( code != 0 )); then
      print "The game was not opened: noting the earlier recordings failed (see above). Nothing was played or filed."
    else
      direnv exec . make play DATA_SET=company
      code=$?
      if (( code == 0 )); then
        direnv exec . make auto-file DATA_SET=company COUNT_AS=$choice
        code=$?
      else
        # make reports every failure as 2, so the capture's own exit code is not visible here.
        print "This play was not filed. If the report above names a seq problem, do not file it; otherwise run: make auto-file DATA_SET=company COUNT_AS=$choice"
      fi
    fi
    (( code == 0 )) && open_dashboard
  fi
fi
print
read -r "?Press Return to close this window."
exit $code
