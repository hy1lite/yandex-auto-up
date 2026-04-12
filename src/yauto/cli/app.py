"""Typer application for yandex auto up."""

from __future__ import annotations

import typer

from yauto.cli.panel import (
    add_manual_profile,
    configure_telegram,
    edit_profile,
    launch_panel,
    manage_profiles_menu,
    manage_telegram_menu,
    run_setup_wizard,
    show_doctor_screen,
    show_logs_screen,
    show_service_menu,
    show_status_screen,
    test_telegram,
    toggle_profile,
    _run_uninstall,
)
from yauto.config.repository import ConfigRepository
from yauto.daemon.main import main as daemon_main
from yauto.storage.repository import RuntimeRepository

app = typer.Typer(add_completion=False, no_args_is_help=False)
vm_app = typer.Typer(help="Profile management commands")
telegram_app = typer.Typer(help="Telegram notification commands")
service_app = typer.Typer(help="systemd service commands")
daemon_app = typer.Typer(help="Daemon commands")

app.add_typer(vm_app, name="vm")
app.add_typer(telegram_app, name="telegram")
app.add_typer(service_app, name="service")
app.add_typer(daemon_app, name="daemon")


@app.callback(invoke_without_command=True)
def callback(ctx: typer.Context) -> None:
    if ctx.invoked_subcommand is None:
        launch_panel()


@app.command()
def panel() -> None:
    """Open the interactive CLI panel."""
    launch_panel()


@app.command()
def setup() -> None:
    """Run the guided setup wizard."""
    config_repo = ConfigRepository()
    run_setup_wizard(config_repo, RuntimeRepository(config_repo.paths))


@app.command()
def status() -> None:
    """Show the current daemon and profile status."""
    config_repo = ConfigRepository()
    show_status_screen(config_repo, RuntimeRepository(config_repo.paths))


@app.command()
def doctor() -> None:
    """Run diagnostic checks."""
    show_doctor_screen(ConfigRepository(), pause=False)


@app.command()
def logs(limit: int = typer.Option(20, min=1, max=200), journal: bool = False) -> None:
    """Show recent events and optional journal output."""
    config_repo = ConfigRepository()
    show_logs_screen(
        config_repo,
        RuntimeRepository(config_repo.paths),
        limit=limit,
        include_journal=journal,
        pause=False,
        prompt_for_journal=False,
    )


@app.command()
def uninstall() -> None:
    """Completely remove yandex auto up from this server."""
    _run_uninstall("en")


@vm_app.command("list")
def list_profiles() -> None:
    """Show profile status in table form."""
    config_repo = ConfigRepository()
    show_status_screen(config_repo, RuntimeRepository(config_repo.paths))


@vm_app.command("add")
def add_profile() -> None:
    """Create a profile interactively."""
    add_manual_profile(ConfigRepository())


@vm_app.command("edit")
def edit_profile_command() -> None:
    """Edit a profile interactively."""
    edit_profile(ConfigRepository())


@vm_app.command("toggle")
def toggle_profile_command() -> None:
    """Enable or disable a profile interactively."""
    toggle_profile(ConfigRepository())


@vm_app.command("panel")
def profile_panel() -> None:
    """Open the profile management panel."""
    config_repo = ConfigRepository()
    manage_profiles_menu(config_repo, RuntimeRepository(config_repo.paths))


@telegram_app.command("setup")
def telegram_setup() -> None:
    """Configure Telegram notifications."""
    configure_telegram(ConfigRepository())


@telegram_app.command("test")
def telegram_test() -> None:
    """Test the Telegram bot configuration."""
    test_telegram(ConfigRepository())


@telegram_app.command("panel")
def telegram_panel() -> None:
    """Open the Telegram panel."""
    manage_telegram_menu(ConfigRepository())


@service_app.command("panel")
def service_panel() -> None:
    """Open the service control panel."""
    show_service_menu(ConfigRepository())


@service_app.command("status")
def service_status() -> None:
    """Show overview including service status."""
    config_repo = ConfigRepository()
    show_status_screen(config_repo, RuntimeRepository(config_repo.paths))


@daemon_app.command("run")
def run_daemon() -> None:
    """Run the monitoring daemon in the foreground."""
    daemon_main()


def _fix_io_encoding() -> None:
    """Ensure stdin/stdout/stderr use UTF-8 with error replacement.

    Minimal VPS images (LANG=C, no locales) cause Python's default
    stdin to crash on any non-ASCII byte.  Call this before any Rich I/O.
    """
    import sys

    for name in ("stdin", "stdout", "stderr"):
        stream = getattr(sys, name, None)
        if stream and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


def main() -> None:
    _fix_io_encoding()
    app()


if __name__ == "__main__":
    main()
