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


if __name__ == '__main__':
    unittest.main()

