# The analytics strategy

**The company must answer three business questions, summed up in one number: operating profit per company year.**

This file holds the words of the showcase page's board meeting and Business insights desk. The page build renders each passage below in place, so these words are edited here, never in the page templates. A passage starts at its `passage` marker and runs to the next one, so each section opens with a marker of its own that holds only the section heading.

## Three questions

1. **Which rides earn their place?** With entry free, rides and stalls bring in the money, so profit by ride type and price decides what to build and charge.
2. **What does weather do to umbrella sales?** Its effect on sales shows what a rainy month is worth.
3. **Where does money come from and go?** A monthly profit and loss statement, checked against the game's books, shows which parks carry the company.

## The one number

Operating profit: income from rides and stalls minus running costs, in dollars per company year (a year on the company calendar: one game season, March to October).

<!-- passage: section-board-meeting -->
## The board meeting

<!-- passage: story-title -->
The board meeting

<!-- passage: story-lead -->
The chart follows the story one company year at a time.

<!-- passage: story-rules -->
The business rules, in one line: entry is free and rides and stalls charge, parks are built one at a time while finished parks run on autopilot, and guests never come back.

<!-- passage: step-1-title -->
What we built

<!-- passage: step-1-note -->
A park's first month has no earlier statement to compare with. Observational; sample: the park that opened first in the exports.

<!-- passage: step-2-title -->
What the money did

<!-- passage: step-2-note -->
Observational; sample: the closed company years in the exports.

<!-- passage: step-3-title -->
What we learned

<!-- passage: step-3-note -->
Like-for-like counts only parks with a full prior year. Observational; sample: figure pending.

<!-- passage: step-4-title -->
Which rides earn their place

<!-- passage: step-4-guide -->
With entry free, rides and stalls bring in the money. Compare ride profit by type, then investigate prices and costs before choosing the next ride.

<!-- passage: step-4-note -->
The ride profit report arrives after v1, in v1.1. The columns already exist in the warehouse.

<!-- passage: step-5-title -->
What we do next

<!-- passage: step-5-body -->
Ride profit by type, then the pricing model, both after v1. Until then, Business Insights below opens three views of the same warehouse.

<!-- passage: step-5-note -->
The real company starts after the site's first release.

<!-- passage: section-insights -->
## Business insights

<!-- passage: insights-title -->
Business insights: the park company by department

<!-- passage: insights-lead -->
I run the park as a company and read it the way three departments of a real operator would. Each panel opens with a note I write at each update: what changed, why, and what I'll watch next. Causes come only from what the data records (weather, days open, price changes, breakdowns and new rides), and the patterns are observational: they show a link, not proof of cause.

<!-- passage: ops-availability-desc -->
The share of operating time each ride was running; operations teams read it every morning to decide which rides need attention first.

<!-- passage: ops-waits-desc -->
Peak wait in minutes; the game does not record average waits.

<!-- passage: ops-riders-desc -->
Throughput: the riders each ride carried.

<!-- passage: ops-gap -->
Time between failures: the game does not record it. Time to repair: the game does not record it. Hourly ride capacity: the game does not record it. Staff hours: the game does not record it.

<!-- passage: riders-note -->
Riders: the game counts a guest on leaving the ride, and also counts each on-ride photo sold.

<!-- passage: attr-lead -->
Rides are the park's product features: riders are usage, guest rating is satisfaction, and ride age signals when to refresh, the same calls an attractions team makes.

<!-- passage: attr-rating-desc -->
Busy rides with low ratings are the first place to look.

<!-- passage: attr-age-desc -->
Game months since each ride was built, with its latest rating.

<!-- passage: attr-later -->
The ride profit and popularity reports arrive in v1.1, the next release. The season range does not apply to rides; the park switch does.

<!-- passage: attr-scatter-desc -->
Observational; sample: figure pending. A pattern here is not a cause.

<!-- passage: fin-profit-desc -->
Revenue minus running costs, before loan interest: the park-level figure operators such as Six Flags report as EBITDA (earnings before interest, taxes, depreciation and amortization).

<!-- passage: fin-visits-desc -->
Visits work like daily and monthly active users (DAU and MAU) in software; per-capita spending is revenue per visit, split into rides, food and merchandise.

<!-- passage: fin-price-desc -->
Each price change I made, against that ride's riders per day. Observational: weather and days open also move riders.

<!-- passage: fin-price-cap -->
Observational: a link, not proof of cause.

<!-- passage: fin-stalls-cap -->
Item names wait for the item rules in the warehouse. Stall profit per single-item stall is in v1.

<!-- passage: fin-mix-cap -->
Entry is free under pay per ride, so entrance revenue is $0.00. On-ride photos sit in merchandise.

<!-- passage: fin-gap -->
Profit after depreciation and tax: the game does not record it. Admission price: not shown; entry is free on the captured parks, which charge per ride.
