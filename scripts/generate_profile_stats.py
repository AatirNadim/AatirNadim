#!/usr/bin/env python3
"""Fetch GitHub profile stats and render palette-matched SVG cards."""

from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import os
import random
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"
ASSETS = ROOT / "assets" / "stats"
USERNAME = "AatirNadim"

# Colors sampled from gifs/default.gif: deep navy, blue, cyan, purple, and pink.
BG = "#090d1d"
PANEL = "#131127"
PANEL_ALT = "#1d1f3f"
TEXT = "#e5e8f4"
MUTED = "#9ba8c6"
CYAN = "#44aab5"
BLUE = "#3074a2"
PURPLE = "#80509b"
PINK = "#de5b99"
GREEN = "#44aa82"
PALETTE = [CYAN, BLUE, PURPLE, PINK, GREEN]

QUOTES = [
    ("Simplicity is prerequisite for reliability.", "Edsger W. Dijkstra", "EWD 498"),
    (
        "The hardest single part of building a software system is deciding precisely what to build.",
        "Fred Brooks",
        "The Mythical Man-Month",
    ),
    (
        "The most dangerous phrase in the language is, 'We've always done it this way.'",
        "Grace Hopper",
        "Commonly attributed",
    ),
    (
        "Programs must be written for people to read, and only incidentally for machines to execute.",
        "Harold Abelson & Gerald Jay Sussman",
        "Structure and Interpretation of Computer Programs",
    ),
    ("Simplicity does not precede complexity, but follows it.", "Alan J. Perlis", "Epigrams on Programming"),
]


def request_json(url: str, token: str, *, method: str = "GET", payload: dict[str, Any] | None = None) -> Any:
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    req.add_header("User-Agent", "profile-readme-stats")
    if payload is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        # Avoid echoing API response bodies: they can contain private resource names.
        raise RuntimeError(f"GitHub API returned HTTP {exc.code}; check token permissions and API availability.") from exc


def fetch_all_repos(token: str) -> list[dict[str, Any]]:
    repos: list[dict[str, Any]] = []
    page = 1
    while True:
        query = urllib.parse.urlencode(
            {
                "visibility": "all",
                "affiliation": "owner",
                "sort": "updated",
                "per_page": 100,
                "page": page,
            }
        )
        batch = request_json(f"https://api.github.com/user/repos?{query}", token)
        repos.extend(batch)
        if len(batch) < 100:
            break
        page += 1
    return repos


def fetch_public_repos(username: str, token: str) -> list[dict[str, Any]]:
    repos: list[dict[str, Any]] = []
    page = 1
    while True:
        query = urllib.parse.urlencode(
            {"type": "owner", "sort": "pushed", "direction": "desc", "per_page": 100, "page": page}
        )
        batch = request_json(f"https://api.github.com/users/{urllib.parse.quote(username)}/repos?{query}", token)
        repos.extend(batch)
        if len(batch) < 100:
            break
        page += 1
    return repos


def fetch_languages(repo: dict[str, Any], token: str) -> dict[str, int]:
    return request_json(repo["languages_url"], token)


def fetch_contributions(username: str, token: str) -> dict[str, Any]:
    end = dt.datetime.now(dt.timezone.utc).replace(hour=23, minute=59, second=59, microsecond=0)
    start = end - dt.timedelta(days=364)
    query = """
    query($login: String!, $from: DateTime!, $to: DateTime!) {
      user(login: $login) {
        contributionsCollection(from: $from, to: $to) {
          totalCommitContributions
          totalIssueContributions
          totalPullRequestContributions
          totalRepositoryContributions
          contributionCalendar {
            totalContributions
            weeks {
              contributionDays { date contributionCount contributionLevel }
            }
          }
        }
      }
    }
    """
    result = request_json(
        "https://api.github.com/graphql",
        token,
        method="POST",
        payload={
            "query": query,
            "variables": {
                "login": username,
                "from": start.isoformat().replace("+00:00", "Z"),
                "to": end.isoformat().replace("+00:00", "Z"),
            },
        },
    )
    if result.get("errors"):
        raise RuntimeError("GitHub GraphQL query failed; check GH_STATS_TOKEN permissions and private contribution settings.")
    user = result.get("data", {}).get("user")
    if not user:
        raise RuntimeError(f"GitHub user {username!r} was not found")
    return user["contributionsCollection"]


