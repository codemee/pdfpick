from importlib.resources import files

from PySide6.QtCore import QLibraryInfo, QLocale, QObject, QTranslator, Signal
from PySide6.QtWidgets import QApplication

from pdfpick import strings


def system_language() -> str:
    locale = QLocale.system()
    preferred = locale.uiLanguages()
    if preferred:
        language = preferred[0].lower().replace("_", "-").split("-")[0]
        return "zh" if language == "zh" else "en"
    return "zh" if locale.language() == QLocale.Language.Chinese else "en"


class DialogTranslator(QTranslator):
    def isEmpty(self):
        return False

    def translate(self, context, source, disambiguation=None, n=-1):
        words = {"&Yes": "是(&Y)", "&No": "否(&N)", "Yes": "是", "No": "否",
                 "OK": "確定", "&OK": "確定", "Cancel": "取消", "&Cancel": "取消",
                 "Open": "開啟", "&Open": "開啟(&O)", "Save": "儲存", "&Save": "儲存(&S)",
                 "Close": "關閉", "&Close": "關閉", "File &name:": "檔案名稱(&N)：",
                 "Files of type:": "檔案類型：", "Look in:": "查詢位置：",
                 "Save in:": "儲存位置：", "Name": "名稱", "Size": "大小", "Type": "類型",
                 "Date Modified": "修改時間", "All Files (*)": "所有檔案 (*)"}
        if source in words:
            return words[source] if strings.LANGUAGE == "zh" else source
        return None


class LanguageController(QObject):
    changed = Signal()

    def __init__(self, mode="system", parent=None):
        super().__init__(parent)
        self.mode = mode if mode in {"system", "zh", "en"} else "system"
        self.translator = DialogTranslator(self)
        self.qt_translator = QTranslator(self)
        if not self.qt_translator.load(str(files("pdfpick").joinpath("assets", "qtbase_zh_TW.qm"))):
            self.qt_translator.load("qtbase_zh_TW", QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath))
        self.refresh()

    @property
    def language(self):
        return strings.LANGUAGE

    def set_mode(self, mode):
        if mode not in {"system", "zh", "en"}:
            raise ValueError(mode)
        self.mode = mode
        self.refresh()

    def refresh(self):
        strings.LANGUAGE = system_language() if self.mode == "system" else self.mode
        app = QApplication.instance()
        app.removeTranslator(self.translator)
        app.removeTranslator(self.qt_translator)
        if strings.LANGUAGE == "zh":
            app.installTranslator(self.qt_translator)
        app.installTranslator(self.translator)
        self.changed.emit()

    def close(self):
        QApplication.instance().removeTranslator(self.translator)
        QApplication.instance().removeTranslator(self.qt_translator)
