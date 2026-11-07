#!/usr/bin/env python3
"""
notebook_writer.py - Generates realistic handwritten G-code for Bambu Lab A1 on a physical notebook.

Features:
  - Loads single-line JSON fonts (default cursive or custom digitized handwriting)
  - Automatic word-wrapping, page margins, and ruled/grid line snapping
  - Realistic Humanizer engine (micro-slant, baseline wobble, organic stroke noise)
  - Bambu Lab A1 safe G-code generation (heaters off, fan off, gentle accelerations, safe Z clearance)
  - Dry-run mode for mid-air alignment verification (+10mm safety offset)
  - Generates visual SVG and high-resolution PNG previews of the written notebook page
"""

import os
import sys
import json
import math
import random
import argparse
from typing import Dict, List, Tuple, Any, Optional

try:
    from PIL import Image, ImageDraw
except ImportError:
    Image, ImageDraw = None, None

try:
    import svgwrite
except ImportError:
    svgwrite = None


class SingleLineFont:
    """Manages loading and querying single-line stroke fonts from JSON."""

    def __init__(self, font_path: str, fallback_font_path: Optional[str] = None):
        self.font_path = font_path
        with open(font_path, 'r', encoding='utf-8') as f:
            self.data = json.load(f)

        self.name = self.data.get("name", "Unknown Single-Line Font")
        self.cap_height = float(self.data.get("cap_height", 21.0))
        self.x_height = float(self.data.get("x_height", 9.0))
        self.descender = float(self.data.get("descender", -12.0))
        self.characters: Dict[str, Any] = self.data.get("characters", {})

        # Optional fallback font (e.g. default cursive if custom font lacks a glyph)
        self.fallback = None
        if fallback_font_path and os.path.exists(fallback_font_path):
            if os.path.abspath(fallback_font_path) != os.path.abspath(font_path):
                self.fallback = SingleLineFont(fallback_font_path, fallback_font_path=None)

        # Accented fallback mapping
        self.accent_fallback = {
            'à': 'a', 'á': 'a', 'è': 'e', 'é': 'e', 'ì': 'i', 'í': 'i',
            'ò': 'o', 'ó': 'o', 'ù': 'u', 'ú': 'u',
            'À': 'A', 'Á': 'A', 'È': 'E', 'É': 'E', 'Ì': 'I', 'Í': 'I',
            'Ò': 'O', 'Ó': 'O', 'Ù': 'U', 'Ú': 'U',
            '“': '"', '”': '"', '‘': "'", '’': "'", '«': '"', '»': '"',
            '–': '-', '—': '-', '•': '*', '·': '*'
        }

    def get_glyph(self, char: str) -> Tuple[float, List[List[Tuple[float, float]]]]:
        """Returns (advance_width, list_of_strokes) for char in font units."""
        if char in self.characters and (self.characters[char].get("strokes") or char == ' '):
            entry = self.characters[char]
            strokes = [
                [(float(pt[0]), float(pt[1])) for pt in s]
                for s in entry.get("strokes", [])
            ]
            return float(entry.get("advance_width", 12.0)), strokes

        # Try fallback font if glyph missing in current font
        if self.fallback:
            return self.fallback.get_glyph(char)

        # Fallback to unaccented or standard char
        if char in self.accent_fallback:
            fb = self.accent_fallback[char]
            if fb in self.characters and (self.characters[fb].get("strokes") or fb == ' '):
                entry = self.characters[fb]
                strokes = [
                    [(float(pt[0]), float(pt[1])) for pt in s]
                    for s in entry.get("strokes", [])
                ]
                return float(entry.get("advance_width", 12.0)), strokes
            elif self.fallback:
                return self.fallback.get_glyph(fb)

        # Default fallback for unknown glyphs: space
        space_entry = self.characters.get(' ', {"advance_width": 12.0, "strokes": []})
        return float(space_entry.get("advance_width", 12.0)), []


class Humanizer:
    """Adds natural human variability to vector strokes."""

    def __init__(self, intensity: float = 0.6, seed: Optional[int] = None):
        self.intensity = max(0.0, min(2.0, intensity))
        if seed is not None:
            random.seed(seed)

    def perturb_glyph(
        self,
        strokes: List[List[Tuple[float, float]]],
        scale: float,
        char_idx: int,
        line_idx: int
    ) -> List[List[Tuple[float, float]]]:
        if not strokes:
            return []

        if self.intensity <= 0.001:
            return [[(round(p[0] * scale, 3), round(p[1] * scale, 3)) for p in s] for s in strokes]

        # Subtle baseline wander (continuous low frequency)
        baseline_drift = math.sin(char_idx * 0.35 + line_idx * 1.5) * (0.12 * self.intensity)

        # Micro slant variation (± 1.5 degrees)
        slant_angle = (random.uniform(-0.025, 0.025)) * self.intensity
        tan_slant = math.tan(slant_angle)

        # Micro position jitter
        dx = random.uniform(-0.06, 0.06) * self.intensity
        dy = (random.uniform(-0.05, 0.05) * self.intensity) + baseline_drift

        # Micro scale fluctuation (± 2.5%)
        s_factor = 1.0 + random.uniform(-0.025, 0.025) * self.intensity

        perturbed_strokes = []
        for stroke in strokes:
            new_stroke = []
            curr_px_noise = random.uniform(-0.015, 0.015) * self.intensity
            curr_py_noise = random.uniform(-0.015, 0.015) * self.intensity
            for (x_raw, y_raw) in stroke:
                # Apply slant shear relative to baseline
                x_scaled = (x_raw + y_raw * tan_slant) * scale * s_factor
                y_scaled = y_raw * scale * s_factor

                # Smooth micro point wobble with temporal damping
                curr_px_noise = 0.7 * curr_px_noise + random.uniform(-0.015, 0.015) * self.intensity
                curr_py_noise = 0.7 * curr_py_noise + random.uniform(-0.015, 0.015) * self.intensity

                new_stroke.append((round(x_scaled + dx + curr_px_noise, 3), round(y_scaled + dy + curr_py_noise, 3)))
            perturbed_strokes.append(new_stroke)

        return perturbed_strokes


