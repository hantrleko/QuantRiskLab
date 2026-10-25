"""QuantRiskLab: public-data research workbench for macro series and risk summaries."""

__version__ = "1.0.0"


def main() -> None:
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "serve":
        from quantrisklab.api.app import main as serve

        serve()
        return
    print(f"QuantRiskLab {__version__}")
    print("复现: uv run python scripts/reproduce_v0.py")
    print("接口: uv run uvicorn quantrisklab.api.app:app --host 127.0.0.1 --port 8876")
