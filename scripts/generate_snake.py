#!/usr/bin/env python3
"""Generate an animated, contribution-driven snake SVG for a GitHub profile."""

from __future__ import annotations

import argparse
from collections import deque
from datetime import date, timedelta
from hashlib import sha256
from html.parser import HTMLParser
from pathlib import Path
import random
from urllib.parse import quote
from urllib.request import Request, urlopen


CELL_SIZE = 16
DOT_SIZE = 12
INITIAL_LENGTH = 4
FOODS_PER_GROWTH = 3
DURATION_MS = 37_000
PLAY_END = 98.0
FADE_START = 98.5
FADE_END = 99.3
RESET_END = 100.0
FRAME_EPSILON = 0.02
ROWS = 7
TARGET_POOL_SIZE = 8

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


Point = tuple[int, int]


def _make_neighbor_map(columns: int, rng: random.Random) -> dict[Point, list[Point]]:
    directions = [(0, -1), (1, 0), (0, 1), (-1, 0)]
    neighbors: dict[Point, list[Point]] = {}
    for y in range(ROWS):
        for x in range(columns):
            order = directions.copy()
            rng.shuffle(order)
            neighbors[(x, y)] = [
                (x + dx, y + dy)
                for dx, dy in order
                if 0 <= x + dx < columns and 0 <= y + dy < ROWS
            ]
    return neighbors


def _initial_snake(columns: int, food: set[Point], rng: random.Random) -> deque[Point]:
    candidates: list[list[Point]] = []
    for y in range(ROWS):
        for x in range(columns - INITIAL_LENGTH + 1):
            line = [(x + offset, y) for offset in range(INITIAL_LENGTH)]
            candidates.extend((line, list(reversed(line))))
    for x in range(columns):
        for y in range(ROWS - INITIAL_LENGTH + 1):
            line = [(x, y + offset) for offset in range(INITIAL_LENGTH)]
            candidates.extend((line, list(reversed(line))))

    fewest_food = min(sum(point in food for point in line) for line in candidates)
    best_lines = [
        line for line in candidates
        if sum(point in food for point in line) == fewest_food
    ]
    return deque(rng.choice(best_lines))


def _breadth_first_search(
    start: Point, blocked: set[Point], neighbors: dict[Point, list[Point]]
) -> tuple[dict[Point, Point | None], dict[Point, int]]:
    parents: dict[Point, Point | None] = {start: None}
    distances = {start: 0}
    queue = deque([start])
    while queue:
        point = queue.popleft()
        for neighbor in neighbors[point]:
            if neighbor in blocked or neighbor in parents:
                continue
            parents[neighbor] = point
            distances[neighbor] = distances[point] + 1
            queue.append(neighbor)
    return parents, distances


def _first_step(target: Point, start: Point, parents: dict[Point, Point | None]) -> Point | None:
    point = target
    while parents.get(point) is not None and parents[point] != start:
        parent = parents[point]
        if parent is None:
            return None
        point = parent
    return point if point != start else None


def _has_exit(
    snake: deque[Point],
    remaining_food: set[Point],
    growth_progress: int,
    neighbors: dict[Point, list[Point]],
) -> bool:
    head = snake[-1]
    occupied = set(snake)
    tail = snake[0]
    for point in neighbors[head]:
        grows = point in remaining_food and growth_progress == FOODS_PER_GROWTH - 1
        if point not in occupied or (point == tail and not grows):
            return True
    return False


def _keeps_food_reachable(
    snake: deque[Point],
    remaining_food: set[Point],
    neighbors: dict[Point, list[Point]],
) -> bool:
    if not remaining_food:
        return True
    head = snake[-1]
    parents, _ = _breadth_first_search(head, set(snake) - {head}, neighbors)
    occupied = set(snake)
    return all(point in occupied or point in parents for point in remaining_food)


def _legal_moves(
    snake: deque[Point],
    remaining_food: set[Point],
    growth_progress: int,
    neighbors: dict[Point, list[Point]],
) -> list[Point]:
    legal: list[Point] = []
    safe: list[Point] = []
    occupied = set(snake)
    tail = snake[0]
    head = snake[-1]

    for point in neighbors[head]:
        eats = point in remaining_food
        grows = eats and growth_progress == FOODS_PER_GROWTH - 1
        if point in occupied and (point != tail or grows):
            continue
        legal.append(point)

        next_snake = deque(snake)
        next_remaining = remaining_food
        next_progress = growth_progress
        if eats:
            next_remaining = remaining_food - {point}
            next_progress = 0 if grows else growth_progress + 1
        if not grows:
            next_snake.popleft()
        next_snake.append(point)
        if _has_exit(next_snake, next_remaining, next_progress, neighbors) and _keeps_food_reachable(
            next_snake, next_remaining, neighbors
        ):
            safe.append(point)

    return safe or legal


