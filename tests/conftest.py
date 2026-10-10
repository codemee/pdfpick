import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest


@pytest.fixture(autouse=True)
def isolated_preferences(monkeypatch, tmp_path):
    from PySide6.QtCore import QSettings
    from pdfpick import strings
    monkeypatch.setattr("pdfpick.app.QSettings", lambda *_args: QSettings(str(tmp_path / "ui.ini"), QSettings.Format.IniFormat))
    monkeypatch.setattr("pdfpick.preferences.system_language", lambda: "zh")
    monkeypatch.setattr(strings, "LANGUAGE", "zh")
