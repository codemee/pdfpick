from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output/desktop"


def run(*args: str, env: dict[str, str] | None = None) -> None:
    subprocess.run(args, cwd=ROOT, check=True, env=env)


def main() -> None:
    if sys.platform not in {"win32", "darwin"}:
        raise SystemExit("Build Windows on Windows or macOS on macOS.")
    version = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    OUT.mkdir(parents=True, exist_ok=True)
    if sys.platform == "darwin":
        from PIL import Image
        with Image.open(ROOT / "src/repdf/assets/repdf.png") as image:
            image.resize((1024, 1024)).save(OUT / "repdf.icns", format="ICNS")
    build_env = os.environ.copy()
    if sys.platform == "win32":
        # Prevent unrelated tools on PATH from supplying incompatible native DLLs.
        system_root = Path(os.environ["SystemRoot"])
        build_env["PATH"] = os.pathsep.join(map(str, (
            Path(sys.executable).parent, Path(sys.base_prefix),
            system_root / "System32", system_root,
        )))
    run(sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
        "--distpath", str(OUT / "dist"), "--workpath", str(OUT / "build"),
        str(ROOT / "packaging/repdf.spec"), env=build_env)
    executable = (OUT / "dist/repdf.app/Contents/MacOS/repdf"
                  if sys.platform == "darwin" else OUT / "dist/repdf.exe")
    report = OUT / "smoke-report.json"
    report.unlink(missing_ok=True)
    result = subprocess.run([str(executable), "--self-test", str(report)], cwd=OUT, timeout=120)
    if not report.is_file():
        raise RuntimeError(f"Packaged smoke test produced no report (exit {result.returncode})")
    smoke = json.loads(report.read_text(encoding="utf-8"))
    if result.returncode != 0 or not smoke.get("ok") or smoke.get("version") != version:
        raise RuntimeError(f"Packaged smoke test failed: {smoke}")
    release = OUT / "release"
    release.mkdir(exist_ok=True)
    arch = {"AMD64": "x86_64", "aarch64": "arm64"}.get(platform.machine(), platform.machine())
    system = "macos" if sys.platform == "darwin" else "windows"
    suffix = "dmg" if sys.platform == "darwin" else "exe"
    artifact = release / f"repdf-{version}-{system}-{arch}.{suffix}"
    if sys.platform == "darwin":
        with tempfile.TemporaryDirectory(prefix="dmg-", dir=OUT) as staging:
            stage = Path(staging)
            run("ditto", str(OUT / "dist/repdf.app"), str(stage / "repdf.app"))
            (stage / "Applications").symlink_to("/Applications", target_is_directory=True)
            run("hdiutil", "create", "-volname", f"repdf {version}", "-srcfolder",
                str(stage), "-format", "UDZO", "-ov", str(artifact))
        run("hdiutil", "verify", str(artifact))
    else:
        shutil.copy2(executable, artifact)
    with artifact.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    artifact.with_suffix(artifact.suffix + ".sha256").write_text(
        f"{digest}  {artifact.name}\n", encoding="utf-8")
    print(f"Built and verified {artifact}")


if __name__ == "__main__":
    main()
