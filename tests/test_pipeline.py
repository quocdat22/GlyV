from argparse import Namespace
from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

import pikepdf
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.t2CharStringPen import T2CharStringPen
from fontTools.ttLib import TTFont

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
from extract_fonts import main as extract
from pipeline import checkpoint, export_fonts, run, sha256, verify_resume
from calibration import calibrate, outline, scanline
from build_otf import build as rebuild_font
from build_vietnamese import build, validate_and_render
from vietnamese_coverage import coverage
from unittest.mock import patch
from types import SimpleNamespace


def font_fixture(path, glyph='a', upm=1000, weight='Regular', angle=0):
    builder = FontBuilder(upm, isTTF=False)
    builder.setupGlyphOrder(['.notdef', glyph])
    builder.setupCharacterMap({ord('a'): glyph})
    glyphs = {}
    for name in ('.notdef', glyph):
        pen = T2CharStringPen(upm/2, None)
        pen.moveTo((upm*.05, 0))
        pen.lineTo((upm*.25, upm*.45))
        pen.lineTo((upm*.45, 0))
        pen.closePath()
        glyphs[name] = pen.getCharString()
    builder.setupCFF('Fixture-Regular', {'FullName': 'Fixture Regular', 'FamilyName': 'Fixture',
                                        'Weight': weight, 'ItalicAngle': angle}, glyphs, {})
    builder.setupHorizontalMetrics({g: (round(upm/2), round(upm*.05)) for g in glyphs})
    builder.setupHorizontalHeader(ascent=800, descent=-200)
    builder.setupNameTable({'familyName': 'Fixture', 'styleName': 'Regular'})
    builder.setupOS2()
    builder.setupPost()
    builder.save(path)
    with TTFont(path) as font:
        return font.getTableData('CFF ')


def pdf_fixture(path, data, name='/Fixture-Regular'):
    with pikepdf.Pdf.new() as pdf:
        page = pdf.add_blank_page()
        fonts = pikepdf.Dictionary()
        for i, (font_name, stream) in enumerate(data if isinstance(data, list) else [(name, data)]):
            descriptor = pdf.make_indirect(pikepdf.Dictionary(
                Type=pikepdf.Name('/FontDescriptor'), FontName=pikepdf.Name(font_name),
                FontFile3=pdf.make_stream(stream)))
            fonts[f'/F{i}'] = pikepdf.Dictionary(Type=pikepdf.Name('/Font'), Subtype=pikepdf.Name('/Type1'),
                                               BaseFont=pikepdf.Name(font_name), FontDescriptor=descriptor)
        page.Resources = pikepdf.Dictionary(Font=fonts)
        pdf.save(path)


