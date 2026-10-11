import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest


@pytest.fixture(autouse=True)
def isolated_preferences(monkeypatch, tmp_path):
    from PySide6.QtCore import QSettings
    from repdf import strings
    monkeypatch.setattr("repdf.app.QSettings", lambda *_args: QSettings(str(tmp_path / "ui.ini"), QSettings.Format.IniFormat))
    monkeypatch.setattr("repdf.preferences.system_language", lambda: "zh")
    monkeypatch.setattr(strings, "LANGUAGE", "zh")
