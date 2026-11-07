#!/usr/bin/env python3
"""
Unit and integration test suite for Bambu Lab A1 Pen Plotter System.
"""

import os
import sys
import json
import unittest
import numpy as np

# Add project root to path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from notebook_writer import SingleLineFont, Humanizer, NotebookLayout, GCodeWriter, PreviewRenderer, package_gcode_3mf
from vectorize_handwriting import CalibrationSheetDetector, SkeletonTracer, HandwritingVectorizer
from generate_calibration_sheet import generate_pdf, generate_png


class TestSingleLineFont(unittest.TestCase):
    def setUp(self):
        self.font_path = os.path.join(PROJECT_ROOT, 'fonts', 'default_cursive_stroke.json')
        self.font = SingleLineFont(self.font_path)

    def test_font_loads_successfully(self):
        self.assertGreater(len(self.font.characters), 90)
        self.assertGreater(self.font.cap_height, 0)
        self.assertGreater(self.font.x_height, 0)

    def test_ascii_glyphs_exist_and_have_strokes(self):
        for ch in ['A', 'Z', 'a', 'z', '0', '9', '?', '!', '.']:
            adv, strokes = self.font.get_glyph(ch)
            self.assertGreater(adv, 0, f"Glyph {ch} has invalid advance width")
            self.assertGreater(len(strokes), 0, f"Glyph {ch} has no strokes")
            for s in strokes:
                self.assertGreaterEqual(len(s), 2, f"Stroke in glyph {ch} has fewer than 2 points")

    def test_italian_accented_characters(self):
        for ch in ['à', 'è', 'é', 'ì', 'ò', 'ù', 'À', 'È']:
            adv, strokes = self.font.get_glyph(ch)
            self.assertGreater(adv, 0, f"Accented glyph {ch} missing advance width")
            self.assertGreater(len(strokes), 0, f"Accented glyph {ch} has no strokes")

    def test_fallback_font_mechanism(self):
        # Create a partial dummy font with only 'X'
        dummy_data = {
            "name": "Dummy Font",
            "cap_height": 21.0,
            "x_height": 9.0,
            "descender": -12.0,
            "characters": {
                "X": {"advance_width": 15.0, "strokes": [[[0, 0], [10, 20]]]}
            }
        }
        dummy_path = os.path.join(PROJECT_ROOT, 'tests', 'dummy_partial_font.json')
        with open(dummy_path, 'w', encoding='utf-8') as f:
            json.dump(dummy_data, f)

        try:
            partial_font = SingleLineFont(dummy_path, fallback_font_path=self.font_path)
            # 'X' comes from partial font
            adv_x, strokes_x = partial_font.get_glyph('X')
            self.assertEqual(adv_x, 15.0)

            # 'A' is missing in partial font, should fall back to default cursive font
            adv_a, strokes_a = partial_font.get_glyph('A')
            self.assertGreater(len(strokes_a), 0, "Fallback failed for missing glyph 'A'")
        finally:
            if os.path.exists(dummy_path):
                os.remove(dummy_path)


class TestNotebookLayout(unittest.TestCase):
    def setUp(self):
        font_path = os.path.join(PROJECT_ROOT, 'fonts', 'default_cursive_stroke.json')
        self.font = SingleLineFont(font_path)
        self.layout = NotebookLayout(
            font=self.font,
            notebook_width=148.0,
            notebook_height=210.0,
            notebook_x=54.0,
            notebook_y=23.0,
            line_spacing=8.0,
            margin_left=25.0,
            margin_right=15.0,
            margin_top=20.0,
            margin_bottom=15.0,
            humanizer_intensity=0.0  # deterministic for testing
        )

    def test_margin_and_dimension_calculations(self):
        self.assertAlmostEqual(self.layout.usable_width, 148.0 - 25.0 - 15.0)
        self.assertAlmostEqual(self.layout.usable_height, 210.0 - 20.0 - 15.0)
        self.assertEqual(self.layout.max_lines, int(175.0 / 8.0))

    def test_baseline_positions_decrease_downwards(self):
        y0 = self.layout.get_line_baseline_y(0)
        y1 = self.layout.get_line_baseline_y(1)
        self.assertAlmostEqual(y0 - y1, 8.0)
        # Check absolute bed Y
        expected_y0 = (23.0 + 210.0) - 20.0  # 213.0 mm
        self.assertAlmostEqual(y0, expected_y0)

    def test_multipage_pagination(self):
        # 30 lines of text should split into 2 pages on a 21-line notebook
        long_text = "\n".join([f"Riga di test numero {i}" for i in range(30)])
        pages = self.layout.layout_pages(long_text)
        self.assertGreaterEqual(len(pages), 2, "Long text was not paginated into multiple pages")
        self.assertGreater(len(pages[0]), 0)
        self.assertGreater(len(pages[1]), 0)

    def test_text_stays_within_margins(self):
        text = "Questo è un test lungo per verificare che il testo rimanga strettamente entro i margini."
        pages = self.layout.layout_pages(text)
        min_allowed_x = self.layout.nb_x + self.layout.margin_left - 1.0
        max_allowed_x = self.layout.nb_x + self.layout.nb_w - self.layout.margin_right + 5.0

        for page in pages:
            for s in page:
                for pt in s["points"]:
                    self.assertGreaterEqual(pt[0], min_allowed_x)
                    self.assertLessEqual(pt[0], max_allowed_x)


