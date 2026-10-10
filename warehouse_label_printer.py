"""Launch the warehouse label printer from the project root."""

def main() -> None:
    from utils.runtime import ensure_repo_venv

    ensure_repo_venv()
    from utils.labels.app import main as run

    run()


if __name__ == "__main__":
    main()
