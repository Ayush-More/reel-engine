"""Tests for all 16 template props models + discriminated union validation."""
import copy

import pytest
from pydantic import ValidationError

from reels.contracts.models import (
    BeforeAfterProps, ArchitectureProps, TerminalCodeProps, BrowserUIProps,
    ChatUIProps, StepProcessProps, CounterProps, KeywordHighlightProps,
    Script, Template, PROPS_BY_TEMPLATE,
)


class TestAllTemplatesHaveProps:
    def test_every_template_has_a_props_model(self):
        for t in Template:
            assert t in PROPS_BY_TEMPLATE, f"template {t.value} is missing from PROPS_BY_TEMPLATE"

    def test_no_generic_props_fallback(self, project_json):
        """With all templates mapped, GenericProps should not exist as a fallback."""
        # Every beat should validate through its dedicated model
        script = Script.model_validate(project_json["script"])
        for b in script.beats:
            assert b.template in PROPS_BY_TEMPLATE


class TestBeforeAfterProps:
    def test_valid(self):
        p = BeforeAfterProps(
            before={"title": "Before", "lines": ["old way"], "color": "red"},
            after={"title": "After", "lines": ["new way"], "color": "green"},
            verdict="Much better",
        )
        assert p.before.title == "Before"

    def test_missing_after_fails(self):
        with pytest.raises(ValidationError):
            BeforeAfterProps(before={"title": "B", "lines": ["x"]})


class TestArchitectureProps:
    def test_valid(self):
        p = ArchitectureProps(
            title="System",
            nodes=[{"id": "a", "label": "A"}, {"id": "b", "label": "B"}],
            edges=[{"src": "a", "dst": "b"}],
        )
        assert len(p.nodes) == 2

    def test_bad_edge_ref(self):
        with pytest.raises(ValidationError):
            ArchitectureProps(
                title="X",
                nodes=[{"id": "a", "label": "A"}, {"id": "b", "label": "B"}],
                edges=[{"src": "a", "dst": "z"}],
            )


class TestTerminalCodeProps:
    def test_valid(self):
        p = TerminalCodeProps(lines=["$ echo hello"], language="bash")
        assert p.lines[0] == "$ echo hello"

    def test_empty_lines_fails(self):
        with pytest.raises(ValidationError):
            TerminalCodeProps(lines=[], language="python")


class TestBrowserUIProps:
    def test_valid(self):
        p = BrowserUIProps(url="https://example.com", title="Example", content_html="<p>Hi</p>")
        assert p.url == "https://example.com"

    def test_missing_url(self):
        with pytest.raises(ValidationError):
            BrowserUIProps(title="X", content_html="<p/>")


class TestChatUIProps:
    def test_valid(self):
        p = ChatUIProps(messages=[{"role": "user", "text": "hi"}, {"role": "assistant", "text": "hello"}])
        assert len(p.messages) == 2

    def test_empty_messages_fails(self):
        with pytest.raises(ValidationError):
            ChatUIProps(messages=[])


class TestStepProcessProps:
    def test_valid(self):
        p = StepProcessProps(steps=[
            {"number": 1, "label": "Start"},
            {"number": 2, "label": "End"},
        ], current_step=1)
        assert p.current_step == 1

    def test_too_few_steps(self):
        with pytest.raises(ValidationError):
            StepProcessProps(steps=[{"number": 1, "label": "Only one"}])


class TestCounterProps:
    def test_valid(self):
        p = CounterProps(from_value=0, to_value=100, unit="%", label="Progress")
        assert p.to_value == 100

    def test_missing_label(self):
        with pytest.raises(ValidationError):
            CounterProps(from_value=0, to_value=100)


class TestKeywordHighlightProps:
    def test_valid(self):
        p = KeywordHighlightProps(sentence="AI tokens are cool", keywords=["AI", "tokens"], style="glow")
        assert p.style == "glow"

    def test_empty_keywords_fails(self):
        with pytest.raises(ValidationError):
            KeywordHighlightProps(sentence="text", keywords=[])

    def test_extra_field_rejected(self):
        with pytest.raises(ValidationError):
            KeywordHighlightProps(sentence="text", keywords=["x"], bonus="nope")


class TestUnmappedTemplateInBeat:
    def test_beat_with_bad_props_for_known_template(self, project_json):
        """A known template with wrong props must fail."""
        d = copy.deepcopy(project_json["script"])
        d["beats"][0]["props"] = {"wrong_field": True}
        with pytest.raises(ValidationError):
            Script.model_validate(d)