def current_streak(days: list[dict[str, Any]]) -> int:
    days = list(days)
    today = dt.datetime.now(dt.timezone.utc).date().isoformat()
    if days and days[-1].get("date") == today and days[-1].get("contributionCount", 0) == 0:
        days.pop()
    count = 0
    for day in reversed(days):
        if day.get("contributionCount", 0) <= 0:
            break
        count += 1
    return count


def ellipsize(value: str, max_chars: int) -> str:
    value = re.sub(r"\s+", " ", value).strip()
    return value if len(value) <= max_chars else value[: max_chars - 1].rstrip() + "…"


def esc(value: Any) -> str:
    return html.escape(str(value), quote=True)


def svg_document(width: int, height: int, title: str, body: str, description: str) -> str:
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-labelledby="title desc">
  <title id="title">{esc(title)}</title>
  <desc id="desc">{esc(description)}</desc>
  <rect width="{width}" height="{height}" rx="18" fill="{BG}"/>
  <rect x="1" y="1" width="{width - 2}" height="{height - 2}" rx="17" fill="none" stroke="{PANEL_ALT}"/>
  {body}
</svg>
'''


def svg_text(x: int, y: int, value: str, *, size: int = 14, color: str = TEXT, weight: int = 400) -> str:
    return f'<text x="{x}" y="{y}" fill="{color}" font-family="ui-monospace, SFMono-Regular, Menlo, Consolas, monospace" font-size="{size}px" font-weight="{weight}">{esc(value)}</text>'


def overview_svg(stats: dict[str, Any]) -> str:
    cells = [
        ("YEARLY CONTRIBUTIONS", f"{stats['contributions']:,}", CYAN),
        ("COMMITS", f"{stats['commits']:,}", BLUE),
        ("PULL REQUESTS", f"{stats['pull_requests']:,}", PINK),
        ("ISSUES", f"{stats['issues']:,}", PURPLE),
        ("REPOSITORIES", f"{stats['repositories']:,}", PURPLE),
        ("STARS EARNED", f"{stats['stars']:,}", PINK),
        ("FOLLOWERS", f"{stats['followers']:,}", BLUE),
        ("PRIVATE REPOS", f"{stats['private_repositories']:,}", GREEN),
    ]
    body = [svg_text(26, 30, "GITHUB / SYSTEM SNAPSHOT", size=12, color=MUTED, weight=700)]
    for i, (label, value, accent) in enumerate(cells):
        col, row = i % 4, i // 4
        x, y = 24 + col * 170, 45 + row * 91
        body.append(f'<rect x="{x}" y="{y}" width="158" height="78" rx="12" fill="{PANEL}"/>')
        body.append(f'<rect x="{x}" y="{y}" width="3" height="78" rx="1.5" fill="{accent}"/>')
        body.append(svg_text(x + 12, y + 23, label, size=8, color=MUTED, weight=700))
        body.append(svg_text(x + 12, y + 57, value, size=23, color=TEXT, weight=700))
    return svg_document(720, 244, "GitHub profile overview", "\n  ".join(body), "Yearly contributions, commits, pull requests, issues, total accessible repositories, stars, followers, and private repository count. Private repository names are not shown.")


def activity_svg(stats: dict[str, Any]) -> str:
    days = [day for week in stats["weeks"] for day in week]
    # GitHub returns 52 or 53 aligned weeks. The chart keeps the newest 53 columns.
    days = days[-371:]
    if len(days) % 7:
        days = ([None] * (7 - len(days) % 7)) + days
    columns = [days[i : i + 7] for i in range(0, len(days), 7)]
    body = [svg_text(24, 32, "CONTRIBUTION PULSE / LAST 12 MONTHS", size=12, color=MUTED, weight=700)]
    x0, y0, cell, gap = 24, 50, 9, 3
    level_colors = {"NONE": PANEL, "FIRST_QUARTILE": "#23304b", "SECOND_QUARTILE": BLUE, "THIRD_QUARTILE": PURPLE, "FOURTH_QUARTILE": PINK}
    for col, week in enumerate(columns):
        for row, day in enumerate(week[:7]):
            level = (day or {}).get("contributionLevel", "NONE")
            color = level_colors.get(level, PANEL)
            x, y = x0 + col * (cell + gap), y0 + row * (cell + gap)
            body.append(f'<rect x="{x}" y="{y}" width="{cell}" height="{cell}" rx="2" fill="{color}"/>')
    streak = stats["streak"]
    body.append(svg_text(24, 142, f"{stats['contributions']:,} contributions this year", size=12, color=TEXT, weight=700))
    body.append(svg_text(24, 162, f"{streak} day current streak", size=11, color=CYAN))
    body.append(svg_text(520, 162, "LOW  ·  MEDIUM  ·  HIGH", size=9, color=MUTED))
    return svg_document(720, 180, "Contribution activity heatmap", "\n  ".join(body), "A 12-month GitHub contribution heatmap, including private contributions where GitHub exposes aggregate contribution counts.")


def languages_svg(stats: dict[str, Any]) -> str:
    all_languages = sorted(stats["languages"].items(), key=lambda pair: pair[1], reverse=True)
    languages = all_languages[:5]
    total = sum(stats["languages"].values())
    other_bytes = total - sum(value for _, value in languages)
    if other_bytes:
        languages.append(("Other", other_bytes))
    body = [svg_text(24, 34, "LANGUAGE MIX / ALL ACCESSIBLE REPOSITORIES", size=12, color=MUTED, weight=700)]
    if not languages or not total:
        body.append(svg_text(24, 100, "Language data will appear after the first successful sync.", color=MUTED))
    else:
        bar_x, bar_y, bar_w = 24, 55, 672
        widths = [max(3, round(bar_w * value / total)) for _, value in languages]
        overflow = sum(widths) - bar_w
        if overflow > 0:
            widths[widths.index(max(widths))] -= overflow
        cursor = bar_x
        for index, width in enumerate(widths):
            body.append(f'<rect x="{cursor}" y="{bar_y}" width="{width}" height="10" fill="{PALETTE[index % len(PALETTE)]}"/>')
            cursor += width
        for index, (name, value) in enumerate(languages):
            col, row = index % 3, index // 3
            x, y = 24 + col * 224, 98 + row * 58
            percent = value / total * 100
            body.append(f'<circle cx="{x + 5}" cy="{y - 5}" r="5" fill="{PALETTE[index % len(PALETTE)]}"/>')
            body.append(svg_text(x + 18, y, name, size=13, weight=700))
            body.append(svg_text(x + 18, y + 20, f"{percent:.1f}%", size=11, color=MUTED))
    return svg_document(720, 190, "Programming language mix", "\n  ".join(body), "A language distribution bar aggregated across accessible repositories. Individual private repository names and language breakdowns are not published.")


def quote_svg(quote: tuple[str, str, str]) -> str:
    text, author, source = quote
    # Split text into up to two lines without letting long prose overflow the SVG card.
    words = text.split()
    lines: list[str] = []
    line = ""
    for word in words:
        candidate = f"{line} {word}".strip()
        if len(candidate) > 62 and line:
            lines.append(line)
            line = word
        else:
            line = candidate
    if line:
        lines.append(line)
    lines = lines[:2]
    body = [
        '<path d="M26 42h26" stroke="' + PINK + '" stroke-width="3" stroke-linecap="round"/>',
        svg_text(24, 70, "FIELD NOTE / RANDOM QUOTE", size=11, color=MUTED, weight=700),
    ]
    for i, line in enumerate(lines):
        body.append(svg_text(24, 108 + i * 25, f'“{line}”', size=15, color=TEXT, weight=500))
    body.append(svg_text(24, 166, f"— {author}  ·  {source}", size=11, color=CYAN))
    return svg_document(720, 188, "Random quote", "\n  ".join(body), f"A randomly selected software engineering quote by {author}, from {source}.")


def recent_projects_markdown(repos: list[dict[str, Any]], username: str) -> str:
    profile_repo = username.casefold()
    projects = [
        repo
        for repo in repos
        if not repo.get("fork")
        and not repo.get("archived")
        and not repo.get("disabled")
        and repo.get("full_name", "").casefold() != f"{profile_repo}/{profile_repo}"
    ]
    projects.sort(key=lambda repo: repo.get("pushed_at") or "", reverse=True)
    projects = projects[:3]
    if not projects:
        return "_No recent public projects found yet._"
    rows = ["| Project | What it does | Stack | Stars |", "|:--|:--|:--|--:|"]
    for repo in projects:
        # This list comes from the public /users/{login}/repos endpoint by design.
        name = re.sub(r"([\\|\[\]])", r"\\\1", repo.get("name", "Repository"))
        url = repo.get("html_url", f"https://github.com/{username}")
        url = url.replace("(", "%28").replace(")", "%29").replace(" ", "%20")
        description = ellipsize(repo.get("description") or "A recent project.", 80).replace("|", "\\|")
        language = repo.get("language") or "—"
        stars = repo.get("stargazers_count", 0)
        rows.append(f"| [{name}]({url}) | {description} | {language} | {stars:,} |")
    return "\n".join(rows)


def update_readme(projects: str, updated_at: str) -> None:
    text = README.read_text(encoding="utf-8")
    start, end = "<!-- recent-projects:start -->", "<!-- recent-projects:end -->"
    pattern = re.compile(re.escape(start) + r".*?" + re.escape(end), re.S)
    replacement = f"{start}\n{projects}\n{end}"
    if not pattern.search(text):
        raise RuntimeError("README is missing recent-projects markers")
    text = pattern.sub(lambda _: replacement, text, count=1)
    date_start, date_end = "<!-- stats-updated:start -->", "<!-- stats-updated:end -->"
    date_pattern = re.compile(re.escape(date_start) + r".*?" + re.escape(date_end), re.S)
    if not date_pattern.search(text):
        raise RuntimeError("README is missing stats-updated markers")
    text = date_pattern.sub(f"{date_start}_Stats last synced: {updated_at} UTC._{date_end}", text, count=1)
    README.write_text(text, encoding="utf-8")


def collect_stats(username: str, stats_token: str, contributions_token: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    repos = fetch_all_repos(stats_token)
    public_repos = fetch_public_repos(username, stats_token)
    contributions = fetch_contributions(username, contributions_token)
    all_days = [day for week in contributions["contributionCalendar"]["weeks"] for day in week["contributionDays"]]

    languages: Counter[str] = Counter()
    repos_for_languages = [repo for repo in repos if not repo.get("fork") and not repo.get("archived") and not repo.get("disabled")]
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = {pool.submit(fetch_languages, repo, stats_token): repo for repo in repos_for_languages}
        for future in as_completed(futures):
            repo = futures[future]
            try:
                languages.update(future.result())
            except RuntimeError:
                raise
            except Exception as exc:  # preserve an accurate chart instead of silently omitting a repo
                raise RuntimeError("Could not fetch language totals; check GH_STATS_TOKEN access to the selected repositories.") from exc

    private_repositories = sum(1 for repo in repos if repo.get("private"))
    stats = {
        "contributions": contributions["contributionCalendar"]["totalContributions"],
        "commits": contributions["totalCommitContributions"],
        "issues": contributions["totalIssueContributions"],
        "pull_requests": contributions["totalPullRequestContributions"],
        "repositories_created": contributions["totalRepositoryContributions"],
        "repositories": len(repos),
        "private_repositories": private_repositories,
        "stars": sum(repo.get("stargazers_count", 0) for repo in repos),
        "followers": request_json(f"https://api.github.com/users/{urllib.parse.quote(username)}", stats_token)["followers"],
        "languages": dict(languages),
        "weeks": [week["contributionDays"] for week in contributions["contributionCalendar"]["weeks"]],
        "streak": current_streak(all_days),
        "updated_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M"),
    }
    return stats, public_repos


def write_assets(stats: dict[str, Any]) -> None:
    ASSETS.mkdir(parents=True, exist_ok=True)
    (ASSETS / "overview.svg").write_text(overview_svg(stats), encoding="utf-8")
    (ASSETS / "activity.svg").write_text(activity_svg(stats), encoding="utf-8")
    (ASSETS / "languages.svg").write_text(languages_svg(stats), encoding="utf-8")
    (ASSETS / "quote.svg").write_text(quote_svg(random.choice(QUOTES)), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--username", default=os.environ.get("GH_USERNAME", USERNAME))
    args = parser.parse_args()
    stats_token = os.environ.get("GH_STATS_TOKEN", "")
    contributions_token = os.environ.get("GH_CONTRIBUTIONS_TOKEN", "")
    if not stats_token or not contributions_token:
        parser.error("Set GH_STATS_TOKEN and GH_CONTRIBUTIONS_TOKEN; see docs/profile-stats-setup.md.")
    try:
        stats, public_repos = collect_stats(args.username, stats_token, contributions_token)
        write_assets(stats)
        update_readme(recent_projects_markdown(public_repos, args.username), stats["updated_at"])
    except Exception as exc:
        print(f"stats generation failed: {exc}", file=sys.stderr)
        return 1
    print(f"Generated aggregate stats for {args.username}; private repository names were not written to disk.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
