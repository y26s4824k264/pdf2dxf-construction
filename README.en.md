# PDF2DXF Construction

[简体中文](README.md) | **English**

[![Package checks](https://github.com/y26s4824k264/pdf2dxf-construction/actions/workflows/ci.yml/badge.svg)](https://github.com/y26s4824k264/pdf2dxf-construction/actions/workflows/ci.yml)

Version: `2.0.0rc24` (prerelease).

Convert construction PDFs into real, readable DXF files, recover verified outlined text as editable `TEXT`, and report the evidence behind drawing scale. Frame splitting and BIM modeling belong to the downstream DXF pipeline.

The Python application does not require a CAD application. PyMuPDF, NumPy, OpenCV and other dependencies still use native binary wheels. Outlined-text recognition operates on **persisted DXF geometry and optional persisted font catalogs**. It does not use OCR, ONNX Runtime, PDF pixels, or an AI model.

Licensed under [AGPL-3.0-only](LICENSE). Commercial use, modification and redistribution are permitted subject to the license conditions. Dependencies and external fonts retain their own licenses; see [NOTICE](NOTICE) and [third-party notices](THIRD_PARTY_NOTICES.md).

## Install and convert

Python 3.10 or later is required. Local validation covers macOS ARM64 with Python 3.10/3.12 and Linux ARM64 with Python 3.12. See the CI badge and [validation record](docs/VALIDATION.md) for current platform results.

```sh
git clone https://github.com/y26s4824k264/pdf2dxf-construction.git
cd pdf2dxf-construction
python3.12 -m venv .venv
.venv/bin/python -m pip install .
.venv/bin/pdf2dxf convert input.pdf -o output/drawing.dxf --pages 1
```

On Windows, use `py -3.12 -m venv .venv`, `.venv\Scripts\python.exe` and `.venv\Scripts\pdf2dxf.exe`. Wheels and source archives are available from [GitHub Releases](https://github.com/y26s4824k264/pdf2dxf-construction/releases). A PyPI publication is not required for these installation methods.

For `--emit-r12` on a server without system fonts, install `'.[render]'`. Matplotlib then supplies fallback metrics for splitting MTEXT, with an explicit `R12_FONT_METRICS_FALLBACK` warning. Chinese font appearance still requires review. The universal DXF preserves native MTEXT; this package does not bundle system font files.

Recover confirmed outlines and apply a unique declared sheet scale when independent calibration is unavailable and the evidence is consistent:

```sh
pdf2dxf convert input.pdf -o output/drawing.dxf \
  --outline-chinese required --scale-mode declared
```

```python
from pdf2dxf_stable import Converter, ConversionRequest

result = Converter().convert(
    "input.pdf", "output/drawing.dxf", ConversionRequest()
)
print(result.status, result.report_path)
```

rc24 restores exact Latin glyphs such as `i` blocked by foreign-font punctuation contours, requiring an established font lock and four distinct unambiguous letters in the same continuous source row. All competing windows remain checked. All-ten-catalog DXF probes improve from 64/84 to 70/84 complete, including all 20 uppercase/lowercase 52-letter stroke/fill cases across ten faces. Matching-face PDFs remain 82/84 complete. Unknown/conflicting outlines stay as geometry; reuse existing `r2` catalogs. See [validation](docs/VALIDATION.md).

## Optional open font catalogs

rc18 adds ten downloadable catalogs from Source Han Sans/Serif, DejaVu, Jigmo and Plangothic. Jigmo’s catalog union covers all 102,998 assigned Han codepoints in Unicode 17’s unified, A–J and compatibility ranges, checked against the official character table. Coverage does not establish recognition for arbitrary fonts, weights or outline sampling.

See [open font resources](docs/OPEN_FONTS.md) for downloads, licenses, `--outline-font-bundle` usage and reproducible builds, and [real-font results](docs/OPEN_FONT_VALIDATION.json) for complete, partial and unconfirmed cases. Resource ZIPs are separate from the Python distributions; conversion stays offline.

## Outlined Chinese text without OCR

The converter first saves a paper-space DXF. Recognition then reads source-mapped `LINE` / `LWPOLYLINE` entities from that file, comparing translation- and uniform-scale-normalized geometry, masks and topology with persistent templates. Accepted text becomes `TEXT` on `PDF_TEXT_RECOVERED_NOOCR`, with `PDF2DXF_GLYPH` XDATA for provenance.

The built-in dictionary contains 101 complete templates covering 63 characters. Of these, 93 require the same manually reviewed label and exact complete glyph in at least two source PDFs; eight are restricted to complete `1:60` / `1:90` tokens with independent engineering-digit evidence. Runtime matching is algorithmic; it does not repeat the historical manual review.

At least two contiguous Chinese characters, or a complete supported scale token, are required for publication. Isolated, unknown, ambiguous, overlapping or discontinuous candidates remain geometry. With the default `off_layer` policy, confirmed source outlines and related fills are retained on the disabled `PDF_OUTLINE_BACKUP` layer. `keep` leaves them visible; `drop` removes confirmed outlines. Reprocessing is idempotent, and `keep` preserves user edits to previously recovered text at the same recovery location.

`--outline-chinese auto` preserves geometry and reports a warning if the dictionary is unavailable or corrupt. `required` fails explicitly in that situation. Neither mode invents missing characters.

### Build a catalog from an OpenType font

Build reusable `.p2dfont` catalogs from TTF, OTF, TTC or OTC files you are entitled to use. Inspect collection faces before selecting one:

```sh
pdf2dxf font-catalog faces /path/to/font.ttc
pdf2dxf font-catalog build /path/to/font.ttc \
  --face-index 3 --charset chinese -o catalogs/font-face-3.p2dfont
pdf2dxf font-catalog inspect catalogs/font-face-3.p2dfont
```

The default `chinese` range follows Unicode 17.0: unified ideographs and extensions A–J, compatibility ideographs, radicals, strokes, Bopomofo, CJK punctuation/symbols and printable ASCII, including A–Z and a–z. `--charset english` selects printable ASCII; `--charset all` includes all drawable Unicode mappings in that font. Only characters actually mapped to drawable outlines are stored. `font-catalog inspect` reports all 52 English letters, missing letters and mapped Han counts by range. See [character support](docs/CHARACTER_SUPPORT.md).

```sh
pdf2dxf convert input.pdf -o output/drawing.dxf \
  --outline-chinese required \
  --outline-font-catalog catalogs/font-face-3.p2dfont \
  --outline-font-catalog catalogs/another-font.p2dfont \
  --scale-mode declared
```

A catalog must first be locked by exact matches for three distinct adjacent Han characters, four distinct adjacent English letters (counted case-insensitively), or three distinct reviewed Han anchors. English-only runs need no Han anchors; recovered text preserves case. Matching requires exact normalized 56×56 masks, contour counts and closed topology, followed by per-template aspect-ratio checks. A locked English/mixed run needs at least two letters/Han characters to publish. Conflicting catalogs, unresolved identical shapes, overlapping segmentations, isolated characters and insufficient evidence remain geometry. Single-character NFKC compatibility aliases are normalized.

Catalogs contain Unicode mappings, topology, masks, curve-discretization fingerprints and the source font SHA256, not the font program. After building a catalog, conversion no longer needs to open the font file. **No catalog guarantees recognition of arbitrary unknown fonts.** Font coverage, actual geometry and successful font locking all matter. A generated catalog is not automatically licensed for redistribution.

## Scale and quality evidence

```sh
# Keep paper coordinates.
pdf2dxf convert input.pdf -o output/drawing.dxf --scale-mode page

# A human has confirmed a whole-sheet scale of 1:100; output in meters.
pdf2dxf convert input.pdf -o output/drawing.dxf \
  --scale-mode manual --manual-scale 100 --units m
```

`manual_scale` is the uniform multiplier from paper millimeters to actual millimeters. `--units` converts coordinate units; it does not establish engineering scale. The default output unit is millimeters. A sheet with multiple scales must not receive an assumed global multiplier.

Automatic calibration reads the saved paper DXF: dimension labels, dimension lines, extension-line intersections, independent horizontal/vertical fits, held-out dimensions and closed dimension chains. Shortened dimension-line endpoints are not substitutes for extension-line intersections. Global fitting uses spans of at least 15 mm on paper; short dimensions remain in the independent checks. The default dimension-error gate remains 0.2%.

`declared` uses a unique standalone `1:n` only when independent calibration is unavailable and dimension conflicts or table/notes evidence do not reject it. Such output is `declared_approximate`, not independently confirmed engineering scale. Multiple supported scale groups, conflicting labels, one-axis evidence or non-millimeter unit declarations prevent automatic whole-sheet calibration. Tables, schedules and explanatory sheets retain paper coordinates.

| Report field | Meaning |
| --- | --- |
| `geometry_valid` | Structural, detected geometry-conversion and external-image checks; not proof of visual fidelity for every entity. |
| `scale_status` | `unknown`, `paper`, `declared_approximate`, `user_confirmed` or `calibrated`. |
| `model_ready` | Geometry gates and confirmed scale passed; automatic calibration also needs reviewable dimensions. This does not mean BIM components or quantities have been identified. |
| `dimension_validation_status` | `unavailable` when no verifiable DIMENSION evidence exists; error values are null, not zero. |
| `dimension_evidence` | Source handles, paper endpoints, labels in millimeters, fit/held-out roles, transformed values, residuals and chains. |

A calibrated single-scale sheet actually scales the entities. The original paper DXF is preserved; `mode=blocks` groups the model into a block. Evidence DIMENSION entities use the disabled `PDF_DIMENSION_EVIDENCE` layer, while source dimension lines remain visible. Missing, moved or duplicated evidence prevents successful revalidation. Block transforms and nested references are resolved with explicit traversal limits; ambiguous or incomplete traversal is reported.

Public modes are `auto`, `sheet` and `blocks`. Automatic frame splitting, multiple viewport calibration, BIM reconstruction and quantity takeoff are outside this package. Unsupported text/curve/fill modes are rejected. `editable` and `hybrid` retain native editable text and unidentified outlines. `strict_validation=False` may relax the effect of unconfirmed scale on `valid`; it never makes `model_ready` true.

Optional `legacy-r12` preserves supported text alignment, rotation, styles and layer visibility, but MTEXT splitting depends on available font metrics. HATCH/IMAGE boundaries and curve discretization are explicit compatibility degradations. R12 units are retained in XDATA and the JSON report because the format lacks modern `$INSUNITS` support. R12 output always needs review.

## Validate saved output

```sh
pdf2dxf validate output/drawing.dxf
pdf2dxf validate output/drawing.r12.dxf --profile legacy-r12
pdf2dxf validate moved.dxf --report drawing.report.json
```

Validation discovers adjacent conversion reports, including multi-page and R12 outputs, then checks the page request, evidence and DXF SHA256. Move the DXF, `images/` and report together. If renaming a DXF, update the artifact and validation filenames in its report. Corrupt reports, missing required evidence or altered DXF content are rejected. Without a report, validation is limited to standalone DXF checks and does not confirm scale.

Image filenames use content hashes and relative references. Each conversion has its own `*_work_*` directory containing intermediate files and logs. Reports include working paths; consume the final `artifacts` list. Preserve the `.dxf.lock` file to avoid concurrent lock-inode races. `--json` cannot overwrite the input, catalogs, output DXF or supporting conversion report. Conversion targets must end in `.dxf`.

| Exit code | Meaning |
| --- | --- |
| `0` | All required gates passed. |
| `5` | Conversion failure or quality degradation under the default policy. |
| `2` | Argument/path error; or degraded output when `--allow-quality-degradation` was explicitly selected. Read stderr and JSON to distinguish them. |
| `130` | Cancelled with Ctrl+C. |

`degraded` may still contain a readable DXF with unconfirmed scale or other quality limitations. Failures after a job starts attempt to save a report; old outputs are not counted as artifacts of the new run. Cancellation terminates the active process tree and signals batch workers to stop starting queued files. Individual reports may exist even if the batch summary was never written.

## Resource limits and batch conversion

Defaults are 2560 MiB, 1800 seconds and 20480 MiB of temporary storage. Input validation, repair, page selection and source hashing run in a supervised child process under those limits. Its results and measured resources are stored in `input_validation`. Each subsequent page is supervised separately, including nested extraction/export/validation processes. These are per-stage time limits, not one whole-document deadline.

Process-tree RSS is sampled every 0.1 seconds; temporary storage is sampled every 0.5 seconds. Exceeding a limit terminates the tree and reports `MEMORY_LIMIT`, `PAGE_TIMEOUT` or `TEMP_DISK_LIMIT`. Sampling permits brief overshoot and is not OS-level memory isolation or a security sandbox. Output-lock waits are bounded by `timeout_seconds` and can be cancelled.

Non-PDF inputs and password-protected PDFs return explicit `NOT_PDF` / `PASSWORD_REQUIRED` errors. Unlock encrypted PDFs before conversion. Optional qpdf/mutool repair attempts have 300-second tool timeouts; failed attempts allow later repair methods, within the overall preflight limits.

```sh
pdf2dxf batch input_directory -o output_directory --workers 1 \
  --outline-chinese required --scale-mode declared
pdf2dxf regress input_directory -o regression_directory --workers 1 \
  --outline-chinese required --scale-mode declared
```

Output subdirectories combine the filename and a hash of its absolute source path to avoid same-name collisions. JSON/YAML manifests accept a path list or a `documents`, `files` or `corpus` list; relative paths resolve against the manifest directory. Duplicate canonical paths are processed once. Empty inputs, invalid manifests and non-PDF entries are rejected.

`workers` controls concurrent documents; pages within each document run sequentially. Limits apply to each active document. Start with one worker for large outlined drawings. Regression converts each file twice and requires both byte equality and passing quality gates; determinism alone is not engineering acceptance.

## Tests and known limits

```sh
python -m pip install '.[test]'
python -m pytest -q
python -m build
python -m twine check dist/*
python tools/check_distribution.py --public dist/*
```

After installing the built wheel, run `python tools/test_installed_wheel.py` to verify imports and tests from an isolated directory using `site-packages`. CI covers Linux, macOS and Windows. Current evidence and the exact executed environments are recorded in [docs/VALIDATION.md](docs/VALIDATION.md) and [docs/validation.json](docs/validation.json).

The rc24 drawing run with the core open-font bundle covers 22 PDFs / 22 pages: all produced DXFs, with zero conversion failures and zero saved-DXF audit errors/fixes. All 22 still reported `degraded`. Built-in templates restored 238 TEXT entities containing 1035 characters. The core catalogs produced 262 candidates, zero font locks and zero external characters. Scale states were 9 calibrated, 6 declared approximate, 6 paper and 1 unknown; 13/22 passed the geometry gate. Nine calibrated sheets still exceeded the dimension-error gate.

A historical rc11 run covered 4290 unique PDFs / 12577 pages for basic conversion. It is not a current full-corpus text-recognition or engineering-quality result. Private PDFs, screenshots, fonts and path-bearing internal reports are not distributed. Unknown fonts, complex clipping, scans and multiple-scale sheets remain limitations. Producing a DXF does not mean every quality gate passed.

## Project structure and contribution

```text
pdf2dxf_stable/
  core.py, request.py, cli.py       Public API and command line
  preflight.py, repair.py          Supervised input validation and repair
  supervision.py, locking.py       Resource limits and cancellable output locks
  profiles.py, r12_fonts.py        Output profiles and optional R12 metrics
  validation.py, saved_validation.py
  dimension_instances.py          Block transforms and dimension instances
  resources.py                    External image publication
  engine/
    pdf.py, pipeline.py, worker.py PDF-to-DXF conversion
    geometry/                     PDF vectors, images and native text
    calibration/                  Evidence from persisted DXF
    text/                         Geometry templates and font catalogs
```

The package has one maintained `pdf2dxf_stable` implementation and one `pdf2dxf` CLI; obsolete version-numbered entry points and unused frame/viewport exporters were removed. Historical XDATA/schema identifiers are retained for provenance compatibility. See [CHANGELOG.md](CHANGELOG.md), [CONTRIBUTING.md](CONTRIBUTING.md), [Issues](https://github.com/y26s4824k264/pdf2dxf-construction/issues) and [SECURITY.md](SECURITY.md).

## License and provenance

The maintainer authorized public distribution of the supplied source, bundled derived glyph data and regression fixtures on 2026-09-07. [SOURCE_ORIGIN.json](SOURCE_ORIGIN.json) records that declaration; it is not independent verification of third-party title. Original source hashes and available attributions are retained. Original customer drawings, system fonts and external `.p2dfont` catalogs are excluded.

AGPL-3.0-only is not an unconditional license. Distribution and covered modified network services carry applicable notice, modification and corresponding-source obligations; the full [LICENSE](LICENSE) controls. [PyMuPDF's AGPL/commercial licensing](https://pymupdf.readthedocs.io/en/latest/about.html#license-and-copyright) continues to apply. Conversion does not grant new rights in your input drawings or fonts.

See the [project brief and maintenance plan](docs/PROJECT_BRIEF.md) for ecosystem goals, verifiable evidence and planned use of Codex.
