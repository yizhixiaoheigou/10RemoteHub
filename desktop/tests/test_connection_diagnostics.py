from remotehub.diagnostics import Diagnostics


def test_connection_log_is_bounded_and_closed(tmp_path):
    log = Diagnostics(tmp_path)
    log.handler.maxBytes = 256
    for i in range(30):
        log.write("capture_failed", message="transport failed", attempt=i)
    log.close()
    files = list(tmp_path.glob("connection.log*"))
    assert len(files) == 3
    assert all(p.stat().st_size < 256 for p in files)
    assert '"attempt": 29' in (tmp_path / "connection.log").read_text()
    previous = (tmp_path / "connection.log").read_bytes()
    log.write("after_shutdown")
    assert (tmp_path / "connection.log").read_bytes() == previous


def test_unwritable_log_directory_does_not_prevent_recovery(tmp_path):
    path = tmp_path / "file"
    path.write_text("keep")
    log = Diagnostics(path)
    log.write("capture_failed", message="transport failed")
    log.close()
    assert path.read_text() == "keep"


def test_application_error_does_not_log_full_path(qapp, tmp_path):
    from remotehub.controller import AppController

    controller = AppController(tmp_path, auto_mapping=False)
    marker = "/Users/audit-example/private/秘密.txt"
    controller.fail("找不到：" + marker)
    controller.diagnostics.handler.flush()
    contents = (tmp_path / "logs" / "connection.log").read_text()
    assert marker not in contents
    assert '"kind": "application"' in contents
    controller.shutdown()
