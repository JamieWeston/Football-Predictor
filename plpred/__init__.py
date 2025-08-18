# plpred/__init__.py
"""
Top-level package for the Premier League predictor (plpred).
Keeping these imports here makes `plpred.elo`, `plpred.ratings`, etc.
available after a plain `import plpred`.
"""

# Optional: expose package version if installed as a package
try:
    from importlib.metadata import version as _v  # Python 3.8+
    __version__ = _v("plpred")
except Exception:  # local/dev runs
    __version__ = "0+local"

# Convenience imports so `plpred.<module>` works after `import plpred`
from . import elo, fd_client, ratings, predict, log  # noqa: F401

__all__ = ["elo", "fd_client", "ratings", "predict", "log", "__version__"]
