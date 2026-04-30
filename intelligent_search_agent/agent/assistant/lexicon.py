from __future__ import annotations

import re

IMAGE_TERMS = {
    "asset",
    "assets",
    "image",
    "images",
    "photo",
    "photos",
    "picture",
    "pictures",
    "painting",
    "paintings",
    "visual",
    "visuals",
    "map",
    "maps",
    "poster",
    "posters",
}

DOCUMENT_TERMS = {
    "article",
    "articles",
    "document",
    "documents",
    "pdf",
    "pdfs",
    "paper",
    "papers",
    "source",
    "sources",
    "text",
    "write",
    "explain",
    "summarize",
}

HISTORY_TERMS = {
    "antwerp",
    "belgian",
    "belgium",
    "brabant",
    "brussels",
    "dutch",
    "flanders",
    "flemish",
    "french",
    "ghent",
    "happened",
    "history",
    "independence",
    "patriotism",
    "revolution",
    "wallonia",
}

QUESTION_TERMS = {"how", "what", "when", "where", "why", "who"}
MIXED_TERMS = {"and", "also", "with", "alongside", "together"}

ASSET_KIND_VALUES = {
    "photo",
    "painting",
    "illustration",
    "map",
    "document_scan",
    "poster",
    "architecture",
    "object",
    "other",
}

STOPWORDS = {
    "a",
    "about",
    "and",
    "are",
    "can",
    "connected",
    "for",
    "from",
    "give",
    "i",
    "in",
    "it",
    "me",
    "more",
    "of",
    "on",
    "only",
    "please",
    "related",
    "same",
    "show",
    "the",
    "them",
    "to",
    "too",
    "what",
    "with",
    "you",
}

FOLLOWUP_TERMS = {
    "also",
    "another",
    "just",
    "more",
    "only",
    "same",
    "similar",
    "them",
    "these",
    "those",
    "too",
}

ASSET_KIND_ALIASES = {
    "photo": {"photo", "photos", "picture", "pictures"},
    "painting": {"painting", "paintings"},
    "illustration": {"illustration", "illustrations"},
    "map": {"map", "maps"},
    "document_scan": {"scan", "scans", "document", "documents", "tract", "tracts"},
    "poster": {"poster", "posters"},
    "architecture": {"architecture", "building", "buildings"},
    "object": {"object", "objects", "artifact", "artifacts"},
}


def tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-zA-Z]+", text.lower()))


def meaningful_query_terms(text: str) -> set[str]:
    return {token for token in tokens(text) if len(token) > 2 and token not in STOPWORDS}
