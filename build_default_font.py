#!/usr/bin/env python3
"""
build_default_font.py - Generates default_cursive_stroke.json

Converts Hershey Cursive stroke data into a clean, normalized JSON font format,
complete with ASCII characters, Italian accented letters (à, è, é, ì, ò, ù, etc.),
and common typography symbols.
"""

import json
import os
from HersheyFonts import HersheyFonts

def build_font(output_path):
    hf = HersheyFonts()
    hf.load_default_font('cursive')
    glyphs_raw = hf._HersheyFonts__glyphs

    baseline = 9.0
    cap_height = 21.0
    x_height = 9.0
    descender = -12.0

    characters = {}

    # Extract all standard ASCII characters
    for code in range(32, 127):
        char = chr(code)
        glyph = glyphs_raw.get(char)
        if not glyph:
            continue

        left = glyph._HersheyGlyph__left_side
        right = glyph._HersheyGlyph__right_side
        adv_width = float(right - left)

        strokes = []
        for raw_stroke in glyph._HersheyGlyph__strokes:
            stroke = []
            for pt in raw_stroke:
                x = round(float(pt[0] - left), 3)
                y = round(float(-(pt[1] - baseline)), 3)
                stroke.append([x, y])
            if stroke:
                strokes.append(stroke)

        characters[char] = {
            "advance_width": adv_width,
            "strokes": strokes
        }

    # Ensure space character is properly defined
    if ' ' not in characters or not characters[' ']['advance_width']:
        characters[' '] = {
            "advance_width": 12.0,
            "strokes": []
        }
    else:
        characters[' ']['strokes'] = []
        if characters[' ']['advance_width'] <= 0:
            characters[' ']['advance_width'] = 12.0

    # Helper to create accented glyph from base char
    def add_accented(target_char, base_char, accent_type, is_uppercase=False):
        if base_char not in characters:
            return
        base_data = characters[base_char]
        adv_width = base_data["advance_width"]
        new_strokes = [list(s) for s in base_data["strokes"]]

        # Find horizontal center of base character
        all_x = [pt[0] for s in new_strokes for pt in s]
        center_x = (min(all_x) + max(all_x)) / 2.0 if all_x else adv_width / 2.0

        if is_uppercase:
            y_top = 26.0
            y_bot = 22.5
        else:
            y_top = 14.5
            y_bot = 11.0

        if accent_type == 'grave':  # ` (top-left to bottom-right)
            accent_stroke = [
                [round(center_x - 2.5, 3), round(y_top, 3)],
                [round(center_x + 1.5, 3), round(y_bot, 3)]
            ]
        elif accent_type == 'acute':  # ´ (top-right to bottom-left)
            accent_stroke = [
                [round(center_x + 2.5, 3), round(y_top, 3)],
                [round(center_x - 1.5, 3), round(y_bot, 3)]
            ]
        elif accent_type == 'circumflex':  # ^
            accent_stroke = [
                [round(center_x - 2.5, 3), round(y_bot, 3)],
                [round(center_x, 3), round(y_top, 3)],
                [round(center_x + 2.5, 3), round(y_bot, 3)]
            ]
        else:
            return

        # For 'ì', remove the dot if present (stroke with small bounding box near y=11)
        if base_char == 'i':
            filtered_strokes = []
            for s in new_strokes:
                s_ys = [p[1] for p in s]
                if min(s_ys) >= 10.0:
                    continue  # skip the dot
                filtered_strokes.append(s)
            new_strokes = filtered_strokes

        new_strokes.append(accent_stroke)
        characters[target_char] = {
            "advance_width": adv_width,
            "strokes": new_strokes
        }

    # Italian lowercase accented letters
    add_accented('à', 'a', 'grave', False)
    add_accented('è', 'e', 'grave', False)
    add_accented('é', 'e', 'acute', False)
    add_accented('ì', 'i', 'grave', False)
    add_accented('í', 'i', 'acute', False)
    add_accented('ò', 'o', 'grave', False)
    add_accented('ù', 'u', 'grave', False)

    # Italian uppercase accented letters
    add_accented('À', 'A', 'grave', True)
    add_accented('È', 'E', 'grave', True)
    add_accented('É', 'E', 'acute', True)
    add_accented('Ì', 'I', 'grave', True)
    add_accented('Ò', 'O', 'grave', True)
    add_accented('Ù', 'U', 'grave', True)

    # Additional typographical symbols
    # Euro symbol €
    if 'C' in characters:
        c_strokes = [list(s) for s in characters['C']["strokes"]]
        c_width = characters['C']["advance_width"]
        # Add two horizontal bars
        c_strokes.append([[round(c_width * 0.1, 3), 12.0], [round(c_width * 0.7, 3), 12.0]])
        c_strokes.append([[round(c_width * 0.1, 3), 9.0], [round(c_width * 0.7, 3), 9.0]])
        characters['€'] = {
            "advance_width": c_width,
            "strokes": c_strokes
        }

    # Degree symbol °
    characters['°'] = {
        "advance_width": 10.0,
        "strokes": [
            [[3.0, 18.0], [5.0, 20.0], [7.0, 18.0], [5.0, 16.0], [3.0, 18.0]]
        ]
    }

    # Italian quotation marks « »
    characters['«'] = {
        "advance_width": 12.0,
        "strokes": [
            [[5.0, 7.0], [2.0, 4.5], [5.0, 2.0]],
            [[9.0, 7.0], [6.0, 4.5], [9.0, 2.0]]
        ]
    }
    characters['»'] = {
        "advance_width": 12.0,
        "strokes": [
            [[2.0, 7.0], [5.0, 4.5], [2.0, 2.0]],
            [[6.0, 7.0], [9.0, 4.5], [6.0, 2.0]]
        ]
    }
    # Curly quotes
    characters['“'] = characters.get('"', {"advance_width": 10.0, "strokes": []})
    characters['”'] = characters.get('"', {"advance_width": 10.0, "strokes": []})
    characters['’'] = characters.get("'", {"advance_width": 6.0, "strokes": []})

    font_data = {
        "name": "Hershey Cursive Single-Line",
        "units_per_em": 32,
        "cap_height": cap_height,
        "x_height": x_height,
        "descender": descender,
        "character_count": len(characters),
        "characters": characters
    }

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(font_data, f, indent=2, ensure_ascii=False)

    print(f"Font successfully built: {output_path}")
    print(f"Total characters: {len(characters)}")

if __name__ == '__main__':
    base_dir = os.path.dirname(os.path.abspath(__file__))
    out_file = os.path.join(base_dir, 'fonts', 'default_cursive_stroke.json')
    build_font(out_file)