class NotebookLayout:
    """Manages page ruling, margins, word wrapping, and text placement."""

    def __init__(
        self,
        font: SingleLineFont,
        notebook_width: float = 148.0,
        notebook_height: float = 210.0,
        notebook_x: float = 54.0,
        notebook_y: float = 23.0,
        line_spacing: float = 8.0,
        margin_left: float = 25.0,
        margin_right: float = 15.0,
        margin_top: float = 20.0,
        margin_bottom: float = 15.0,
        font_size_mm: Optional[float] = None,
        grid_type: str = "lines",
        humanizer_intensity: float = 0.6,
        red_margin: bool = False
    ):
        self.font = font
        self.nb_w = notebook_width
        self.nb_h = notebook_height
        self.nb_x = notebook_x
        self.nb_y = notebook_y
        self.line_spacing = line_spacing
        self.margin_left = margin_left
        self.margin_right = margin_right
        self.margin_top = margin_top
        self.margin_bottom = margin_bottom
        self.grid_type = grid_type
        self.red_margin = red_margin

        # Sizing: cap height in mm
        if font_size_mm is None or font_size_mm <= 0:
            self.font_size_mm = min(line_spacing * 0.55, 4.5)
        else:
            self.font_size_mm = font_size_mm

        # Font scale factor: scale units to mm
        self.scale = self.font_size_mm / self.font.cap_height
        self.humanizer = Humanizer(humanizer_intensity)

        # Usable text area on the notebook
        self.usable_width = self.nb_w - self.margin_left - self.margin_right
        self.usable_height = self.nb_h - self.margin_top - self.margin_bottom
        self.max_lines = int(math.floor(self.usable_height / self.line_spacing))

        # Clamp max_lines to ensure baseline and descenders never exceed physical Bambu bed (Y >= 5.0 mm)
        first_line_y = (self.nb_y + self.nb_h) - self.margin_top
        min_safe_baseline = 14.0  # mm, ensures descenders stay strictly above 5.0 mm limit
        if first_line_y > min_safe_baseline:
            max_bed_lines = int(math.floor((first_line_y - min_safe_baseline) / self.line_spacing)) + 1
            self.max_lines = min(self.max_lines, max_bed_lines)

    def get_line_baseline_y(self, line_index: int) -> float:
        """Returns bed Y coordinate (in mm) for the baseline of line_index (0-based)."""
        # Top of notebook on bed is (nb_y + nb_h)
        # First line is below margin_top
        first_line_y = (self.nb_y + self.nb_h) - self.margin_top
        return first_line_y - (line_index * self.line_spacing)

    def measure_word_width(self, word: str) -> float:
        """Measures exact width of a word accounting for tight cursive connections."""
        if not word:
            return 0.0
        cur_x = 0.0
        prev_raw = None
        prev_exit = None
        prev_char_x = 0.0
        prev_char = None
        for c_idx, char in enumerate(word):
            adv_units, raw_strokes = self.font.get_glyph(char)
            if not raw_strokes:
                cur_x += adv_units * self.scale
                prev_char = char
                prev_exit = None
                continue
            s0 = raw_strokes[0]
            p_entry = s0[0]
            p_exit = s0[-1]
            adv = adv_units * self.scale

            prev_is_lower = prev_char is not None and (prev_char.islower() or prev_char in 'àèéìòù')
            is_cursive = (char.islower() or char in 'àèéìòù') and c_idx > 0 and prev_is_lower and prev_exit is not None
            if is_cursive:
                target_dx = 0.35
                match_x = prev_exit[0] - p_entry[0] * self.scale + target_dx
                prev_max_x = prev_char_x + max([p[0] for s in prev_raw for p in s]) * self.scale
                curr_min_x = min([p[0] for s in raw_strokes for p in s]) * self.scale
                min_adv = max(prev_char_x + 1.5, prev_max_x - curr_min_x + 0.25)
                char_x = max(match_x, min_adv, cur_x)
            else:
                char_x = cur_x

            prev_char = char
            prev_char_x = char_x
            prev_exit = (char_x + p_exit[0] * self.scale, p_exit[1] * self.scale)
            prev_raw = raw_strokes
            cur_x = char_x + adv

        if prev_exit:
            return prev_exit[0]
        return cur_x

    def layout_pages(self, text: str, start_line: int = 0) -> List[List[Dict[str, Any]]]:
        """Splits text into pages and lines, wrapping to margins, computing bed mm coordinates."""
        paragraphs = text.replace('\r\n', '\n').replace('\r', '\n').split('\n')

        pages = []
        current_page_strokes = []
        current_line_idx = start_line
        global_char_idx = 0

        space_width_mm = self.font.get_glyph(' ')[0] * self.scale

        for para in paragraphs:
            # If paragraph starts and line exceeds max_lines, start new page
            if current_line_idx >= self.max_lines:
                if current_page_strokes:
                    pages.append(current_page_strokes)
                current_page_strokes = []
                current_line_idx = 0

            words = para.split(' ')
            if not para.strip():
                # Empty line / paragraph break
                current_line_idx += 1
                continue

            current_line_x = self.nb_x + self.margin_left
            baseline_y = self.get_line_baseline_y(current_line_idx)

            for w_idx, word in enumerate(words):
                if not word:
                    current_line_x += space_width_mm
                    continue

                # Measure tight cursive word width
                word_width = self.measure_word_width(word)
                max_line_x = self.nb_x + self.nb_w - self.margin_right

                # Wrap to next line if word exceeds margin and we're not already at line start
                if (current_line_x + word_width) > max_line_x and current_line_x > (self.nb_x + self.margin_left):
                    current_line_idx += 1
                    if current_line_idx >= self.max_lines:
                        # Page full -> start next page
                        pages.append(current_page_strokes)
                        current_page_strokes = []
                        current_line_idx = 0
                    current_line_x = self.nb_x + self.margin_left
                    baseline_y = self.get_line_baseline_y(current_line_idx)

                # Render characters of this word with tight cursive ligatures
                word_body_stroke = []
                word_secondary_strokes = []
                prev_char_bed_x = None
                prev_exit = None
                prev_raw_strokes = None
                prev_char = None

                for c_idx, char in enumerate(word):
                    adv_units, raw_strokes = self.font.get_glyph(char)
                    adv_mm = adv_units * self.scale

                    if not raw_strokes:
                        current_line_x += adv_mm
                        prev_char = char
                        prev_exit = None
                        continue

                    s0 = raw_strokes[0]
                    p_entry = s0[0]
                    p_exit = s0[-1]

                    prev_is_lower = prev_char is not None and (prev_char.islower() or prev_char in 'àèéìòù')
                    is_cursive_lower = (char.islower() or char in 'àèéìòù') and prev_is_lower and (prev_exit is not None)

                    # Authentic calligraphy pen-lift rules:
                    # 1. Oval letters starting at waist counter (a, o, c, d, g, q) when preceded by baseline exit
                    # 2. Steep vertical step (dy > 1.2 mm) to prevent cross-cutting diagonals
                    TOP_ENTRY_CHARS = set('aocdgqàò')
                    wants_pen_lift = False
                    if is_cursive_lower:
                        if char in TOP_ENTRY_CHARS and (p_entry[1] * self.scale >= 1.2) and (prev_exit[1] - baseline_y <= 1.0):
                            wants_pen_lift = True
                        elif prev_exit is not None and abs(p_entry[1] * self.scale - (prev_exit[1] - baseline_y)) > 1.2:
                            wants_pen_lift = True

                    if is_cursive_lower and not wants_pen_lift:
                        target_dx = 0.35  # mm natural forward step
                        match_x = prev_exit[0] - p_entry[0] * self.scale + target_dx
                        prev_max_x = prev_char_bed_x + max([p[0] for s in prev_raw_strokes for p in s]) * self.scale
                        curr_min_x = min([p[0] for s in raw_strokes for p in s]) * self.scale
                        min_adv = max(prev_char_bed_x + 1.5, prev_max_x - curr_min_x + 0.25)
                        char_bed_x = max(match_x, min_adv, current_line_x)
                    elif prev_char_bed_x is not None and prev_raw_strokes is not None:
                        # Natural inter-letter spacing with pen lift inside a word
                        prev_max_x = prev_char_bed_x + max([p[0] for s in prev_raw_strokes for p in s]) * self.scale
                        curr_min_x = min([p[0] for s in raw_strokes for p in s]) * self.scale
                        char_bed_x = max(prev_max_x - curr_min_x + 0.40, current_line_x)
                    else:
                        char_bed_x = current_line_x

                    # If character exceeds max_line_x (rare overflow)
                    char_max_x = char_bed_x + max([p[0] for s in raw_strokes for p in s]) * self.scale
                    if char_max_x > max_line_x and current_line_x > (self.nb_x + self.margin_left):
                        if word_body_stroke:
                            current_page_strokes.append({
                                "type": "stroke",
                                "line_idx": current_line_idx,
                                "char": "word_body",
                                "points": word_body_stroke
                            })
                            word_body_stroke = []
                        for s in word_secondary_strokes:
                            current_page_strokes.append({
                                "type": "stroke",
                                "line_idx": current_line_idx,
                                "char": "accent/dot",
                                "points": s
                            })
                        word_secondary_strokes = []

                        current_line_idx += 1
                        if current_line_idx >= self.max_lines:
                            pages.append(current_page_strokes)
                            current_page_strokes = []
                            current_line_idx = 0
                        current_line_x = self.nb_x + self.margin_left
                        char_bed_x = current_line_x
                        baseline_y = self.get_line_baseline_y(current_line_idx)
                        prev_exit = None

                    perturbed = self.humanizer.perturb_glyph(
                        raw_strokes, self.scale, global_char_idx, current_line_idx
                    )

                    bed_char_strokes = []
                    for stroke in perturbed:
                        bed_stroke = []
                        for (pt_x, pt_y) in stroke:
                            bx = char_bed_x + pt_x
                            by = baseline_y + pt_y
                            bed_stroke.append((round(bx, 3), round(by, 3)))
                        if bed_stroke:
                            bed_char_strokes.append(bed_stroke)

                    can_connect_cursive = (char.islower() or char in 'àèéìòù')

                    if can_connect_cursive and bed_char_strokes:
                        bed_char_strokes.sort(key=len, reverse=True)
                        primary_s = bed_char_strokes[0]
                        extra_s = bed_char_strokes[1:]
                        if char in ['i', 'j', 't', 'à', 'è', 'é', 'ì', 'ò', 'ù', 'z', 'Z']:
                            word_secondary_strokes.extend(extra_s)
                        else:
                            for es in extra_s:
                                current_page_strokes.append({
                                    "type": "stroke",
                                    "line_idx": current_line_idx,
                                    "char": char,
                                    "points": es
                                })

                        if word_body_stroke and not wants_pen_lift:
                            p_curr_exit = word_body_stroke[-1]
                            p_curr_entry = primary_s[0]
                            dx = p_curr_entry[0] - p_curr_exit[0]
                            dy = abs(p_curr_entry[1] - p_curr_exit[1])

                            exit_valid = -1.0 <= (p_curr_exit[1] - baseline_y) <= 4.5
                            entry_valid = -1.0 <= (p_curr_entry[1] - baseline_y) <= 4.5

                            if (-0.2 <= dx <= 4.0) and (dy <= 1.2) and exit_valid and entry_valid:
                                # Smooth natural cursive ligature
                                if dx > 0.15:
                                    scoop_y = min(p_curr_exit[1], p_curr_entry[1], baseline_y + 1.2 * self.scale)
                                    mid = (round(p_curr_exit[0] + 0.5 * dx, 3), round(scoop_y, 3))
                                    word_body_stroke.append(mid)
                                word_body_stroke.extend(primary_s)
                            else:
                                current_page_strokes.append({
                                    "type": "stroke",
                                    "line_idx": current_line_idx,
                                    "char": prev_char if prev_char else "word_body",
                                    "points": word_body_stroke
                                })
                                word_body_stroke = list(primary_s)
                        else:
                            if word_body_stroke:
                                current_page_strokes.append({
                                    "type": "stroke",
                                    "line_idx": current_line_idx,
                                    "char": prev_char if prev_char else "word_body",
                                    "points": word_body_stroke
                                })
                            word_body_stroke = list(primary_s)
                    else:
                        # Non-lowercase (uppercase, digit, punctuation)
                        if word_body_stroke:
                            current_page_strokes.append({
                                "type": "stroke",
                                "line_idx": current_line_idx,
                                "char": "word_body",
                                "points": word_body_stroke
                            })
                            word_body_stroke = []
                        for s in bed_char_strokes:
                            current_page_strokes.append({
                                "type": "stroke",
                                "line_idx": current_line_idx,
                                "char": char,
                                "points": s
                            })

                    prev_char = char
                    prev_char_bed_x = char_bed_x
                    prev_exit = (char_bed_x + p_exit[0] * self.scale, baseline_y + p_exit[1] * self.scale)
                    prev_raw_strokes = raw_strokes
                    current_line_x = char_bed_x + adv_mm
                    global_char_idx += 1

                # End of word: flush body and secondary dots/crossbars
                if word_body_stroke:
                    current_page_strokes.append({
                        "type": "stroke",
                        "line_idx": current_line_idx,
                        "char": "word_body",
                        "points": word_body_stroke
                    })
                    word_body_stroke = []
                for s in word_secondary_strokes:
                    current_page_strokes.append({
                        "type": "stroke",
                        "line_idx": current_line_idx,
                        "char": "accent/dot",
                        "points": s
                    })
                word_secondary_strokes = []

                # Space after word
                if w_idx < len(words) - 1:
                    current_line_x += space_width_mm * (1.0 + random.uniform(-0.06, 0.06) * self.humanizer.intensity)

            current_line_idx += 1

        if current_page_strokes or not pages:
            pages.append(current_page_strokes)

        return pages

    def layout_text(self, text: str, start_line: int = 0) -> List[Dict[str, Any]]:
        pages = self.layout_pages(text, start_line)
        return pages[0] if pages else []