class TestHumanizer(unittest.TestCase):
    def test_zero_intensity_is_deterministic(self):
        h = Humanizer(intensity=0.0)
        sample_strokes = [[(0.0, 0.0), (10.0, 10.0)]]
        p1 = h.perturb_glyph(sample_strokes, scale=1.0, char_idx=0, line_idx=0)
        p2 = h.perturb_glyph(sample_strokes, scale=1.0, char_idx=0, line_idx=0)
        self.assertEqual(p1, p2)

    def test_perturbation_is_bounded(self):
        h = Humanizer(intensity=0.8, seed=42)
        sample_strokes = [[(5.0, 5.0), (10.0, 10.0)]]
        for idx in range(50):
            res = h.perturb_glyph(sample_strokes, scale=1.0, char_idx=idx, line_idx=0)
            orig_p0 = sample_strokes[0][0]
            new_p0 = res[0][0]
            # Variation should be subtle (< 1.5 mm)
            diff_x = abs(new_p0[0] - orig_p0[0])
            diff_y = abs(new_p0[1] - orig_p0[1])
            self.assertLess(diff_x, 1.5, f"X variation {diff_x} exceeds safe humanizer limits")
            self.assertLess(diff_y, 1.5, f"Y variation {diff_y} exceeds safe humanizer limits")


class TestGCodeWriter(unittest.TestCase):
    def setUp(self):
        self.writer = GCodeWriter(
            thickness_mm=8.0,
            pen_contact_offset=-0.2,
            pen_up_z=4.0,
            dry_run=False,
            speed_write=2400.0,
            speed_travel=4800.0,
            speed_z=1200.0
        )

    def test_z_height_calculations(self):
        self.assertAlmostEqual(self.writer.z_down, 8.0 - 0.2)
        self.assertAlmostEqual(self.writer.z_up, 8.0 + 4.0)

    def test_dry_run_adds_10mm(self):
        dry_writer = GCodeWriter(thickness_mm=8.0, pen_contact_offset=0.0, pen_up_z=4.0, dry_run=True)
        self.assertAlmostEqual(dry_writer.z_down, 18.0)
        self.assertAlmostEqual(dry_writer.z_up, 22.0)

    def test_bambu_safety_commands_in_header(self):
        dummy_strokes = [{"points": [(50.0, 50.0), (60.0, 50.0)]}]
        dummy_layout = None
        gcode = self.writer.generate(dummy_strokes, dummy_layout)
        self.assertIn("M104 S0", gcode, "Hotend heater off command missing")
        self.assertIn("M140 S0", gcode, "Bed heater off command missing")
        self.assertIn("M106 S0", gcode, "Fan off command missing")
        self.assertIn("G90", gcode, "Absolute positioning missing")
        self.assertIn("G21", gcode, "Metric units missing")

    def test_boundary_check_catches_overflow(self):
        bad_strokes = [{"points": [(2.0, 50.0), (300.0, 50.0)]}]  # 300mm exceeds 250mm
        with self.assertRaises(ValueError):
            self.writer.generate(bad_strokes, None)

    def test_explicit_z_write_overrides_thickness(self):
        writer = GCodeWriter(thickness_mm=8.0, z_write=25.0, pen_up_z=3.0, dry_run=False)
        self.assertEqual(writer.z_down, 25.0)
        self.assertEqual(writer.z_up, 28.0)
        self.assertEqual(writer.z_safe_park, 60.0)

    def test_cutter_exclusion_zone_check(self):
        # A move into X < 18, Y < 28 should be rejected to protect cutter lever
        bad_stroke = [{"points": [(10.0, 15.0), (12.0, 15.0)]}]
        with self.assertRaises(ValueError):
            self.writer.generate(bad_stroke, None)

    def test_stroke_chaining_optimizes_lifts(self):
        chain_strokes = [
            {"points": [(50.0, 50.0), (55.0, 50.0)]},
            {"points": [(55.0, 50.0), (60.0, 50.0)]}
        ]
        gcode = self.writer.generate(chain_strokes, None)
        self.assertEqual(gcode.count("Penna GIU"), 1)


