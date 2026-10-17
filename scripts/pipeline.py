"""Run PDF extraction, calibrated Vietnamese construction and validation.

Without --yes, save review artifacts and stop; --resume RUN --yes finishes them.
"""
import argparse
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from io import BytesIO
import hashlib
import json
from math import ceil
from pathlib import Path
import shutil
import re
import subprocess
import sys
from tempfile import TemporaryDirectory
import traceback

from fontTools.pens.recordingPen import RecordingPen
from fontTools.ttLib import TTFont
from PIL import Image, ImageDraw, ImageFont

from extract_fonts import main as extract
from build_otf import build as build_otf
from vietnamese_coverage import coverage
from draw_marks import main as draw_marks
from draw_horns import main as draw_horns
from build_vietnamese import build, validate_and_render


from calibration import TEMPLATES, calibrate


BUILD_DIR = Path(__file__).resolve().parents[1]/'build'


def export_fonts(root, records):
    for record in records:
        if record['status'] not in ('complete', 'partial'):
            continue
        source = root/record['output']
        BUILD_DIR.mkdir(parents=True, exist_ok=True)
        destination = BUILD_DIR/source.name
        with TemporaryDirectory(dir=BUILD_DIR) as temp:
            staged = Path(temp)/source.name
            shutil.copy2(source, staged)
            staged.replace(destination)
        record['exported_output'] = str(destination)


def sha256(path):
    with Path(path).open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256')
    return digest.hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n')


