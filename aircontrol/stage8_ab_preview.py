"""Optional A/B comparison entry point; main.py uses Scheme B directly."""

from .aircontrol_app import main as run_app


def main() -> None:
    run_app(compare=True)


if __name__ == "__main__":
    main()
