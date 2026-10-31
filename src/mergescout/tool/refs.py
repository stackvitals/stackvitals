import re
from dataclasses import dataclass

REF = re.compile(r"(?:https?://)?(?:www\.)?(?:github\.com/)?([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)"
                 r"(?:\.git)?(?:(?:/issues/|/pull/|#)(\d+))?/?$")


@dataclass(frozen=True)
class Ref:
    owner: str
    name: str
    number: int | None

    @property
    def repo(self) -> str:
        return f"{self.owner}/{self.name}"

    @property
    def key(self) -> str:
        return f"{self.repo}#{self.number}" if self.number else self.repo


def parse_ref(text: str) -> Ref:
    s = re.sub(r"\?.*$", "", (text or "").strip())
    # "#issuecomment-123" and other anchors are not part of the issue reference; "#7" is.
    s = re.sub(r"#(?!\d+/?$).*$", "", s)
    s = re.sub(r"\s+#", "#", s)
    m = REF.match(s)
    if not m:
        raise ValueError(f"Could not read {text!r}; use owner/name#number or a GitHub issue URL.")
    return Ref(m.group(1), m.group(2), int(m.group(3)) if m.group(3) else None)
