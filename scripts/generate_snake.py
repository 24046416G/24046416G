#!/usr/bin/env python3
"""Generate an animated, contribution-driven snake SVG for a GitHub profile."""

from __future__ import annotations

import argparse
from datetime import date, timedelta
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import quote
from urllib.request import Request, urlopen


CELL_SIZE = 16
DOT_SIZE = 12
INITIAL_LENGTH = 4
DURATION_MS = 37_000
PLAY_END = 98.0
FADE_START = 98.5
FADE_END = 99.3
RESET_END = 100.0
FRAME_EPSILON = 0.02

LIGHT_PALETTE = {
    "snake": "purple",
    "empty": "#ebedf0",
    "border": "#1b1f231a",
    "levels": {1: "#9be9a8", 2: "#40c463", 3: "#30a14e", 4: "#216e39"},
}

DARK_PALETTE = {
    "snake": "purple",
    "empty": "#161b22",
    "border": "#ffffff1a",
    "levels": {1: "#0e4429", 2: "#006d32", 3: "#26a641", 4: "#39d353"},
}


class ContributionParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.days: dict[date, int] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "td":
            return

        values = dict(attrs)
        date_value = values.get("data-date")
        level_value = values.get("data-level")
        if date_value is None or level_value is None:
            return

        try:
            day = date.fromisoformat(date_value)
            level = int(level_value)
        except (TypeError, ValueError):
            return

        if 0 <= level <= 4:
            self.days[day] = level