def _random_move(
    snake: deque[Point],
    remaining_food: set[Point],
    growth_progress: int,
    neighbors: dict[Point, list[Point]],
    rng: random.Random,
) -> Point | None:
    options = _legal_moves(snake, remaining_food, growth_progress, neighbors)
    if not options:
        return None

    previous_direction = None
    if len(snake) > 1:
        previous_direction = (
            snake[-1][0] - snake[-2][0],
            snake[-1][1] - snake[-2][1],
        )

    weights = []
    for point in options:
        direction = (point[0] - snake[-1][0], point[1] - snake[-1][1])
        weights.append(1.0 if direction == previous_direction else 1.5)
    return rng.choices(options, weights=weights, k=1)[0]


def _choose_food_target(
    remaining_food: set[Point],
    snake: deque[Point],
    parents: dict[Point, Point | None],
    distances: dict[Point, int],
    rng: random.Random,
) -> Point | None:
    occupied = set(snake)
    reachable = sorted(
        (point for point in remaining_food if point not in occupied and point in parents),
        key=lambda point: (distances[point], point[1], point[0]),
    )
    if not reachable:
        return None
    return rng.choice(reachable[:TARGET_POOL_SIZE])


def make_snake_path(
    cells: dict[Point, int], columns: int
) -> tuple[list[Point], dict[Point, int], dict[Point, list[tuple[int, int]]], set[Point], set[Point]]:
    food = {point for point, level in cells.items() if level > 0}
    signature = ",".join(
        f"{x}:{y}:{level}"
        for x, y, level in sorted((x, y, level) for (x, y), level in cells.items() if level > 0)
    )
    seed = int.from_bytes(sha256(f"{columns}|{signature}".encode()).digest()[:8], "big")
    rng = random.Random(seed)
    neighbors = _make_neighbor_map(columns, rng)

    snake = _initial_snake(columns, food, rng)
    initial_body = set(list(snake)[:-1])
    body_started = {point: 0 for point in initial_body}
    body_intervals: dict[Point, list[tuple[int, int]]] = {}
    remaining_food = set(food)
    eaten_at: dict[Point, int] = {}
    growth_progress = 0

    if snake[-1] in remaining_food:
        remaining_food.remove(snake[-1])
        eaten_at[snake[-1]] = 0
        growth_progress = 1

    path = [snake[-1]]
    target: Point | None = None
    minimum_steps = columns * ROWS
    maximum_steps = minimum_steps * 2

    while (len(path) - 1 < minimum_steps or remaining_food) and len(path) - 1 < maximum_steps:
        head = snake[-1]
        parents, distances = _breadth_first_search(head, set(snake) - {head}, neighbors)

        if target not in remaining_food or target in snake or target not in parents:
            target = _choose_food_target(remaining_food, snake, parents, distances, rng)

        next_point = _first_step(target, head, parents) if target is not None else None
        safe_moves = _legal_moves(snake, remaining_food, growth_progress, neighbors)
        if next_point not in safe_moves:
            next_point = rng.choice(safe_moves) if safe_moves else None
            target = None
        if next_point is None:
            break

        step = len(path)
        eats = next_point in remaining_food
        grows = eats and growth_progress == FOODS_PER_GROWTH - 1
        if eats:
            remaining_food.remove(next_point)
            eaten_at[next_point] = step
            growth_progress = 0 if grows else growth_progress + 1

        if not grows:
            tail = snake.popleft()
            start = body_started.pop(tail, None)
            if start is not None:
                body_intervals.setdefault(tail, []).append((start, step))

        old_head = snake[-1]
        body_started[old_head] = step
        snake.append(next_point)
        path.append(next_point)

    if len(path) == 1:
        path.append(path[0])
    final_step = len(path) - 1
    for point, start in body_started.items():
        body_intervals.setdefault(point, []).append((start, final_step))

    return path, eaten_at, body_intervals, initial_body, set(list(snake)[:-1])


def pct(value: float) -> str:
    return f"{value:.4f}%"


