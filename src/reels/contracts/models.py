"""Single source of truth for every artefact contract (Pydantic v2)."""
from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SCHEMA_VERSION = "1.0"


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Role(str, Enum):
    HOOK = "HOOK"
    PROBLEM = "PROBLEM"
    ANALOGY = "ANALOGY"
    MECHANISM = "MECHANISM"
    TAKEAWAY = "TAKEAWAY"
    CTA = "CTA"


class Template(str, Enum):
    hook_big_type = "hook_big_type"
    problem_explain = "problem_explain"
    analogy = "analogy"
    split_compare = "split_compare"
    before_after = "before_after"
    flow_diagram = "flow_diagram"
    architecture = "architecture"
    terminal_code = "terminal_code"
    browser_ui = "browser_ui"
    chat_ui = "chat_ui"
    step_process = "step_process"
    data_viz = "data_viz"
    counter = "counter"
    keyword_highlight = "keyword_highlight"
    takeaway = "takeaway"
    cta = "cta"
    token_split = "token_split"  # topic-specific template used by the sample Reel


Color = Literal["green", "cyan", "blue", "purple", "amber", "red", "white"]
Transition = Literal["cut", "glitch_cut", "slide_up", "slide_left", "fade", "zoom", "wipe"]


# ---------- template props (what the renderer actually receives) ----------
class HookBigTypeProps(Strict):
    line1: str
    line2: str
    accent_word: str | None = None
    morph_to: list[str] = []


class ProblemExplainProps(Strict):
    headline: str
    bullets: list[str] = Field(min_length=1, max_length=4)
    tone: Literal["problem", "neutral"] = "problem"


class AnalogyProps(Strict):
    metaphor: str
    left_label: str
    right_label: str
    items: list[str] = Field(min_length=1, max_length=6)


class TokenSplitProps(Strict):
    sentence: str
    tokens: list[str] = Field(min_length=1)
    illustrative: bool = True
    show_count: bool = True


class FlowNode(Strict):
    id: str
    label: str
    color: Color = "blue"


class FlowEdge(Strict):
    src: str
    dst: str
    label: str | None = None


class FlowDiagramProps(Strict):
    nodes: list[FlowNode] = Field(min_length=2, max_length=7)
    edges: list[FlowEdge] = Field(min_length=1)
    direction: Literal["horizontal", "vertical"] = "vertical"

    @model_validator(mode="after")
    def edges_reference_nodes(self) -> "FlowDiagramProps":
        ids = {n.id for n in self.nodes}
        for e in self.edges:
            if e.src not in ids or e.dst not in ids:
                raise ValueError(f"edge {e.src}->{e.dst} references unknown node")
        return self


class ComparePane(Strict):
    title: str
    lines: list[str] = Field(min_length=1, max_length=5)
    color: Color = "blue"


class SplitCompareProps(Strict):
    left: ComparePane
    right: ComparePane
    verdict: str | None = None


class Series(Strict):
    label: str
    value: float


class DataVizProps(Strict):
    kind: Literal["meter", "bar", "line"]
    title: str
    series: list[Series] = Field(min_length=1, max_length=8)
    unit: str | None = None
    illustrative: bool = True


class TakeawayProps(Strict):
    title: str
    items: list[str] = Field(min_length=1, max_length=5)


class CtaProps(Strict):
    primary: str
    secondary: str | None = None
    style: Literal["share", "comment", "follow"] = "share"


class BeforeAfterProps(Strict):
    before: ComparePane
    after: ComparePane
    verdict: str | None = None


class ArchitectureProps(Strict):
    nodes: list[FlowNode] = Field(min_length=2, max_length=10)
    edges: list[FlowEdge] = Field(min_length=1)
    title: str
    direction: Literal["horizontal", "vertical"] = "vertical"

    @model_validator(mode="after")
    def edges_reference_nodes(self) -> "ArchitectureProps":
        ids = {n.id for n in self.nodes}
        for e in self.edges:
            if e.src not in ids or e.dst not in ids:
                raise ValueError(f"edge {e.src}->{e.dst} references unknown node")
        return self


