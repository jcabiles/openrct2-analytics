# Showcase design mockups (October 2026)

**Bottom line.** The showcase design is picked: Mockup 18, the Ticket Booth look (Mockup 15) carried forward with the
approved section rewrites, accepted by the project owner on 2026-11-02 as the v1 design target. It was reached in
three steps after the fifteen original mockups (below). Like every mockup, it is a design study on illustrative data,
not the site: nothing is built on the warehouse, committed or published. Its light-mode palette is "RCT exact", the
original RollerCoaster Tycoon logo colours, picked on 2026-11-02 and carried in Mockup 19. The brand brief (NEXT 26,
the record of the site's palette, type and tokens) is drawn from both.

## The pick: Mockup 18 (2026-11-02)

- **Mockup 16, Ticket Booth final (2026-10-31).** The project owner picked Ticket Booth as the base and the north star
  for the design.
- **Mockup 17, v1 quick fixes (2026-10-31).** Mockup 16 with a round of small fixes, plainer headings, and the Pricing
  Model section removed.
- **Mockup 18, v1 sections (2026-11-02).** Mockup 17 with three changes:
  - **Business Insights** became three department panels, Finance, Operations and Attractions (Product), each opening
    with a dated note on what changed and why, and each chart naming its unit and clock.
  - **How it was built** became "The build crew": a diagram of the project owner directing AI agents from three
    vendors (Claude, Codex and Gemini), each box naming its model and why it fits, hover detail for each role and for
    three rules added after something broke, and a short case for cross-vendor, adversarial review.
  - **The section menu** is Mockup 8's (Greatest Hits) top bar, recoloured to the Ticket Booth palette.
- **Desktop only for now.** Phone layout is deferred to the first item after v1 ships (roadmap, Phase 4).
- **Known gaps, deferred:** Business Insights needs its content and controls finished (a roadmap LATER item: an
  awkward month dropdown, no reset on some drill-down charts, and whether to bring back an executive view), and all
  page copy gets final passes before publication (roadmap, publication preparation).

## The palette: RCT exact (2026-11-02)

The project owner picked "RCT exact" for light mode after comparing seven palettes drawn from the original
RollerCoaster Tycoon box-art logo and the OpenRCT2 logo (exact, muted, and one main colour with logo accents). Mockup 19
(`mockups/mockup-19-rct-exact.html`) is Mockup 18 with this palette and the accessibility fixes below.

- **Five seed colours drive every token** through `color-mix(in oklab, …)`:
  - main: logo coaster-track red `#C4161C`;
  - accent: logo letter yellow `#F7C21B`, used as a fill behind dark text, never as a thin line or text on the page;
  - third: sky blue `#3E8EDE`, for chart fills only;
  - page tint: `#E8B23A`, giving a cream page of about `#FDF8EE`;
  - text: dark brown `#3B2412` (14.3:1 on the page surface).
- **Fixes from an independent colour review** (WCAG 2.2 AA, the web accessibility standard):
  - small text on the red ticket stub uses `#FCDDD5` (4.73:1; the mixed shade was 4.15:1, under the 4.5:1 minimum);
  - ride revenue is dark blue `#245C87`, so red means the brand or a loss, never income;
  - the palest cost series carries a 2 px dark outline in the chart and its legend key;
  - the profit-and-loss chart folds Stock into the other small costs, leaving five colour series;
  - the stacked Park 1 and Park 2 bar has a 2 px gap and the park names written beside it, so colour is not the only
    label.
- **Still open:** dark mode gets its own designed palette (Mockup 19 is light only), and gains and losses keep their
  plus and minus signs, because the gain green and loss red are hard to tell apart for red-green colour-blind readers.

## The rule for choosing (2026-10-20, now settled)

- **Candidates were** Mockups 8 to 15; the pick is Ticket Booth (Mockup 15), refined into Mockup 18.
- **Reference only:** Mockups 1 to 7. A section that exists only in the first batch returns only by a new ruling.

## What a mockup is

Each mockup is one self-contained HTML page that carries the site's full outline: a first screen with six section
buttons, Theme Park Enterprise, Extracting Data, Data and Analytics Infrastructure, Business Insights (Executive, Finance
and Product views), the Pricing Model, the board-meeting story and the Git repository. Every chart reads a fixed
illustrative data set and carries an "Illustrative data" label; the only real figures are the March to May 2000 rehearsal
months, marked as real. Each mockup page loads GSAP (an animation library) from cdnjs and its fonts from Google Fonts, so it
needs a network connection to draw its charts; the site page built from a frozen copy of Mockup 19 (Mockup 18 with the RCT exact palette) does not (ADR 0043).

The audience is recruiters, hiring managers and senior engineering and data leaders. The pages are judged on whether a
reader quickly understands what the project is and why one person owning the whole path, from game events to business
insight, has analytics value.

## The candidates: Mockups 8 to 15 (built 2026-10-20)

Every page in this batch has a section menu that stays reachable from anywhere on the page, opens Theme Park Enterprise
with the company's four house rules, draws the pipeline as one horizontal route (a U-turn on some pages), and gives Business Insights working filters, a
sortable table and takeaway sentences computed from the data.

| # | Name | Kind | Look | Showpiece |
|---|---|---|---|---|
| 8 | Greatest Hits | approved sections | Mockup 1's look unchanged | Mockup 1's page with the approved sections swapped in; a ride table that highlights the ride in the ratings chart |
| 9 | Retro Window, Remastered | approved sections | Mockup 3's console with one retro game-style frame | a ratings scatter the reader reshapes by park, ride type and rating; a break-the-pipeline diagram |
| 10 | Golden Hour | approved sections | Mockup 1 re-coloured to late afternoon, over a fixed still sky | findings that set the dashboard to the view that shows them; the board story opens into the Insights views |
| 11 | Flock Yeah, Tycoon | some variety | playful sticker board, sticker yellow | a mascot that rides the monthly profit curve; a Park 1 against Park 2 comparison mode |
| 12 | Data Platform Launch | some variety | developer-platform launch page, coaster red on white | a command palette; notebook-style Insights cells; pipeline failures shown as an incident status page |
| 13 | Annual Report | approved sections | financial-statement chapters, statement navy with colour fields | one board story whose slides open the Executive, Product and Finance chapters |
| 14 | Block Section | takes risks | ride operator's console, mint and teal | throw one of eight documented faults and watch the pipeline hold the train; a click-through board story |
| 15 | Ticket Booth | takes risks | vintage ride tickets, claret and gold, fixed still pattern | trace any table through its lineage; a coupon dock as the section menu |

Each was built by one design agent, graded by a separate design-review agent against the requirements, the page brief
and the project facts, and fixed once. The fixes are checked only by the designer's own screenshots; no page has had a
second review.

## Reference: Mockups 1 to 7 (built 2026-10-15 and 2026-10-16)

| # | Name | What the second batch kept from it |
|---|---|---|
| 1 | A Day in the Park | the page structure, story progression, look and the scroll-driven board-meeting chart |
| 2 | Night Park Control Room | the idea of a button that makes the pipeline diagram act |
| 3 | Retro Window | the Business Insights section and the two-chart Pricing section |
| 4 | Park Map | the rules-first Theme Park Enterprise section and the left-to-right pipeline diagram |
| 5 | Blueprint | nothing; its look was rejected |
| 6 | Quiet Ledger | nothing; judged too plain |
| 7 | Pricing Lab | the price probe slider |

## Where the files live

The finished pages sit in an untracked `mockups/` folder of the main checkout (Mockup 18 is
`mockups/mockup-18-v1-sections.html`); the design kit and each mockup's progress notes are kept in the project owner's
notes. The site page takes its design from a frozen copy of Mockup 19 (Mockup 18 with the RCT exact palette) but no value from it: no mockup file is committed, the
illustrative numbers are not carried over, every figure comes from the marts or shows "figure pending", and the page
stays offline, with system fonts, no animation library and zero network requests (ADR 0043).

## Design checks learned

These checks come from the page brief and the second batch's fix rounds, and they also apply to the real site build.

1. Hold the layout at in-between widths (1366, 1280, 1100, 1024 and 820 px), not only at desktop and phone.
2. Never draw a mark for a value that is not in the data; show an empty, labelled slot instead.
3. Give every colour code a visible legend in its panel, and keep one meaning per colour across the page.
4. Give each chart's screen-reader label a one-sentence data summary.
5. Meet contrast without exceptions: never dim text with transparency, put a backing behind text over pictures or
   hatching, and reach at least 3:1 for chart segments and control borders.
6. Never disable a control a reader needs, and never let a sticky panel cover a focused element.
7. Keep chart text at least 11 px on phones, keep tap targets apart, thin out bar labels, and keep a scrolling table's
   key column in view.
8. Stop animation races before each new chart state, and check that bars land on zero after fast switching.
9. Break long model names only at `__`.
10. Size each chart from its own box, not its padded parent, and leave room for value labels.
11. Wire hover and focus handlers only after their elements exist, and re-measure a hidden panel when it is shown.
12. Cap the width of a phone table's sticky key column so the other columns can scroll into view.
13. Stop aspect-ratio boxes in grid cells from spilling sideways.
14. Draw the architecture as it is: marts, then site export, then the page; publishing is a separate path outside
    `make check` that the page never reads.
15. Make `hidden` actually hide, and test every empty state by switching filters back and forth.
16. Use no sticky figure below 1024 px; on phones, give each story step its own chart that changes from the previous
    step's state as it scrolls into view.
17. Show a scrolling table's right-edge fade only while more columns sit to the right.
18. Give every focus ring at least 3:1 against what it sits on, including on a selected or filled control.
19. Keep a diagram and the control that changes it on one screen, so the reader sees the change happen.
20. Check colour contrast where each colour is actually used, including mixed shades and neighbouring chart series,
    not only the seed colours in the abstract.

## What is left

- **The brand brief (NEXT 26).** Record the type scale, tone and design tokens of Mockup 18 with the RCT exact palette
  (above), and design its dark mode.
- **Real-phone checks** (iPhone Safari and a mid-range Android phone) of Mockup 18, with the phone-layout work after
  v1: scrolling, the fixed backgrounds, the section menu and the sliders cannot be judged in a desktop browser.
