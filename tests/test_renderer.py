import io

from pdfpick.renderer import RenderService


class FakeBackend:
    def __init__(self):
        self.stdin = io.StringIO()
        self.stdout = io.StringIO()
        self.stderr = io.StringIO()

    def poll(self):
        return 0


def test_render_queue_coalesces_per_document_and_prioritizes_current(qtbot, tmp_path, monkeypatch):
    service = RenderService(FakeBackend())
    service._reader.join()
    sent = []
    monkeypatch.setattr(service, "_write", lambda payload: (sent.append(payload), True)[1])
    service.request(tmp_path / "a.pdf", 1, tmp_path, 1, document_id=1)
    service.request(tmp_path / "b.pdf", 1, tmp_path, 2, document_id=2)
    service.request(tmp_path / "a.pdf", 2, tmp_path, 3, document_id=1)
    service.request(tmp_path / "b.pdf", 2, tmp_path, 4, document_id=2)
    assert [payload["generation"] for payload in sent] == [1]
    assert [payload["generation"] for payload in service._pending.values()] == [4, 3]
    service.prioritize(1)
    assert list(service._pending) == [1, 2]
    service.cancel_pending(2)
    service._busy = False
    service._start_next()
    assert [payload["generation"] for payload in sent] == [1, 3]
    service.close()


def test_stopped_backend_reports_failure_without_stalling_queue(qtbot, tmp_path):
    service = RenderService(FakeBackend())
    service._reader.join()
    with qtbot.waitSignal(service.message) as signal:
        service.request(tmp_path / "a.pdf", 1, tmp_path, 1, document_id=1)
    assert signal.args[0]["type"] == "error"
    assert not service._busy
    assert not service._pending
    service.close()
