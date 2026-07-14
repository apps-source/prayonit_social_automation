"""Verifies no Python 3.10+ syntax (PEP 604 unions, match/case) is used, and
that all project modules import cleanly under Python 3.9.
"""
import ast
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MODULE_NAMES = [
    "config",
    "history_store",
    "tracking",
    "buffer_client",
    "image_renderer",
    "campaign_engine",
    "prompt_builder",
    "analytics",
    "prayonit_social",
]


def test_python_version_is_at_least_3_9():
    assert sys.version_info >= (3, 9)


def test_no_match_statement_in_source_files():
    for name in MODULE_NAMES:
        source = (PROJECT_ROOT / f"{name}.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            assert not isinstance(node, getattr(ast, "Match", ())), (
                f"{name}.py uses a match statement (Python 3.10+ only)."
            )


def test_no_pep604_union_type_hints():
    for name in MODULE_NAMES:
        source = (PROJECT_ROOT / f"{name}.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
                # A BinOp with | used inside an annotation context is the
                # PEP 604 union syntax; flag any top-level occurrence.
                raise AssertionError(f"{name}.py appears to use `X | Y` union syntax.")


def test_all_modules_import_successfully():
    import importlib

    for name in MODULE_NAMES:
        importlib.import_module(name)