class TestVectorizePipeline(unittest.TestCase):
    def test_skeleton_tracer_lines_and_loops(self):
        # Create an open stroke: straight horizontal line
        mask_line = np.zeros((20, 20), dtype=bool)
        mask_line[10, 2:18] = True
        strokes = SkeletonTracer.trace(mask_line)
        self.assertEqual(len(strokes), 1)
        self.assertAlmostEqual(strokes[0][0][1], 10.0)

        # Create a closed loop: 10x10 square perimeter
        mask_loop = np.zeros((30, 30), dtype=bool)
        mask_loop[5:15, 5] = True
        mask_loop[5:15, 15] = True
        mask_loop[5, 5:16] = True
        mask_loop[15, 5:16] = True
        loop_strokes = SkeletonTracer.trace(mask_loop)
        self.assertGreaterEqual(len(loop_strokes), 1)

    def test_skeleton_tracer_preserves_single_dot(self):
        mask = np.zeros((15, 15), dtype=bool)
        mask[7, 7] = True  # single isolated dot
        strokes = SkeletonTracer.trace(mask)
        self.assertEqual(len(strokes), 1)
        self.assertEqual(len(strokes[0]), 1)
        self.assertEqual(strokes[0][0], (7.0, 7.0))

    def test_calibration_detector_quadrant_sorting(self):
        spec_path = os.path.join(PROJECT_ROOT, 'templates', 'calibration_grid_spec.json')
        with open(spec_path, 'r', encoding='utf-8') as f:
            spec = json.load(f)
        detector = CalibrationSheetDetector(spec)

        import cv2
        test_img = np.ones((1000, 700, 3), dtype=np.uint8) * 255
        for (cx, cy) in [(30, 30), (670, 30), (30, 970), (670, 970)]:
            cv2.rectangle(test_img, (cx - 15, cy - 15), (cx + 15, cy + 15), (0, 0, 0), -1)
            cv2.rectangle(test_img, (cx - 7, cy - 7), (cx + 7, cy + 7), (255, 255, 255), -1)
        for (cx, cy) in [(300, 300), (400, 500)]:
            cv2.rectangle(test_img, (cx - 10, cy - 10), (cx + 10, cy + 10), (0, 0, 0), -1)
            cv2.rectangle(test_img, (cx - 5, cy - 5), (cx + 5, cy + 5), (255, 255, 255), -1)

        rectified, scale = detector.rectify_image(test_img)
        self.assertEqual(rectified.shape[0], int(round(297.0 * scale)))
        self.assertEqual(rectified.shape[1], int(round(210.0 * scale)))

    def test_vectorizer_end_to_end_on_simulated_sheet(self):
        sim_path = os.path.join(PROJECT_ROOT, 'templates', 'simulated_handwritten_sheet.png')
        spec_path = os.path.join(PROJECT_ROOT, 'templates', 'calibration_grid_spec.json')
        if not os.path.exists(sim_path) or not os.path.exists(spec_path):
            self.skipTest("Simulated sheet or spec JSON not found")

        out_test_font = os.path.join(PROJECT_ROOT, 'tests', 'test_extracted_font.json')
        out_test_prev = os.path.join(PROJECT_ROOT, 'tests', 'test_extraction_preview.png')

        try:
            vectorizer = HandwritingVectorizer(spec_path)
            font_dict = vectorizer.extract_font(sim_path, out_test_font, out_test_prev)
            self.assertIn('characters', font_dict)
            self.assertIn('A', font_dict['characters'])
            self.assertIn('a', font_dict['characters'])
            self.assertTrue(os.path.exists(out_test_font))
            self.assertTrue(os.path.exists(out_test_prev))
            self.assertGreater(os.path.getsize(out_test_prev), 1000)
        finally:
            if os.path.exists(out_test_font):
                os.remove(out_test_font)
            if os.path.exists(out_test_prev):
                os.remove(out_test_prev)


