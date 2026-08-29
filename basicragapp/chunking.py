import math
import re


SEPARATORS = ("\n\n", "\n", ". ", " ")


def fixed_chunks(text: str, size: int, overlap: int) -> list[str]:
    _validate(size, overlap)
    step = size - overlap
    return [text[start : start + size].strip() for start in range(0, len(text), step) if text[start : start + size].strip()]


def recursive_chunks(text: str, size: int, overlap: int) -> list[str]:
    _validate(size, overlap)

    def split(value: str, separators=SEPARATORS) -> list[str]:
        if len(value) <= size:
            return [value.strip()] if value.strip() else []
        if not separators:
            return fixed_chunks(value, size, 0)
        separator, *remaining = separators
        parts = value.split(separator)
        if len(parts) == 1:
            return split(value, remaining)
        chunks, current = [], ""
        for part in parts:
            candidate = f"{current}{separator if current else ''}{part}"
            if len(candidate) <= size:
                current = candidate
            else:
                chunks.extend(split(current, remaining))
                current = part
        chunks.extend(split(current, remaining))
        return chunks

    chunks = split(text)
    if not overlap or len(chunks) < 2:
        return chunks
    return [chunks[0], *[(chunks[index - 1][-overlap:] + chunk).strip() for index, chunk in enumerate(chunks[1:], 1)]]


def content_chunks(text: str, size: int, overlap: int) -> list[str]:
    blocks = [block.strip() for block in re.split(r"\n\s*\n", text) if block.strip()]
    return recursive_chunks("\n\n".join(blocks), size, overlap)


def semantic_chunks(sentences: list[str], embeddings: list[list[float]], threshold: float = 0.72) -> list[str]:
    if len(sentences) != len(embeddings):
        raise ValueError("Each sentence needs one embedding")
    if not sentences:
        return []
    chunks = [[sentences[0].strip()]]
    for index in range(1, len(sentences)):
        if _cosine(embeddings[index - 1], embeddings[index]) < threshold:
            chunks.append([])
        chunks[-1].append(sentences[index].strip())
    return [" ".join(chunk) for chunk in chunks]


def sentences(text: str) -> list[str]:
    return [part.strip() for part in re.split(r"(?<=[.!?])\s+|\n+", text) if part.strip()]


def chunk_text(strategy: str, text: str, size: int, overlap: int) -> list[str]:
    if strategy == "fixed":
        return fixed_chunks(text, size, overlap)
    if strategy == "recursive":
        return recursive_chunks(text, size, overlap)
    if strategy == "content-aware":
        return content_chunks(text, size, overlap)
    raise ValueError("Semantic chunking requires embeddings")


def _validate(size: int, overlap: int) -> None:
    if size < 100 or size > 4000:
        raise ValueError("Chunk size must be between 100 and 4000")
    if overlap < 0 or overlap >= size:
        raise ValueError("Overlap must be smaller than chunk size")


def _cosine(left: list[float], right: list[float]) -> float:
    if len(left) != len(right) or not left:
        raise ValueError("Embedding dimensions must match")
    denominator = math.sqrt(sum(value * value for value in left)) * math.sqrt(sum(value * value for value in right))
    return sum(a * b for a, b in zip(left, right)) / denominator if denominator else 0.0
