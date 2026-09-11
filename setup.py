import re
from pathlib import Path

from setuptools import find_packages, setup

root = Path(__file__).parent
version_source = (root / "pdf2dxf_stable/version.py").read_text(encoding="utf-8")
version_match = re.search(
    r'^__version__\s*=\s*["\']([^"\']+)["\']$', version_source, re.MULTILINE
)
if version_match is None:
    raise RuntimeError("pdf2dxf_stable/version.py does not define __version__")
package_version = version_match.group(1)
setup(
    name="pdf2dxf-construction",
    version=package_version,
    description="Vector PDF to persisted DXF with explicit scale and quality reports",
    long_description=(root / "README.en.md").read_text(encoding="utf-8"),
    long_description_content_type="text/markdown",
    license_expression="AGPL-3.0-only",
    license_files=("LICENSE", "NOTICE", "THIRD_PARTY_NOTICES.md"),
    url="https://github.com/y26s4824k264/pdf2dxf-construction",
    project_urls={
        "Source": "https://github.com/y26s4824k264/pdf2dxf-construction",
        "Issues": "https://github.com/y26s4824k264/pdf2dxf-construction/issues",
        "Changelog": "https://github.com/y26s4824k264/pdf2dxf-construction/blob/main/CHANGELOG.md",
    },
    classifiers=[
        "Development Status :: 4 - Beta",
        "Programming Language :: Python :: 3",
        "Topic :: Multimedia :: Graphics :: Graphics Conversion",
    ],
    packages=find_packages(exclude=("tests", "tests.*", "tools", "tools.*")),
    package_data={"pdf2dxf_stable.engine.text": ["assets/*.json", "assets/*.npz"]},
    install_requires=[
        "ezdxf>=1.4.4,<1.5",
        "PyMuPDF==1.26.4",
        "pydantic>=2.10,<3",
        "numpy>=2,<3",
        "scipy>=1.15,<2",
        "shapely>=2.1,<3",
        "psutil>=6,<8",
        "Pillow>=12.3,<13",
        "PyYAML>=6,<7",
        "opencv-python-headless>=4.10.0.84,<6",
        "fonttools>=4.60.2,<5",
    ],
    extras_require={
        "test": [
            "pytest>=8,<10",
            "ruff==0.9.10",
            "reportlab>=4",
            "build>=1",
            "twine>=6,<7",
            "matplotlib>=3.9,<4",
        ],
        "render": ["matplotlib>=3.9,<4"],
    },
    entry_points={"console_scripts": ["pdf2dxf=pdf2dxf_stable.cli:main"]},
    python_requires=">=3.10",
)
