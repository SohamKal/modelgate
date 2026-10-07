from pathlib import Path

import pytest

from scripts import verify_models


@pytest.mark.parametrize("active", ["fake", "openai-a"])
def test_missing_provider_key_identifies_only_missing_setting(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    active: str,
) -> None:
    monkeypatch.chdir(tmp_path)
    hidden = "synthetic-gateway-secret-marker"
    Path(".env").write_text(
        f"MODELGATE_CLIENT_API_KEY={hidden}\nMODELGATE_STABLE_RELEASE={active}\n"
        "OPENAI_MODEL_A=model-a\nOPENAI_MODEL_B=model-b\nOPENAI_API_KEY=\n"
    )
    output = tmp_path / "evidence.json"
    monkeypatch.setattr("sys.argv", ["verify_models", "--output", str(output)])
    assert verify_models.main() == 2
    text = capsys.readouterr().err
    assert "OPENAI_API_KEY is empty or missing" in text
    assert "OPENAI_MODEL_A" not in text and "OPENAI_MODEL_B" not in text
    assert "MODELGATE_CLIENT_API_KEY" not in text
    assert hidden not in text
    assert not output.exists()


def test_check_config_sends_no_requests_and_writes_no_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    Path(".env").write_text(
        "MODELGATE_CLIENT_API_KEY=synthetic.gateway.secret-marker\n"
        "OPENAI_API_KEY=synthetic.provider.secret-marker\n"
        "OPENAI_MODEL_A=model-a\nOPENAI_MODEL_B=model-b\n"
    )

    def never(*args: object, **kwargs: object) -> None:
        pytest.fail("A configuration check must not invoke live verification.")

    monkeypatch.setattr(verify_models, "verify", never)
    output = tmp_path / "evidence.json"
    monkeypatch.setattr("sys.argv", ["verify_models", "--check-config", "--output", str(output)])
    assert verify_models.main() == 0
    captured = capsys.readouterr()
    assert '"live_requests_sent": 0' in captured.out
    assert "secret-marker" not in captured.out + captured.err
    assert not output.exists()


def test_invalid_gateway_key_does_not_echo_value(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    Path(".env").write_text("MODELGATE_CLIENT_API_KEY=short.sensitive\n")
    monkeypatch.setattr("sys.argv", ["verify_models", "--check-config"])
    assert verify_models.main() == 2
    text = capsys.readouterr().err
    assert "MODELGATE_CLIENT_API_KEY is missing or invalid" in text
    assert "short.sensitive" not in text


def test_missing_groq_key_identifies_provider_without_openai_requirements(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    Path(".env").write_text(
        "MODELGATE_CLIENT_API_KEY=synthetic.gateway.credential\n"
        "MODELGATE_VERIFICATION_PROVIDER=groq\nGROQ_API_KEY=\n"
        "GROQ_MODEL_A=openai/gpt-oss-20b\n"  # pragma: allowlist secret (public model ID)
        "GROQ_MODEL_B=openai/gpt-oss-120b\n"  # pragma: allowlist secret (public model ID)
    )
    monkeypatch.setattr("sys.argv", ["verify_models", "--check-config"])
    assert verify_models.main() == 2
    text = capsys.readouterr().err
    assert "GROQ_API_KEY is empty or missing" in text
    assert "OPENAI_API_KEY" not in text


def test_explicit_provider_flag_selects_groq_without_openai_key(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    Path(".env").write_text(
        "MODELGATE_CLIENT_API_KEY=synthetic.gateway.credential\n"
        "GROQ_API_KEY=synthetic.groq.credential\n"
        "GROQ_MODEL_A=openai/gpt-oss-20b\n"  # pragma: allowlist secret (public model ID)
        "GROQ_MODEL_B=openai/gpt-oss-120b\n"  # pragma: allowlist secret (public model ID)
    )
    monkeypatch.setattr("sys.argv", ["verify_models", "--provider", "groq", "--check-config"])
    assert verify_models.main() == 0
    captured = capsys.readouterr()
    assert '"live_requests_sent": 0' in captured.out