def glyph_sheet(path, output):
    with TTFont(path) as font:
        order = font.getGlyphOrder()
        codes = {}
        for code, name in (font.getBestCmap() or {}).items():
            codes.setdefault(name, []).append(f'U+{code:04X}')
        if len(order) > 0x1900:
            raise ValueError('Glyph sheet exceeds the temporary BMP private-use range')
        for table in font['cmap'].tables:
            if table.isUnicode():
                table.cmap.update({0xE000+i: name for i, name in enumerate(order)})
        data = BytesIO()
        font.save(data)
    data.seek(0)
    glyph_font = ImageFont.truetype(data, 54)
    label = ImageFont.truetype('DejaVuSans.ttf', 13)
    title = ImageFont.truetype('DejaVuSans.ttf', 25)
    cols, width, height = 8, 180, 156
    image = Image.new('RGB', (cols*width+40, 100+ceil(len(order)/cols)*height), '#f4f6f8')
    draw = ImageDraw.Draw(image)
    draw.text((20, 18), path.stem, font=title, fill='#172334')
    draw.text((20, 60), f'{len(order)} glyphs | GID / name / Unicode', font=label, fill='#526174')
    for i, name in enumerate(order):
        x, y = 20+(i % cols)*width, 95+(i//cols)*height
        draw.rounded_rectangle((x+2, y+2, x+width-3, y+height-3), 6, fill='white', outline='#d9dfe6')
        draw.text((x+10, y+9), str(i), font=label, fill='#526174')
        draw.text((x+width/2, y+98), chr(0xE000+i), font=glyph_font, anchor='ms', fill='#172334')
        draw.text((x+width/2, y+112), name, font=label, anchor='mt', fill='#172334')
        draw.text((x+width/2, y+134), ', '.join(codes.get(name, [])) or 'unencoded', font=label, anchor='mt', fill='#526174')
    image.save(output)


def checkpoint(root, manifest):
    manifest['sha256'] = {str(p.relative_to(root)): sha256(p)
                          for p in sorted(root.rglob('*')) if p.is_file() and p != root/'manifest.json'}
    write_json(root/'manifest.json', manifest)


def verify_resume(root, manifest):
    if manifest['status'] != 'awaiting_review':
        raise ValueError('Only an awaiting_review run can be resumed')
    if sha256(manifest['source_pdf']) != manifest['source_sha256']:
        raise ValueError('The source PDF changed since the review run')
    # Review edits belong in a new run; resume must use the exact recorded inputs.
    for relative, expected in manifest['sha256'].items():
        if sha256(root/relative) != expected:
            raise ValueError(f'Artifact changed since review: {relative}')
    for name, expected in manifest.get('script_sha256', {}).items():
        if sha256(Path(__file__).parent/name) != expected:
            raise ValueError(f'Script changed since review: {name}')


def run(args):
    if args.resume:
        root = args.resume.resolve()
        manifest = json.loads((root/'manifest.json').read_text())
        verify_resume(root, manifest)
        if manifest.get('pipeline_version') != 2:
            raise ValueError('This run predates per-font calibration; start a new run')
    else:
        source = args.pdf.resolve()
        if not source.is_file():
            raise FileNotFoundError(source)
        root = (args.run_dir or Path('artifacts')/datetime.now(timezone.utc).strftime('run-%Y%m%dT%H%M%S%fZ')).resolve()
        root.mkdir(parents=True, exist_ok=False)
        for sub in ('fonts', 'otf', 'sheets', 'reports', 'logs', 'build'):
            (root/sub).mkdir()
        manifest = {'source_pdf': str(source), 'source_sha256': sha256(source),
                    'pipeline_version': 2, 'fonts': [], 'status': 'running', 'review_mode': 'automatic' if args.yes else 'manual',
                    'created_utc': datetime.now(timezone.utc).isoformat(), 'stages': {},
                    'python': sys.version, 'script_sha256': {p.name: sha256(p) for p in sorted(Path(__file__).parent.glob('*.py'))}}
        shutil.copyfile(TEMPLATES, root/'templates.json')
        checkpoint(root, manifest)

    def stage(name, operation):
        print(f'[{name}] {root}', flush=True)
        manifest['status'] = 'running'
        manifest['stages'][name] = {'status': 'running'}
        checkpoint(root, manifest)
        try:
            with (root/'logs'/f'{name}.log').open('w') as log, redirect_stdout(log), redirect_stderr(log):
                result = operation()
                for relative, expected in manifest.get('source_artifacts_sha256', {}).items():
                    if sha256(root/relative) != expected:
                        raise ValueError(f'Source artifact changed: {relative}')
        except BaseException as error:
            with (root/'logs'/f'{name}.log').open('a') as log:
                traceback.print_exc(file=log)
            manifest['status'] = 'failed'
            manifest['stages'][name] = {'status': 'failed', 'error': str(error)}
            checkpoint(root, manifest)
            raise
        manifest['stages'][name] = {'status': 'complete'}
        checkpoint(root, manifest)
        return result

    if not args.resume:
        stage('extract', lambda: extract(str(source), str(root/'fonts')))

        def rebuild():
            results, names = [], set()
            for raw in sorted((root/'fonts').glob('*.bin')):
                name = re.sub(r'^[A-Z]{6}_', '', raw.stem.rsplit('_FontFile', 1)[0])
                base_name, index = name, 1
                while name in names:
                    index += 1
                    name = f'{base_name}-subset-{index}'
                names.add(name)
                record = {'id': name, 'stream': str(raw.relative_to(root))}
                try:
                    path, count = build_otf(str(raw), str(root/'otf'), out_name=name)
                    record.update(source_otf=str(Path(path).relative_to(root)), original_glyphs=count, status='pending')
                except Exception as error:
                    record.update(status='unsupported', error=str(error))
                    print(f'Cannot rebuild {raw.name}: {error}')
                results.append(record)
            manifest['fonts'] = results
            write_json(root/'reports/extraction.json', results)
            if not results:
                raise ValueError('No embedded font streams found in the PDF')

        stage('otf', rebuild)
        manifest['source_artifacts_sha256'] = {str(p.relative_to(root)): sha256(p)
                                              for sub in ('fonts', 'otf') for p in (root/sub).iterdir()}
        manifest['source_artifacts_sha256']['templates.json'] = sha256(root/'templates.json')
        if args.font and not any(r['id'] == args.font for r in manifest['fonts']):
            manifest['status'] = 'failed'
            checkpoint(root, manifest)
            raise ValueError(f'Font not found: {args.font}')
        for index, record in enumerate(manifest['fonts']):
            if args.font and record['id'] != args.font:
                record['status'] = 'not_selected'
                continue
            if record['status'] == 'unsupported':
                continue
            source_otf = root/record['source_otf']
            work = root/'processed'/record['id']
            for sub in ('sheets', 'reports'):
                (work/sub).mkdir(parents=True, exist_ok=True)
            record['work_dir'] = str(work.relative_to(root))
            try:
                def prepare():
                    write_json(work/'reports/coverage-before.json', coverage(source_otf))
                    glyph_sheet(source_otf, work/'sheets/glyphs-before.png')
                    calibration = calibrate(source_otf, root/'templates.json')
                    write_json(work/'calibration.json', calibration)
                    return calibration

                calibration = stage(f'font{index+1}-calibrate', prepare)
                stage(f'font{index+1}-marks', lambda: draw_marks(root=root, source=source_otf, out=work/'sheets/marks-v1', calibration=calibration))
                stage(f'font{index+1}-horns', lambda: draw_horns(root=root, source=source_otf, out=work/'sheets/horns-strokes-v1', calibration=calibration))
                record['status'] = 'awaiting_review'
            except Exception as error:
                record.update(status='failed', error=str(error))
        manifest['status'] = 'awaiting_review' if any(r['status'] == 'awaiting_review' for r in manifest['fonts']) else 'failed'
        write_json(root/'reports/summary.json', manifest['fonts'])
        checkpoint(root, manifest)
        if manifest['status'] == 'failed':
            raise ValueError('No fonts could be prepared; see per-font reports and logs')
        if not args.yes:
            print(f'Review all font images under {root}/processed, then run:\n'
                  f'{sys.executable} {Path(__file__).resolve()} --resume "{root}" --yes')
            return root

    manifest['review_decision'] = 'bypassed' if not args.resume else 'accepted'
    for index, record in enumerate(manifest['fonts']):
        if record['status'] != 'awaiting_review':
            continue
        source_otf = root/record['source_otf']
        work = root/record['work_dir']
        output = root/'build'/f'{record["id"]}-Vietnamese.otf'
        calibration = json.loads((work/'calibration.json').read_text())
        try:
            placements, originals = stage(f'font{index+1}-build', lambda: build(
                source=source_otf, output=output, marks_path=work/'sheets/marks-v1/outlines.json',
                horns_path=work/'sheets/horns-strokes-v1/outlines.json', calibration=calibration))
            stage(f'font{index+1}-harfbuzz', lambda: validate_and_render(placements, originals, source=source_otf,
                  output=output, sheet=work/'sheets/render-harfbuzz.png', reports=work/'reports'))

            def validate():
                report = coverage(output)
                write_json(work/'reports/coverage-after.json', report)
                glyph_sheet(output, work/'sheets/glyphs-after.png')
                return report

            report = stage(f'font{index+1}-validate', validate)
            record.update(status='complete' if not report['missing_count'] else 'partial',
                          output=str(output.relative_to(root)),
                          render=str((work/'sheets/render-harfbuzz.png').relative_to(root)),
                          present_count=report['present_count'], missing_count=report['missing_count'])
        except Exception as error:
            record.update(status='failed', error=str(error))
        checkpoint(root, manifest)

    families = {}
    for record in manifest['fonts']:
        if record['status'] in ('complete', 'partial'):
            with TTFont(root/record['output']) as font:
                family = font['name'].getDebugName(16) or font['name'].getDebugName(1)
            families.setdefault(family, []).append(record)
    family_reports = []
    for index, (family, records) in enumerate(families.items(), 1):
        report_path = root/'reports'/f'fontbakery-family{index}.json'
        family_reports.append({'family': family, 'report': str(report_path.relative_to(root))})
        for record in records:
            record['fontbakery_report'] = str(report_path.relative_to(root))

        def fontbakery():
            result = subprocess.run([sys.executable, '-m', 'fontbakery', 'check-opentype',
                                    *[str(root/r['output']) for r in records], '--skip-network', '--no-progress', '--no-colors',
                                    '--json', str(report_path)], stdout=sys.stdout, stderr=sys.stderr)
            if result.returncode:
                report = json.loads(report_path.read_text())
                failures = [check for section in report['sections'] for check in section['checks']
                            if check['result'] in ('FAIL', 'ERROR', 'FATAL')]
                for record in records:
                    relevant = [c for c in failures if not c.get('filename') or c['filename'] == Path(record['output']).name]
                    if relevant:
                        record.update(status='failed', error='FontBakery: '+', '.join(c['description'] for c in relevant))
                raise ValueError(f'FontBakery reported failed checks; see {report_path}')
        try:
            stage(f'fontbakery-family{index}', fontbakery)
        except Exception as error:
            if not any(r['status'] == 'failed' for r in records):
                for record in records:
                    record.update(status='failed', error=str(error))
    write_json(root/'reports/fontbakery-summary.json', family_reports)

    if sha256(manifest['source_pdf']) != manifest['source_sha256']:
        manifest['status'] = 'failed'
        checkpoint(root, manifest)
        raise ValueError('Source PDF changed during the pipeline')
    stage('export', lambda: export_fonts(root, manifest['fonts']))
    results = [r for r in manifest['fonts'] if r['status'] != 'not_selected']
    manifest['failed_count'] = sum(r['status'] in ('failed', 'unsupported') for r in results)
    manifest['status'] = 'complete' if all(r['status'] == 'complete' for r in results) else 'partial' if any(r['status'] in ('complete', 'partial') for r in results) else 'failed'
    write_json(root/'reports/summary.json', results)
    checkpoint(root, manifest)
    for record in results:
        print(f'{record["id"]}: {record["status"]}'+(f' ({record["present_count"]}/134) -> {record.get("exported_output", root/record["output"])}' if 'output' in record else f' - {record.get("error", "")}'))
    print(f'Manifest: {root}/manifest.json')
    return root


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('pdf', nargs='?', type=Path)
    parser.add_argument('--run-dir', type=Path, help='New directory; existing directories are never overwritten')
    parser.add_argument('--font', help='Optionally process just this extracted OTF stem; by default process all fonts')
    parser.add_argument('--yes', action='store_true', help='Build without stopping for visual review; retain all artifacts')
    parser.add_argument('--resume', type=Path, help='Continue an unchanged awaiting_review run')
    args = parser.parse_args()
    if args.resume:
        if args.pdf or args.run_dir or args.font or not args.yes:
            parser.error('--resume requires --yes and cannot be combined with pdf, --run-dir or --font')
    elif not args.pdf:
        parser.error('pdf is required for a new run')
    try:
        root = run(args)
        manifest = json.loads((root/'manifest.json').read_text())
        if manifest.get('failed_count', 0):
            return 1
    except Exception as error:
        print(f'Pipeline failed: {error}. See the run manifest and logs.', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
