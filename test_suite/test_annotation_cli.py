from sister_sto.annotations import cli


def test_cli_requires_explicit_platform_and_domain():
    parser = cli.build_parser()
    action_destinations = {action.dest for action in parser._actions}

    assert {"inputs", "output_dir", "platform", "domain"} <= action_destinations


def test_cli_returns_failure_when_any_image_fails(monkeypatch, tmp_path):
    class FakeExporter:
        def __init__(self, _options):
            pass

        def export(self, _inputs):
            return {
                "processed": 0,
                "skipped": 0,
                "failed": 1,
                "annotations": [],
                "failures": [{"source_path": "bad.png", "error": "bad"}],
            }

    monkeypatch.setattr(cli, "TeacherAnnotationExporter", FakeExporter)

    result = cli.main(
        [
            "bad.png",
            "--output-dir",
            str(tmp_path),
            "--platform",
            "pc",
            "--domain",
            "space",
        ]
    )

    assert result == 1


def test_cli_reports_teacher_initialization_failure(monkeypatch, tmp_path, capsys):
    class BrokenExporter:
        def __init__(self, _options):
            raise RuntimeError("model unavailable")

    monkeypatch.setattr(cli, "TeacherAnnotationExporter", BrokenExporter)

    result = cli.main(
        [
            "source.png",
            "--output-dir",
            str(tmp_path),
            "--platform",
            "pc",
            "--domain",
            "space",
        ]
    )

    assert result == 1
    assert "teacher initialization: model unavailable" in capsys.readouterr().out
