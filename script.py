#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Sat Dec 27 11:28:12 2025

@author: ms33sm

Workflow to make night_sky map for digiKam / Marble

Milky way picture downloaded from:
    download STAR map - top one (nice color of stars)
    https://svs.gsfc.nasa.gov/4851/
    link to poicture 8k (there are also bigger) https://svs.gsfc.nasa.gov/vis/a000000/a004800/a004851/milkyway_2020_8k.exr

export MAGICK_TMPDIR=/home/ms33sm/tmp/
convert -debug cache starmap_2020_32k.exr  -depth 8 starmap_2020_32k_8bit.png
convert -debug cache -contrast-stretch 0.5x0.5% starmap_2020_32k_8bit.png starmap_2020_32k_8bit_stretch.png

For json to kml - useful links
    https://stackoverflow.com/questions/71113897/converting-geojson-to-kml-using-python
    
    kml documentation / standars: https://docs.ogc.org/is/12-007r2/12-007r2.html
    
    
"""

from PIL import Image, ImageOps

from urllib.request import urlretrieve

import argparse
import math
import os
import pathlib
import platform
import re
import shutil
import subprocess
import sys
from collections import defaultdict, deque, namedtuple


COORD_EPS = 1e-9
THEME_NAME = "night_sky"
DGML_FILE = pathlib.Path("night_sky.dgml")
DEFAULT_LINE_COLOR = "FF0000FF"
DEFAULT_LINE_WIDTH = 2.5
DEFAULT_LINE_STYLE = "solidline"

# Marble DGML pen style tokens from DgmlPenTagHandler.cpp. KML LineStyle has no
# dash field, so the line type is applied through the DGML <pen> element.
LINE_STYLE_ALIASES = {
    "solid": "solidline",
    "solidline": "solidline",
    "dash": "dashline",
    "dashed": "dashline",
    "dashline": "dashline",
    "dot": "dotline",
    "dotted": "dotline",
    "dotline": "dotline",
    "dashdot": "dashdotline",
    "dashdotline": "dashdotline",
    "dashdotdot": "dashdotdotline",
    "dashdotdotline": "dashdotdotline",
    "none": "nopen",
    "nopen": "nopen",
}

LineColor = namedtuple("LineColor", ["kml", "dgml"])


def format_number(value):
    """Format a CLI number compactly for XML attributes."""
    return f"{value:g}"


def make_line_color(alpha, red, green, blue):
    """Build the two color spellings used by KML and DGML."""
    kml = f"{alpha:02X}{blue:02X}{green:02X}{red:02X}"
    if alpha == 255:
        dgml = f"#{red:02x}{green:02x}{blue:02x}"
    else:
        dgml = f"#{alpha:02x}{red:02x}{green:02x}{blue:02x}"
    return LineColor(kml, dgml)


def parse_line_color(value):
    """Accept RGB, HTML/CSS, or Marble/KML colors and return both forms.

    Supported examples:
        255, 0, 0          rgb(255, 0, 0)       rgb(255 0 0)
        #ff0000            #f00                 ff0000
        FF0000FF           #FF0000FF            ff0000ff

    Eight hex digits are always treated as Marble/KML AABBGGRR; six or three
    hex digits are HTML RRGGBB.
    """
    raw = str(value).strip()
    if not raw:
        raise argparse.ArgumentTypeError("line color cannot be empty")

    rgb_match = re.fullmatch(r"rgba?\s*\(([^)]*)\)", raw, flags=re.IGNORECASE)
    if rgb_match:
        parts = [part for part in re.split(r"[\s,]+", rgb_match.group(1).strip()) if part]
        if len(parts) not in (3, 4):
            raise argparse.ArgumentTypeError("RGB colors need three or four channels")
        channels = []
        for part in parts:
            if not re.fullmatch(r"\d{1,3}", part):
                raise argparse.ArgumentTypeError(f"invalid RGB channel: {part!r}")
            channel = int(part)
            if channel > 255:
                raise argparse.ArgumentTypeError(f"RGB channel out of range: {part!r}")
            channels.append(channel)
        if len(channels) == 3:
            channels.append(255)
        return make_line_color(channels[3], channels[0], channels[1], channels[2])

    if re.fullmatch(r"\d{1,3}[\s,]+\d{1,3}[\s,]+\d{1,3}", raw):
        parts = re.split(r"[\s,]+", raw)
        channels = []
        for part in parts:
            channel = int(part)
            if channel > 255:
                raise argparse.ArgumentTypeError(f"RGB channel out of range: {part!r}")
            channels.append(channel)
        return make_line_color(255, channels[0], channels[1], channels[2])

    hex_value = raw[1:] if raw.startswith("#") else raw
    if not re.fullmatch(r"[0-9A-Fa-f]+", hex_value):
        raise argparse.ArgumentTypeError(
            "color must be RGB (255,0,0), HTML (#ff0000), or Marble AABBGGRR (FF0000FF)"
        )

    if len(hex_value) == 8:
        alpha = int(hex_value[0:2], 16)
        red = int(hex_value[6:8], 16)
        green = int(hex_value[4:6], 16)
        blue = int(hex_value[2:4], 16)
        return make_line_color(alpha, red, green, blue)
    if len(hex_value) == 6:
        return make_line_color(
            255,
            int(hex_value[0:2], 16),
            int(hex_value[2:4], 16),
            int(hex_value[4:6], 16),
        )
    if len(hex_value) == 3:
        return make_line_color(
            255,
            int(hex_value[0] * 2, 16),
            int(hex_value[1] * 2, 16),
            int(hex_value[2] * 2, 16),
        )
    raise argparse.ArgumentTypeError(
        "hex colors must have 3, 6 (HTML), or 8 (Marble AABBGGRR) digits"
    )


def parse_line_style(value):
    """Normalize a user-facing line style name to a DGML pen style token."""
    normalized = re.sub(r"[-_\s]+", "", str(value).strip().lower())
    if normalized in LINE_STYLE_ALIASES:
        return LINE_STYLE_ALIASES[normalized]
    supported = ", ".join(sorted(set(LINE_STYLE_ALIASES.values())))
    raise argparse.ArgumentTypeError(f"unsupported line type {value!r}; use one of: {supported}")


def positive_float(value):
    """Argparse type for strictly positive finite numbers."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise argparse.ArgumentTypeError(f"expected a number, got {value!r}")
    if not math.isfinite(number) or number <= 0:
        raise argparse.ArgumentTypeError("value must be greater than zero")
    return number


