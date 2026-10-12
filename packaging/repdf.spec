import sys
import tomllib
from PySide6.QtCore import QLibraryInfo
from pathlib import Path
from PyInstaller.utils.hooks import collect_all, copy_metadata

root = Path(SPECPATH).parent
version = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
data = [(str(root / "src/repdf/assets"), "repdf/assets")]
data += [(str(Path(QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)) / "qtbase_zh_TW.qm"), "repdf/assets")]
data += copy_metadata("repdf")
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
    exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="repdf",
              console=False, upx=False, argv_emulation=False)
    coll = COLLECT(exe, a.binaries, a.datas, name="repdf", upx=False)
    app = BUNDLE(coll, name="RePDF.app",
                 icon=str(root / "output/desktop/repdf.icns"),
                 bundle_identifier="io.github.codemee.repdf",
                 version=version,
                 info_plist={"CFBundleShortVersionString": version,
                             "CFBundleName": "RePDF",
                             "CFBundleDisplayName": "RePDF",
                             "NSHighResolutionCapable": True})
else:
    exe = EXE(pyz, a.scripts, a.binaries, a.datas, name="repdf",
              console=False, upx=False,
              icon=str(root / "src/repdf/assets/repdf.ico"))
