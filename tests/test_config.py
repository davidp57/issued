"""Reading config.ini: trailing comments, encoding, readable errors."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import typer

import main
from server.config import PROJECT_ROOT, load_config


def _load(tmp_path: Path, content: str):
    path = tmp_path / "config.ini"
    path.write_text(content, encoding="utf-8")
    return load_config(path)


def _readme_ini_blocks() -> list[str]:
    readme = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")
    return re.findall(r"```ini\n(.*?)```", readme, flags=re.DOTALL)


def test_readme_has_ini_examples():
    assert len(_readme_ini_blocks()) >= 3


@pytest.mark.parametrize("block", _readme_ini_blocks())
def test_every_readme_example_loads(tmp_path, block):
    _load(tmp_path, block)


def test_trailing_comments_are_stripped(tmp_path):
    config = _load(
        tmp_path,
        "[server]\n"
        "port = 8282              # Change if port is already in use\n"
        "[deletion]\n"
        "mode = trash       # off (par défaut), delete ou trash\n"
        f"trash_path = {tmp_path / 'trash'}  ; outside the library\n",
    )

    assert config.server.port == 8282
    assert config.deletion.mode == "trash"
    assert config.deletion.trash_path == tmp_path / "trash"


def test_a_hash_inside_a_value_is_kept(tmp_path):
    config = _load(tmp_path, "[library]\nname = BD#2\n")

    assert config.library.name == "BD#2"


def test_config_is_read_as_utf8(tmp_path):
    config = _load(tmp_path, "[library]\nname = Bandes dessinées\n")

    assert config.library.name == "Bandes dessinées"


def test_invalid_setting_is_reported_in_one_line(monkeypatch, capsys):
    def invalid():
        raise ValueError("[deletion] mode must be one of off, delete, trash, got 'shred'")

    monkeypatch.setattr(main, "load_config", invalid)

    with pytest.raises(typer.Exit) as exit_info:
        main._ensure_config()

    assert exit_info.value.exit_code == 1
    assert capsys.readouterr().out.strip() == (
        "[ERROR] config.ini: [deletion] mode must be one of off, delete, trash, got 'shred'"
    )