def build_svg(
    cells: dict[tuple[int, int], int], columns: int, palette: dict[str, object]
) -> str:
    path, eaten_at, body_intervals, initial_body, final_body = make_snake_path(cells, columns)
    steps = max(1, len(path) - 1)
    duration_ms = max(DURATION_MS, steps * 75)
    step_pct = PLAY_END / steps
    epsilon = min(FRAME_EPSILON, step_pct / 4)
    levels = palette["levels"]
    empty_color = palette["empty"]
    snake_color = palette["snake"]
    border_color = palette["border"]

    styles = [
        ":root{"
        f"--cs:{snake_color};--ce:{empty_color};--cb:{border_color};"
        + ";".join(f"--c{level}:{color}" for level, color in levels.items())
        + "}",
        f".cell{{fill:var(--ce);stroke:var(--cb);stroke-width:1px;width:{DOT_SIZE}px;height:{DOT_SIZE}px}}",
        ".body{fill:var(--cs);opacity:0}",
        f".head{{fill:var(--cs);opacity:1;animation:head {duration_ms}ms linear infinite}}",
    ]

    grid_elements: list[str] = []
    body_elements: list[str] = []
    for y in range(ROWS):
        for x in range(columns):
            point = (x, y)
            level = cells.get(point, 0)
            cell_class = f"cell cell-{x}-{y}"
            grid_elements.append(
                f'<rect class="{cell_class}" x="{x * CELL_SIZE + 2}" '
                f'y="{y * CELL_SIZE + 2}" width="{DOT_SIZE}" height="{DOT_SIZE}" '
                'rx="2" ry="2"/>'
            )

            if level > 0 and point in eaten_at:
                color_var = f"var(--c{level})"
                eat_time = eaten_at[point] / steps * PLAY_END
                if eaten_at[point] == 0:
                    eat_frames = "0%{fill:var(--ce)}"
                else:
                    eat_frames = (
                        f"0%,{pct(max(0, eat_time - epsilon))}{{fill:{color_var}}}"
                        f"{pct(min(PLAY_END, eat_time + epsilon))}{{fill:var(--ce)}}"
                    )
                styles.append(
                    f"@keyframes eat-{x}-{y}{{{eat_frames}"
                    f"{pct(RESET_END - FRAME_EPSILON)}{{fill:var(--ce)}}"
                    f"100%{{fill:{color_var}}}}}"
                    f".cell-{x}-{y}{{fill:{color_var};animation:eat-{x}-{y} "
                    f"{duration_ms}ms linear infinite}}"
                )

            body_frames = [f"0%{{opacity:{1 if point in initial_body else 0}}}"]
            for start, end in body_intervals.get(point, []):
                if start > 0:
                    enter_time = start / steps * PLAY_END
                    body_frames.append(f"{pct(max(0, enter_time - epsilon))}{{opacity:0}}")
                    body_frames.append(f"{pct(min(PLAY_END, enter_time + epsilon))}{{opacity:1}}")
                if end < steps:
                    leave_time = end / steps * PLAY_END
                    body_frames.append(f"{pct(max(0, leave_time - epsilon))}{{opacity:1}}")
                    body_frames.append(f"{pct(min(PLAY_END, leave_time + epsilon))}{{opacity:0}}")
            body_frames.extend(
                (
                    f"{pct(FADE_START)}{{opacity:{1 if point in final_body else 0}}}",
                    f"{pct(FADE_END)}{{opacity:0}}",
                    f"{pct(RESET_END - FRAME_EPSILON)}{{opacity:0}}",
                    f"100%{{opacity:{1 if point in initial_body else 0}}}",
                )
            )
            styles.append(
                f"@keyframes body-{x}-{y}{{{''.join(body_frames)}}}"
                f".body-{x}-{y}{{animation:body-{x}-{y} {duration_ms}ms linear infinite}}"
            )
            body_elements.append(
                f'<rect class="body body-{x}-{y}" x="{x * CELL_SIZE + 2}" '
                f'y="{y * CELL_SIZE + 2}" width="{DOT_SIZE}" height="{DOT_SIZE}" '
                'rx="2" ry="2"/>'
            )

    head_frames = []
    for step, (x, y) in enumerate(path):
        time = step / steps * PLAY_END
        head_frames.append(
            f"{pct(time)}{{transform:translate({x * CELL_SIZE}px,{y * CELL_SIZE}px)"
            ";opacity:1}"
        )
    first_x, first_y = path[0]
    last_x, last_y = path[-1]
    head_frames.extend(
        (
            f"{pct(FADE_START)}{{transform:translate({last_x * CELL_SIZE}px,{last_y * CELL_SIZE}px);opacity:1}}",
            f"{pct(FADE_END)}{{opacity:0}}",
            f"{pct(RESET_END - FRAME_EPSILON)}{{opacity:0}}",
            f"100%{{transform:translate({first_x * CELL_SIZE}px,{first_y * CELL_SIZE}px);opacity:1}}",
        )
    )
    styles.append(f"@keyframes head{{{''.join(head_frames)}}}")

    width = columns * CELL_SIZE + 32
    height = 192
    return (
        f'<svg viewBox="-16 -32 {width} {height}" width="{width}" height="{height}" '
        'xmlns="http://www.w3.org/2000/svg">'
        '<desc>Animated contribution snake. It follows a randomized route and grows once per three contributions.</desc>'
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