class GCodeWriter:
    """Generates Bambu Lab A1 compatible G-code with strict safety checks."""

    BED_LIMIT_X = (5.0, 250.0)
    BED_LIMIT_Y = (5.0, 250.0)

    def __init__(
        self,
        thickness_mm: float = 7.0,
        z_write: Optional[float] = None,
        pen_contact_offset: float = 0.0,
        pen_up_z: float = 3.0,
        dry_run: bool = False,
        speed_write: float = 2400.0,  # mm/min = 40 mm/s
        speed_travel: float = 4800.0, # mm/min = 80 mm/s
        speed_z: float = 1200.0,      # mm/min = 20 mm/s
        home_on_start: bool = False
    ):
        self.thickness = thickness_mm
        self.z_write = z_write
        self.pen_contact_offset = pen_contact_offset
        self.lift = pen_up_z
        self.dry_run = dry_run
        self.speed_write = speed_write
        self.speed_travel = speed_travel
        self.speed_z = speed_z
        self.home_on_start = home_on_start

        # Calculate writing and safe travel heights
        dry_offset = 10.0 if dry_run else 0.0
        base_surface = z_write if z_write is not None else self.thickness
        self.z_down = round(base_surface + self.pen_contact_offset + dry_offset, 2)
        self.z_up = round(base_surface + self.lift + dry_offset, 2)
        self.z_safe_park = round(base_surface + 35.0, 2)

    def validate_bounds(self, strokes: List[Dict[str, Any]]) -> Tuple[float, float, float, float]:
        """Ensures all coordinates lie strictly within Bambu A1 bed dimensions."""
        all_pts = [pt for s in strokes for pt in s["points"]]
        if not all_pts:
            raise ValueError("No strokes to write!")

        xs = [pt[0] for pt in all_pts]
        ys = [pt[1] for pt in all_pts]
        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)

        if min_x < self.BED_LIMIT_X[0] or max_x > self.BED_LIMIT_X[1]:
            raise ValueError(
                f"X bounds [{min_x:.1f}, {max_x:.1f}] exceed safe Bambu bed limit "
                f"[{self.BED_LIMIT_X[0]}, {self.BED_LIMIT_X[1]}] mm!"
            )
        if min_y < self.BED_LIMIT_Y[0] or max_y > self.BED_LIMIT_Y[1]:
            raise ValueError(
                f"Y bounds [{min_y:.1f}, {max_y:.1f}] exceed safe Bambu bed limit "
                f"[{self.BED_LIMIT_Y[0]}, {self.BED_LIMIT_Y[1]}] mm!"
            )
        if min_x < 18.0 and min_y < 28.0:
            raise ValueError(
                f"Coordinates [{min_x:.1f}, {min_y:.1f}] encroach on Bambu A1 front-left cutter lever zone (X<18, Y<28)!"
            )

        return min_x, max_x, min_y, max_y

    def generate(self, strokes: List[Dict[str, Any]], layout: Optional[NotebookLayout] = None) -> str:
        min_x, max_x, min_y, max_y = self.validate_bounds(strokes)

        total_strokes = len(strokes)
        total_points = sum(len(s["points"]) for s in strokes)

        # Estimate write length in mm
        draw_distance_mm = 0.0
        for s in strokes:
            pts = s["points"]
            for i in range(len(pts) - 1):
                dx = pts[i+1][0] - pts[i][0]
                dy = pts[i+1][1] - pts[i][1]
                draw_distance_mm += math.hypot(dx, dy)

        est_time_sec = (draw_distance_mm / (self.speed_write / 60.0)) + (total_strokes * 0.4)
        est_min = est_time_sec / 60.0

        lines = []
        lines.append("; ===============================================================")
        lines.append("; BAMBU LAB A1 - PEN PLOTTER G-CODE (NOTEBOOK WRITER)")
        if self.z_write is not None:
            lines.append(f"; Explicit Z Write   : {self.z_write:.2f} mm")
        else:
            lines.append(f"; Notebook Thickness : {self.thickness:.2f} mm")
        lines.append(f"; Pen Down (Writing) : Z={self.z_down:.2f} mm")
        lines.append(f"; Pen Up (Travel)    : Z={self.z_up:.2f} mm")
        lines.append(f"; Dry-Run Active     : {'YES (+10mm mid-air)' if self.dry_run else 'NO (Pen touches paper)'}")
        lines.append(f"; Bounding Box X     : {min_x:.1f} to {max_x:.1f} mm")
        lines.append(f"; Bounding Box Y     : {min_y:.1f} to {max_y:.1f} mm")
        lines.append(f"; Total Strokes      : {total_strokes}")
        lines.append(f"; Total Pen Path     : {draw_distance_mm:.1f} mm")
        lines.append(f"; Estimated Time     : {est_min:.1f} minutes")
        lines.append("; ===============================================================")
        lines.append("")

        # Header: Safety commands
        lines.append("; --- INIZIALIZZAZIONE SICURA BAMBU A1 ---")
        lines.append("M1002 gcode_claim_action : 0 ; Registra azione gcode su firmware Bambu")
        lines.append("M104 S0 ; Disattiva riscaldatore Hotend")
        lines.append("M140 S0 ; Disattiva riscaldatore Piatto")
        lines.append("M106 S0 ; Disattiva ventola di raffreddamento")
        lines.append("M106 P1 S0 ; Disattiva ventola parte")
        lines.append("M106 P2 S0 ; Disattiva ventola ausiliaria")
        lines.append("G21     ; Unita in millimetri")
        lines.append("G90     ; Coordinate assolute")
        lines.append("M83     ; Estrusione relativa (sicurezza)")
        lines.append("M204 P1200 T1200 ; Limita accelerazioni per non far vibrare il quaderno")
        lines.append("")

        if self.home_on_start:
            lines.append("G28 ; Azzeramento assi (Home) per calibrare quota Z del piatto")
            lines.append(f"G0 Z10.00 F{self.speed_z:.0f} ; Solleva toolhead a quota di disimpegno")
            if layout:
                target_x = layout.nb_x + layout.margin_left
                target_y = layout.get_line_baseline_y(0)
                lines.append(f"G0 X{target_x:.1f} Y{target_y:.1f} F{self.speed_travel:.0f} ; Posiziona sopra inizio pagina")
        else:
            lines.append("; NOTA: La stampante deve essere gia azzerata prima di questo file.")
            lines.append(f"G0 Z{self.z_up:.2f} F{self.speed_z:.0f} ; Solleva asse Z a quota di sicurezza penna")

        lines.append("")
        lines.append("; --- INIZIO SCRITTURA TESTO ---")

        current_z = self.z_up
        last_pt: Optional[Tuple[float, float]] = None

        for s_idx, stroke in enumerate(strokes):
            pts = stroke["points"]
            if not pts:
                continue

            first_pt = pts[0]

            # Check if continuous stroke can chain without lifting pen
            can_chain = (
                abs(current_z - self.z_down) < 0.01 and
                last_pt is not None and
                math.hypot(first_pt[0] - last_pt[0], first_pt[1] - last_pt[1]) < 0.15
            )

            if not can_chain:
                # 1. Ensure pen is UP before moving to start of stroke
                if abs(current_z - self.z_up) > 0.01:
                    lines.append(f"G0 Z{self.z_up:.2f} F{self.speed_z:.0f} ; Penna SU")
                    current_z = self.z_up

                # 2. Travel move to stroke start
                lines.append(f"G0 X{first_pt[0]:.2f} Y{first_pt[1]:.2f} F{self.speed_travel:.0f}")

                # 3. Pen DOWN
                lines.append(f"G1 Z{self.z_down:.2f} F{self.speed_z:.0f} ; Penna GIU (tratto {s_idx+1}/{total_strokes})")
                current_z = self.z_down

            # 4. Draw stroke points (or make contact dot if single point)
            if len(pts) <= 1:
                lines.append("G4 P40 ; Micro-tocco inchiostro istantaneo per puntino")
            else:
                for pt in pts[1:]:
                    lines.append(f"G1 X{pt[0]:.2f} Y{pt[1]:.2f} F{self.speed_write:.0f}")

            last_pt = pts[-1]

        # Finish: Lift pen and park in safe center-back
        lines.append("")
        lines.append("; --- FINE SCRITTURA & PARCHEGGIO ---")
        lines.append(f"G0 Z{self.z_safe_park:.2f} F{self.speed_z:.0f} ; Solleva penna a quota libera")
        lines.append(f"G0 X128.0 Y240.0 F{self.speed_travel:.0f} ; Parcheggia toolhead in centro posteriore sicuro")
        lines.append("M400 ; Attendi completamento movimenti prima di rilasciare i motori")
        lines.append("M84 X Y Z ; Disattiva motori (fine lavoro)")
        lines.append("; ===============================================================")

        return "\n".join(lines)


