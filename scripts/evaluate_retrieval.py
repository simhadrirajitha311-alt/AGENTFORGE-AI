"""Reproduce a tiny synthetic ranking check; it is not a production benchmark."""

from app.rag import TfidfRanker

CASES = [
    ("approval before a payment", "Payments over $500 require manager approval."),
    ("how to chunk knowledge documents", "Text documents are split into overlapping chunks."),
    ("calculator arithmetic limits", "Arithmetic powers are bounded to avoid runaway results."),
    ("cancel a running process", "Runs can be cancelled by an authorized administrator."),
]
CANDIDATES = [
    "Payments over $500 require manager approval.",
    "Text documents are split into overlapping chunks.",
    "Arithmetic powers are bounded to avoid runaway results.",
    "Runs can be cancelled by an authorized administrator.",
    "MCP tools are discovered and checked against an explicit allowlist.",
]


def main() -> None:
    ranker = TfidfRanker()
    reciprocal_ranks = []
    recalls_at_one = []
    for query, relevant in CASES:
        ranked = sorted(
            enumerate(ranker.rank(query, CANDIDATES)), key=lambda item: item[1], reverse=True,
        )
        position = next((rank for rank, (index, _) in enumerate(ranked, 1)
                         if CANDIDATES[index] == relevant), None)
        reciprocal_ranks.append(1 / position if position else 0)
        recalls_at_one.append(float(position == 1))
    print(f"cases={len(CASES)} MRR={sum(reciprocal_ranks) / len(CASES):.3f} "
          f"Recall@1={sum(recalls_at_one) / len(CASES):.3f}")


if __name__ == "__main__":
    main()