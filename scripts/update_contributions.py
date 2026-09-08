#!/usr/bin/env python3
"""Refresh the GitHub contribution total shown on the portfolio hero.

Writes data/github.json (read by the page at runtime) and updates the
fallback baked into index.html, so the tile is still correct when the
fetch is blocked or the file is missing.

Prefers GitHub's own GraphQL API when a token is present, and falls back
to a public unauthenticated endpoint. Exits 0 without changes if neither
source answers, so a transient outage never fails the workflow.
"""
import json
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import date

USER = "praveenkumar-ponnugupati"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JSON_PATH = os.path.join(ROOT, "data", "github.json")
HTML_PATH = os.path.join(ROOT, "index.html")


def request(url, data=None, headers=None):
    req = urllib.request.Request(url, data=data, headers=headers or {})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def from_graphql(token):
    query = (
        '{ user(login: "%s") { contributionsCollection '
        "{ contributionCalendar { totalContributions } } } }" % USER
    )
    payload = json.dumps({"query": query}).encode()
    body = request(
        "https://api.github.com/graphql",
        data=payload,
        headers={
            "Authorization": "bearer " + token,
            "Content-Type": "application/json",
            "User-Agent": USER + "-portfolio",
        },
    )
    if body.get("errors"):
        raise RuntimeError(body["errors"][0].get("message", "GraphQL error"))
    return int(
        body["data"]["user"]["contributionsCollection"]["contributionCalendar"][
            "totalContributions"
        ]
    )


def from_public_api():
    body = request(
        "https://github-contributions-api.jogruber.de/v4/%s?y=last" % USER,
        headers={"User-Agent": USER + "-portfolio"},
    )
    return int(body["total"]["lastYear"])


def resolve_total():
    token = os.environ.get("GITHUB_TOKEN", "")
    sources = []
    if token:
        sources.append(("GraphQL", lambda: from_graphql(token)))
    sources.append(("public API", from_public_api))
    for name, fetch in sources:
        try:
            total = fetch()
        except (urllib.error.URLError, OSError, KeyError, ValueError, RuntimeError) as exc:
            print("%s failed: %s" % (name, exc), file=sys.stderr)
            continue
        if total > 0:
            print("%s reported %d contributions" % (name, total))
            return total
        print("%s reported 0, ignoring" % name, file=sys.stderr)
    return None


def main():
    total = resolve_total()
    if total is None:
        print("No source available, leaving the committed value alone.")
        return 0

    with open(JSON_PATH, "w", encoding="utf-8") as fh:
        json.dump(
            {
                "contributions": total,
                "window": "last 365 days",
                "updated": date.today().isoformat(),
            },
            fh,
            indent=2,
        )
        fh.write("\n")

    # Keep the no-JavaScript fallback in the markup in step with the JSON
    with open(HTML_PATH, encoding="utf-8") as fh:
        html = fh.read()
    pattern = re.compile(r'(id="gh-contrib" data-to=")\d+(")')
    if not pattern.search(html):
        print("Could not find the gh-contrib fallback in index.html", file=sys.stderr)
        return 1
    updated = pattern.sub(r"\g<1>%d\g<2>" % total, html)
    if updated != html:
        with open(HTML_PATH, "w", encoding="utf-8") as fh:
            fh.write(updated)
    return 0


if __name__ == "__main__":
    sys.exit(main())
