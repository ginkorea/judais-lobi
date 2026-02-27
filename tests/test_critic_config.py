# tests/test_critic_config.py — Tests for core.critic.config

from pathlib import Path

from core.critic.config import CriticConfig, load_critic_config


def test_load_default_config(tmp_path):
    cfg = load_critic_config(project_root=tmp_path, user_home=tmp_path / "home")
    assert isinstance(cfg, CriticConfig)
    assert cfg.enabled is False
    assert cfg.cache_dir.endswith(str(Path(".judais-lobi") / "cache" / "critic"))


def test_load_user_config(tmp_path):
    home = tmp_path / "home"
    (home / ".judais-lobi").mkdir(parents=True)
    (home / ".judais-lobi" / "critic.yml").write_text(
        "enabled: true\nmax_rounds_per_invocation: 2\n"
    )
    cfg = load_critic_config(project_root=tmp_path, user_home=home)
    assert cfg.enabled is True
    assert cfg.max_rounds_per_invocation == 2


def test_project_config_overrides(tmp_path):
    project_cfg = tmp_path / ".judais-lobi.yml"
    project_cfg.write_text(
        "critic:\n  enabled: true\n  max_calls_per_session: 5\n"
    )
    cfg = load_critic_config(project_root=tmp_path, user_home=tmp_path / "home")
    assert cfg.enabled is True
    assert cfg.max_calls_per_session == 5


def test_cli_overrides(tmp_path):
    project_cfg = tmp_path / ".judais-lobi.yml"
    project_cfg.write_text("critic:\n  enabled: false\n")
    cfg = load_critic_config(
        project_root=tmp_path,
        user_home=tmp_path / "home",
        cli_overrides={"enabled": True},
    )
    assert cfg.enabled is True


def test_default_providers_injected(tmp_path):
    home = tmp_path / "home"
    (home / ".judais-lobi").mkdir(parents=True)
    (home / ".judais-lobi" / "critic.yml").write_text("enabled: true\n")
    cfg = load_critic_config(project_root=tmp_path, user_home=home)
    assert cfg.enabled is True
    assert len(cfg.providers) >= 1
