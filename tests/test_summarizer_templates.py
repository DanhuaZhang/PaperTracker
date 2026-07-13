from unittest import mock
from types import SimpleNamespace

from papertracker import config, summarizer, summary_templates


def _template(monkeypatch, tmp_path, template_id="A", content="## Finding"):
    path = tmp_path / f"{template_id}.md"
    path.write_text(content, encoding="utf-8")
    template = summary_templates.SummaryTemplate(template_id, path)
    monkeypatch.setattr(config, "summary_template", lambda selected: template)
    return template


def test_build_prompt_fills_selected_template_from_abstract(monkeypatch, tmp_path):
    _template(monkeypatch, tmp_path, content="---\ntitle:\n---\n## Finding")

    prompt, uses_pdf = summarizer.build_prompt(
        {"title": "T", "abstract": "A"}, template_id="A", pdf_path=None
    )

    assert "## Finding" in prompt
    assert "Title: T" in prompt and "Abstract: A" in prompt
    assert "frontmatter and headings EXACTLY" in prompt
    assert uses_pdf is False


def test_template_choice_does_not_change_pdf_source(monkeypatch, tmp_path):
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF")
    _template(monkeypatch, tmp_path, content="## Result")

    prompt, uses_pdf = summarizer.build_prompt(
        {"title": "T", "abstract": "A"}, "A", pdf
    )

    assert str(pdf) in prompt and "## Result" in prompt
    assert uses_pdf is True


def test_build_prompt_preserves_project_context(monkeypatch, tmp_path):
    _template(monkeypatch, tmp_path)
    profile = SimpleNamespace(name="Project Name", topic_statement="Project topic")

    prompt, _ = summarizer.build_prompt(
        {"title": "T", "abstract": "A"}, "A", None, profile
    )

    assert "Project: Project Name" in prompt
    assert "Project topic focus: Project topic" in prompt


def test_claude_command_enables_read_when_pdf_present(monkeypatch, tmp_path):
    pdf = tmp_path / "p.pdf"
    pdf.write_bytes(b"%PDF")
    _template(monkeypatch, tmp_path)
    with mock.patch("papertracker.summarizer.subprocess.run") as run:
        run.return_value = mock.Mock(stdout="ok")
        summarizer.summarize_paper(
            {"title": "T", "abstract": "A"},
            "claude",
            "sonnet",
            "A",
            pdf_path=pdf,
        )

    cmd = run.call_args.args[0]
    assert "--allowedTools" in cmd and "Read" in cmd
    assert "--add-dir" in cmd
    assert "--disallowed-tools" not in cmd


def test_claude_command_sandboxed_when_no_pdf(monkeypatch, tmp_path):
    _template(monkeypatch, tmp_path)
    with mock.patch("papertracker.summarizer.subprocess.run") as run:
        run.return_value = mock.Mock(stdout="ok")
        summary = summarizer.summarize_paper(
            {"title": "T", "abstract": "A"}, "claude", "sonnet", "A"
        )

    cmd = run.call_args.args[0]
    assert "--disallowed-tools" in cmd
    assert "Abstract-based" in summary


def test_summarize_paper_uses_configured_default_when_omitted(monkeypatch, tmp_path):
    template = _template(monkeypatch, tmp_path, template_id="A")
    monkeypatch.setattr(
        config, "summary_template_catalog", lambda: ((template,), template)
    )
    selected = []
    monkeypatch.setattr(
        config,
        "summary_template",
        lambda template_id: selected.append(template_id) or template,
    )
    with mock.patch("papertracker.summarizer.subprocess.run") as run:
        run.return_value = mock.Mock(stdout="ok")

        summarizer.summarize_paper(
            {"title": "T", "abstract": "A"}, "claude", "sonnet"
        )

    assert selected == ["A"]


def test_codex_pdf_summary_inlines_extracted_text(monkeypatch, tmp_path):
    pdf = tmp_path / "p.pdf"
    pdf.write_bytes(b"%PDF")
    _template(monkeypatch, tmp_path)
    with (
        mock.patch(
            "papertracker.summarizer.extract_pdf_text",
            return_value="Full PDF body",
        ) as extract,
        mock.patch("papertracker.summarizer.subprocess.run") as run,
    ):
        run.return_value = mock.Mock(stdout="ok")
        summarizer.summarize_paper(
            {"title": "T", "abstract": "A"},
            "codex",
            "gpt",
            "A",
            pdf_path=pdf,
        )

    cmd = run.call_args.args[0]
    prompt = run.call_args.kwargs["input"]
    extract.assert_called_once_with(pdf)
    assert "Full PDF body" in prompt
    assert str(pdf) not in prompt
    assert "--add-dir" not in cmd
