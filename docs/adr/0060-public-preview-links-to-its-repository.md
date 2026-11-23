# ADR 0060: the public preview may link to its own repository and its author

- Date: 2026-11-22.
- Status: Accepted 2026-11-22 (the project owner approved the narrow gate change). It adds the one
  exception to the page rule that ADR 0043 and ADR 0047 describe; it edits no other record.

## Bottom line

The showcase page and the player guide may carry an `<a href>` to `https://github.com/jcabiles`, to
`https://github.com/jcabiles/openrct2-analytics` or to a file under
`https://github.com/jcabiles/openrct2-analytics/blob/main/`. Every other `src`, every `href` on another
element and every other host stays refused. The page still loads nothing from another host.

## Context

The public preview needs links to its repository, its author's profile and the review record. The page check
(`check_page`, `check_guide`) refused every `src` or `href` that starts with `http:`, `https:`, `//` or `/`, so
those links could not be built. ADR 0047 expected such an exception for video links and left the allowlist to
the build that needed it.

## Decision

One shared allowlist, `is_public_link` in `src/openrct2_analytics/showcase/page_check_site.py`, is used by both
checkers. A value passes only when it is on an `<a>` element's `href` and equals one of the two public URLs
exactly, or starts with the `blob/main/` URL and its path after `blob/main/` is not empty and holds no `%` (a browser decodes `%2e%2e` to `..`)
and no `.` or `..` segment. Matching is exact: no trimming, no case
folding, no `http:` or protocol-relative form.

## Consequences

- Gain: the preview can link out to its repository and review record with the page check still green.
- Cost: a link to another host (a video site, say) still needs its own amendment; the rule that module
  string literals hold no remote URL is unchanged.
