"""PyInstaller entry point.

A separate launcher (instead of pointing PyInstaller at worklog/app.py directly)
avoids a sys.path collision: PyInstaller adds the target script's own directory
to sys.path, which would shadow the `worklog` package if the script lived inside it.
"""
from worklog.app import main

if __name__ == "__main__":
    raise SystemExit(main())