class TerminalCodeProps(Strict):
    lines: list[str] = Field(min_length=1, max_length=20)
    language: str = "bash"
    highlight_lines: list[int] = []
    title: str | None = None


class BrowserUIProps(Strict):
    url: str
    title: str
    content_html: str
    highlight: str | None = None


class ChatMessage(Strict):
    role: Literal["user", "assistant", "system"]
    text: str


class ChatUIProps(Strict):
    messages: list[ChatMessage] = Field(min_length=1, max_length=10)
    typing: bool = False


class StepItem(Strict):
    number: int
    label: str
    done: bool = False


class StepProcessProps(Strict):
    steps: list[StepItem] = Field(min_length=2, max_length=8)
    current_step: int | None = None


class CounterProps(Strict):
    from_value: float
    to_value: float
    unit: str = ""
    label: str
    illustrative: bool = True


class KeywordHighlightProps(Strict):
    sentence: str
    keywords: list[str] = Field(min_length=1)
    style: Literal["underline", "bold", "glow"] = "bold"


PROPS_BY_TEMPLATE: dict[Template, type[BaseModel]] = {
    Template.hook_big_type: HookBigTypeProps,
    Template.problem_explain: ProblemExplainProps,
    Template.analogy: AnalogyProps,
    Template.token_split: TokenSplitProps,
    Template.flow_diagram: FlowDiagramProps,
    Template.split_compare: SplitCompareProps,
    Template.before_after: BeforeAfterProps,
    Template.architecture: ArchitectureProps,
    Template.terminal_code: TerminalCodeProps,
    Template.browser_ui: BrowserUIProps,
    Template.chat_ui: ChatUIProps,
    Template.step_process: StepProcessProps,
    Template.counter: CounterProps,
    Template.keyword_highlight: KeywordHighlightProps,
    Template.data_viz: DataVizProps,
    Template.takeaway: TakeawayProps,
    Template.cta: CtaProps,
}


# ---------- script ----------
class Animation(Strict):
    entrance: str = "fade_up"
    emphasis: str = "none"
    exit: str = "fade"


class Beat(Strict):
    id: str = Field(pattern=r"^b\d{2}$")
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    role: Role
    narration: str = Field(min_length=3)
    keywords: list[str] = []
    headline: str
    visual_concept: str
    template: Template
    props: dict[str, Any]
    animation: Animation = Animation()
    caption_emphasis: list[str] = []
    transition: Transition = "cut"
    claim_ids: list[str] = []

    @model_validator(mode="after")
    def check_times_and_props(self) -> "Beat":
        if self.end <= self.start:
            raise ValueError(f"{self.id}: end must be greater than start")
        model = PROPS_BY_TEMPLATE.get(self.template)
        if model is None:
            raise ValueError(f"{self.id}: unknown template '{self.template.value}'; every template must have a props model")
        # Validate and normalise; raises ValidationError naming the bad prop.
        self.props = model.model_validate(self.props).model_dump(mode="json")
        return self


class Claim(Strict):
    id: str = Field(pattern=r"^c\d+$")
    text: str
    source_urls: list[str] = []
    is_analogy: bool = False
    illustrative: bool = False
    verified: bool = False  # set True only after the research stage fetched the source


class Meta(Strict):
    title: str
    category: str
    thumbnail_headline: str
    instagram_caption: str = Field(max_length=2200)
    hashtags: list[str] = Field(min_length=3, max_length=15)

    @field_validator("hashtags")
    @classmethod
    def hashtags_start_with_hash(cls, v: list[str]) -> list[str]:
        bad = [h for h in v if not h.startswith("#") or " " in h]
        if bad:
            raise ValueError(f"invalid hashtags: {bad}")
        return v


