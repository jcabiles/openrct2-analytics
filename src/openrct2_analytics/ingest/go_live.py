"""Refuse go-live until permanent captures can survive a seq audit stop."""


def main() -> int:
    """Explain the prerequisite without writing either marker."""
    print(
        "go-live refused: seq-stop: the way around the seq stop in make pipeline is not built "
        '(roadmap backlog item "A way around the seq stop in make pipeline"). Nothing was changed.'
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
