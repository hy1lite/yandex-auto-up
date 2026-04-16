"""Interactive CLI panel for yandex auto up."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any, Iterable

from rich import box
from rich.align import Align
from rich.console import Console, Group
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.table import Table
from rich.text import Text

from yauto import __display_name__, __tagline__, __version__
from yauto.cloud.client import YandexCloudClient
from yauto.cloud.selectel_client import SelectelCloudClient
from yauto.cli.i18n import normalize_language, status_text, tr
from yauto.cli.update_checker import get_update_status
from yauto.cli.helpers import _parse_selection
from yauto.config.repository import ConfigRepository
from yauto.doctor import run_doctor
from yauto.models import TelegramConfig, VMProfile
from yauto.notify.telegram import TelegramNotifier
from yauto.service_ctl import get_service_status, read_journal, run_service_action
from yauto.storage.repository import RuntimeRepository

console = Console()


def launch_panel(config_repo: ConfigRepository | None = None, runtime_repo: RuntimeRepository | None = None) -> None:
    config_repo = config_repo or ConfigRepository()
    runtime_repo = runtime_repo or RuntimeRepository(config_repo.paths)
    language = _select_language(config_repo)

    while True:
        console.clear()
        show_status_screen(config_repo, runtime_repo, language=language)
        console.print()
        console.print(
            _menu_table(
                language,
                tr(language, "main_panel"),
                [
                    ("1", tr(language, "action_setup"), tr(language, "why_setup")),
                    ("2", tr(language, "action_profiles"), tr(language, "why_profiles")),
                    ("3", tr(language, "action_telegram"), tr(language, "why_telegram")),
                    ("4", tr(language, "action_doctor"), tr(language, "why_doctor")),
                    ("5", tr(language, "action_service"), tr(language, "why_service")),
                    ("6", tr(language, "action_logs"), tr(language, "why_logs")),
                    ("0", tr(language, "action_exit"), tr(language, "why_exit")),
                ],
            )
        )
        choice = Prompt.ask(tr(language, "select_action"), choices=["1", "2", "3", "4", "5", "6", "0"], default="1")
        if choice == "1":
            run_setup_wizard(config_repo, runtime_repo, language=language)
        elif choice == "2":
            manage_profiles_menu(config_repo, runtime_repo, language=language)
        elif choice == "3":
            manage_telegram_menu(config_repo, language=language)
        elif choice == "4":
            show_doctor_screen(config_repo, language=language)
        elif choice == "5":
            show_service_menu(config_repo, language=language)
        elif choice == "6":
            show_logs_screen(config_repo, runtime_repo, language=language)
        else:
            return


def show_status_screen(
    config_repo: ConfigRepository | None = None,
    runtime_repo: RuntimeRepository | None = None,
    language: str | None = None,
) -> None:
    config_repo = config_repo or ConfigRepository()
    runtime_repo = runtime_repo or RuntimeRepository(config_repo.paths)
    config = config_repo.load_app_config()
    language = _resolve_language(config_repo, language)
    state = runtime_repo.load_state()
    profiles = config_repo.list_profiles()
    service = get_service_status(config.service_name)

    console.print(_hero_panel(language))

    summary = Table.grid(padding=(0, 2), expand=False)
    key_files = config_repo.list_key_files()
    summary.add_row(f"[bold bright_white]{tr(language, 'service_state')}[/bold bright_white]", _style_status(state.service_state, language))
    summary.add_row(f"[bold bright_white]{tr(language, 'message')}[/bold bright_white]", state.message or "ready")
    summary.add_row(f"[bold bright_white]{tr(language, 'profiles')}[/bold bright_white]", tr(language, "profiles_configured", count=len(profiles)))
    summary.add_row(f"[bold bright_white]{tr(language, 'keys')}[/bold bright_white]", f"{len(key_files)} @ {config_repo.get_keys_dir()}")
    summary.add_row(
        f"[bold bright_white]{tr(language, 'systemd')}[/bold bright_white]",
        f"supported={service.supported} installed={service.installed} active={service.active} enabled={service.enabled}",
    )
    summary.add_row(f"[bold bright_white]{tr(language, 'config')}[/bold bright_white]", str(config_repo.paths.config_file))
    summary.add_row(f"[bold bright_white]{tr(language, 'state')}[/bold bright_white]", str(config_repo.paths.state_file))
    console.print(Panel(summary, title=tr(language, "system_summary"), border_style="bright_black", box=box.ROUNDED, padding=(0, 1)))

    table = Table(
        box=box.SIMPLE_HEAVY,
        title=tr(language, "vm_profiles"),
        header_style="bold bright_white",
        row_styles=["none", "grey35"],
    )
    table.add_column(tr(language, "name"), style="bold")
    table.add_column("Host", style="bright_magenta")
    table.add_column(tr(language, "status"))
    table.add_column("Cloud")
    table.add_column("Next check")

    if not profiles:
        table.add_row("-", "-", f"[yellow]{tr(language, 'not_configured')}[/yellow]", "-", "-")
    else:
        for profile in profiles:
            runtime = state.profiles.get(profile.profile_id)
            runtime_status = runtime.status if runtime else ("disabled" if not profile.enabled else "unknown")
            table.add_row(
                profile.name,
                profile.check_host,
                _style_status(runtime_status, language),
                runtime.cloud_status if runtime and runtime.cloud_status else "-",
                _format_dt(runtime.next_check_at if runtime else None),
            )

    console.print(table)


def run_setup_wizard(
    config_repo: ConfigRepository | None = None,
    runtime_repo: RuntimeRepository | None = None,
    language: str | None = None,
) -> None:
    config_repo = config_repo or ConfigRepository()
    runtime_repo = runtime_repo or RuntimeRepository(config_repo.paths)
    language = _resolve_language(config_repo, language)
    
    while True:
        console.clear()
        console.print(Panel.fit(f"[bold bright_cyan]{tr(language, 'setup_title')}[/bold bright_cyan]\n[grey70]{tr(language, 'setup_subtitle')}[/grey70]", border_style="bright_cyan", box=box.ROUNDED, padding=(1, 2)))
        
        console.print()
        console.print(
            _menu_table(
                language,
                tr(language, "setup_menu"),
                [
                    ("1", tr(language, "setup_yandex"), tr(language, "setup_yandex_desc")),
                    ("2", tr(language, "setup_selectel"), tr(language, "setup_selectel_desc")),
                    ("3", tr(language, "setup_telegram_menu"), tr(language, "setup_telegram_desc")),
                    ("4", tr(language, "setup_service_menu"), tr(language, "setup_service_desc")),
                    ("0", tr(language, "action_exit"), tr(language, "why_exit")),
                ],
            )
        )
        
        choice = Prompt.ask(tr(language, "select_action"), choices=["1", "2", "3", "4", "0"], default="0")
        
        if choice == "0":
            break
        elif choice == "1":
            _setup_yandex_cloud(config_repo, language)
        elif choice == "2":
            _setup_selectel_cloud(config_repo, language)
        elif choice == "3":
            if Confirm.ask(tr(language, "setup_configure_telegram"), default=False):
                configure_telegram(config_repo, language=language)
            _pause(language)
        elif choice == "4":
            _setup_service(config_repo, language)


def _setup_yandex_cloud(config_repo: ConfigRepository, language: str) -> None:
    console.clear()
    console.print(Panel.fit(f"[bold cyan]{tr(language, 'setup_configuring_yandex')}[/bold cyan]", border_style="cyan", box=box.ROUNDED, padding=(1, 2)))
    
    if not _ensure_service_account(config_repo, language):
        _pause(language)
        return

    imported = 0
    client = _build_cloud_client(config_repo, language)
    if client is not None:
        try:
            folder_id = _choose_folder(client, language)
            if folder_id:
                imported = _import_profiles_from_folder(config_repo, client, folder_id, language)
        finally:
            client.close()
    
    console.print()
    console.print(f"[green]{tr(language, 'setup_imported', count=imported)}[/green]")
    _pause(language)


def _setup_selectel_cloud(config_repo: ConfigRepository, language: str) -> None:
    console.clear()
    console.print(Panel.fit(f"[bold cyan]{tr(language, 'setup_configuring_selectel')}[/bold cyan]", border_style="cyan", box=box.ROUNDED, padding=(1, 2)))
    
    from pathlib import Path
    config = config_repo.load_app_config()
    creds_file = Path(config.selectel_credentials_file)
    
    if not creds_file.exists():
        console.print(f"[yellow]{tr(language, 'setup_selectel_no_creds')}[/yellow]")
        console.print(f"[grey70]{tr(language, 'setup_selectel_creds_path')}: {creds_file}[/grey70]")
        console.print()
        
        if Confirm.ask(tr(language, "setup_selectel_create_creds"), default=True):
            username = Prompt.ask(tr(language, "selectel_username"))
            password = Prompt.ask(tr(language, "selectel_password"), password=True)
            account_id = Prompt.ask(tr(language, "selectel_account_id"))
            project_id = Prompt.ask(tr(language, "selectel_project_id"), default="")
            
            creds_data = {
                "username": username,
                "password": password,
                "account_id": account_id,
            }
            if project_id:
                creds_data["project_id"] = project_id
            
            import json
            creds_file.parent.mkdir(parents=True, exist_ok=True)
            creds_file.write_text(json.dumps(creds_data, indent=2))
            console.print(f"[green]{tr(language, 'setup_selectel_creds_saved')}[/green]")
        else:
            _pause(language)
            return
    
    imported = 0
    selectel_client = _build_selectel_client(config_repo, language)
    if selectel_client is not None:
        try:
            project_id = _choose_selectel_project(selectel_client, language)
            if project_id:
                _import_profiles_from_selectel(config_repo, selectel_client, project_id, language)
                imported = 1
        finally:
            selectel_client.close()
    
    console.print()
    console.print(f"[green]{tr(language, 'setup_imported', count=imported)}[/green]")
    _pause(language)


def _setup_service(config_repo: ConfigRepository, language: str) -> None:
    console.clear()
    console.print(Panel.fit(f"[bold cyan]{tr(language, 'setup_service_menu')}[/bold cyan]", border_style="cyan", box=box.ROUNDED, padding=(1, 2)))
    
    config = config_repo.load_app_config()
    
    if Confirm.ask(tr(language, "setup_enable_autostart"), default=True):
        ok, message = run_service_action(config.service_name, "enable")
        console.print(f"[{'green' if ok else 'red'}]{message}[/{'green' if ok else 'red'}]")
    
    if Confirm.ask(tr(language, "setup_start_service"), default=True):
        action = "restart" if get_service_status(config.service_name).active else "start"
        ok, message = run_service_action(config.service_name, action)
        console.print(f"[{'green' if ok else 'red'}]{message}[/{'green' if ok else 'red'}]")
    
    _pause(language)


def manage_profiles_menu(
    config_repo: ConfigRepository | None = None,
    runtime_repo: RuntimeRepository | None = None,
    language: str | None = None,
) -> None:
    config_repo = config_repo or ConfigRepository()
    runtime_repo = runtime_repo or RuntimeRepository(config_repo.paths)
    language = _resolve_language(config_repo, language)

    while True:
        console.clear()
        show_status_screen(config_repo, runtime_repo, language=language)
        console.print()
        console.print(
            _menu_table(
                language,
                tr(language, "profile_actions"),
                [
                    ("1", tr(language, "action_add_manual"), tr(language, "why_add_manual")),
                    ("2", tr(language, "action_import_cloud"), tr(language, "why_import_cloud")),
                    ("3", tr(language, "action_import_selectel"), tr(language, "why_import_selectel")),
                    ("4", tr(language, "action_edit_profile"), tr(language, "why_edit_profile")),
                    ("5", tr(language, "action_toggle_profile"), tr(language, "why_toggle_profile")),
                    ("6", tr(language, "action_delete_profile"), tr(language, "why_delete_profile")),
                    ("0", tr(language, "action_back"), tr(language, "why_back")),
                ],
            )
        )
        choice = Prompt.ask(tr(language, "select_action"), choices=["1", "2", "3", "4", "5", "6", "0"], default="1")
        if choice == "1":
            add_manual_profile(config_repo, language=language)
        elif choice == "2":
            client = _build_cloud_client(config_repo, language)
            if client is not None:
                try:
                    folder_id = _choose_folder(client, language)
                    if folder_id:
                        _import_profiles_from_folder(config_repo, client, folder_id, language)
                finally:
                    client.close()
                _pause(language)
        elif choice == "3":
            selectel_client = _build_selectel_client(config_repo, language)
            if selectel_client is not None:
                try:
                    project_id = _choose_selectel_project(selectel_client, language)
                    if project_id:
                        _import_profiles_from_selectel(config_repo, selectel_client, project_id, language)
                finally:
                    selectel_client.close()
                _pause(language)
        elif choice == "4":
            edit_profile(config_repo, language=language)
        elif choice == "5":
            toggle_profile(config_repo, language=language)
        elif choice == "6":
            delete_profile(config_repo, language=language)
        else:
            return


def add_manual_profile(config_repo: ConfigRepository | None = None, language: str | None = None) -> None:
    config_repo = config_repo or ConfigRepository()
    language = _resolve_language(config_repo, language)
    console.clear()
    console.print(Panel.fit(f"[bold bright_cyan]{tr(language, 'add_manual_profile')}[/bold bright_cyan]", border_style="bright_cyan", box=box.ROUNDED, padding=(1, 2)))
    name = Prompt.ask(tr(language, "profile_name")).strip()
    if not name:
        console.print(f"[red]{tr(language, 'profile_name_required')}[/red]")
        _pause(language)
        return
    provider = Prompt.ask(tr(language, "provider"), default="yandex").strip().lower()
    if provider not in {"yandex", "selectel"}:
        provider = "yandex"
    folder_id = Prompt.ask(tr(language, "folder_id")).strip()
    instance_id = Prompt.ask(tr(language, "instance_id")).strip()
    project_id = None
    if provider == "selectel":
        project_id = Prompt.ask(tr(language, "project_id")).strip()
    host = Prompt.ask(tr(language, "health_host")).strip()
    interval = _ask_int(language, tr(language, "check_interval"), 60)
    timeout = _ask_int(language, tr(language, "ping_timeout"), 3)
    grace = _ask_int(language, tr(language, "startup_grace"), 180)
    cooldown = _ask_int(language, tr(language, "cooldown"), 300)
    attempts = _ask_int(language, tr(language, "max_start_attempts"), 3)
    notes = Prompt.ask(tr(language, "notes"), default="")

    profile = VMProfile(
        name=name,
        provider=provider,
        folder_id=folder_id,
        instance_id=instance_id,
        project_id=project_id,
        check_host=host,
        check_interval_seconds=interval,
        ping_timeout_seconds=timeout,
        startup_grace_seconds=grace,
        cooldown_seconds=cooldown,
        max_start_attempts=attempts,
        notes=notes,
    )
    config_repo.save_profile(profile)
    console.print(f"[green]{tr(language, 'profile_saved', name=profile.name)}[/green]")
    _pause(language)


def edit_profile(config_repo: ConfigRepository | None = None, language: str | None = None) -> None:
    config_repo = config_repo or ConfigRepository()
    language = _resolve_language(config_repo, language)
    profile = _pick_profile(config_repo, tr(language, "select_profile_edit"), language)
    if profile is None:
        return
    console.clear()
    console.print(Panel.fit(f"[bold bright_cyan]{tr(language, 'edit_profile')}[/bold bright_cyan]\n[white]{profile.name}[/white]", border_style="bright_cyan", box=box.ROUNDED, padding=(1, 2)))

    profile.name = Prompt.ask(tr(language, "profile_name"), default=profile.name).strip() or profile.name
    profile.folder_id = Prompt.ask(tr(language, "folder_id"), default=profile.folder_id).strip() or profile.folder_id
    profile.instance_id = Prompt.ask(tr(language, "instance_id"), default=profile.instance_id).strip() or profile.instance_id
    profile.check_host = Prompt.ask(tr(language, "health_host"), default=profile.check_host).strip() or profile.check_host
    profile.check_interval_seconds = _ask_int(language, tr(language, "check_interval"), profile.check_interval_seconds)
    profile.ping_timeout_seconds = _ask_int(language, tr(language, "ping_timeout"), profile.ping_timeout_seconds)
    profile.startup_grace_seconds = _ask_int(language, tr(language, "startup_grace"), profile.startup_grace_seconds)
    profile.cooldown_seconds = _ask_int(language, tr(language, "cooldown"), profile.cooldown_seconds)
    profile.max_start_attempts = _ask_int(language, tr(language, "max_start_attempts"), profile.max_start_attempts)
    profile.notes = Prompt.ask(tr(language, "notes"), default=profile.notes)
    config_repo.save_profile(profile)
    console.print(f"[green]{tr(language, 'profile_updated', name=profile.name)}[/green]")
    _pause(language)


def toggle_profile(config_repo: ConfigRepository | None = None, language: str | None = None) -> None:
    config_repo = config_repo or ConfigRepository()
    language = _resolve_language(config_repo, language)
    profile = _pick_profile(config_repo, tr(language, "select_profile_toggle"), language)
    if profile is None:
        return
    profile.enabled = not profile.enabled
    config_repo.save_profile(profile)
    key = "profile_enabled" if profile.enabled else "profile_disabled"
    console.print(f"[green]{tr(language, key, name=profile.name)}[/green]")
    _pause(language)


def delete_profile(config_repo: ConfigRepository | None = None, language: str | None = None) -> None:
    config_repo = config_repo or ConfigRepository()
    language = _resolve_language(config_repo, language)
    profile = _pick_profile(config_repo, tr(language, "select_profile_delete"), language)
    if profile is None:
        return
    if Confirm.ask(tr(language, "delete_profile_confirm", name=profile.name), default=False):
        config_repo.delete_profile(profile.profile_id)
        console.print(f"[green]{tr(language, 'profile_deleted', name=profile.name)}[/green]")
    _pause(language)


def manage_telegram_menu(config_repo: ConfigRepository | None = None, language: str | None = None) -> None:
    config_repo = config_repo or ConfigRepository()
    language = _resolve_language(config_repo, language)
    while True:
        console.clear()
        config = config_repo.load_app_config()
        notifier = TelegramNotifier(config.telegram)
        status = tr(language, "telegram_configured") if notifier.configured() else tr(language, "telegram_not_configured")
        console.print(Panel.fit(f"[bold bright_cyan]{tr(language, 'telegram_title')}[/bold bright_cyan]\n[grey70]{tr(language, 'telegram_current_status', status=status)}[/grey70]", border_style="bright_cyan", box=box.ROUNDED, padding=(1, 2)))
        console.print(
            _menu_table(
                language,
                tr(language, "telegram_actions"),
                [
                    ("1", tr(language, "action_configure"), tr(language, "why_configure")),
                    ("2", tr(language, "action_test"), tr(language, "why_test")),
                    ("3", tr(language, "action_disable"), tr(language, "why_disable")),
                    ("0", tr(language, "action_back"), tr(language, "why_back")),
                ],
            )
        )
        choice = Prompt.ask(tr(language, "select_action"), choices=["1", "2", "3", "0"], default="1")
        if choice == "1":
            configure_telegram(config_repo, language=language)
        elif choice == "2":
            test_telegram(config_repo, language=language)
        elif choice == "3":
            disable_telegram(config_repo, language=language)
        else:
            return


def configure_telegram(config_repo: ConfigRepository | None = None, language: str | None = None) -> None:
    config_repo = config_repo or ConfigRepository()
    language = _resolve_language(config_repo, language)
    config = config_repo.load_app_config()
    console.clear()
    console.print(Panel.fit(f"[bold bright_cyan]{tr(language, 'configure_telegram')}[/bold bright_cyan]", border_style="bright_cyan", box=box.ROUNDED, padding=(1, 2)))
    token = Prompt.ask(tr(language, "bot_token"), default=config.telegram.bot_token)
    chat_id = Prompt.ask(tr(language, "chat_id"), default=config.telegram.chat_id)
    telegram = TelegramConfig(
        enabled=True,
        bot_token=token.strip(),
        chat_id=chat_id.strip(),
        notify_on_start=Confirm.ask(tr(language, "notify_start"), default=config.telegram.notify_on_start),
        notify_on_recovery=Confirm.ask(tr(language, "notify_recovery"), default=config.telegram.notify_on_recovery),
        notify_on_error=Confirm.ask(tr(language, "notify_errors"), default=config.telegram.notify_on_error),
    )
    config.telegram = telegram
    config_repo.save_app_config(config)
    test_telegram(config_repo, pause=False, language=language)
    _pause(language)


def test_telegram(config_repo: ConfigRepository | None = None, pause: bool = True, language: str | None = None) -> None:
    config_repo = config_repo or ConfigRepository()
    language = _resolve_language(config_repo, language)
    config = config_repo.load_app_config()
    notifier = TelegramNotifier(config.telegram)
    ok, message = notifier.test_connection()
    console.print(f"[{'green' if ok else 'red'}]{message}[/{'green' if ok else 'red'}]")
    if ok and notifier.send("[yandex auto up] test message"):
        console.print(f"[green]{tr(language, 'telegram_test_sent')}[/green]")
    elif ok:
        console.print(f"[yellow]{tr(language, 'telegram_test_send_failed')}[/yellow]")
    if pause:
        _pause(language)


def disable_telegram(config_repo: ConfigRepository | None = None, language: str | None = None) -> None:
    config_repo = config_repo or ConfigRepository()
    language = _resolve_language(config_repo, language)
    config = config_repo.load_app_config()
    config.telegram.enabled = False
    config_repo.save_app_config(config)
    console.print(f"[green]{tr(language, 'telegram_disabled')}[/green]")
    _pause(language)


def show_doctor_screen(config_repo: ConfigRepository | None = None, pause: bool = True, language: str | None = None) -> None:
    config_repo = config_repo or ConfigRepository()
    language = _resolve_language(config_repo, language)
    console.clear()
    console.print(Panel.fit(f"[bold bright_cyan]{tr(language, 'doctor_title')}[/bold bright_cyan]", border_style="bright_cyan", box=box.ROUNDED, padding=(1, 2)))
    checks = run_doctor(config_repo)
    table = Table(box=box.SIMPLE_HEAVY, header_style="bold bright_white", row_styles=["none", "grey35"])
    table.add_column(tr(language, "doctor_check"), style="bold")
    table.add_column(tr(language, "doctor_status"))
    table.add_column(tr(language, "doctor_detail"))
    for check in checks:
        table.add_row(check.name, _style_status(check.status, language), check.detail)
    console.print(table)
    if pause:
        _pause(language)


def show_service_menu(config_repo: ConfigRepository | None = None, language: str | None = None) -> None:
    config_repo = config_repo or ConfigRepository()
    language = _resolve_language(config_repo, language)
    service_name = config_repo.load_app_config().service_name
    while True:
        console.clear()
        status = get_service_status(service_name)
        console.print(
            Panel.fit(
                f"[bold bright_cyan]{tr(language, 'service_controls')}[/bold bright_cyan]\n"
                f"[grey70]{tr(language, 'service_overview', name=service_name, supported=status.supported, installed=status.installed, active=status.active, enabled=status.enabled)}[/grey70]",
                border_style="bright_cyan",
                box=box.ROUNDED,
                padding=(1, 2),
            )
        )
        console.print(
            _menu_table(
                language,
                tr(language, "service_actions"),
                [
                    ("1", tr(language, "action_start"), tr(language, "why_start")),
                    ("2", tr(language, "action_stop"), tr(language, "why_stop")),
                    ("3", tr(language, "action_restart"), tr(language, "why_restart")),
                    ("4", tr(language, "action_enable"), tr(language, "why_enable")),
                    ("5", tr(language, "action_disable_service"), tr(language, "why_disable_service")),
                    ("6", tr(language, "action_uninstall"), tr(language, "why_uninstall")),
                    ("0", tr(language, "action_back"), tr(language, "why_back")),
                ],
            )
        )
        choice = Prompt.ask(tr(language, "select_action"), choices=["1", "2", "3", "4", "5", "6", "0"], default="1")
        if choice == "0":
            return
        if choice == "6":
            if _run_uninstall(language):
                return
            continue
        action_map = {"1": "start", "2": "stop", "3": "restart", "4": "enable", "5": "disable"}
        ok, message = run_service_action(service_name, action_map[choice])
        console.print(f"[{'green' if ok else 'red'}]{message}[/{'green' if ok else 'red'}]")
        _pause(language)


def show_logs_screen(
    config_repo: ConfigRepository | None = None,
    runtime_repo: RuntimeRepository | None = None,
    limit: int = 20,
    include_journal: bool = False,
    pause: bool = True,
    prompt_for_journal: bool = True,
    language: str | None = None,
) -> None:
    config_repo = config_repo or ConfigRepository()
    runtime_repo = runtime_repo or RuntimeRepository(config_repo.paths)
    language = _resolve_language(config_repo, language)
    console.clear()
    console.print(Panel.fit(f"[bold bright_cyan]{tr(language, 'logs_title')}[/bold bright_cyan]", border_style="bright_cyan", box=box.ROUNDED, padding=(1, 2)))
    events = runtime_repo.tail_events(limit)
    table = Table(box=box.SIMPLE_HEAVY, title=tr(language, "recent_events"), header_style="bold bright_white", row_styles=["none", "grey35"])
    table.add_column(tr(language, "time"))
    table.add_column(tr(language, "level"))
    table.add_column(tr(language, "category"))
    table.add_column(tr(language, "profile"))
    table.add_column(tr(language, "message_column"))
    if events:
        for event in events:
            table.add_row(
                _format_dt(event.timestamp),
                _style_status(event.level.lower(), language),
                event.category,
                event.profile_name or "-",
                event.message,
            )
    else:
        table.add_row("-", "-", "-", "-", tr(language, "no_events"))
    console.print(table)

    if include_journal or (prompt_for_journal and Confirm.ask(tr(language, "show_journal"), default=False)):
        service_name = config_repo.load_app_config().service_name
        journal = read_journal(service_name, limit=limit)
        console.print(Panel(journal or "No journal output.", title=tr(language, "journal_title"), border_style="bright_black", box=box.SIMPLE))
    if pause:
        _pause(language)


def _ensure_service_account(config_repo: ConfigRepository, language: str) -> bool:
    keys_dir = config_repo.get_keys_dir()

    while True:
        if config_repo.has_keys():
            files = config_repo.list_key_files()
            console.print(f"[green]{tr(language, 'service_account_ready', path=keys_dir, count=len(files))}[/green]")
            return True

        # Show diagnostics
        diag = config_repo.diagnose_keys_dir()
        body_lines = [
            f"[bold bright_cyan]{tr(language, 'service_account_input')}[/bold bright_cyan]",
            f"[bold bright_white]{tr(language, 'service_account_drop_dir')}[/bold bright_white]",
            str(keys_dir),
            "",
            f"[grey70]{tr(language, 'service_account_instructions', path=keys_dir)}[/grey70]",
        ]
        if diag["invalid"]:
            body_lines.append("")
            body_lines.append(f"[yellow]{tr(language, 'keys_skipped_files')}[/yellow]")
            for bad_path, reason in diag["invalid"]:
                body_lines.append(f"  [yellow]• {bad_path.name}[/yellow]: [grey70]{reason}[/grey70]")

        console.print(
            Panel.fit(
                "\n".join(body_lines),
                border_style="bright_cyan",
                box=box.ROUNDED,
                padding=(1, 2),
            )
        )
        if not Confirm.ask(tr(language, "service_account_recheck"), default=True):
            return False


def _build_selectel_client(config_repo: ConfigRepository, language: str) -> SelectelCloudClient | None:
    from pathlib import Path
    config = config_repo.load_app_config()
    creds_file = Path(config.selectel_credentials_file)
    
    if not creds_file.exists():
        console.print(f"[red]Selectel credentials file not found: {creds_file}[/red]")
        console.print(f"[yellow]Create a JSON file with: username, password, account_id, project_id[/yellow]")
        _pause(language)
        return None
    
    try:
        console.print(f"[cyan]Reading credentials from {creds_file}...[/cyan]")
        client = SelectelCloudClient.from_credentials_file(creds_file)
        console.print(f"[cyan]Authenticating with Selectel...[/cyan]")
        if not client.ensure_authenticated():
            console.print(f"[red]Failed to authenticate with Selectel[/red]")
            console.print(f"[yellow]Check your credentials in {creds_file}[/yellow]")
            _pause(language)
            return None
        console.print(f"[green]Successfully authenticated with Selectel![/green]")
        return client
    except Exception as exc:
        console.print(f"[red]Selectel auth failed:[/red]")
        console.print(f"[red]{exc}[/red]")
        console.print()
        console.print(f"[yellow]Full error details:[/yellow]")
        import traceback
        console.print(f"[grey70]{traceback.format_exc()}[/grey70]")
        _pause(language)
        return None


def _choose_selectel_project(client: SelectelCloudClient, language: str) -> str | None:
    try:
        console.print(f"[cyan]Loading Selectel projects...[/cyan]")
        projects = client.list_projects()
        console.print(f"[green]Found {len(projects)} project(s)[/green]")
    except Exception as exc:
        console.print(f"[red]Failed to list Selectel projects:[/red]")
        console.print(f"[red]{exc}[/red]")
        console.print()
        console.print(f"[yellow]Full error details:[/yellow]")
        import traceback
        console.print(f"[grey70]{traceback.format_exc()}[/grey70]")
        _pause(language)
        return None
    
    if not projects:
        console.print(f"[yellow]No Selectel projects found[/yellow]")
        _pause(language)
        return None
    
    project = _pick_record(
        language,
        "Selectel Projects",
        projects,
        lambda item: (item.get("name", "unnamed"), item.get("id", "")),
        ("Name", "Project ID"),
    )
    if project is None:
        return None
    return project.get("id")


def _import_profiles_from_selectel(
    config_repo: ConfigRepository,
    client: SelectelCloudClient,
    project_id: str,
    language: str,
) -> None:
    try:
        console.print(f"[cyan]Loading servers from project {project_id}...[/cyan]")
        servers = client.list_servers(project_id)
        console.print(f"[green]Found {len(servers)} server(s)[/green]")
    except Exception as exc:
        console.print(f"[red]Failed to list servers:[/red]")
        console.print(f"[red]{exc}[/red]")
        console.print()
        console.print(f"[yellow]Full error details:[/yellow]")
        import traceback
        console.print(f"[grey70]{traceback.format_exc()}[/grey70]")
        _pause(language)
        return
    
    if not servers:
        console.print(f"[yellow]No servers found in project[/yellow]")
        console.print()
        if Confirm.ask("Create profile manually?", default=True):
            _create_selectel_profile_manually(config_repo, project_id, language)
        return
    
    table = Table(title="Servers in Project", box=box.ROUNDED, border_style="bright_cyan")
    table.add_column("#", style="bright_white", justify="right")
    table.add_column(tr(language, "name"), style="bright_cyan")
    table.add_column(tr(language, "status"), style="bright_white")
    table.add_column(tr(language, "primary_ip"), style="bright_white")
    
    for idx, server in enumerate(servers, start=1):
        name = server.get("name", "unnamed")
        status = server.get("status", "UNKNOWN")
        ip = SelectelCloudClient.extract_primary_ip(server)
        table.add_row(str(idx), name, status, ip or tr(language, "manual_host_required"))
    
    console.print(table)
    
    selection = Prompt.ask(tr(language, "select_instances"), default="").strip()
    if not selection:
        return
    
    indices = _parse_selection(selection, len(servers))
    if not indices:
        console.print(f"[red]{tr(language, 'invalid_selection')}[/red]")
        return
    
    interval = _ask_int(language, tr(language, "default_interval"), 60)
    timeout = _ask_int(language, tr(language, "default_timeout"), 3)
    
    existing_ids = {p.instance_id for p in config_repo.list_profiles()}
    imported = 0
    
    for idx in indices:
        server = servers[idx - 1]
        server_id = server.get("id", "")
        name = server.get("name", "unnamed")
        
        if server_id in existing_ids:
            console.print(f"[yellow]{tr(language, 'skip_already_configured', name=name)}[/yellow]")
            continue
        
        ip = SelectelCloudClient.extract_primary_ip(server)
        if not ip:
            ip = Prompt.ask(tr(language, "health_host_for", name=name), default="").strip()
            if not ip:
                console.print(f"[yellow]{tr(language, 'skip_missing_host', name=name)}[/yellow]")
                continue
        
        profile = VMProfile(
            name=name,
            provider="selectel",
            folder_id=project_id,
            instance_id=server_id,
            project_id=project_id,
            check_host=ip,
            check_interval_seconds=interval,
            ping_timeout_seconds=timeout,
        )
        config_repo.save_profile(profile)
        imported += 1
    
    console.print(f"[green]{tr(language, 'profiles_imported', count=imported)}[/green]")


def _build_cloud_client(config_repo: ConfigRepository, language: str) -> YandexCloudClient | None:
    keys_dir = config_repo.get_keys_dir()
    try:
        files = config_repo.validate_keys()
    except FileNotFoundError:
        console.print(f"[red]{tr(language, 'service_account_missing', path=keys_dir)}[/red]")
        return None
    except Exception as exc:
        console.print(f"[red]{tr(language, 'service_account_failed', error=exc)}[/red]")
        return None
    try:
        client = YandexCloudClient.from_service_account_files(files)
        client.ensure_authenticated()
        return client
    except Exception as exc:
        console.print(f"[red]{tr(language, 'cloud_auth_failed', error=exc)}[/red]")
        return None


def _choose_folder(client: YandexCloudClient, language: str) -> str | None:
    try:
        clouds = client.list_clouds()
    except CloudApiError:
        clouds = []
    if not clouds:
        console.print(f"[yellow]{tr(language, 'no_clouds')}[/yellow]")
        return _choose_folder_manual(client, language)
    cloud = _pick_record(
        language,
        tr(language, "visible_clouds"),
        clouds,
        lambda item: (item.get("name", "unnamed"), item.get("id", "")),
        (tr(language, "name"), "Cloud ID"),
    )
    if cloud is None:
        return None
    try:
        folders = client.list_folders(cloud.get("id", ""))
    except CloudApiError:
        folders = []
    if not folders:
        console.print(f"[yellow]{tr(language, 'no_folders')}[/yellow]")
        return _choose_folder_manual(client, language)
    folder = _pick_record(
        language,
        tr(language, "visible_folders"),
        folders,
        lambda item: (item.get("name", "unnamed"), item.get("id", ""), item.get("status", "")),
        (tr(language, "name"), "Folder ID", tr(language, "status")),
    )
    if folder is None:
        return None
    return folder.get("id", "")


def _choose_folder_manual(client: YandexCloudClient, language: str) -> str | None:
    if not Confirm.ask(tr(language, "manual_folder_try"), default=True):
        return None

    folder_id = Prompt.ask(tr(language, "folder_id")).strip()
    if not folder_id:
        return None

    try:
        client.list_instances(folder_id)
    except Exception as exc:
        console.print(f"[red]{tr(language, 'manual_folder_failed', folder_id=folder_id, error=exc)}[/red]")
        return None
    return folder_id


def _import_profiles_from_folder(config_repo: ConfigRepository, client: YandexCloudClient, folder_id: str, language: str) -> int:
    instances = client.list_instances(folder_id)
    if not instances:
        console.print(f"[yellow]{tr(language, 'no_profiles_yet')}[/yellow]")
        return 0

    table = Table(box=box.SIMPLE_HEAVY, title=tr(language, "instances_folder"), header_style="bold bright_white", row_styles=["none", "grey35"])
    table.add_column("#", style="bold bright_cyan")
    table.add_column(tr(language, "name"))
    table.add_column(tr(language, "status"))
    table.add_column(tr(language, "primary_ip"))
    table.add_column("Instance ID")
    for index, instance in enumerate(instances, start=1):
        table.add_row(
            str(index),
            instance.get("name", "unnamed"),
            instance.get("status", "UNKNOWN"),
            client.extract_primary_ip(instance) or tr(language, "manual_host_required"),
            instance.get("id", ""),
        )
    console.print(table)

    raw_selection = Prompt.ask(tr(language, "select_instances"), default="").strip().lower()
    if not raw_selection:
        return 0
    if raw_selection == "all":
        selected = instances
    else:
        try:
            indices = [int(chunk.strip()) for chunk in raw_selection.split(",") if chunk.strip()]
        except ValueError:
            console.print(f"[red]{tr(language, 'invalid_selection')}[/red]")
            return 0
        selected = [instances[index - 1] for index in indices if 1 <= index <= len(instances)]

    default_interval = _ask_int(language, tr(language, "default_interval"), 60)
    default_timeout = _ask_int(language, tr(language, "default_timeout"), 3)
    imported = 0
    existing_by_instance = {profile.instance_id for profile in config_repo.list_profiles()}

    for instance in selected:
        instance_id = instance.get("id", "")
        instance_name = instance.get("name", "unnamed")
        if instance_id in existing_by_instance:
            console.print(f"[yellow]{tr(language, 'skip_already_configured', name=instance_name)}[/yellow]")
            continue
        host = client.extract_primary_ip(instance)
        if not host:
            host = Prompt.ask(tr(language, "health_host_for", name=instance_name)).strip()
            if not host:
                console.print(f"[yellow]{tr(language, 'skip_missing_host', name=instance_name)}[/yellow]")
                continue
        profile = VMProfile(
            name=instance_name,
            provider="yandex",
            folder_id=folder_id,
            instance_id=instance_id,
            check_host=host,
            check_interval_seconds=default_interval,
            ping_timeout_seconds=default_timeout,
        )
        config_repo.save_profile(profile)
        imported += 1

    console.print(f"[green]{tr(language, 'profiles_imported', count=imported)}[/green]")
    return imported


def _pick_profile(config_repo: ConfigRepository, title: str, language: str) -> VMProfile | None:
    profiles = config_repo.list_profiles()
    if not profiles:
        console.print(f"[yellow]{tr(language, 'no_profiles_yet')}[/yellow]")
        _pause(language)
        return None
    record = _pick_record(
        language,
        title,
        profiles,
        lambda profile: (profile.name, profile.check_host, status_text(language, "enabled" if profile.enabled else "disabled")),
        (tr(language, "name"), "Host", tr(language, "state_column")),
    )
    return record if isinstance(record, VMProfile) else None


def _pick_record(language: str, title: str, records: Iterable[Any], row_builder, columns: tuple[str, ...]):
    items = list(records)
    table = Table(box=box.SIMPLE_HEAVY, title=title, header_style="bold bright_white", row_styles=["none", "grey35"])
    table.add_column("#", style="bold bright_cyan")
    for column in columns:
        table.add_column(column)
    for index, record in enumerate(items, start=1):
        values = row_builder(record)
        table.add_row(str(index), *[str(value) for value in values])
    console.print(table)
    choices = [str(index) for index in range(1, len(items) + 1)] + ["0"]
    selected = Prompt.ask(tr(language, "choose_number"), choices=choices, default="0")
    if selected == "0":
        return None
    return items[int(selected) - 1]


def _menu_table(language: str, title: str, rows: list[tuple[str, str, str]]) -> Table:
    table = Table(title=f"[italic bright_black]{title}[/italic bright_black]", box=box.SIMPLE_HEAVY, header_style="bold bright_white", row_styles=["none", "grey35"])
    table.add_column(tr(language, "menu_key"), style="bold bright_cyan", width=8, no_wrap=True)
    table.add_column(tr(language, "menu_action"), style="white")
    table.add_column(tr(language, "menu_why"), style="grey70")
    for key, action, why in rows:
        table.add_row(key, action, why)
    return table


def _ask_int(language: str, label: str, default: int) -> int:
    raw = Prompt.ask(label, default=str(default)).strip()
    try:
        return int(raw)
    except ValueError:
        console.print(f"[yellow]{tr(language, 'using_default', value=default)}[/yellow]")
        return default


def _style_status(status: str | None, language: str) -> str:
    normalized = (status or "unknown").lower()
    styles = {
        "running": "green",
        "online": "green",
        "ok": "green",
        "active": "green",
        "enabled": "green",
        "starting": "cyan",
        "idle": "cyan",
        "warn": "yellow",
        "cooldown": "yellow",
        "disabled": "yellow",
        "needs-setup": "yellow",
        "stopped": "yellow",
        "error": "red",
        "degraded": "red",
        "inactive": "red",
        "unknown": "white",
    }
    color = styles.get(normalized, "white")
    return f"[{color}]{status_text(language, status)}[/{color}]"


def _format_dt(value) -> str:
    if value is None:
        return "-"
    return value.astimezone().strftime("%Y-%m-%d %H:%M:%S")


def _pause(language: str) -> None:
    Prompt.ask(tr(language, "press_enter"), default="")


def _resolve_language(config_repo: ConfigRepository, language: str | None) -> str:
    if language:
        return normalize_language(language)
    return normalize_language(config_repo.load_app_config().language)


def _select_language(config_repo: ConfigRepository) -> str:
    config = config_repo.load_app_config()
    current = normalize_language(config.language)
    console.clear()

    options = Table.grid(padding=(0, 1))
    options.add_row(f"[bold bright_cyan]{tr(current, 'language_option_ru')}[/bold bright_cyan]")
    options.add_row(f"[bold bright_cyan]{tr(current, 'language_option_en')}[/bold bright_cyan]")
    console.print(
        Panel.fit(
            f"[bold bright_cyan]{tr(current, 'language_title')}[/bold bright_cyan]\n"
            f"[grey70]{tr(current, 'language_subtitle')}[/grey70]\n\n",
            border_style="bright_cyan",
            box=box.ROUNDED,
            padding=(1, 2),
        )
    )
    console.print(options)

    choice = Prompt.ask(tr(current, "language_prompt"), choices=["1", "2"], default="1" if current == "ru" else "2")
    selected = "ru" if choice == "1" else "en"
    if config.language != selected:
        config.language = selected
        config_repo.save_app_config(config)
    return selected


def _hero_panel(language: str) -> Panel:
    update_status = get_update_status(ConfigRepository().paths)
    update_line = Text("", style="dim")
    if update_status.has_update and update_status.latest_version:
        update_line = Text(tr(language, "update_available", version=update_status.latest_version), style="green")

    body = Group(
        Text(__display_name__, style="bold bright_cyan"),
        Text(__tagline__ or tr(language, "app_subtitle"), style="grey70"),
        Text(f"{tr(language, 'language_label')}: {tr(language, 'language_name')}   {tr(language, 'version_label')}: {__version__}", style="dim"),
        Align.right(update_line),
    )
    return Panel.fit(body, title=tr(language, "overview_title"), border_style="bright_cyan", box=box.ROUNDED, padding=(1, 2))


def _run_uninstall(language: str) -> bool:
    if not Confirm.ask(tr(language, "uninstall_confirm"), default=False):
        return False

    script_path = Path(os.environ.get("YAUTO_INSTALL_ROOT", "/opt/yandex-auto-up")) / "app" / "scripts" / "uninstall.sh"
    if not script_path.exists():
        console.print(f"[red]{tr(language, 'uninstall_missing', path=script_path)}[/red]")
        _pause(language)
        return False

    console.print(f"[yellow]{tr(language, 'uninstall_running')}[/yellow]")
    result = subprocess.run(["bash", str(script_path)], capture_output=True, text=True, check=False)
    output = (result.stdout or result.stderr or "").strip()
    if output:
        console.print(output)
    console.print(f"[green]{tr(language, 'uninstall_done')}[/green]")
    return True
