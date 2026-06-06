from unittest import mock

from papertracker import summarizer


def test_build_prompt_triage_uses_abstract():
    paper = {"title": "T", "abstract": "A", "doi": None}
    prompt, uses_pdf = summarizer.build_prompt(paper, mode="triage", pdf_path=None)
    assert "A" in prompt and "Core objective" in prompt
    assert uses_pdf is False


def test_build_prompt_deep_includes_template_and_pdf(tmp_path):
    pdf = tmp_path / "p.pdf"
    pdf.write_bytes(b"%PDF")
    paper = {"title": "T", "abstract": "A", "doi": None}
    prompt, uses_pdf = summarizer.build_prompt(paper, mode="deep", pdf_path=pdf)
    assert "## TL;DR" in prompt          # from default Obsidian template
    assert str(pdf) in prompt            # model is told where to read
    assert uses_pdf is True


def test_claude_command_enables_read_when_pdf_present(tmp_path):
    pdf = tmp_path / "p.pdf"
    pdf.write_bytes(b"%PDF")
    with mock.patch("papertracker.summarizer.subprocess.run") as run:
        run.return_value = mock.Mock(stdout="ok")
        with mock.patch("papertracker.summarizer.zotero.find_pdf", return_value=pdf):
            summarizer.summarize_paper(
                {"title": "T", "abstract": "A", "doi": None}, "claude", "sonnet", "deep"
            )
        cmd = run.call_args.args[0]
        assert "--allowedTools" in cmd and "Read" in cmd
        assert "--add-dir" in cmd
        assert "--disallowed-tools" not in cmd


def test_claude_command_sandboxed_when_no_pdf():
    with mock.patch("papertracker.summarizer.subprocess.run") as run:
        run.return_value = mock.Mock(stdout="ok")
        with mock.patch("papertracker.summarizer.zotero.find_pdf", return_value=None):
            summarizer.summarize_paper(
                {"title": "T", "abstract": "A", "doi": None}, "claude", "sonnet", "triage"
            )
        cmd = run.call_args.args[0]
        assert "--disallowed-tools" in cmd
