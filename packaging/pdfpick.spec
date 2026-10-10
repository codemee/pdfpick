import sys
import tomllib
import PySide6
from pathlib import Path
from PyInstaller.utils.hooks import collect_all, copy_metadata

root = Path(SPECPATH).parent
version = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
data = [(str(root / "src/pdfpick/assets"), "pdfpick/assets")]
data += [(str(Path(PySide6.__file__).parent / "translations/qtbase_zh_TW.qm"), "pdfpick/assets")]
data += copy_metadata("pdfpick")
binaries = []
hiddenimports = []
for package in ("pypdfium2", "pypdfium2_raw"):
    package_data, package_binaries, package_imports = collect_all(package)
    data += package_data
    binaries += package_binaries
    hiddenimports += package_imports

a = Analysis(
    [str(root / "packaging/launcher.py")],
    pathex=[str(root / "src")],
    binaries=binaries, datas=data, hiddenimports=hiddenimports,
    excludes=["pytest", "tkinter"], noarchive=False,
)
pyz = PYZ(a.pure)
if sys.platform == "darwin":
    exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="PDFPick",
              console=False, upx=False, argv_emulation=False)
    coll = COLLECT(exe, a.binaries, a.datas, name="PDFPick", upx=False)
    app = BUNDLE(coll, name="PDFPick.app",
                 icon=str(root / "output/desktop/PDFPick.icns"),
                 bundle_identifier="io.github.meeinoffice.pdfpick",
                 version=version,
                 info_plist={"CFBundleShortVersionString": version,
                             "NSHighResolutionCapable": True})
else:
    exe = EXE(pyz, a.scripts, a.binaries, a.datas, name="PDFPick",
              console=False, upx=False,
              icon=str(root / "src/pdfpick/assets/pdfpick.ico"))
