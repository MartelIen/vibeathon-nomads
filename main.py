"""NomadMeet — entry point."""

from nomadmeet.ui import build_app, THEME, CSS

if __name__ == "__main__":
    app = build_app()
    app.launch(theme=THEME, css=CSS)