class PipelineTests(unittest.TestCase):
    def test_all_fonts_are_attempted_and_one_failure_does_not_stop_others(self):
        with TemporaryDirectory() as temp, patch('pipeline.BUILD_DIR', Path(temp)/'build'):
            root = Path(temp)
            good = font_fixture(root/'good.otf')
            bad = font_fixture(root/'bad.otf', glyph='unmapped')
            pdf_fixture(root/'input.pdf', [('/Good', good), ('/Bad', bad)])
            args = Namespace(pdf=root/'input.pdf', run_dir=root/'run', font=None, resume=None, yes=False)
            with redirect_stdout(StringIO()):
                run(args)
            manifest = json.loads((root/'run/manifest.json').read_text())
            self.assertEqual(manifest['status'], 'awaiting_review')
            self.assertEqual(len(manifest['fonts']), 2)
            self.assertEqual({r['id']: r['status'] for r in manifest['fonts']}, {'Good': 'awaiting_review', 'Bad': 'failed'})
            self.assertFalse(list((root/'run/build').glob('*.otf')))
            self.assertFalse((root/'build').exists())
            before = (root/'run/manifest.json').read_bytes()
            with self.assertRaises(FileExistsError):
                run(args)
            self.assertEqual(before, (root/'run/manifest.json').read_bytes())
            resume = Namespace(pdf=None, run_dir=None, font=None, resume=root/'run', yes=True)
            with redirect_stdout(StringIO()), patch('pipeline.subprocess.run', return_value=SimpleNamespace(returncode=0)):
                run(resume)
            manifest = json.loads((root/'run/manifest.json').read_text())
            self.assertEqual(manifest['status'], 'partial')
            self.assertEqual(manifest['failed_count'], 1)
            self.assertEqual({r['id']: r['status'] for r in manifest['fonts']}, {'Good': 'partial', 'Bad': 'failed'})
            self.assertTrue((root/'run/build/Good-Vietnamese.otf').is_file())
            self.assertEqual((root/'build/Good-Vietnamese.otf').read_bytes(), (root/'run/build/Good-Vietnamese.otf').read_bytes())
            self.assertFalse((root/'build/Bad-Vietnamese.otf').exists())
            self.assertEqual(manifest['stages']['export']['status'], 'complete')
            self.assertTrue((root/'run/processed/Good/sheets/render-harfbuzz.png').is_file())
            for relative, expected in manifest['sha256'].items():
                self.assertEqual(sha256(root/'run'/relative), expected)

    def test_export_copies_only_validated_fonts_and_keeps_unrelated_files(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            outputs = root/'build'
            outputs.mkdir()
            (outputs/'complete.otf').write_bytes(b'old')
            (outputs/'unrelated.otf').write_bytes(b'keep')
            records = []
            for status in ('complete', 'partial', 'failed', 'unsupported', 'not_selected'):
                source = root/f'{status}.otf'
                source.write_bytes(status.encode())
                records.append({'status': status, 'output': source.name})
            with patch('pipeline.BUILD_DIR', outputs):
                export_fonts(root, records)
            self.assertEqual({p.name for p in outputs.iterdir()}, {'complete.otf', 'partial.otf', 'unrelated.otf'})
            self.assertEqual((outputs/'unrelated.otf').read_bytes(), b'keep')
            for record in records[:2]:
                self.assertEqual(Path(record['exported_output']).read_bytes(), (root/record['output']).read_bytes())

    def test_export_copy_failure_preserves_existing_font(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            (root/'font.otf').write_bytes(b'new')
            outputs = root/'build'
            outputs.mkdir()
            (outputs/'font.otf').write_bytes(b'old')
            record = {'status': 'complete', 'output': 'font.otf'}

            def failed_copy(source, destination):
                destination.write_bytes(b'incomplete')
                raise OSError('disk full')

            with patch('pipeline.BUILD_DIR', outputs), patch('pipeline.shutil.copy2', side_effect=failed_copy):
                with self.assertRaisesRegex(OSError, 'disk full'):
                    export_fonts(root, [record])
            self.assertEqual((outputs/'font.otf').read_bytes(), b'old')
            self.assertEqual(list(outputs.iterdir()), [outputs/'font.otf'])
            self.assertNotIn('exported_output', record)

    def test_streams_cannot_be_overwritten(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            pdf_fixture(root/'input.pdf', b'original')
            with redirect_stdout(StringIO()):
                extract(str(root/'input.pdf'), str(root/'fonts'))
            raw = next((root/'fonts').glob('*.bin'))
            original_time = raw.stat().st_mtime_ns
            with redirect_stdout(StringIO()):
                extract(str(root/'input.pdf'), str(root/'fonts'))
            self.assertEqual(raw.stat().st_mtime_ns, original_time)
            pdf_fixture(root/'input.pdf', b'replacement')
            with self.assertRaisesRegex(ValueError, 'khác nội dung'):
                extract(str(root/'input.pdf'), str(root/'fonts'))
            self.assertEqual(raw.read_bytes(), b'original')

    def test_font_name_cannot_escape_output_directory(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            pdf_fixture(root/'input.pdf', b'bytes', name='/../escape')
            with self.assertRaisesRegex(ValueError, 'không hợp lệ'):
                extract(str(root/'input.pdf'), str(root/'fonts'))
            self.assertFalse(list((root/'fonts').iterdir()))

    def test_resume_requires_unchanged_inputs_and_review_status(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            (root/'input.pdf').write_bytes(b'pdf')
            (root/'outlines.json').write_text('{}')
            manifest = {'source_pdf': str(root/'input.pdf'), 'source_sha256': sha256(root/'input.pdf'),
                        'status': 'awaiting_review'}
            checkpoint(root, manifest)
            verify_resume(root, manifest)
            manifest['script_sha256'] = {'pipeline.py': 'changed'}
            with self.assertRaisesRegex(ValueError, 'Script changed'):
                verify_resume(root, manifest)
            del manifest['script_sha256']
            (root/'outlines.json').write_text('{"changed":true}')
            with self.assertRaisesRegex(ValueError, 'Artifact changed'):
                verify_resume(root, manifest)
            (root/'outlines.json').write_text('{}')
            (root/'input.pdf').write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError, 'PDF changed'):
                verify_resume(root, manifest)
            manifest['status'] = 'complete'
            with self.assertRaisesRegex(ValueError, 'awaiting_review'):
                verify_resume(root, manifest)

    def test_calibration_measures_units_weight_and_slant(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            font_fixture(root/'regular.otf')
            font_fixture(root/'bold-italic.otf', upm=2000, weight='Bold', angle=-10)
            regular, bold = calibrate(root/'regular.otf'), calibrate(root/'bold-italic.otf')
            self.assertEqual(bold['units_per_em'], 2000)
            self.assertAlmostEqual(bold['x_height'], regular['x_height']*2)
            self.assertAlmostEqual(bold['stem'], regular['stem']*2)
            self.assertEqual(bold['weight_class'], 700)
            self.assertEqual(bold['italic_angle'], -10)
            self.assertEqual(bold['style'], 'Bold Italic')
            self.assertIn('E', regular['missing_bases'])
            self.assertIn('acute', regular['marks'])
            (root/'marks.json').write_text(json.dumps({'marks': bold['marks']}))
            (root/'horns.json').write_text(json.dumps({'glyphs': bold['glyphs']}))
            build(root/'bold-italic.otf', root/'output.otf', root/'marks.json', root/'horns.json', bold)
            with TTFont(root/'output.otf') as output:
                self.assertEqual(output['post'].italicAngle, -10)
                self.assertEqual(output['OS/2'].usWeightClass, 700)
                self.assertEqual(output['head'].macStyle, 3)
                self.assertEqual(output['hhea'].caretSlopeRise, 2000)
                self.assertGreater(output['hhea'].caretSlopeRun, 0)
                self.assertIn('STAT', output)

    def test_missing_bases_are_reported_without_claiming_full_coverage(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            font_fixture(root/'source.otf', upm=2000)
            calibration = calibrate(root/'source.otf')
            (root/'marks.json').write_text(json.dumps({'marks': calibration['marks']}))
            (root/'horns.json').write_text(json.dumps({'glyphs': calibration['glyphs']}))
            placements, originals = build(root/'source.otf', root/'output.otf', root/'marks.json', root/'horns.json', calibration)
            with redirect_stdout(StringIO()):
                validate_and_render(placements, originals, root/'source.otf', root/'output.otf', root/'render.png', root)
            report = coverage(root/'output.otf')
            self.assertEqual(report['present_count'], 17)
            self.assertEqual(report['missing_count'], 117)
            self.assertEqual(len(placements), 17)
            self.assertTrue((root/'render.png').is_file())

    def test_true_type_stream_is_converted_to_cff(self):
        from fontTools.pens.ttGlyphPen import TTGlyphPen
        with TemporaryDirectory() as temp:
            root = Path(temp)
            builder = FontBuilder(2048, isTTF=True)
            builder.setupGlyphOrder(['.notdef', 'a'])
            builder.setupCharacterMap({ord('a'): 'a'})
            glyphs = {}
            for name in ('.notdef', 'a'):
                pen = TTGlyphPen(None)
                pen.moveTo((0, 0))
                pen.qCurveTo((1000, 1500), (1000, 0))
                pen.closePath()
                glyphs[name] = pen.glyph()
            builder.setupGlyf(glyphs)
            builder.setupHorizontalMetrics({g: (1100, 0) for g in glyphs})
            builder.setupHorizontalHeader(ascent=1600, descent=-400)
            builder.setupNameTable({'familyName': 'Fixture', 'styleName': 'Regular'})
            builder.setupOS2()
            builder.setupPost()
            builder.save(root/'source.ttf')
            out, count = rebuild_font(root/'source.ttf', root/'otf', out_name='converted')
            with TTFont(out) as converted:
                self.assertIn('CFF ', converted)
                self.assertNotIn('glyf', converted)
                self.assertEqual(converted['head'].unitsPerEm, 2048)
                self.assertEqual(count, 2)
                self.assertEqual(converted.getBestCmap()[ord('a')], 'a')

    def test_scanline_respects_counter_and_overlapping_contours(self):
        outer = [('moveTo', ((0, 0),)), ('lineTo', ((100, 0),)), ('lineTo', ((100, 100),)),
                 ('lineTo', ((0, 100),)), ('closePath', ())]
        inner = [('moveTo', ((20, 20),)), ('lineTo', ((20, 80),)), ('lineTo', ((80, 80),)),
                 ('lineTo', ((80, 20),)), ('closePath', ())]
        self.assertEqual(scanline(outline(outer+inner), 50), [(0, 20), (80, 100)])


if __name__ == '__main__':
    unittest.main()