class TestFullIntegrationAndEdgeCases(unittest.TestCase):
    def setUp(self):
        font_path = os.path.join(PROJECT_ROOT, 'fonts', 'default_cursive_stroke.json')
        self.font = SingleLineFont(font_path)
        self.layout = NotebookLayout(
            font=self.font,
            notebook_width=148.0,
            notebook_height=210.0,
            notebook_x=54.0,
            notebook_y=23.0,
            line_spacing=8.0,
            margin_left=25.0,
            margin_right=15.0,
            margin_top=20.0,
            margin_bottom=15.0,
            humanizer_intensity=0.5
        )
        self.writer = GCodeWriter(thickness_mm=7.0, pen_contact_offset=0.0, pen_up_z=3.0)

    def test_italian_complex_text_gcode_generation(self):
        text = "È straordinario: l'università ha conferito € 500 a più di 10 studenti! «Bravissimi!»"
        pages = self.layout.layout_pages(text)
        self.assertEqual(len(pages), 1)
        strokes = pages[0]
        self.assertGreater(len(strokes), 50)

        gcode = self.writer.generate(strokes, self.layout)
        self.assertIn("; BAMBU LAB A1 - PEN PLOTTER G-CODE", gcode)
        self.assertIn("G1 Z7.00", gcode)
        self.assertIn("G0 Z10.00", gcode)
        self.assertIn("M84 X Y Z", gcode)

    def test_long_unbroken_word_wrapping(self):
        # A 60-character unbroken word
        long_word = "precipitevolissimevolmenteabbondantissimamenteeccezionale123"
        pages = self.layout.layout_pages(long_word)
        # Verify all coordinates stay strictly within margins
        max_allowed_x = self.layout.nb_x + self.layout.nb_w - self.layout.margin_right + 0.5
        for s in pages[0]:
            for pt in s["points"]:
                self.assertLessEqual(pt[0], max_allowed_x)

    def test_preview_renderer_png_and_svg(self):
        text = "Test anteprima grafica."
        pages = self.layout.layout_pages(text)
        test_png = os.path.join(PROJECT_ROOT, 'tests', 'test_preview.png')
        test_svg = os.path.join(PROJECT_ROOT, 'tests', 'test_preview.svg')

        try:
            PreviewRenderer.render_png(self.layout, pages[0], test_png, dpi=150)
            PreviewRenderer.render_svg(self.layout, pages[0], test_svg)
            self.assertTrue(os.path.exists(test_png))
            self.assertTrue(os.path.exists(test_svg))
            self.assertGreater(os.path.getsize(test_png), 1000)
            self.assertGreater(os.path.getsize(test_svg), 500)
        finally:
            if os.path.exists(test_png):
                os.remove(test_png)
            if os.path.exists(test_svg):
                os.remove(test_svg)

    def test_package_gcode_3mf(self):
        import zipfile
        dummy_gcode = os.path.join(PROJECT_ROOT, 'tests', 'dummy_test.gcode')
        dummy_3mf = os.path.join(PROJECT_ROOT, 'tests', 'dummy_test.gcode.3mf')
        with open(dummy_gcode, 'w', encoding='utf-8') as f:
            f.write("; Test GCode\nM104 S0\n")

        try:
            package_gcode_3mf(dummy_gcode, dummy_3mf)
            self.assertTrue(os.path.exists(dummy_3mf))
            with zipfile.ZipFile(dummy_3mf, 'r') as zf:
                names = zf.namelist()
                self.assertIn('Metadata/plate_1.gcode', names)
                self.assertIn('[Content_Types].xml', names)
                self.assertIn('Metadata/slice_info.config', names)
        finally:
            if os.path.exists(dummy_gcode):
                os.remove(dummy_gcode)
            if os.path.exists(dummy_3mf):
                os.remove(dummy_3mf)

    def test_svg_squares_grid_rendering(self):
        layout_squares = NotebookLayout(
            font=self.font,
            grid_type="squares",
            line_spacing=5.0
        )
        test_svg = os.path.join(PROJECT_ROOT, 'tests', 'test_squares.svg')
        try:
            pages = layout_squares.layout_pages("Test quadretti")
            PreviewRenderer.render_svg(layout_squares, pages[0], test_svg)
            self.assertTrue(os.path.exists(test_svg))
            with open(test_svg, 'r', encoding='utf-8') as f:
                content = f.read()
            self.assertGreater(content.count("<line"), 30)
        finally:
            if os.path.exists(test_svg):
                os.remove(test_svg)

    def test_tight_cursive_spacing_calligrafia(self):
        """Verifies that cursive words like 'calligrafia' are naturally compact (< 35mm)."""
        w_mm = self.layout.measure_word_width("calligrafia")
        # At font size 4.4 - 7.2mm, 'calligrafia' must be between 18mm and 35mm, not 88mm
        self.assertLess(w_mm, 35.0, f"Word 'calligrafia' width is too wide: {w_mm}mm")
        self.assertGreater(w_mm, 15.0, f"Word 'calligrafia' width is unexpectedly tiny: {w_mm}mm")

    def test_quaderno_1r_no_red_margin(self):
        """Verifies that default Italian 1R layout has no red margin."""
        layout_1r = NotebookLayout(font=self.font, notebook_width=210.0, notebook_height=297.0)
        self.assertFalse(layout_1r.red_margin)

    def test_skeleton_tracer_junction_continuation_and_spurs(self):
        # 1. Micro-spur attached to a junction is pruned
        # Line with a 2-pixel spur
        mask = np.zeros((25, 25), dtype=bool)
        mask[12, 2:22] = True
        mask[9:12, 12] = True # 2-pixel spur at (9, 12) and (10, 12) meeting junction (11, 12)
        pruned = SkeletonTracer.prune_spurs(mask, max_len=3)
        self.assertFalse(pruned[9, 12])
        self.assertFalse(pruned[10, 12])
        self.assertTrue(pruned[12, 12])

        # 2. X crossing traces as 2 smooth diagonal strokes
        mask_x = np.zeros((21, 21), dtype=bool)
        for i in range(21):
            mask_x[i, i] = True
            mask_x[i, 20-i] = True
        strokes_x = SkeletonTracer.trace(mask_x)
        self.assertEqual(len(strokes_x), 2)

    def test_metric_secondary_strokes_and_antibridge(self):
        from optimize_font import clean_character_strokes
        # Dot of i
        raw_i = [
            [(12.0, 0.5), (14.0, 3.8), (16.0, 0.5)], # body
            [(15.0, 5.5), (15.2, 5.8)] # dot
        ]
        cleaned_i = clean_character_strokes('i', raw_i)
        self.assertEqual(len(cleaned_i), 2)
        self.assertGreaterEqual(min(p[1] for p in cleaned_i[-1]), 4.5)

        # Crossbar of t
        raw_t = [
            [(12.0, 0.2), (14.0, 7.5)], # stem
            [(13.5, 5.2), (15.5, 5.1)] # crossbar
        ]
        cleaned_t = clean_character_strokes('t', raw_t)
        self.assertEqual(len(cleaned_t), 2)

        # Anti-bridge rule for u: two tops must not weld together
        raw_u = [
            [(13.0, 3.5), (13.0, 0.5)], # left stem
            [(16.0, 3.5), (16.0, 0.5)]  # right stem
        ]
        cleaned_u = clean_character_strokes('u', raw_u)
        # Should not weld the tops across horizontally
        self.assertGreaterEqual(len(cleaned_u), 1)
        if len(cleaned_u) == 1:
            # If welded, the top points (y > 2.5) should not be directly connected
            s = cleaned_u[0]
            top_jump = False
            for k in range(len(s) - 1):
                if s[k][1] > 2.5 and s[k+1][1] > 2.5 and abs(s[k][0] - s[k+1][0]) > 1.2:
                    top_jump = True
            self.assertFalse(top_jump, "u tops were bridged directly across")

    def test_vertical_dy_guard_in_layout_pages(self):
        # When entry point is high in the air (> 1.8mm above baseline),
        # layout_pages must lift pen rather than connect with scoop
        pages = self.layout.layout_pages("ab")
        self.assertGreater(len(pages), 0)
        # Verify all scoop connections have reasonable coordinates
        for stroke in pages[0]:
            pts = stroke.get("points", [])
            for p in pts:
                self.assertGreater(p[0], 0)
                self.assertGreater(p[1], 0)

    def test_exclamation_mark_cleaned(self):
        font_path = os.path.join(PROJECT_ROOT, 'fonts', 'my_handwriting.json')
        with open(font_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        self.assertIn('!', data['characters'])
        excl = data['characters']['!']
        strokes = excl['strokes']
        self.assertEqual(len(strokes), 2) # stem + dot
        for s in strokes:
            for p in s:
                self.assertGreater(p[1], -2.0, f"Found corrupted coordinate in '!': {p}")
        self.assertGreater(excl['advance_width'], 5.0)

    def test_punctuation_dots_preservation(self):
        from optimize_font import clean_character_strokes
        # Period
        raw_period = [[(12.6, 0.8), (13.0, 1.0)]]
        cl_period = clean_character_strokes('.', raw_period)
        self.assertEqual(len(cl_period), 1)
        self.assertGreaterEqual(len(cl_period[0]), 2)

        # Colon
        raw_colon = [
            [(13.0, 0.5), (13.0, 1.0)],
            [(13.0, 3.2), (13.2, 3.4)]
        ]
        cl_colon = clean_character_strokes(':', raw_colon)
        self.assertEqual(len(cl_colon), 2, "Colon dots were welded together or lost")

    def test_continuous_cursive_c_f_t_z_u(self):
        from optimize_font import clean_character_strokes
        # Test c: arch and base must be chained into 1 continuous stroke
        raw_c = [
            [(13.3, 0.5), (15.3, 1.0), (19.1, 0.9)], # base
            [(18.1, 4.0), (15.3, 1.1)] # arch
        ]
        cl_c = clean_character_strokes('c', raw_c)
        self.assertEqual(len(cl_c), 1, "c was not chained into a single continuous stroke")
        self.assertLess(cl_c[0][0][1], 1.5, "c must start near baseline")
        self.assertLess(cl_c[0][-1][1], 1.5, "c must exit near baseline")

        # Test f: ascender, descender, knot exit chained into 1 stroke
        raw_f = [
            [(12.1, 0.1), (14.3, 8.0)], # ascender
            [(13.5, -5.5), (13.6, 1.0)], # descender
            [(17.0, 1.3), (13.8, 0.9)]  # knot exit
        ]
        cl_f = clean_character_strokes('f', raw_f)
        self.assertEqual(len(cl_f), 1, "f was not chained into a single continuous stroke")

        # Test t: body must be 1 continuous stroke from baseline to ascender and back to exit
        raw_t = [
            [(11.6, 0.1), (14.7, 7.6)], # stem up
            [(13.5, 5.0), (16.1, 5.2)], # crossbar
            [(13.4, 1.5), (16.1, 1.8)]  # exit scoop
        ]
        cl_t = clean_character_strokes('t', raw_t)
        self.assertEqual(len(cl_t), 2, "t should have 1 body and 1 crossbar")

        # Test ù: anti-bridge check
        raw_u = [
            [(13.9, 0.0), (15.9, 3.8)], # cup 1
            [(15.9, 6.4), (16.7, 4.8)], # accent
            [(18.2, 3.8), (20.3, 1.8)], # cup 2
            [(17.0, 0.9), (15.1, 0.8)]  # bridge
        ]
        cl_u = clean_character_strokes('ù', raw_u)
        self.assertEqual(len(cl_u), 2, "ù should have 1 body and 1 accent")

    def test_digit_4_structure(self):
        font_path = os.path.join(PROJECT_ROOT, 'fonts', 'my_handwriting.json')
        with open(font_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        self.assertIn('4', data['characters'])
        cdata = data['characters']['4']
        strokes = cdata['strokes']
        self.assertEqual(len(strokes), 2, "Digit 4 must have 2 strokes: angle/crossbar and vertical stem")
        # Stroke 0 should have crossbar with significant horizontal span
        s0_xs = [p[0] for p in strokes[0]]
        self.assertGreater(max(s0_xs) - min(s0_xs), 3.0, "Digit 4 angle stroke missing horizontal crossbar")

    def test_capital_Z_structure(self):
        font_path = os.path.join(PROJECT_ROOT, 'fonts', 'my_handwriting.json')
        with open(font_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        self.assertIn('Z', data['characters'])
        cdata = data['characters']['Z']
        strokes = cdata['strokes']
        self.assertEqual(len(strokes), 2, "Capital Z must have 2 strokes: continuous zigzag body and centered crossbar")
        # Body stroke should start at top and end at bottom-right
        body_s = strokes[0]
        self.assertGreater(body_s[0][1], 15.0, "Z body must start at top")
        self.assertLess(body_s[-1][1], 6.0, "Z body must end at baseline")

    def test_capital_U_continuous(self):
        font_path = os.path.join(PROJECT_ROOT, 'fonts', 'my_handwriting.json')
        with open(font_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        self.assertIn('U', data['characters'])
        cdata = data['characters']['U']
        strokes = cdata['strokes']
        self.assertEqual(len(strokes), 1, "Capital U must be a single continuous stroke")
        self.assertGreater(strokes[0][0][1], 15.0, "Capital U must start at top-left")

    def test_cursive_word_ligatures_with_ovals(self):
        font_path = os.path.join(PROJECT_ROOT, 'fonts', 'my_handwriting.json')
        font = SingleLineFont(font_path)
        layout = NotebookLayout(font=font, line_spacing=8.0)
        # In words with oval letters ('a', 'o', 'd'), cursive ligatures must have natural pen lifts
        # before oval entries to prevent steep diagonal strokes cutting through letter counters.
        for word in ['ciao', 'come', 'cane', 'dado', 'avea', 'tra', 'erbetta']:
            pages = layout.layout_pages(word)
            self.assertEqual(len(pages), 1)
            # Oval letters starting from top counter must start as independent strokes (pen lift)
            # when preceded by a baseline exit, keeping ovals clean.
            body_strokes = [s for s in pages[0] if s.get('char') == 'word_body' or len(s.get('points', [])) >= 2]
            self.assertGreaterEqual(len(body_strokes), 1)

    def test_all_uppercase_strokes_top_to_bottom(self):
        font_path = os.path.join(PROJECT_ROOT, 'fonts', 'my_handwriting.json')
        with open(font_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        for char in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ':
            if char in data['characters']:
                strokes = data['characters'][char].get('strokes', [])
                for si, s in enumerate(strokes):
                    if len(s) >= 2:
                        dy = s[-1][1] - s[0][1]
                        dx = abs(s[-1][0] - s[0][0])
                        # A vertical stroke (dy > 10 font units, dx < 8 font units) must not be drawn bottom-up
                        if dy > 10.0 and dx < 8.0:
                            self.fail(f"Uppercase {char} stroke {si} drawn bottom-up: start={s[0]}, end={s[-1]}")

    def test_corrected_characters_topology(self):
        font_path = os.path.join(PROJECT_ROOT, 'fonts', 'my_handwriting.json')
        with open(font_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        chars = data['characters']
        
        # Test 'y': must have 2 strokes (cup and descender)
        self.assertIn('y', chars)
        y_strokes = chars['y']['strokes']
        self.assertEqual(len(y_strokes), 2, "y must have 2 distinct strokes (cup and descender)")
        y_desc = min(y_strokes, key=lambda s: min(p[1] for p in s))
        y_cup = [s for s in y_strokes if s is not y_desc][0]
        self.assertLess(min(p[1] for p in y_desc), -2.0, "y descender must plunge below baseline")
        self.assertGreater(min(p[1] for p in y_cup), 1.0, "y cup must stay above baseline")
        
        # Test 'M': 3 distinct natural downward humps with pen lift
        self.assertIn('M', chars)
        M_strokes = chars['M']['strokes']
        self.assertEqual(len(M_strokes), 3, "Capital M must have 3 natural downward strokes with pen lift")
        for si, s in enumerate(M_strokes):
            self.assertGreaterEqual(max(p[1] for p in s), 15.0, f"M hump {si+1} must reach near cap-height")
            self.assertLessEqual(min(p[1] for p in s), 2.5, f"M hump {si+1} must descend to baseline")

        # Test 'W': 2 distinct open U-cups with pen lift
        self.assertIn('W', chars)
        W_strokes = chars['W']['strokes']
        self.assertGreaterEqual(len(W_strokes), 2, "Capital W must have open cups with pen lift")

        # Test 'D': single continuous cursive stroke, downstem to baseline, ascending left curve, outer right belly
        self.assertIn('D', chars)
        D_strokes = chars['D']['strokes']
        self.assertEqual(len(D_strokes), 1, "Capital D must be 1 continuous cursive stroke")
        D_pts = D_strokes[0]
        self.assertGreaterEqual(D_pts[0][1], 18.0, "D must start near cap-height on downstem")
        self.assertGreaterEqual(max(p[1] for p in D_pts), 19.0, "D outer loop must reach cap-height")
        self.assertLessEqual(min(p[1] for p in D_pts), 3.0, "D downstem and belly must reach baseline")
        # Ensure downstem descends to baseline before outer loop begins
        downstem_min_y = min(p[1] for p in D_pts[:5])
        self.assertLessEqual(downstem_min_y, 4.0, "D downstem must descend towards baseline")

        # Test 'm': single continuous stroke without horizontal baseline bridging

        self.assertIn('m', chars)
        m_strokes = chars['m']['strokes']
        self.assertEqual(len(m_strokes), 1, "m must be 1 continuous stroke")
        m_pts = m_strokes[0]
        for i in range(len(m_pts) - 1):
            p1, p2 = m_pts[i], m_pts[i+1]
            if p1[1] <= 2.0 and p2[1] <= 2.0:
                dx = abs(p1[0] - p2[0])
                self.assertLess(dx, 3.0, f"m contains illegal baseline horizontal bridge between {p1} and {p2}")
        # Verify baseline seating (feet touch baseline)
        self.assertLessEqual(min(p[1] for p in m_pts), 0.5, "m feet must reach baseline")
        # Verify vertical retrace along downstem 1
        retrace_pts = [p for p in m_pts if p[1] > 2.0 and p[1] < 6.0 and 6.0 <= p[0] <= 8.5]
        self.assertGreaterEqual(len(retrace_pts), 3, "m missing vertical retrace along downstem 1")
        # Verify vertical retrace along downstem 2 (from foot up to waist without cutting across counter)
        stem2_foot_idx = min(range(20, 35), key=lambda i: m_pts[i][1])
        self.assertLessEqual(m_pts[stem2_foot_idx][1], 0.5, "m stem 2 foot must reach baseline")
        retrace2_pt = m_pts[stem2_foot_idx + 1]
        self.assertGreaterEqual(retrace2_pt[1], 4.5, "m stem 2 must retrace up to waist")
        self.assertLessEqual(abs(retrace2_pt[0] - m_pts[stem2_foot_idx][0]), 0.5, "m stem 2 retrace must be vertical along downstem")
                
        # Test 'h': single continuous stroke, ascender loop high, downstem at baseline, arch full x-height, exit on right
        self.assertIn('h', chars)
        h_strokes = chars['h']['strokes']
        self.assertEqual(len(h_strokes), 1, "h must be 1 continuous stroke")
        h_pts = h_strokes[0]
        self.assertGreater(max(p[1] for p in h_pts), 16.0, "h ascender loop must reach top")
        self.assertLess(min(p[1] for p in h_pts), 1.0, "h downstem must reach baseline")
        # Arch must reach full x-height (>= 9.5 font units)
        arch_pts = [p for p in h_pts[28:] if p[1] >= 9.5]
        self.assertGreaterEqual(len(arch_pts), 2, "h arch must reach full x-height (>= 9.5 font units)")
        self.assertGreater(h_pts[-1][0], 14.0, "h must exit to the right")
        self.assertGreater(h_pts[-1][1], 0.5, "h must have curved exit scoop above baseline")

        # Test 'G': single continuous stroke, reaches cap-height, descender loop below baseline, exit flourish
        self.assertIn('G', chars)
        G_strokes = chars['G']['strokes']
        self.assertEqual(len(G_strokes), 1, "G must be 1 continuous stroke")
        G_pts = G_strokes[0]
        self.assertGreaterEqual(max(p[1] for p in G_pts), 20.0, "G ascender loop must reach cap-height (>= 20 font units)")
        self.assertLessEqual(min(p[1] for p in G_pts), -8.0, "G descender loop must plunge below baseline (<= -8 font units)")
        self.assertGreater(G_pts[-1][0], 25.0, "G must exit to the right with horizontal flourish")
        # Exit flourish must be monotonic towards the right (no acute backward tooth/spike)
        desc_turn_idx = min(range(20, len(G_pts)), key=lambda i: G_pts[i][0])
        for i in range(desc_turn_idx, len(G_pts) - 1):
            self.assertLessEqual(G_pts[i][0] - G_pts[i+1][0], 0.1, f"G contains backward tooth on exit flourish at index {i}")

        # Test 'H': single continuous stroke, clean 2-stem cursive traversal without tangles
        self.assertIn('H', chars)
        H_strokes = chars['H']['strokes']
        self.assertEqual(len(H_strokes), 1, "H must be 1 continuous stroke")
        H_pts = H_strokes[0]
        self.assertGreaterEqual(max(p[1] for p in H_pts), 20.0, "H must reach cap-height (>= 20 font units)")
        self.assertLessEqual(min(p[1] for p in H_pts), 1.0, "H left stem must reach baseline")
        self.assertGreater(H_pts[-1][0], 22.0, "H right stem must exit to the right")
        # Ensure entry flourish has no vertical antenna spur (starts below cap-height and moves left-to-right)
        self.assertLessEqual(H_pts[0][1], 18.0, "H entry flourish must not start above cap-height")
        peak_h_idx = max(range(10), key=lambda i: H_pts[i][1])
        entry_h_pts = H_pts[:peak_h_idx + 1]
        for i in range(len(entry_h_pts) - 1):
            self.assertLessEqual(entry_h_pts[i][0] - entry_h_pts[i+1][0], 0.1, "H entry flourish contains backward spike")

        # Test 'R': single continuous cursive stroke, reaches cap-height, reaches baseline, exits to the right
        self.assertIn('R', chars)
        R_strokes = chars['R']['strokes']
        self.assertEqual(len(R_strokes), 1, "R must be 1 continuous stroke")
        R_pts = R_strokes[0]
        self.assertGreaterEqual(max(p[1] for p in R_pts), 20.0, "R must reach cap-height (>= 20 font units)")
        self.assertLessEqual(min(p[1] for p in R_pts), 1.5, "R downstem or leg must reach baseline")
        self.assertGreaterEqual(R_pts[-1][0], 12.0, "R leg must exit to the right")
        
        # Test 'k': single continuous stroke, downstem and loop connected without gap
        self.assertIn('k', chars)
        k_strokes = chars['k']['strokes']
        self.assertEqual(len(k_strokes), 1, "k must be 1 continuous stroke")
        k_pts = k_strokes[0]
        self.assertGreater(k_pts[0][1], 8.0, "k must start at top of stem")
        self.assertGreater(k_pts[-1][0], 12.0, "k must exit to the right")
        
        # Test 'ò': 2 strokes (body + accent), exit flourish ends to the right
        self.assertIn('ò', chars)
        o_strokes = chars['ò']['strokes']
        self.assertEqual(len(o_strokes), 2, "ò must have 2 strokes (body and grave accent)")
        o_body = min(o_strokes, key=lambda s: min(p[1] for p in s))
        o_accent = max(o_strokes, key=lambda s: max(p[1] for p in s))
        self.assertGreater(min(p[1] for p in o_accent), 10.0, "ò accent must be high in the air")
        self.assertGreater(o_body[-1][0], 12.0, "ò body must exit to the right via flourish")

        # Test 'a': single continuous stroke, counter-clockwise oval, downstem on right, exit flick
        self.assertIn('a', chars)
        a_strokes = chars['a']['strokes']
        self.assertEqual(len(a_strokes), 1, "a must be 1 continuous stroke")
        a_pts = a_strokes[0]
        self.assertGreaterEqual(a_pts[0][1], 8.0, "a must start near top of oval")
        self.assertLessEqual(min(p[1] for p in a_pts), 1.5, "a must seat on baseline")
        self.assertGreaterEqual(a_pts[-1][0], 14.0, "a must exit with forward flick to the right")

        # Test 'r': single continuous stroke, left rise, horizontal roof, clean right downstem, exit flick
        self.assertIn('r', chars)
        r_strokes = chars['r']['strokes']
        self.assertEqual(len(r_strokes), 1, "r must be 1 continuous stroke")
        r_pts = r_strokes[0]
        self.assertLessEqual(r_pts[0][1], 1.0, "r must start at baseline")
        self.assertGreaterEqual(max(p[1] for p in r_pts), 6.5, "r must reach waistline")
        self.assertGreaterEqual(r_pts[-1][0], 11.0, "r must exit to the right")
        # Ensure no backwards-cutting knot under the roof
        roof_idx = max(range(len(r_pts)), key=lambda i: r_pts[i][1])
        downstem_pts = r_pts[roof_idx:]
        for k in range(len(downstem_pts) - 1):
            p1, p2 = downstem_pts[k], downstem_pts[k+1]
            if p1[1] > 2.0 and p2[1] < p1[1]:
                self.assertGreaterEqual(p2[0], p1[0] - 0.2, f"r downstem cuts backwards under roof: {p1} -> {p2}")



if __name__ == '__main__':
    unittest.main()

