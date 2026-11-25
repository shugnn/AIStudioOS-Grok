"""Allow `python -m control_plane <command>` as the human CLI entrypoint."""

from .cli import main

if __name__ == "__main__":
    main()