class PreviewRenderer:
    """Renders visual previews of the notebook with realistic ruling and ink."""

    @staticmethod
    def render_png(layout: NotebookLayout, strokes: List[Dict[str, Any]], output_png_path: str, dpi: int = 200):
        if not Image or not ImageDraw:
            print("Pillow not installed; skipping PNG preview.")
            return

        scale = dpi / 25.4
        img_w = int(round(layout.nb_w * scale))
        img_h = int(round(layout.nb_h * scale))

        # Cream / notebook paper background (authentic Italian quaderno page)
        img = Image.new('RGB', (img_w, img_h), '#fdfdf9')
        draw = ImageDraw.Draw(img)

        # Coordinate transform from bed mm to notebook pixel (origin top-left of notebook)
        def to_px(bx, by):
            nx = bx - layout.nb_x
            # in bed coords: top of notebook is nb_y + nb_h
            ny = (layout.nb_y + layout.nb_h) - by
            return int(round(nx * scale)), int(round(ny * scale))

        # 1. Draw notebook ruling
        line_color = '#c2d5e8'        # soft blue/grey Italian quaderno 1R ruling
        margin_line_color = '#ff9aa2' # soft red margin line (only if enabled)

        # Red vertical left margin line (only for primary school or when explicitly requested)
        if layout.red_margin and layout.grid_type != 'blank':
            margin_x_px = int(round(layout.margin_left * scale))
            draw.line([margin_x_px, 0, margin_x_px, img_h], fill=margin_line_color, width=max(1, int(round(0.8 * scale))))

        # Ruled horizontal lines (30 lines for 1R)
        if layout.grid_type in ['lines', 'squares']:
            for l_idx in range(layout.max_lines + 1):
                baseline_bed_y = layout.get_line_baseline_y(l_idx)
                _, y_px = to_px(layout.nb_x, baseline_bed_y)
                if 0 <= y_px < img_h:
                    draw.line([0, y_px, img_w, y_px], fill=line_color, width=1)

        # If squares / quadretti, draw vertical lines as well
        if layout.grid_type == 'squares':
            grid_step_px = int(round(layout.line_spacing * scale))
            for x_px in range(0, img_w, grid_step_px):
                draw.line([x_px, 0, x_px, img_h], fill=line_color, width=1)

        # 2. Draw ink strokes (Authentic Bic Cristal Royal Blue)
        ink_color = '#153675'
        pen_width_px = max(2, int(round(0.42 * scale)))

        for stroke in strokes:
            pts = stroke["points"]
            if len(pts) < 2:
                if len(pts) == 1:
                    px, py = to_px(pts[0][0], pts[0][1])
                    dot_r = max(1, int(round(0.28 * scale)))
                    draw.ellipse([px-dot_r, py-dot_r, px+dot_r, py+dot_r], fill=ink_color)
                continue

            pixel_pts = [to_px(p[0], p[1]) for p in pts]
            draw.line(pixel_pts, fill=ink_color, width=pen_width_px, joint='round')

        img.save(output_png_path, "PNG")
        print(f"Visual preview saved: {output_png_path}")

    @staticmethod
    def render_svg(layout: NotebookLayout, strokes: List[Dict[str, Any]], output_svg_path: str):
        if not svgwrite:
            print("svgwrite not installed; skipping SVG preview.")
            return

        dwg = svgwrite.Drawing(
            output_svg_path,
            size=(f"{layout.nb_w}mm", f"{layout.nb_h}mm"),
            viewBox=f"0 0 {layout.nb_w} {layout.nb_h}"
        )

        # Background
        dwg.add(dwg.rect(insert=(0, 0), size=(layout.nb_w, layout.nb_h), fill="#fdfdf9"))

        # Red left margin line (only if enabled)
        if layout.red_margin and layout.grid_type != 'blank':
            dwg.add(dwg.line(
                start=(layout.margin_left, 0),
                end=(layout.margin_left, layout.nb_h),
                stroke="#ff9aa2", stroke_width=0.4
            ))

        # Ruling horizontal lines
        if layout.grid_type in ['lines', 'squares']:
            for l_idx in range(layout.max_lines + 2):
                baseline_bed_y = layout.get_line_baseline_y(l_idx)
                y_nb = (layout.nb_y + layout.nb_h) - baseline_bed_y
                if 0 <= y_nb <= layout.nb_h:
                    dwg.add(dwg.line(start=(0, y_nb), end=(layout.nb_w, y_nb), stroke="#c9d6e4", stroke_width=0.25))

        # Ruling vertical lines for squares
        if layout.grid_type == 'squares':
            x_step = layout.line_spacing
            x_pos = 0.0
            while x_pos <= layout.nb_w:
                dwg.add(dwg.line(start=(x_pos, 0), end=(x_pos, layout.nb_h), stroke="#c9d6e4", stroke_width=0.25))
                x_pos += x_step

        # Strokes
        for stroke in strokes:
            pts = stroke["points"]
            if not pts:
                continue
            svg_pts = []
            for (bx, by) in pts:
                nx = bx - layout.nb_x
                ny = (layout.nb_y + layout.nb_h) - by
                svg_pts.append((round(nx, 2), round(ny, 2)))

            if len(svg_pts) == 1:
                dwg.add(dwg.circle(center=svg_pts[0], r=0.25, fill="#1b2a4a"))
            else:
                dwg.add(dwg.polyline(points=svg_pts, fill="none", stroke="#1b2a4a", stroke_width=0.4, stroke_linecap="round", stroke_linejoin="round"))

        dwg.save()
        print(f"SVG preview saved: {output_svg_path}")