def update_dgml_line_style(path, color, width, style):
    """Write the selected constellation-line style into the DGML theme file."""
    path = pathlib.Path(path)
    text = path.read_text(encoding="utf-8")

    geodata_pattern = re.compile(
        r'(<geodata\b(?=[^>]*\bname\s*=\s*["\']constellation_lines["\'])[^>]*>)'
        r'(.*?)'
        r'(</geodata\s*>)',
        flags=re.IGNORECASE | re.DOTALL,
    )
    match = geodata_pattern.search(text)
    if not match:
        raise ValueError('no <geodata name="constellation_lines"> element found')

    block = match.group(0)
    pen = f'<pen color="{color.dgml}" width="{format_number(width)}" style="{style}"/>'
    new_block, count = re.subn(r'<pen\b[^>]*?/?>', pen, block, count=1, flags=re.IGNORECASE)
    if count != 1:
        raise ValueError('no <pen> element found in the constellation_lines geodata block')

    path.write_text(text[:match.start()] + new_block + text[match.end():], encoding="utf-8")
    return path


def default_install_target():
    """Native digiKam Marble theme directory for the current Linux user."""
    data_home = os.environ.get("XDG_DATA_HOME")
    base = pathlib.Path.home() / ".local/share"
    if data_home:
        candidate = pathlib.Path(data_home).expanduser()
        if candidate.is_absolute():
            base = candidate
    return base / "digikam" / "marble_data" / "maps" / "earth" / THEME_NAME


def install_theme(target, failed):
    """Copy the generated theme into a Linux digiKam/Marble data directory."""
    target = pathlib.Path(target).expanduser()
    print(f"Installing to: {target}")

    try:
        target.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        print(f"[FAIL] install {target}: {type(exc).__name__}: {exc}")
        failed.append(str(target))
        return False

    required = [pathlib.Path(DGML_FILE), pathlib.Path(panorama_final)]
    required.extend(pathlib.Path(pair[1] + ".kml") for pair in allfiles)

    try:
        for source in required:
            if str(source) in failed:
                raise RuntimeError(f"generation failed for {source}")
            if not source.is_file() or source.stat().st_size == 0:
                raise FileNotFoundError(f"missing or empty source: {source}")
            shutil.copy2(source, target / source.name)

        pics_source = pathlib.Path("pics")
        pics = sorted(
            path for path in pics_source.glob("*.png")
            if path.is_file() and path.stat().st_size > 0
        )
        if not pics:
            raise FileNotFoundError(f"no PNG icons found in {pics_source}")
        pics_target = target / "pics"
        pics_target.mkdir(parents=True, exist_ok=True)
        for source in pics:
            shutil.copy2(source, pics_target / source.name)

        tiles_source = pathlib.Path("tiles")
        tile_levels = []
        if tiles_source.is_dir():
            tile_levels = sorted(
                (path for path in tiles_source.iterdir() if path.is_dir() and path.name.isdigit()),
                key=lambda path: int(path.name),
            )

        tile_count = 0
        for source in tile_levels:
            tile_files = [path for path in source.rglob("*") if path.is_file()]
            if not tile_files:
                raise FileNotFoundError(f"tile level is empty: {source}")
            shutil.copytree(source, target / source.name, dirs_exist_ok=True)
            tile_count += len(tile_files)

        license_source = pathlib.Path(download_folder) / "BSD-3-Clause.html"
        copied_license = False
        if license_source.is_file() and license_source.stat().st_size > 0:
            shutil.copy2(license_source, target / license_source.name)
            copied_license = True
    except Exception as exc:
        print(f"[FAIL] install {target}: {type(exc).__name__}: {exc}")
        failed.append(str(target))
        return False

    print(
        f"[OK] installed theme: {len(required)} files, {len(pics)} icons, "
        f"{len(tile_levels)} tile levels ({tile_count} tiles)"
    )
    if copied_license:
        print(f"[OK] installed attribution: {target / license_source.name}")
    else:
        print("[SKIP] optional BSD-3-Clause.html was not present")
    if not tile_levels:
        print("[SKIP] no numbered tile levels found; Marble can build them from mirrored.jpg")
    return True


