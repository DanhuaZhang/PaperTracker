"""Guards for the assumptions that only break off the development machine.

Every test here runs on all three platforms; each one covers a bug that is
invisible on macOS and fatal on Windows.
"""

import os
import sqlite3
import stat
import sys
from pathlib import Path
from unittest import mock

import pytest

from papertracker import bootstrap, summarizer, zotero


def _fake_cli(directory, name):
    """Create an executable stub and return the path callers should get back."""
    # .cmd is how npm installs a CLI on Windows, and the extension is exactly
    # what CreateProcess needs spelled out for it.
    suffix = ".cmd" if sys.platform == "win32" else ""
    path = directory / f"{name}{suffix}"
    path.write_text("", encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


def _same_path(a, b) -> bool:
    """Compare paths the way the OS does.

    shutil.which spells the extension the way PATHEXT does (".CMD"), not the
    way the file does, so an exact string match fails on Windows for two paths
    that name the same executable. normcase is identity on POSIX.
    """
    return os.path.normcase(str(a)) == os.path.normcase(str(b))


@pytest.mark.parametrize("provider", ["claude", "codex"])
def test_a_provider_on_path_is_spawned_by_full_path_not_bare_name(provider, monkeypatch, tmp_path):
    """The Windows shim bug: which() finds claude.cmd, CreateProcess never does."""
    expected = _fake_cli(tmp_path, provider)
    monkeypatch.setenv("PATH", str(tmp_path))

    resolved = summarizer.resolve_binary(provider)

    assert _same_path(resolved, expected)
    assert resolved != provider, "a bare name is not resolvable by CreateProcess"
    assert Path(resolved).is_absolute(), "subprocess needs a path, not a lookup"


@pytest.mark.parametrize("provider", ["claude", "codex"])
def test_a_missing_provider_falls_back_so_preflight_owns_the_error(provider, monkeypatch, tmp_path):
    """One place reports "not installed", and it is not the argv builder."""
    monkeypatch.setenv("PATH", str(tmp_path))

    assert summarizer.resolve_binary(provider) == provider

    with pytest.raises(SystemExit) as excinfo:
        summarizer.preflight(provider)
    assert provider in str(excinfo.value)


def test_the_spawned_argv_leads_with_the_resolved_path(monkeypatch, tmp_path):
    expected = _fake_cli(tmp_path, "claude")
    monkeypatch.setenv("PATH", str(tmp_path))

    with mock.patch("papertracker.summarizer.subprocess.run") as run:
        run.return_value = mock.Mock(stdout="ok")
        summarizer._summarize_claude("prompt", "sonnet")

    assert _same_path(run.call_args.args[0][0], expected)


def test_a_prompt_outside_the_ansi_code_page_survives_the_pipe():
    """`text=True` alone encodes stdin with cp1252 on Windows, and PDFs are not cp1252.

    U+02C7 came out of a real paper. Encoding it for the provider's stdin raised
    UnicodeEncodeError partway through a chunked full-text summary, discarding
    the extraction and every chunk already summarized.
    """
    prompt = "caron ˇ emdash — cjk 中文 ligature ﬁ"
    echo = "import sys; sys.stdout.buffer.write(sys.stdin.buffer.read())"

    assert summarizer._run_provider_cli([sys.executable, "-c", echo], prompt) == prompt


@pytest.mark.parametrize("provider", ["claude", "codex"])
def test_neither_provider_is_spawned_at_the_locale_encoding(provider):
    """Both CLIs write UTF-8 to a pipe, so decoding their reply must match."""
    with mock.patch("papertracker.summarizer.subprocess.run") as run:
        run.return_value = mock.Mock(stdout="ok")
        getattr(summarizer, f"_summarize_{provider}")("prompt", "model")

    assert run.call_args.kwargs["encoding"] == "utf-8"


def test_zotero_opens_a_database_under_a_path_containing_a_space(tmp_path):
    """Windows temp dirs sit under C:\\Users\\First Last\\ more often than not."""
    data_dir = tmp_path / "Zotero Data"
    data_dir.mkdir()
    con = sqlite3.connect(data_dir / "zotero.sqlite")
    con.execute("CREATE TABLE items (itemID INTEGER)")
    con.commit()
    con.close()

    copied = zotero._copy_db(data_dir)
    assert copied is not None, "a URI built by interpolation would fail here"
    tmp, con = copied
    try:
        assert con.execute("SELECT count(*) FROM items").fetchone() == (0,)
        with pytest.raises(sqlite3.OperationalError):
            con.execute("CREATE TABLE written (x)")
    finally:
        con.close()
        tmp.cleanup()


def test_forcing_utf8_output_is_a_no_op_off_windows_and_safe_under_capture():
    """Must not explode when stdout is pytest's capture rather than a real stream."""
    bootstrap._force_utf8_output()


def test_forcing_utf8_output_reconfigures_both_streams_on_windows(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    stdout, stderr = mock.Mock(), mock.Mock()
    monkeypatch.setattr(sys, "stdout", stdout)
    monkeypatch.setattr(sys, "stderr", stderr)

    bootstrap._force_utf8_output()

    stdout.reconfigure.assert_called_once_with(encoding="utf-8")
    stderr.reconfigure.assert_called_once_with(encoding="utf-8")


def test_every_shipped_template_is_stored_with_unix_newlines():
    """.gitattributes pins this; a CRLF template would reach the model prompt."""
    from papertracker import config

    # rglob, not glob: templates sit one level down in abstract/ and fulltext/,
    # so a top-level glob matches nothing and the loop below asserts nothing.
    templates = sorted(config.summary_template_directory().rglob("*.md"))
    assert templates, "found no templates to check — the layout moved again"
    for template in templates:
        assert b"\r\n" not in template.read_bytes(), f"{template.name} has CRLF"
