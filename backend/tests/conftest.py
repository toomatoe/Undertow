import os

# Tests use an in-memory SQLite DB and never hit the network or the LLM.
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ.pop("ANTHROPIC_API_KEY", None)
