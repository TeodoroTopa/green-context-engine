"""Tests for per-stage model configuration."""

from pipeline import model_config


def _reset_cache():
    model_config._load.cache_clear()


def test_model_for_reads_configured_stage(tmp_path, monkeypatch):
    cfg = tmp_path / "models.yaml"
    cfg.write_text(
        "stages:\n"
        "  drafter: claude-sonnet-5\n"
        "  selector: claude-haiku-4-5\n"
        "default: claude-haiku-4-5\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(model_config, "CONFIG_PATH", cfg)
    _reset_cache()
    monkeypatch.setattr(
        model_config, "_load", lambda path=str(cfg): __import__("yaml").safe_load(cfg.read_text())
    )
    assert model_config.model_for("drafter") == "claude-sonnet-5"
    assert model_config.model_for("selector") == "claude-haiku-4-5"


def test_model_for_falls_back_to_config_default(monkeypatch):
    monkeypatch.setattr(model_config, "_load", lambda path=None: {"default": "claude-haiku-4-5"})
    assert model_config.model_for("unknown_stage") == "claude-haiku-4-5"


def test_model_for_uses_builtin_when_no_config(monkeypatch):
    monkeypatch.setattr(model_config, "_load", lambda path=None: {})
    # Built-in per-stage default
    assert model_config.model_for("drafter") == "claude-sonnet-5"
    # Built-in fallback for a truly unknown stage
    assert model_config.model_for("nope") == "claude-haiku-4-5"


def test_real_config_has_all_expected_stages():
    """The committed config/models.yaml resolves every pipeline stage."""
    _reset_cache()
    for stage in ("selector", "strategist", "drafter", "editor", "verifier", "feedback"):
        assert model_config.model_for(stage).startswith("claude-")