def package_gcode_3mf(gcode_path: str, output_3mf_path: str, preview_png_path: Optional[str] = None):
    """Packages G-code and preview thumbnail into Bambu-compatible .gcode.3mf container for SD card / touchscreen."""
    import zipfile, hashlib

    with open(gcode_path, 'r', encoding='utf-8') as f:
        gcode_content = f.read()

    # Prepend required Bambu header if not present
    if "; HEADER_BLOCK_START" not in gcode_content:
        header_block = (
            "; HEADER_BLOCK_START\n"
            "; BambuStudio 02.04.00.70\n"
            "; model printing time: 2m 30s; total estimated time: 2m 30s\n"
            "; total layer number: 1\n"
            "; total filament length [mm] : 0.00\n"
            "; total filament volume [cm^3] : 0.00\n"
            "; total filament weight [g] : 0.00\n"
            "; model label id: 1\n"
            "; filament_density: 1.24\n"
            "; filament_diameter: 1.75\n"
            "; max_z_height: 6.50\n"
            "; filament: 1\n"
            "; HEADER_BLOCK_END\n\n"
            "; CONFIG_BLOCK_START\n"
            "; bed_temperature = 0\n"
            "; nozzle_temperature = 0\n"
            "; CONFIG_BLOCK_END\n\n"
        )
        gcode_content = header_block + gcode_content

    gcode_bytes = gcode_content.encode('utf-8')
    md5_hash = hashlib.md5(gcode_bytes).hexdigest().upper()

    content_types = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">\n'
        '  <Default Extension="gcode" ContentType="text/x.gcode"/>\n'
        '  <Default Extension="png" ContentType="image/png"/>\n'
        '  <Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>\n'
        '  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>\n'
        '</Types>'
    )

    slice_info = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<config>\n'
        '  <header>\n'
        '    <header_item key="X-BBL-Client-Type" value="slicer"/>\n'
        '    <header_item key="X-BBL-Client-Version" value="02.04.00.70"/>\n'
        '  </header>\n'
        '  <plate>\n'
        '    <metadata key="index" value="1"/>\n'
        '    <metadata key="extruder_type" value="0"/>\n'
        '    <metadata key="nozzle_volume_type" value="0"/>\n'
        '    <metadata key="printer_model_id" value="N2S"/>\n'
        '    <metadata key="nozzle_diameters" value="0.4"/>\n'
        '    <metadata key="timelapse_type" value="-1"/>\n'
        '    <metadata key="prediction" value="150"/>\n'
        '    <metadata key="weight" value="0.00"/>\n'
        '    <metadata key="first_layer_time" value="60"/>\n'
        '    <metadata key="outside" value="false"/>\n'
        '    <metadata key="support_used" value="false"/>\n'
        '    <metadata key="label_object_enabled" value="false"/>\n'
        '    <metadata key="filament_maps" value="1"/>\n'
        '    <metadata key="limit_filament_maps" value="0"/>\n'
        '    <filament id="1" tray_info_idx="GFA00" type="PLA" color="#166534" used_m="0.00" used_g="0.00" group_id="0" nozzle_diameter="0.40" volume_type="Standard"/>\n'
        '  </plate>\n'
        '</config>'
    )

    model_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<model unit="millimeter" xml:lang="en-US" xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02">\n'
        ' <resources></resources>\n'
        ' <build></build>\n'
        '</model>'
    )

    rels_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">\n'
        ' <Relationship Target="/3D/3dmodel.model" Id="rel0" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>\n'
        '</Relationships>'
    )

    model_settings = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<config>\n'
        '  <plate>\n'
        '    <metadata key="plater_id" value="1"/>\n'
        '    <metadata key="gcode_file" value="Metadata/plate_1.gcode"/>\n'
        '    <metadata key="thumbnail_file" value="Metadata/plate_1.png"/>\n'
        '  </plate>\n'
        '</config>'
    )

    with zipfile.ZipFile(output_3mf_path, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr('[Content_Types].xml', content_types)
        zf.writestr('_rels/.rels', rels_xml)
        zf.writestr('3D/3dmodel.model', model_xml)
        zf.writestr('Metadata/slice_info.config', slice_info)
        zf.writestr('Metadata/model_settings.config', model_settings)
        zf.writestr('Metadata/plate_1.gcode', gcode_bytes)
        zf.writestr('Metadata/plate_1.gcode.md5', md5_hash)
        if preview_png_path and os.path.exists(preview_png_path):
            zf.write(preview_png_path, 'Metadata/plate_1.png')
            zf.write(preview_png_path, 'Metadata/plate_1_small.png')


def main():
    parser = argparse.ArgumentParser(
        description="Bambu Lab A1 Notebook Writer - Converts text to realistic handwritten G-code."
    )
    parser.add_argument("--preset", choices=["quaderno-1r", "foglio-singolo", "custom"], default=None, help="Preset geometrico per quaderno italiano 1R o foglio singolo con magneti")
    parser.add_argument("--input", "-i", type=str, help="Path to input text file (.txt)")
    parser.add_argument("--text", "-t", type=str, help="Raw text string to write (alternative to --input)")
    parser.add_argument("--font", "-f", type=str, help="Path to single-line font JSON (defaults to my_handwriting.json or default_cursive_stroke.json)")
    parser.add_argument("--output", "-o", type=str, default="output/pagina_quaderno.gcode", help="Output G-code file path")
    parser.add_argument("--preview-png", type=str, default="output/anteprima_pagina.png", help="Output PNG preview file path")
    parser.add_argument("--preview-svg", type=str, default="output/anteprima_pagina.svg", help="Output SVG preview file path")

    # Geometry & ruling
    parser.add_argument("--thickness", type=float, default=7.0, help="Notebook thickness in mm (CRITICAL for safety, default: 7.0)")
    parser.add_argument("--z-down", "--z-write", type=float, default=None, help="Explicit Z height for pen contact on paper in mm (overrides --thickness)")
    parser.add_argument("--pen-offset", type=float, default=0.0, help="Pen contact micro-offset in mm (default: 0.0, e.g. -0.3 for more pressure)")
    parser.add_argument("--pen-up", type=float, default=3.0, help="Pen clearance height above notebook during travel in mm (default: 3.0)")
    parser.add_argument("--dry-run", action="store_true", help="Mid-air test mode: adds +10mm to Z so pen hovers without touching paper")
    parser.add_argument("--home", action="store_true", help="Include G28 in start g-code (with Bambu M400 U1 pause to safely insert pen)")
    parser.add_argument("--no-3mf", action="store_true", help="Do not generate .gcode.3mf container (only raw .gcode)")

    # Notebook dimensions on bed
    parser.add_argument("--notebook-width", type=float, default=148.0, help="Notebook width in mm (default: 148.0 for A5)")
    parser.add_argument("--notebook-height", type=float, default=210.0, help="Notebook height in mm (default: 210.0 for A5)")
    parser.add_argument("--notebook-x", type=float, default=54.0, help="Notebook bed X origin in mm (default: 54.0)")
    parser.add_argument("--notebook-y", type=float, default=23.0, help="Notebook bed Y origin in mm (default: 23.0)")

    # Page layout
    parser.add_argument("--page", type=int, default=None, help="Specific page number to render (1-based). If omitted, renders all pages.")
    parser.add_argument("--grid-type", choices=["lines", "squares", "blank"], default="lines", help="Ruling type (lines, squares, blank)")
    parser.add_argument("--red-margin", action="store_true", help="Draw red vertical margin line (default: False for Italian 1R)")
    parser.add_argument("--line-spacing", "--grid-size", type=float, default=8.0, help="Distance between lines in mm (default: 8.0 for standard notebook)")
    parser.add_argument("--margin-left", type=float, default=25.0, help="Left margin in mm (default: 25.0)")
    parser.add_argument("--margin-right", type=float, default=15.0, help="Right margin in mm (default: 15.0)")
    parser.add_argument("--margin-top", type=float, default=20.0, help="Top margin in mm (default: 20.0)")
    parser.add_argument("--margin-bottom", type=float, default=15.0, help="Bottom margin in mm (default: 15.0)")
    parser.add_argument("--font-size", type=float, default=None, help="Capital letter height in mm (auto-calculated from line spacing if omitted)")
    parser.add_argument("--start-line", type=int, default=0, help="Index of line to start writing on (0-based, default: 0)")

    # Natural handwriting
    parser.add_argument("--humanize", type=float, default=0.6, help="Humanizer intensity 0.0 (mechanical) to 1.5 (heavy natural wobble), default: 0.6")

    # Speeds
    parser.add_argument("--speed-write", type=float, default=2400.0, help="Writing speed in mm/min (default: 2400 mm/min = 40 mm/s)")
    parser.add_argument("--speed-travel", type=float, default=4800.0, help="Travel speed in mm/min (default: 4800 mm/min = 80 mm/s)")
    parser.add_argument("--speed-z", type=float, default=1200.0, help="Z lift speed in mm/min (default: 1200 mm/min = 20 mm/s)")

    args = parser.parse_args()

    if args.preset == "quaderno-1r":
        print("Applicato Preset: Quaderno di Italiano 1R (A4 210x297mm, Righe 8.0mm, Margine Alto 32mm)")
        args.notebook_width = 210.0
        args.notebook_height = 297.0
        args.notebook_x = 23.0
        args.notebook_y = -57.0
        args.line_spacing = 8.0
        args.margin_top = 32.0
        args.margin_bottom = 25.0
        args.margin_left = 22.0
        args.margin_right = 18.0
        if args.font_size is None:
            args.font_size = 7.2
        if args.z_down is None:
            args.z_down = 1.8
        args.pen_up = 4.5
        args.home = True
    elif args.preset == "foglio-singolo":
        print("Applicato Preset: Foglio Singolo A4 con Magneti (Rigatura 1R, 210x297mm)")
        args.notebook_width = 210.0
        args.notebook_height = 297.0
        args.notebook_x = 23.0
        args.notebook_y = -57.0
        args.line_spacing = 8.0
        args.margin_top = 32.0
        args.margin_bottom = 25.0
        args.margin_left = 22.0
        args.margin_right = 18.0
        args.thickness = 0.0
        if args.z_down is None:
            args.z_down = 1.8
        args.pen_up = 4.5
        if args.font_size is None:
            args.font_size = 7.2
        args.home = True
    else:
        if args.font_size is None:
            args.font_size = 7.2

    base_dir = os.path.dirname(os.path.abspath(__file__))

    # Read input text
    text_content = ""
    if args.text is not None:
        text_content = args.text
    elif args.input:
        in_path = os.path.abspath(args.input)
        if not os.path.exists(in_path):
            print(f"Error: Input file not found: {in_path}")
            sys.exit(1)
        with open(in_path, 'r', encoding='utf-8') as f:
            text_content = f.read()
    else:
        # Default fallback sample
        default_in = os.path.join(base_dir, 'input', 'testo_da_scrivere.txt')
        if os.path.exists(default_in):
            print(f"No input specified, using default: {default_in}")
            with open(default_in, 'r', encoding='utf-8') as f:
                text_content = f.read()
        else:
            print("Error: Please provide --input <file.txt> or --text '<text>'")
            sys.exit(1)

    if not text_content.strip():
        print("Warning: Input text is empty or contains only whitespace. No G-code generated.")
        return

    # Determine font and fallback
    my_font = os.path.join(base_dir, 'fonts', 'my_handwriting.json')
    def_font = os.path.join(base_dir, 'fonts', 'default_cursive_stroke.json')

    def count_glyphs(fpath):
        try:
            with open(fpath, 'r', encoding='utf-8') as f:
                d = json.load(f)
                return len(d.get("characters", {}))
        except Exception:
            return 0

    if args.font:
        font_path = os.path.abspath(args.font)
        fallback_font_path = def_font
        print(f"Using explicitly specified font: {font_path}")
    elif os.path.exists(my_font) and count_glyphs(my_font) >= 20:
        font_path = my_font
        fallback_font_path = def_font
        print(f"Using personalized handwriting font: {font_path} ({count_glyphs(my_font)} glyphs, with fallback to default cursive)")
    elif os.path.exists(def_font):
        font_path = def_font
        fallback_font_path = None
        print(f"Using default cursive stroke font: {font_path}")
    elif os.path.exists(my_font):
        font_path = my_font
        fallback_font_path = def_font
        print(f"Using personalized handwriting font: {font_path}")
    else:
        print(f"Error: Font file not found: {def_font}")
        sys.exit(1)

    font = SingleLineFont(font_path, fallback_font_path=fallback_font_path)

    # Layout text
    layout = NotebookLayout(
        font=font,
        notebook_width=args.notebook_width,
        notebook_height=args.notebook_height,
        notebook_x=args.notebook_x,
        notebook_y=args.notebook_y,
        line_spacing=args.line_spacing,
        margin_left=args.margin_left,
        margin_right=args.margin_right,
        margin_top=args.margin_top,
        margin_bottom=args.margin_bottom,
        font_size_mm=args.font_size,
        grid_type=args.grid_type,
        humanizer_intensity=args.humanize,
        red_margin=args.red_margin
    )

    print("Formatting text onto notebook ruling...")
    pages = layout.layout_pages(text_content, start_line=args.start_line)
    num_pages = len(pages)
    print(f"Text formatted into {num_pages} notebook page(s).")

    if args.page is not None:
        if args.page < 1 or args.page > num_pages:
            print(f"Error: Requested page {args.page}, but document has {num_pages} pages.")
            sys.exit(1)
        target_pages = [(args.page, pages[args.page - 1])]
    else:
        target_pages = list(enumerate(pages, start=1))

    # Base output paths
    out_gcode = os.path.abspath(args.output) if os.path.isabs(args.output) else os.path.join(base_dir, args.output)
    out_png = os.path.abspath(args.preview_png) if os.path.isabs(args.preview_png) else os.path.join(base_dir, args.preview_png)
    out_svg = os.path.abspath(args.preview_svg) if os.path.isabs(args.preview_svg) else os.path.join(base_dir, args.preview_svg)

    writer = GCodeWriter(
        thickness_mm=args.thickness,
        z_write=args.z_down,
        pen_contact_offset=args.pen_offset,
        pen_up_z=args.pen_up,
        dry_run=args.dry_run,
        speed_write=args.speed_write,
        speed_travel=args.speed_travel,
        speed_z=args.speed_z,
        home_on_start=args.home
    )

    for p_num, strokes in target_pages:
        if not strokes:
            print(f"Warning: Page {p_num} has no drawable strokes. Skipping.")
            continue

        if num_pages == 1 or args.page is not None:
            cur_gcode = out_gcode
            cur_png = out_png
            cur_svg = out_svg
        else:
            base_gc, ext_gc = os.path.splitext(out_gcode)
            cur_gcode = f"{base_gc}_pag{p_num}{ext_gc}"
            base_p, ext_p = os.path.splitext(out_png)
            cur_png = f"{base_p}_pag{p_num}{ext_p}"
            base_s, ext_s = os.path.splitext(out_svg)
            cur_svg = f"{base_s}_pag{p_num}{ext_s}"

        os.makedirs(os.path.dirname(cur_gcode), exist_ok=True)
        print(f"\n--- Generazione Pagina {p_num}/{num_pages} ({len(strokes)} tratti penna) ---")

        gcode_text = writer.generate(strokes, layout)
        with open(cur_gcode, 'w', encoding='utf-8') as f:
            f.write(gcode_text)
        print(f"G-code salvato: {cur_gcode}")

        # Previews
        if cur_png:
            os.makedirs(os.path.dirname(cur_png), exist_ok=True)
            PreviewRenderer.render_png(layout, strokes, cur_png)
            try:
                import shutil
                user_dl = os.path.join(os.path.expanduser('~'), 'Downloads', 'anteprima_quaderno_reale.png')
                shutil.copyfile(cur_png, user_dl)
                print(f"Anteprima fotorealistica quaderno salvata in Download: {user_dl}")
            except Exception as e:
                print(f"Avviso copia Download: {e}")
        if cur_svg:
            os.makedirs(os.path.dirname(cur_svg), exist_ok=True)
            PreviewRenderer.render_svg(layout, strokes, cur_svg)

        # Bambu Lab .gcode.3mf container for direct SD card touchscreen printing
        out_3mf = None
        if not args.no_3mf:
            base_no_ext = cur_gcode[:-6] if cur_gcode.endswith(".gcode") else cur_gcode
            out_3mf = f"{base_no_ext}.gcode.3mf"
            package_gcode_3mf(cur_gcode, out_3mf, cur_png if os.path.exists(cur_png) else None)
            print(f"Bambu 3MF pacchetto salvato: {out_3mf}")

        # Automatic synchronization to Google Drive "2 | Second Brain/Scrittura"
        gdrive_dir = "/home/buco-py/GoogleDrive/2 | Second Brain/Scrittura"
        if os.path.exists(gdrive_dir):
            try:
                import shutil
                gd_gcode = os.path.join(gdrive_dir, os.path.basename(cur_gcode))
                shutil.copyfile(cur_gcode, gd_gcode)
                if out_3mf and os.path.exists(out_3mf):
                    gd_3mf = os.path.join(gdrive_dir, os.path.basename(out_3mf))
                    shutil.copyfile(out_3mf, gd_3mf)
                if cur_png and os.path.exists(cur_png):
                    gd_png = os.path.join(gdrive_dir, os.path.basename(cur_png))
                    shutil.copyfile(cur_png, gd_png)
                if cur_svg and os.path.exists(cur_svg):
                    gd_svg = os.path.join(gdrive_dir, os.path.basename(cur_svg))
                    shutil.copyfile(cur_svg, gd_svg)
                print(f"Sincronizzato automaticamente su Google Drive: {gdrive_dir}")
            except Exception as e:
                print(f"Avviso sincronizzazione Google Drive: {e}")


if __name__ == '__main__':
    main()