class Script(Strict):
    schema_version: str = SCHEMA_VERSION
    topic_title: str
    target_audience: str
    hook_variants: list[str] = Field(min_length=1)
    chosen_hook: str
    meta: Meta
    beats: list[Beat] = Field(min_length=5)
    claims: list[Claim] = []
    estimated_duration_s: float


# ---------- audio ----------
class WordTiming(Strict):
    text: str
    start: float
    end: float
    confidence: float | None = None

    @model_validator(mode="after")
    def ordered(self) -> "WordTiming":
        if self.end < self.start:
            raise ValueError("word end before start")
        return self


class Alignment(Strict):
    aligner: str
    audio_duration_s: float
    words: list[WordTiming]
    coverage: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def monotonic_words(self) -> "Alignment":
        previous_end = 0.0
        for word in self.words:
            if word.start < previous_end:
                raise ValueError("alignment word timings must be monotonic and non-overlapping")
            if word.end > self.audio_duration_s + 0.15:
                raise ValueError("word timing exceeds audio duration tolerance")
            previous_end = word.end
        return self


class CaptionWord(Strict):
    text: str
    start: float = Field(ge=0)
    end: float = Field(gt=0)


class CaptionSegment(Strict):
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    words: list[CaptionWord] = Field(min_length=1, max_length=4)


class CaptionTrack(Strict):
    language: Literal["roman_hinglish"] = "roman_hinglish"
    segments: list[CaptionSegment]


class VoiceMetadata(Strict):
    provider: str
    model: str
    voice_id: str | None = None
    text_hash: str
    audio_path: str
    duration_s: float = Field(gt=0)
    longest_silence_s: float = Field(ge=0)
    mean_db: float
    cache_hit: bool


class RenderScene(Strict):
    beat_id: str
    template: Template
    from_frame: int = Field(ge=0)
    duration_frames: int = Field(gt=0)
    headline: str
    props: dict[str, Any]
    transition: Transition = "cut"


class RenderProps(Strict):
    schema_version: str = SCHEMA_VERSION
    job_id: str
    fps: Literal[30] = 30
    size: tuple[Literal[1080], Literal[1920]] = (1080, 1920)
    audio_path: str
    scenes: list[RenderScene] = Field(min_length=1)
    captions: CaptionTrack
    assets: list[str] = []


class LayoutBox(Strict):
    name: str
    x: float
    y: float
    width: float = Field(gt=0)
    height: float = Field(gt=0)
    zone: Literal["chrome", "headline", "stage", "caption"]


class LayoutReport(Strict):
    width: Literal[1080] = 1080
    height: Literal[1920] = 1920
    safe_area_passed: bool
    boxes: list[LayoutBox]
    violations: list[str] = []


class Topic(Strict):
    id: str
    title: str
    source: Literal["manual", "hn", "rss", "github", "reddit", "producthunt", "trends", "curated"] = "manual"
    source_url: str | None = None


class ReelProject(Strict):
    """Bundle used by examples and tests; real runs store each artefact as its own file."""
    schema_version: str = SCHEMA_VERSION
    job_id: str
    topic: Topic
    script: Script
    alignment_excerpt: Alignment | None = None


# ---------- QC / publishing ----------
class QCCheck(Strict):
    name: str
    severity: Literal["hard", "soft"]
    passed: bool
    measured: str | None = None
    limit: str | None = None


class QCReport(Strict):
    job_id: str | None = None
    schema_version: str = SCHEMA_VERSION
    checks: list[QCCheck]
    verdict: Literal["pass", "fail"]
    score: float = Field(ge=0, le=100)
    quality_dimensions: dict[str, float] = {}


class PublishPackage(Strict):
    job_id: str
    video_path: str
    cover_path: str | None
    caption: str
    hashtags: list[str]
    idempotency_key: str


class PublishResult(Strict):
    mode: Literal["dry_run", "live"]
    status: Literal["blocked", "would_publish", "published", "failed"]
    blocked_reasons: list[str] = []
    container_id: str | None = None
    media_id: str | None = None
    detail: dict[str, Any] = {}