def parse_args():
    parser = argparse.ArgumentParser(
        description="Generate the night_sky Marble theme and install it on Linux.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""color examples:
  --line-color '255,0,0'        RGB channels
  --line-color 'rgb(255,0,0)'   CSS-like RGB
  --line-color '#3366cc'        HTML color
  --line-color 'FFCC6633'       Marble/KML AABBGGRR

line type examples: solid, dashed, dotted, dash-dot, dash-dot-dot, none
""",
    )
    parser.add_argument(
        "-c", "--line-color",
        type=parse_line_color,
        default=parse_line_color(DEFAULT_LINE_COLOR),
        metavar="COLOR",
        help=(
            "constellation line color as RGB, HTML, or Marble AABBGGRR "
            f"(default: {DEFAULT_LINE_COLOR})"
        ),
    )
    parser.add_argument(
        "-t", "--line-type", "--line-style",
        dest="line_type",
        type=parse_line_style,
        default=DEFAULT_LINE_STYLE,
        metavar="TYPE",
        help=(
            "constellation line type: solid, dashed, dotted, dash-dot, "
            f"dash-dot-dot, or none (default: {DEFAULT_LINE_STYLE})"
        ),
    )
    parser.add_argument(
        "-w", "--line-width", "--line-thickness",
        dest="line_width",
        type=positive_float,
        default=DEFAULT_LINE_WIDTH,
        metavar="WIDTH",
        help=f"constellation line thickness in pixels (default: {DEFAULT_LINE_WIDTH})",
    )
    parser.add_argument(
        "-i", "--install-target",
        type=pathlib.Path,
        default=None,
        metavar="DIR",
        help=(
            "full theme directory to install into; default is this user's native "
            "digiKam night_sky directory"
        ),
    )
    parser.add_argument(
        "--no-install",
        action="store_true",
        help="generate and style the theme files but skip the automatic Linux install",
    )
    return parser.parse_args()


def coord_key(point):
    """Return a graph key for a coordinate, treating both antimeridian sides as one point."""
    lon, lat = float(point[0]), float(point[1])
    if abs(abs(lon) - 180.0) < COORD_EPS:
        lon = 180.0
    return (round(lon, 9), round(lat, 9))


def build_graph(lines):
    """Build an undirected multigraph from a list of coordinate sequences."""
    edges = []
    adjacency = defaultdict(list)
    for line in lines:
        points = [(float(point[0]), float(point[1])) for point in line]
        for a, b in zip(points, points[1:]):
            key_a, key_b = coord_key(a), coord_key(b)
            if key_a == key_b and a == b:
                continue
            edge_id = len(edges)
            edges.append({"a": a, "b": b, "key_a": key_a, "key_b": key_b})
            adjacency[key_a].append((key_b, edge_id))
            adjacency[key_b].append((key_a, edge_id))
    return edges, adjacency


def graph_components(adjacency):
    """Return the connected vertex sets of an undirected adjacency mapping."""
    seen = set()
    components = []
    for node in adjacency:
        if node in seen:
            continue
        queue = deque([node])
        seen.add(node)
        component = []
        while queue:
            current = queue.popleft()
            component.append(current)
            for neighbour, _ in adjacency[current]:
                if neighbour not in seen:
                    seen.add(neighbour)
                    queue.append(neighbour)
        components.append(component)
    return components


def shortest_paths(adjacency, source):
    """Breadth-first distances and predecessor edges from one vertex."""
    distance = {source: 0}
    previous = {}
    queue = deque([source])
    while queue:
        current = queue.popleft()
        for neighbour, edge_id in adjacency[current]:
            if neighbour not in distance:
                distance[neighbour] = distance[current] + 1
                previous[neighbour] = (current, edge_id)
                queue.append(neighbour)
    return distance, previous


def path_edges(previous, target):
    """Rebuild an edge path from the predecessor map made by shortest_paths."""
    result = []
    while target in previous:
        current, edge_id = previous[target]
        result.append(edge_id)
        target = current
    result.reverse()
    return result


def min_perfect_matching(nodes, cost_function):
    """Choose the cheapest pairing of an even number of vertices."""
    count = len(nodes)
    if count % 2:
        raise ValueError("odd number of vertices cannot be matched")
    memo = {}

    def solve(mask):
        if mask == 0:
            return (0, [])
        if mask in memo:
            return memo[mask]
        first = 0
        while not (mask & (1 << first)):
            first += 1
        best = None
        for other in range(first + 1, count):
            if not (mask & (1 << other)):
                continue
            rest_cost, rest_pairs = solve(mask ^ (1 << first) ^ (1 << other))
            total = cost_function(nodes[first], nodes[other]) + rest_cost
            if best is None or total < best[0]:
                best = (total, [(nodes[first], nodes[other])] + rest_pairs)
        memo[mask] = best
        return best

    return solve((1 << count) - 1)[1]


def euler_trail(start, adjacency, edges, used=None):
    """Return edge IDs for a trail that uses every edge in a component once."""
    if used is None:
        used = set()
    pointer = defaultdict(int)
    stack = [(start, None)]
    result = []
    while stack:
        current, incoming_edge = stack[-1]
        while pointer[current] < len(adjacency[current]) and adjacency[current][pointer[current]][1] in used:
            pointer[current] += 1
        if pointer[current] == len(adjacency[current]):
            if incoming_edge is not None:
                result.append(incoming_edge)
            stack.pop()
            continue
        neighbour, edge_id = adjacency[current][pointer[current]]
        pointer[current] += 1
        if edge_id in used:
            continue
        used.add(edge_id)
        stack.append((neighbour, edge_id))
    result.reverse()
    return result


def trail_coordinates(start, edge_ids, edges):
    """Turn an ordered list of edge IDs into one continuous coordinate sequence."""
    current = start
    coordinates = []
    for edge_id in edge_ids:
        edge = edges[edge_id]
        if current == edge["key_a"]:
            coordinates.append(edge["a"])
            coordinates.append(edge["b"])
            current = edge["key_b"]
        elif current == edge["key_b"]:
            coordinates.append(edge["b"])
            coordinates.append(edge["a"])
            current = edge["key_a"]
        else:
            raise AssertionError((current, edge["key_a"], edge["key_b"]))
    if not coordinates:
        return []
    result = [coordinates[0]]
    for point in coordinates[1:]:
        if point != result[-1]:
            result.append(point)
    return result


def unwrap_longitudes(coordinates):
    """Unwrap a coordinate sequence so antimeridian crossings stay continuous.

    Marble splits a tessellated LineString whenever two adjacent longitudes have
    opposite signs and are far enough from zero.  Writing a seam crossing as,
    for example, 179 -> 182 instead of 179 -> -178 avoids that split.  Marble's
    cylindrical projection repeats the world, so the unwrapped segment still
    renders on the correct side of the seam.
    """
    if not coordinates:
        return []
    unwrapped = [(float(coordinates[0][0]), float(coordinates[0][1]))]
    for longitude, latitude in coordinates[1:]:
        longitude = float(longitude)
        latitude = float(latitude)
        previous_longitude = unwrapped[-1][0]
        delta = longitude - previous_longitude
        while delta > 180.0:
            delta -= 360.0
        while delta < -180.0:
            delta += 360.0
        unwrapped.append((previous_longitude + delta, latitude))
    return unwrapped


def stitch_lines(lines):
    """Join touching line parts into connected trails without adding new edges.

    The input GeoJSON contains constellations whose lines are split into many
    parts. Where parts already share an endpoint, a multigraph can be traversed
    as one connected trail. Components with more than two odd-degree vertices
    are made traversable by duplicating existing shortest paths between odd
    vertices. This never connects genuinely separate figures. Longitudes are
    unwrapped at the antimeridian so Marble renders seam crossings as one line.
    """
    edges, adjacency = build_graph(lines)
    if not edges:
        return []
    output = []
    for component in graph_components(adjacency):
        degrees = {vertex: len(adjacency[vertex]) for vertex in component}
        odd_vertices = [vertex for vertex in component if degrees[vertex] % 2]
        component_adjacency = {vertex: adjacency[vertex] for vertex in component}
        if len(odd_vertices) > 2:
            all_distances = {}
            all_previous = {}
            for vertex in odd_vertices:
                all_distances[vertex], all_previous[vertex] = shortest_paths(component_adjacency, vertex)
            pairs = min_perfect_matching(odd_vertices, lambda a, b: all_distances[a][b])
            for a, b in pairs:
                for edge_id in path_edges(all_previous[a], b):
                    original = edges[edge_id]
                    new_id = len(edges)
                    edges.append(dict(original))
                    adjacency[original["key_a"]].append((original["key_b"], new_id))
                    adjacency[original["key_b"]].append((original["key_a"], new_id))
                    component_adjacency[original["key_a"]].append((original["key_b"], new_id))
                    component_adjacency[original["key_b"]].append((original["key_a"], new_id))
        start = odd_vertices[0] if odd_vertices else component[0]
        edge_ids = euler_trail(start, component_adjacency, edges)
        coordinates = trail_coordinates(start, edge_ids, edges)
        output.append(unwrap_longitudes(coordinates))
    return output


download_huge_files = True

# Track outcomes so the script can print a summary and exit non-zero on failures
generated = []
skipped = []
failed = []

args = parse_args()
line_color = args.line_color
line_width = args.line_width
line_style = args.line_type

try:
    update_dgml_line_style(DGML_FILE, line_color, line_width, line_style)
except Exception as exc:
    print(f"[FAIL] line style {DGML_FILE}: {type(exc).__name__}: {exc}")
    failed.append(str(DGML_FILE))
else:
    print(
        f"[OK] line style: color={line_color.kml}, width={format_number(line_width)}, "
        f"type={line_style}"
    )

download_folder="downloads"
results_folder="final"

if not os.path.exists(download_folder):
    os.makedirs(download_folder)

if not os.path.exists(results_folder):
    os.makedirs(results_folder)

Panorama_name=os.path.join(download_folder, "milkyway_2020_8k.exr")
panorama_final=os.path.join(results_folder, "mirrored.jpg")


clausule=os.path.join(download_folder, "BSD-3-Clause.html")
constellations_borders=os.path.join(download_folder, "constellations_borders.geojson")
constellations_lines=os.path.join(download_folder, "constellations_lines.geojson")
constellations=os.path.join(download_folder, "constellations.geojson")
dso_mag6=os.path.join(download_folder, "dsos.6.geojson")
stars_mag6=os.path.join(download_folder, "stars.6.geojson")


constellations_borders_mirror=os.path.join(results_folder, "constellations_borders_mirror.geojson")
constellations_lines_mirror=os.path.join(results_folder, "constellations_lines_mirror.geojson")
constellations_mirror=os.path.join(results_folder, "constellations_mirror.geojson")
dso_mag6_mirror=os.path.join(results_folder, "dsos_mag6_mirror.geojson")
stars_mag6_mirror=os.path.join(results_folder, "stars_6_mirror.geojson")

download_files=[
        [ clausule, "https://opensource.org/license/BSD-3-Clause"],
        [ Panorama_name, "https://svs.gsfc.nasa.gov/vis/a000000/a004800/a004851/milkyway_2020_8k.exr"],
        [ constellations_borders, "https://raw.githubusercontent.com/dieghernan/celestial_data/refs/heads/main/data/constellations.borders.geojson"], 
        [ constellations_lines, "https://raw.githubusercontent.com/dieghernan/celestial_data/refs/heads/main/data/constellations.lines.geojson"],
        [ constellations,       "https://raw.githubusercontent.com/dieghernan/celestial_data/refs/heads/main/data/constellations.geojson"],
        [ dso_mag6 , "https://raw.githubusercontent.com/dieghernan/celestial_data/refs/heads/main/data/dsos.6.geojson"],
        [ stars_mag6, "https://raw.githubusercontent.com/dieghernan/celestial_data/refs/heads/main/data/stars.6.geojson"],
    ]


### first file to process, second output file, third: icon filename under the theme's pics/ folder, 4th: KML color AABBGGRR, 5th: linewidth 2.5
mirror_geojson_files=[
    #### Multiline coordinate file
        [constellations_borders, constellations_borders_mirror, None, "FFFF00FF", 2.5],
        # [constellations_lines, constellations_lines_mirror],
    ]

mirror_geojson_files1=[
        # [constellations_borders, constellations_borders_mirror],
        [constellations_lines, constellations_lines_mirror, None, line_color.kml, line_width],
    ]

mirror_geojson_files2=[
    #### Point coordinate file
        # [constellations_borders, constellations_borders_mirror],
        [constellations, constellations_mirror, "pics/star.png", "FFFFFFFF", 2.5],
        [dso_mag6, dso_mag6_mirror, "pics/dso.png", "FFFFFFFF", 2.5],
        [stars_mag6, stars_mag6_mirror, "pics/star.png", "FFFFFFFF", 2.5],
    ]



##### download files
if download_huge_files:
    for item in download_files:
        target, url = item
        if os.path.exists(target) and os.path.getsize(target) > 0:
            print(f"[SKIP] already present: {target}")
            skipped.append(target)
            continue
        print(f"Downloading: {url}")
        print(f"         to: {target}")
        try:
            urlretrieve(url, target)
        except Exception as exc:
            # Some hosts (e.g. opensource.org) reject Python's user agent with HTTP 403
            # but accept curl's default one, so retry once with curl.
            print(f"[WARN] urllib failed for {target}: {type(exc).__name__}: {exc}")
            print("       retrying with curl")
            try:
                subprocess.run(
                    ["curl", "-fsSL", "--retry", "3", "-o", target, url],
                    check=True,
                )
            except Exception as curl_exc:
                print(f"[FAIL] download {target}: {type(curl_exc).__name__}: {curl_exc}")
                print("       hint: check the URL and your network connection; partial file will be removed")
                failed.append(target)
                try:
                    if os.path.exists(target):
                        os.remove(target)
                except OSError:
                    pass
                continue
        if not os.path.exists(target) or os.path.getsize(target) == 0:
            print(f"[FAIL] download {target}: file is missing or empty after download")
            failed.append(target)
        else:
            print(f"[OK] downloaded: {target}")
            generated.append(target)

# #### mirror panorama and save it as jpg file
# Best effort: if this fails, keep going and generate the KML files anyway.
try:
    from wand.image import Image as WandImage
except Exception as exc:
    print(f"[FAIL] {panorama_final}: cannot import wand: {type(exc).__name__}: {exc}")
    print("       hint: install with 'python3 -m pip install --user Wand' and make sure ImageMagick is installed")
    failed.append(panorama_final)
else:
    if not os.path.exists(Panorama_name) or os.path.getsize(Panorama_name) == 0:
        print(f"[FAIL] {panorama_final}: source panorama is missing or empty: {Panorama_name}")
        print("       hint: set download_huge_files = True or download the .exr panorama manually")
        failed.append(panorama_final)
    else:
        try:
            print(f"Creating: {panorama_final}")
            # The NASA panorama is a linear HDR EXR. Boost it in linear light and
            # then roll the highlights off with a Reinhard curve (u/(1+u)): the
            # faint stars stay above the noise floor while bright stars do not
            # clip to white. A plain brightness boost on the 8-bit JPEG instead
            # flattens the sky to grey.
            exposure = 100
            img = WandImage(filename=Panorama_name)
            # Wand reports the EXR as 16-bit sRGB; go to linear RGB first so the
            # multiply and the tone curve operate on physical light values.
            img.transform_colorspace('rgb')
            img.evaluate(operator='multiply', value=exposure)
            img.fx('u/(1+u)')
            img.transform_colorspace('srgb')
            img.format = 'jpeg'
            img.compression_quality = 95
            img.save(filename=panorama_final)
        except Exception as exc:
            print(f"[FAIL] {panorama_final}: {type(exc).__name__}: {exc}")
            print("       hint: check ImageMagick EXR/JPEG delegates, MAGICK_TMPDIR and free disk space")
            failed.append(panorama_final)
        else:
            if not os.path.exists(panorama_final) or os.path.getsize(panorama_final) == 0:
                print(f"[FAIL] {panorama_final}: output is missing or empty")
                failed.append(panorama_final)
            else:
                print(f"[OK] created: {panorama_final}")
                generated.append(panorama_final)



# for mirror_pair in mirror_geojson_files:

#     geojson_in=mirror_pair[0]
#     gojson_out=mirror_pair[1]

#     with open(geojson_in, 'r') as file_in:
#         geojson_data = geojson.load(file_in)
        

#     for feature in geojson_data['features']:
#         for point in feature['geometry']['coordinates'][0]:
#             point[0] = point[0]*(-1)
#             # print(point[0])
#     file_in.close()
#     with open(gojson_out, 'w') as file_out:
#         geojson.dump(geojson_data, file_out)
#     file_out.close()

# for mirror_pair in mirror_geojson_files1:

#     geojson_in=mirror_pair[0]
#     gojson_out=mirror_pair[1]

#     with open(geojson_in, 'r') as file_in:
#         geojson_data = geojson.load(file_in)
        

#     # for item in geojson_data['features']:
#     #     for i
#     #     item['geometry']['coordinates'][0]=(-1)*item['geometry']['coordinates'][0]
    
#     for item in geojson_data['features']:
#         cord = item['geometry']['coordinates']
#         for i in range(0, len(cord)):
#             for j in range(0, len(cord[i])):
#                 cord[i][j][0]=(-1)*cord[i][j][0]
#                 # for k in range(len(cord[i][j])):
#                 # print(k[0])
#                 # lats.append(k[1])
#                 # lons.append(k[0])
                
#     file_in.close()
#     with open(gojson_out, 'w') as file_out:
#         geojson.dump(geojson_data, file_out)
#     file_out.close()  
    
    
# for mirror_pair in mirror_geojson_files2:

#     geojson_in=mirror_pair[0]
#     gojson_out=mirror_pair[1]

#     with open(geojson_in, 'r') as file_in:
#         geojson_data = geojson.load(file_in)
        

#     for item in geojson_data['features']:
#         # geojson_data['features'][i]
#         item['geometry']['coordinates'][0]=(-1)*item['geometry']['coordinates'][0]
        
#     file_in.close()
#     with open(gojson_out, 'w') as file_out:
#         geojson.dump(geojson_data, file_out)
#     file_out.close()   
    
    
    
# Open with marble and save as kml file
# Include files in gdml file with path maps/earth/night_sky/abc.kml
# copy whole night_sky folder with edited dgml file to digikam folder matble_data/earth/...



# from pygeoif.factories import shape
# from pygeoif.geometry import Point
# # # import sys
# # import fastkml
# # import fastkml.containers
# # import fastkml.features
# # import fastkml.styles
# # from fastkml.geometry import create_kml_geometry
# # from fastkml.enums import AltitudeMode

# import pathlib
# import simplekml

# from simplekml import Kml, Color

# mirror_x_geometry = True

# allfiles = mirror_geojson_files + mirror_geojson_files1 + mirror_geojson_files2

# kml = Kml()
# multilin = kml.newmultigeometry()
# for mirror_pair in allfiles:
    
#     mirror_pair = allfiles[0]
    
#     geojson_in=mirror_pair[0]
#     gojson_out=mirror_pair[1]
#     icon_url = mirror_pair[2]
#     linecolor= mirror_pair[3]
#     linewidth= mirror_pair[4]
    
#     icon_scale=0.2
    
#     placemarks = []
#     with open(geojson_in, 'r') as file_in:
#         data = geojson.load(file_in)
#     for feature in data['features']:
        
#          geometry = shape(feature["geometry"])
         
#          if mirror_x_geometry:
#              if feature['geometry'].type == "Point":
#                  feature['geometry']['coordinates'][0] = (-1)*feature['geometry']['coordinates'][0]
#                  # for point in feature['geometry']['coordinates']:
#                  #     feature['geometry']['coordinates'][0] = point*(-1)
                     
#              elif feature['geometry'].type == "MultiLineString":
#                  cord = feature['geometry']['coordinates']
#                  for i in range(0, len(cord)):
#                     for j in range(0, len(cord[i])):
#                         cord[i][j][0]=(-1)*cord[i][j][0]
#              else: 
#                 print(f"Not supported geometry type: {feature['geometry'].type}")
                    
#          geometry = shape(feature["geometry"])
#          # print(geometry)
         
#          # geometry_old=geometry
#          # if mirror_x_geometry:
#          #     for gm in geometry.geoms:
#          #         for point in gm.geoms:
#          #             new_x = (-1)*point.x
#          #             p = Point(new_x, point.y)
#          #             point = shape(p)
#          # geometry = shape(feature["geometry"])
#          # kml_geometry = create_kml_geometry(
#          #     geometry,
#          #     tessellate=1,
#          #     # extrude=False,
#          #    # altitude_mode=AltitudeMode.relative_to_ground,
#          #    )
#          # # color = 4283782485
         
#          # style = fastkml.styles.Style(
#          #     styles=[
#          #         fastkml.styles.LineStyle(color=linecolor, width=linewidth),
#          #         fastkml.styles.PolyStyle(
#          #             color=linecolor,
#          #             # fill=True,
#          #             # outline=True,
#          #             ),
#          #         fastkml.styles.IconStyle(icon_href=icon_url, scale=icon_scale, color=linecolor),
#          #         ]
#          #     )
#          try:
#              name=feature["properties"]["name"]
#          except:
#              name=""
#              pass
#          if name is not None:
#              print(name)
         
#          coords=[]
#          for g in geometry.geoms:
#              coords.append(g.coords)
#              print(g.coords)
         
#          placemark = multilin.newlinestring(coords=feature['geometry']['coordinates'])
             
#          # placemark = fastkml.features.Placemark(
#          #     name = name,
#          #     # description=feature["properties"]["FORMAL_EN"],
#          #     kml_geometry=kml_geometry,
#          #     styles=[style],
#          # )
         
#          placemarks.append(placemark)
    
#     for place in placemarks:
#         pnt = kml.newpoint()
#     kml.save("test" + ".kml")
    
#     document = fastkml.containers.Document(features=placemarks)
#     kml = fastkml.KML(features=[document])
#     outfile = pathlib.Path(gojson_out + ".kml")
#     kml.write(outfile, prettyprint=True, precision=3)


try:
    import geojson
    from pygeoif.factories import shape
    # from pygeoif.geometry import Point
    # import sys
    import fastkml
    import fastkml.containers
    import fastkml.features
    import fastkml.styles
    from fastkml.geometry import create_kml_geometry
    # from fastkml.enums import AltitudeMode
except Exception as exc:
    print(f"[FAIL] KML generation: cannot import geojson/pygeoif/fastkml: {type(exc).__name__}: {exc}")
    print("       hint: install with 'python3 -m pip install --user geojson fastkml pygeoif'")
    shape = None

mirror_x_geometry = True

allfiles = mirror_geojson_files + mirror_geojson_files1 + mirror_geojson_files2

if shape is not None:
    for mirror_pair in allfiles:

        geojson_in=mirror_pair[0]
        gojson_out=mirror_pair[1]
        icon_url = mirror_pair[2]
        linecolor= mirror_pair[3]
        linewidth= mirror_pair[4]

        icon_scale=0.2

        # KML colors are AABBGGRR, with no leading '#'. Marble's KML parser
        # rejects '#'-prefixed colors as QColor(), which made point labels
        # invisible. Marble's default label color is black, so every point
        # layer now sets an explicit white label color.
        is_point_layer = False
        try:
            with open(geojson_in, 'r') as probe:
                probe_data = geojson.load(probe)
            is_point_layer = all(
                f.get('geometry', {}).get('type') == 'Point'
                for f in probe_data.get('features', [])
            )
        except Exception:
            pass

        outfile = pathlib.Path(gojson_out + ".kml")

        if not os.path.exists(geojson_in) or os.path.getsize(geojson_in) == 0:
            print(f"[SKIP] {outfile}: input is missing or empty: {geojson_in}")
            skipped.append(str(outfile))
            continue

        print(f"Creating: {outfile}")
        try:
            placemarks = []
            with open(geojson_in, 'r') as file_in:
                data = geojson.load(file_in)
            for feature in data['features']:

                geometry = shape(feature["geometry"])

                if mirror_x_geometry:
                    if feature['geometry'].type == "Point":
                        feature['geometry']['coordinates'][0] = (-1)*feature['geometry']['coordinates'][0]
                    elif feature['geometry'].type == "MultiLineString":
                        cord = feature['geometry']['coordinates']
                        for i in range(0, len(cord)):
                            for j in range(0, len(cord[i])):
                                cord[i][j][0]=(-1)*cord[i][j][0]
                        # Join touching line parts into connected trails. Only
                        # the constellation-lines layer gets this treatment;
                        # borders keep their original topology.
                        if geojson_in == constellations_lines:
                            feature['geometry']['coordinates'] = stitch_lines(cord)
                    else:
                        print(f"Not supported geometry type: {feature['geometry'].type}")

                geometry = shape(feature["geometry"])
                kml_geometry = create_kml_geometry(
                    geometry,
                    tessellate=1,
                    # extrude=False,
                    # altitude_mode=AltitudeMode.relative_to_ground,
                    )

                styles = []
                if is_point_layer:
                    # For Point placemarks Marble keeps the inline KML style, so
                    # emit only the icon style and a plain white label color. Do
                    # not add line/poly styles to point layers.
                    if icon_url:
                        styles.append(fastkml.styles.IconStyle(icon_href=icon_url, scale=icon_scale))
                    if linecolor:
                        styles.append(fastkml.styles.LabelStyle(color=linecolor))
                else:
                    # Non-point styles are normally replaced by the DGML geodata
                    # style at load time, but these values are useful in other
                    # KML viewers and as a fallback.
                    if linecolor:
                        styles.append(fastkml.styles.LineStyle(color=linecolor, width=linewidth))
                        styles.append(fastkml.styles.PolyStyle(color=linecolor))
                style = fastkml.styles.Style(styles=styles)
                try:
                    name=feature["properties"]["name"]
                except Exception:
                    name=""
                if name is not None:
                    print(name)
                placemark = fastkml.features.Placemark(
                    name = name,
                    # description=feature["properties"]["FORMAL_EN"],
                    kml_geometry=kml_geometry,
                    styles=[style],
                )
                placemarks.append(placemark)

            document = fastkml.containers.Document(features=placemarks)
            kml = fastkml.KML(features=[document])
            kml.write(outfile, prettyprint=True, precision=3)
        except Exception as exc:
            print(f"[FAIL] {outfile}: {type(exc).__name__}: {exc}")
            failed.append(str(outfile))
        else:
            if not outfile.exists() or outfile.stat().st_size == 0:
                print(f"[FAIL] {outfile}: output is missing or empty")
                failed.append(str(outfile))
            else:
                print(f"[OK] created: {outfile}")
                generated.append(str(outfile))


#### constellation descriptions
# test for constellations info download


def clean_div(string):
    string = string.replace('[<div class="zodiac-characteristics_text">\n', "<![CDATA[")
    string = string.replace("</div>]", "").replace('&lt;',"<").replace('&gt;',">")
    string = string + "<p>From: https://www.star-registration.com/blogs/constellations-and-zodiac-signs/an-overview-of-all-88-constellations</p>"
    string = string + "]]>"
    string = str(re.sub(r"\s\s+" , " ", str(string))).replace("\n","\r\n")
    return string


webpage="https://www.star-registration.com"
overview_url="https://www.star-registration.com/blogs/constellations-and-zodiac-signs/an-overview-of-all-88-constellations"

constelations=[]
try:
    import requests
    from bs4 import BeautifulSoup
except Exception as exc:
    print(f"[WARN] constellation descriptions: cannot import requests/bs4: {type(exc).__name__}: {exc}")
    print("       hint: install with 'python3 -m pip install --user requests beautifulsoup4'")
else:
    try:
        html = requests.get(overview_url, timeout=60).text
        soup = BeautifulSoup(html, "html.parser")

        const_title=soup.find_all(class_="constellation-card-title")
        for i in range(len(const_title)):
            string = const_title[i].text.replace('\n',"")
            const_title[i] = re.sub(r"\s\s+" , "", string)

        buttons_links=soup.find_all(class_="btn")

        if len(const_title) != len(buttons_links):
            raise ValueError(f"found {len(const_title)} constellation names but {len(buttons_links)} links")

        for link in buttons_links:
            hreff = link.get('href')
            if not hreff:
                raise ValueError("constellation link without href")
            constelation = hreff.split('constellation-')[-1:]
            print(f"Getting data for constellation: {constelation}")

            html = requests.get(webpage+hreff, timeout=60).text
            soup = BeautifulSoup(html, "html.parser")

            characteristics=str(soup.find_all(class_="zodiac-characteristics_text"))

            constelations.append( clean_div( str(characteristics)) )
    except Exception as exc:
        print(f"[WARN] constellation descriptions unavailable: {type(exc).__name__}: {exc}")
        constelations = []

#######
if not constelations:
    print(f"[SKIP] constellation descriptions: nothing downloaded, {constellations_mirror}.kml left unchanged")
    skipped.append(str(constellations_mirror + ".kml"))
else:
    try:
        from fastkml import kml
        from fastkml.utils import find_all
        from fastkml import Placemark
        from pathlib import Path

        file_path = Path(constellations_mirror +".kml")

        if not file_path.exists() or file_path.stat().st_size == 0:
            raise FileNotFoundError(f"KML file is missing or empty: {file_path}")

        k = kml.KML.parse(file_path, validate=False)

        features = k.features[0].features
        if len(constelations) + 1 != len(features):
            raise ValueError(f"downloaded {len(constelations)} descriptions for {len(features)} placemarks")

        ## 75 'Serpens Caput' OR 76 'Serpens Cauda' should be identical
        if len(features) <= 76:
            # No Serpens split to account for; assign what we have.
            for i in range(min(len(features), len(constelations))):
                features[i].description = str(constelations[i])
        else:
            for i in range(len(features)):
                if i == 75:
                    continue
                if i > 75:
                    i -= 1
                features[i].description = str(constelations[i])

        k.write(file_path)
        print(f"[OK] descriptions written: {file_path}")

        i=0
        placemarks = list(find_all(k, of_type=Placemark))
        for p in placemarks:
            print(f"{i}\t{p.name}")
            i += 1
    except Exception as exc:
        print(f"[WARN] constellation descriptions not written to {constellations_mirror}.kml: {type(exc).__name__}: {exc}")

# points = list(find_all(k, of_type=Point))
# for p in points:
#     print(p.geometry)


if platform.system() == "Linux":
    if args.no_install:
        print("[SKIP] automatic install: disabled by --no-install")
    else:
        install_theme(args.install_target or default_install_target(), failed)
else:
    print("[SKIP] automatic install: Linux only (copy the theme manually)")

print()
print("=" * 60)
print(f"Generated: {len(generated)}")
for path in generated:
    print(f"  [OK]   {path}")
if skipped:
    print(f"Skipped: {len(skipped)}")
    for path in skipped:
        print(f"  [SKIP] {path}")
if failed:
    print(f"Failed: {len(failed)}")
    for path in failed:
        print(f"  [FAIL] {path}")
    print("Some steps failed; see messages above.")
    sys.exit(1)
print("All steps completed successfully.")
        
# points = list(find_all(k, of_type=Point))
# for p in points:
#     print(p.geometry)
    
    
    
    
    
    
    
    