def fetch_contributions(username: str) -> tuple[dict[tuple[int, int], int], int]:
    url = f"https://github.com/users/{quote(username, safe='')}/contributions"
    request = Request(url, headers={"User-Agent": "profile-contribution-snake/1.0"})
    with urlopen(request, timeout=30) as response:
        html = response.read().decode("utf-8")

    parser = ContributionParser()
    parser.feed(html)
    if not parser.days:
        raise RuntimeError("GitHub returned no contribution cells for this profile")

    first_day = min(parser.days)
    last_day = max(parser.days)
    calendar_start = first_day - timedelta(days=(first_day.weekday() + 1) % 7)
    columns = (last_day - calendar_start).days // 7 + 1

    cells: dict[tuple[int, int], int] = {}
    for day, level in parser.days.items():
        day_offset = (day - calendar_start).days
        cells[(day_offset // 7, (day.weekday() + 1) % 7)] = level

    return cells, columns


def make_snake_path(columns: int) -> tuple[list[tuple[int, int]], dict[tuple[int, int], int]]:
    # Start with three body cells behind the head so the snake is already four cells long.
    start_x = min(INITIAL_LENGTH - 1, columns - 1)
    path = [(x, 0) for x in range(start_x, columns)]

    for y in range(1, 7):
        xs = range(columns - 1, -1, -1) if y % 2 else range(columns)
        path.extend((x, y) for x in xs)

    indexes = {point: index for index, point in enumerate(path)}
    for x in range(start_x):
        indexes[(x, 0)] = x - start_x

    return path, indexes


def pct(value: float) -> str:
    return f"{value:.4f}%"


def build_svg(
    cells: dict[tuple[int, int], int], columns: int, palette: dict[str, object]
) -> str:
    path, path_indexes = make_snake_path(columns)
    steps = len(path)
    levels = palette["levels"]
    empty_color = palette["empty"]
    snake_color = palette["snake"]
    border_color = palette["border"]

    initial_food = sum(
        1
        for point, index in path_indexes.items()
        if index < 0 and cells.get(point, 0) > 0
    )
    length = INITIAL_LENGTH + initial_food
    tail_indexes: list[int] = []
    for step, point in enumerate(path):
        if cells.get(point, 0) > 0:
            length += 1
        tail_indexes.append(step - length + 1)

    styles = [
        ":root{"
        f"--cs:{snake_color};--ce:{empty_color};--cb:{border_color};"
        + ";".join(f"--c{level}:{color}" for level, color in levels.items())
        + "}",
        f".cell{{fill:var(--ce);stroke:var(--cb);stroke-width:1px;width:{DOT_SIZE}px;height:{DOT_SIZE}px}}",
        ".body{fill:var(--cs);opacity:0}",
        f".head{{fill:var(--cs);opacity:1;animation:head {DURATION_MS}ms linear infinite}}",
    ]

    grid_elements: list[str] = []
    body_elements: list[str] = []
    for y in range(7):
        for x in range(columns):
            point = (x, y)
            index = path_indexes[point]
            level = cells.get(point, 0)
            cell_class = f"cell cell-{x}-{y}"
            grid_elements.append(
                f'<rect class="{cell_class}" x="{x * CELL_SIZE + 2}" '
                f'y="{y * CELL_SIZE + 2}" width="{DOT_SIZE}" height="{DOT_SIZE}" '
                'rx="2" ry="2"/>'
            )

            if level > 0:
                color_var = f"var(--c{level})"
                eat_step = max(0, index)
                eat_at = eat_step / steps * PLAY_END
                if eat_at <= FRAME_EPSILON:
                    eat_frames = (
                        f"0%{{fill:{color_var}}}"
                        f"{pct(FRAME_EPSILON)}{{fill:var(--ce)}}"
                    )
                else:
                    eat_frames = (
                        f"0%,{pct(eat_at - FRAME_EPSILON)}{{fill:{color_var}}}"
                        f"{pct(eat_at + FRAME_EPSILON)}{{fill:var(--ce)}}"
                    )
                styles.append(
                    f"@keyframes eat-{x}-{y}{{{eat_frames}"
                    f"{pct(RESET_END - FRAME_EPSILON)}{{fill:var(--ce)}}"
                    f"100%{{fill:{color_var}}}}}"
                    f".cell-{x}-{y}{{fill:{color_var};"
                    f"animation:eat-{x}-{y} {DURATION_MS}ms linear infinite}}"
                )

            enter_step = max(0, index)
            leave_step = next(
                (
                    step
                    for step in range(enter_step, steps)
                    if tail_indexes[step] > index
                ),
                steps,
            )
            enter_at = enter_step / steps * PLAY_END
            leave_at = min(leave_step / steps * PLAY_END, PLAY_END)

            body_frames: list[str] = []
            initially_visible = index <= 0
            body_frames.append(f"0%{{opacity:{1 if initially_visible else 0}}}")
            if not initially_visible:
                body_frames.append(f"{pct(max(0, enter_at - FRAME_EPSILON))}{{opacity:0}}")
                body_frames.append(f"{pct(min(enter_at + FRAME_EPSILON, leave_at))}{{opacity:1}}")

            if leave_step < steps:
                body_frames.append(f"{pct(max(enter_at, leave_at - FRAME_EPSILON))}{{opacity:1}}")
                body_frames.append(f"{pct(min(leave_at + FRAME_EPSILON, FADE_START))}{{opacity:0}}")
            else:
                body_frames.append(f"{pct(FADE_START)}{{opacity:1}}")
                body_frames.append(f"{pct(FADE_END)}{{opacity:0}}")

            body_frames.extend((f"{pct(RESET_END - FRAME_EPSILON)}{{opacity:0}}", "100%{opacity:0}"))
            styles.append(
                f"@keyframes body-{x}-{y}{{{''.join(body_frames)}}}"
                f".body-{x}-{y}{{animation:body-{x}-{y} {DURATION_MS}ms linear infinite}}"
            )
            body_elements.append(
                f'<rect class="body body-{x}-{y}" x="{x * CELL_SIZE + 2}" '
                f'y="{y * CELL_SIZE + 2}" width="{DOT_SIZE}" height="{DOT_SIZE}" '
                'rx="2" ry="2"/>'
            )

    head_frames = []
    for step, (x, y) in enumerate(path):
        time = step / steps * PLAY_END
        initial_state = ";opacity:1" if step == 0 else ""
        head_frames.append(
            f"{pct(time)}{{transform:translate({x * CELL_SIZE}px,{y * CELL_SIZE}px)"
            f"{initial_state}}}"
        )
    last_x, last_y = path[-1]
    head_frames.extend(
        (
            f"{pct(FADE_START)}{{transform:translate({last_x * CELL_SIZE}px,{last_y * CELL_SIZE}px);opacity:1}}",
            f"{pct(FADE_END)}{{opacity:0}}",
            "100%{opacity:0}",
        )
    )
    styles.append(f"@keyframes head{{{''.join(head_frames)}}}")

    width = columns * CELL_SIZE + 32
    height = 192
    return (
        f'<svg viewBox="-16 -32 {width} {height}" width="{width}" height="{height}" '
        'xmlns="http://www.w3.org/2000/svg">'
        '<desc>Animated contribution snake. The snake grows as it eats contribution cells.</desc>'
        f'<style>{"".join(styles)}</style>'
        '<g>'
        f'{"".join(grid_elements)}'
        f'{"".join(body_elements)}'
        '<rect class="head" x="1" y="1" width="14" height="14" rx="4.5" ry="4.5"/>'
        '</g></svg>'
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--username", required=True)
    parser.add_argument("--output-dir", default="dist")
    args = parser.parse_args()

    cells, columns = fetch_contributions(args.username)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    (output_dir / "github-contribution-grid-snake.svg").write_text(
        build_svg(cells, columns, LIGHT_PALETTE), encoding="utf-8"
    )
    (output_dir / "github-contribution-grid-snake-dark.svg").write_text(
        build_svg(cells, columns, DARK_PALETTE), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
