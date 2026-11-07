# OWNER: P5 | STATUS: ACTIVE
"""Local document retrieval for the copilot (no network, no extra dependencies).

The corpus (``copilot/corpus/*.md``) holds project-authored summaries, each marked as an
illustrative summary rather than official standard or report text. Documents are split at
``##`` headings; retrieval is hybrid TF-IDF (word 1-2-grams + character 3-5-grams) with a small
boost for tag matches. Passage text is data, never instructions.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
import yaml
from sklearn.feature_extraction.text import TfidfVectorizer

CORPUS_DIR = Path(__file__).resolve().parent / "corpus"


@dataclass
class Passage:
    n: int
    doc_id: str
    title: str
    section: str
    status: str
    tags: list[str]
    text: str

    def as_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


def load_corpus(directory: Path = CORPUS_DIR) -> list[Passage]:
    passages: list[Passage] = []
    for path in sorted(directory.glob("*.md")):
        raw = path.read_text(encoding="utf-8")
        meta: dict[str, Any] = {}
        body = raw
        m = re.match(r"^---\n(.*?)\n---\n(.*)$", raw, flags=re.S)
        if m:
            meta = yaml.safe_load(m.group(1)) or {}
            body = m.group(2)
        for sec in re.split(r"\n(?=## )", body):
            heading = re.match(r"##\s+(.*)", sec.strip())
            if not heading:
                continue
            text = sec.strip().split("\n", 1)[1].strip() if "\n" in sec.strip() else ""
            if text:
                passages.append(Passage(len(passages), path.stem, str(meta.get("title", path.stem)),
                                        heading.group(1).strip(), str(meta.get("status", "")),
                                        list(meta.get("tags", [])), text))
    return passages


class Retriever:
    def __init__(self, passages: list[Passage] | None = None):
        self.passages = passages or load_corpus()
        docs = [f"{p.title} {p.section} {' '.join(p.tags)} {p.text}" for p in self.passages]
        self.word = TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True, stop_words="english")
        self.char = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), sublinear_tf=True)
        self.Xw = self.word.fit_transform(docs)
        self.Xc = self.char.fit_transform(docs)

    def search(self, query: str, k: int = 5, boost_tags: list[str] | None = None) -> list[tuple[Passage, float]]:
        sw = (self.Xw @ self.word.transform([query]).T).toarray().ravel()
        sc = (self.Xc @ self.char.transform([query]).T).toarray().ravel()
        score = 0.6 * sw + 0.4 * sc
        if boost_tags:
            tags = {t.lower() for t in boost_tags}
            score += np.array([0.08 if tags & {t.lower() for t in p.tags} else 0.0 for p in self.passages])
        order = np.argsort(-score)
        seen_docs: dict[str, int] = {}
        out = []
        for i in order:
            p = self.passages[i]
            if seen_docs.get(p.doc_id, 0) >= 2:          # at most two sections per document
                continue
            seen_docs[p.doc_id] = seen_docs.get(p.doc_id, 0) + 1
            out.append((p, float(score[i])))
            if len(out) == k:
                break
        return out


@lru_cache(maxsize=1)
def default_retriever() -> Retriever:
    return Retriever()
