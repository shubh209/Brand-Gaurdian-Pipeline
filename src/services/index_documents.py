import sys
from src.db.session import SessionLocal
from src.services.policy_indexing import run_policy_index
from src.services.policy_sources import POLICY_SOURCES


def index_docs(limit: int | None = None):
    db = SessionLocal()
    try:
        sources = POLICY_SOURCES[:limit] if limit else None
        result = run_policy_index(db, sources=sources)
        print(f"Indexing complete: {result}")
    finally:
        db.close()


if __name__ == "__main__":
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else None
    index_docs(limit)
