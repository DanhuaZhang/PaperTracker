from types import SimpleNamespace
from unittest import mock

import pytest

from papertracker import config, summarizer, summary_templates


def _template(tmp_path, evidence="abstract", body="## Finding"):
    template_id = "screen" if evidence == "abstract" else "deep"
    return summary_templates.SummaryTemplate(
        template_id,
        tmp_path / f"{template_id}.md",
        "Template label",
        "Template description",
        evidence,
        body,
    )


def test_abstract_prompt_has_deterministic_metadata_and_no_template_header(monkeypatch, tmp_path):
    template = _template(tmp_path)
    monkeypatch.setattr(config, "summary_template", lambda selected: template)
    paper = {
        "title": "T",
        "abstract": "A",
        "authors": ["One", "Two"],
        "published": "2026-07-01",
        "container_title": "Venue",
        "doi": "10.1/x",
        "url": "https://example.test",
    }
    profile = SimpleNamespace(name="Project Name", topic_statement="Project topic")

    prompt, uses_pdf = summarizer.build_prompt(paper, "screen", profile=profile)

    assert "Title: T" in prompt
    assert "Authors: One, Two" in prompt
    assert "Year/date: 2026-07-01" in prompt
    assert "Project: Project Name" in prompt
    assert "Project focus: Project topic" in prompt
    assert "Abstract (the only analytical evidence):\nA" in prompt
    assert "papertracker-template" not in prompt
    assert uses_pdf is False


def test_abstract_template_ignores_supplied_pdf(monkeypatch, tmp_path):
    template = _template(tmp_path)
    monkeypatch.setattr(config, "summary_template", lambda selected: template)
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"not relevant")
    monkeypatch.setattr(
        summarizer,
        "extract_pdf_evidence",
        lambda path: (_ for _ in ()).throw(AssertionError("PDF must not be read")),
    )
    monkeypatch.setattr(summarizer, "_invoke", lambda *args: "## Finding\nResult")

    result = summarizer.summarize_paper(
        {"title": "T", "abstract": "Only this"},
        "claude",
        "sonnet",
        "screen",
        pdf_path=pdf,
    )

    assert result.startswith("> Evidence: abstract only")


def test_abstract_template_rejects_missing_abstract_before_llm(monkeypatch, tmp_path):
    template = _template(tmp_path)
    monkeypatch.setattr(config, "summary_template", lambda selected: template)
    invoke = mock.Mock()
    monkeypatch.setattr(summarizer, "_invoke", invoke)
    with pytest.raises(summarizer.EvidenceError, match="requires an abstract"):
        summarizer.summarize_paper({"title": "T"}, "claude", "sonnet", "screen")
    invoke.assert_not_called()


def test_fulltext_pipeline_processes_every_chunk_for_both_providers(monkeypatch, tmp_path):
    template = _template(tmp_path, "fulltext", "## Method\n\n## Results")
    monkeypatch.setattr(config, "summary_template", lambda selected: template)
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"pdf")
    monkeypatch.setattr(
        summarizer,
        "extract_pdf_evidence",
        lambda path: summarizer.PdfEvidence(path, 3, (1, 3), ("[Page 1]\nONE", "[Page 3]\nTHREE")),
    )
    prompts = []

    def invoke(provider, model, prompt):
        prompts.append((provider, prompt))
        if "PDF chunk" in prompt:
            return "page-cited notes"
        return "## Method\nM\n\n## Results\nR"

    monkeypatch.setattr(summarizer, "_invoke", invoke)
    paper = {"title": "T", "abstract": "MUST NOT LEAK", "pdf_path": str(pdf)}

    for provider in ("claude", "codex"):
        prompts.clear()
        result = summarizer.summarize_paper(paper, provider, "model", "deep")
        assert len(prompts) == 3
        assert "[Page 1]\nONE" in prompts[0][1]
        assert "[Page 3]\nTHREE" in prompts[1][1]
        assert all("MUST NOT LEAK" not in prompt for _, prompt in prompts)
        assert result.startswith("> Evidence: full text — 2/3 pages")


def test_extract_pdf_preserves_all_pages_and_splits_oversized_page(monkeypatch, tmp_path):
    import pypdf

    class Page:
        def __init__(self, text):
            self.text = text

        def extract_text(self):
            return self.text

    monkeypatch.setattr(
        pypdf,
        "PdfReader",
        lambda path: SimpleNamespace(pages=[Page("A" * 230), Page(""), Page("C")]),
    )
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"pdf")

    evidence = summarizer.extract_pdf_evidence(pdf, chunk_char_limit=100)

    assert evidence.total_pages == 3
    assert evidence.extractable_pages == (1, 3)
    assert all(len(chunk) <= 100 for chunk in evidence.chunks)
    combined = "\n".join(evidence.chunks)
    assert "[Page 1, part" in combined
    assert "[Page 3]" in combined
    assert combined.count("A") == 230


def test_scanned_pdf_fails_with_ocr_message_before_llm(monkeypatch, tmp_path):
    import pypdf

    monkeypatch.setattr(
        pypdf,
        "PdfReader",
        lambda path: SimpleNamespace(
            pages=[SimpleNamespace(extract_text=lambda: "") for _ in range(2)]
        ),
    )
    pdf = tmp_path / "scan.pdf"
    pdf.write_bytes(b"pdf")
    with pytest.raises(summarizer.PdfTextExtractionError, match="OCR required"):
        summarizer.extract_pdf_evidence(pdf)


def test_recursive_note_consolidation_bounds_large_intermediate_evidence(monkeypatch, tmp_path):
    template = _template(tmp_path, "fulltext")
    calls = []

    def invoke(provider, model, prompt):
        calls.append(prompt)
        return "short consolidated notes"

    monkeypatch.setattr(summarizer, "_invoke", invoke)
    result = summarizer._consolidate_notes(
        {"title": "T"},
        template,
        None,
        "claude",
        "sonnet",
        ["A" * 35_000, "B" * 35_000],
    )

    assert len(calls) == 2
    assert len(result) < summarizer.NOTES_CONSOLIDATION_CHAR_LIMIT


def test_both_cli_providers_are_run_without_file_tools():
    with mock.patch("papertracker.summarizer.subprocess.run") as run:
        run.return_value = mock.Mock(stdout="ok")
        summarizer._summarize_claude("prompt", "sonnet")
        claude_cmd = run.call_args.args[0]
        assert "--disallowed-tools" in claude_cmd
        assert "--allowedTools" not in claude_cmd

        summarizer._summarize_codex("prompt", "gpt")
        codex_cmd = run.call_args.args[0]
        assert "--add-dir" not in codex_cmd
        assert "--sandbox" in codex_cmd and "read-only" in codex_cmd
