"""
Утилита для экспорта расписания за семестр в Excel.

Запуск:
    python -m excel_export.export_semester --query "ИС1-227-ОТ" --mode student
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import logging
import os
import sys
from collections import OrderedDict
from importlib import import_module
from pathlib import Path
from typing import Dict, Iterable, Optional, Tuple

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

try:
    from telegram import Bot
    from telegram.error import TelegramError
except Exception:  # pragma: no cover
    Bot = None  # type: ignore
    TelegramError = Exception  # type: ignore

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.constants import API_TYPE_GROUP, API_TYPE_TEACHER  # noqa: E402
from app.schedule import get_schedule_structured  # noqa: E402

logger = logging.getLogger("excel_export")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

WEEKDAY_NAMES = [
    "Понедельник",
    "Вторник",
    "Среда",
    "Четверг",
    "Пятница",
    "Суббота",
    "Воскресенье",
]

SEMESTER_PRESETS = {
    "autumn": {
        "label": "Осенний семестр",
        "start": (9, 1),
        "end": (12, 31),
    },
    "spring": {
        "label": "Весенний семестр",
        "start": (1, 1),
        "end": (4, 30),
    },
}

try:
    config = import_module("excel_export.config")
except ModuleNotFoundError:
    config = None

CONFIG_BOT_TOKEN = getattr(config, "TELEGRAM_BOT_TOKEN", os.getenv("EXPORT_BOT_TOKEN"))
CONFIG_CHAT_ID = getattr(config, "TELEGRAM_CHAT_ID", os.getenv("EXPORT_CHAT_ID"))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Экспорт расписания за семестр в Excel")
    parser.add_argument("--query", required=True, help="Название группы или преподавателя")
    parser.add_argument(
        "--mode",
        choices=("student", "teacher"),
        default="student",
        help="Режим экспорта: группа (student) или преподаватель (teacher)",
    )
    parser.add_argument(
        "--semester",
        choices=("autumn", "spring"),
        help="Семестр: autumn (сентябрь-декабрь) или spring (январь-апрель). По умолчанию определяется по текущей дате.",
    )
    parser.add_argument(
        "--year",
        type=int,
        help="Год семестра (например 2025). Если не указан, определяется автоматически.",
    )
    parser.add_argument("--start", type=str, help="Переопределить дату начала (формат YYYY-MM-DD)")
    parser.add_argument("--end", type=str, help="Переопределить дату окончания (формат YYYY-MM-DD)")
    parser.add_argument(
        "--output",
        type=str,
        default="exports",
        help="Каталог для сохранения Excel-файла (по умолчанию exports/)",
    )
    parser.add_argument("--filename", type=str, help="Имя файла (по умолчанию генерируется автоматически)")
    parser.add_argument(
        "--send",
        action="store_true",
        help="Отправить результат в Telegram (нужен токен и chat_id)",
    )
    parser.add_argument("--bot-token", type=str, help="Токен Telegram-бота для отправки файла")
    parser.add_argument("--chat-id", type=str, help="ID чата для отправки файла")
    parser.add_argument("--silent", action="store_true", help="Отключить информационные логи")
    return parser.parse_args()


def resolve_semester_bounds(
    semester: Optional[str], year: Optional[int], start: Optional[str], end: Optional[str]
) -> Tuple[dt.date, dt.date, str]:
    today = dt.date.today()
    if semester is None:
        if today.month >= 9:
            semester = "autumn"
        elif today.month <= 4:
            semester = "spring"
        else:
            semester = "autumn"

    preset = SEMESTER_PRESETS[semester]
    if year is None:
        if semester == "autumn":
            year = today.year if today.month >= 9 else today.year - 1
        else:  # spring
            year = today.year if today.month <= 4 else today.year + 1

    start_date = dt.date(year, preset["start"][0], preset["start"][1])
    end_date = dt.date(year, preset["end"][0], preset["end"][1])

    label = f"{preset['label']} {year}"
    if start:
        start_date = _parse_date(start)
        label = "Произвольный период"
    if end:
        end_date = _parse_date(end)
        label = "Произвольный период"
    if start_date > end_date:
        raise ValueError("Дата начала позже даты окончания")
    return start_date, end_date, label


def _parse_date(value: str) -> dt.date:
    return dt.datetime.strptime(value, "%Y-%m-%d").date()


async def fetch_semester_schedule(
    query: str,
    entity_type: str,
    start_date: dt.date,
    end_date: dt.date,
) -> "OrderedDict[dt.date, Dict]":
    aggregated: "OrderedDict[dt.date, Dict]" = OrderedDict()
    date_cursor = start_date
    total_days = (end_date - start_date).days + 1
    logger.info(
        "📅 Собираю расписание для '%s' (%s) с %s по %s (%d дней)",
        query,
        "группа" if entity_type == API_TYPE_GROUP else "преподаватель",
        start_date.strftime("%d.%m.%Y"),
        end_date.strftime("%d.%m.%Y"),
        total_days,
    )

    while date_cursor <= end_date:
        if date_cursor.weekday() == 6:  # воскресенье пропускаем
            date_cursor += dt.timedelta(days=1)
            continue

        date_str = date_cursor.strftime("%Y-%m-%d")
        structured, err = await get_schedule_structured(date_str, query, entity_type)
        if err:
            logger.debug("Нет расписания на %s: %s", date_str, err)
        elif structured and structured.get("pairs"):
            actual_date_str = structured.get("date_iso", date_str)
            actual_date = dt.datetime.strptime(actual_date_str, "%Y-%m-%d").date()
            aggregated[actual_date] = {
                "weekday": structured.get("weekday") or WEEKDAY_NAMES[actual_date.weekday()],
                "pairs": structured.get("pairs", []),
            }
        date_cursor += dt.timedelta(days=1)

    logger.info("✅ Найдено %d учебных дней с расписанием", len(aggregated))
    return aggregated


def build_excel_workbook(
    entity_name: str,
    mode: str,
    semester_label: str,
    data: "OrderedDict[dt.date, Dict]",
) -> Workbook:
    wb = Workbook()
    ws = wb.active
    sheet_name = _sanitize_sheet_name(entity_name)
    ws.title = sheet_name

    entity_label = "Группа" if mode == "student" else "Преподаватель"
    ws.merge_cells("A1:I1")
    ws["A1"] = f"Расписание за семестр ({semester_label})"
    ws["A1"].font = Font(bold=True, size=16)
    ws["A1"].alignment = Alignment(horizontal="center")

    ws.merge_cells("A2:I2")
    ws["A2"] = f"{entity_label}: {entity_name}"
    ws["A2"].font = Font(bold=True, size=13)
    ws["A2"].alignment = Alignment(horizontal="center")

    headers = [
        "Дата",
        "День недели",
        "№ пары",
        "Время",
        "Дисциплина",
        "Преподаватель",
        "Аудитория",
        "Группы / подгруппа",
        "Комментарий",
    ]
    ws.append([])
    ws.append(headers)

    header_row = ws[4]
    header_fill = PatternFill("solid", fgColor="E8F5E9")
    thin_side = Side(style="thin", color="CCCCCC")
    border = Border(left=thin_side, right=thin_side, top=thin_side, bottom=thin_side)
    for cell in header_row:
        cell.font = Font(bold=True)
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = border

    for date_obj, info in data.items():
        weekday = info.get("weekday") or WEEKDAY_NAMES[date_obj.weekday()]
        pairs = info.get("pairs", [])
        if not pairs:
            continue

        pair_counter = 0
        last_time = ""
        for pair in pairs:
            time_slot = pair.get("time", "-")
            if time_slot != last_time:
                pair_counter += 1
                last_time = time_slot

            teacher = pair.get("teacher") or pair.get("fio") or ""
            auditorium = pair.get("auditorium") or pair.get("room") or ""

            groups_data = pair.get("groups") or []
            if isinstance(groups_data, str):
                groups_str = groups_data
            elif isinstance(groups_data, Iterable):
                groups_str = ", ".join(map(str, groups_data))
            else:
                groups_str = ""

            subgroup = pair.get("subgroup")
            if subgroup:
                groups_str = f"{groups_str} ({subgroup})" if groups_str else str(subgroup)

            comment_parts = [
                pair.get("type"),
                pair.get("comment"),
                pair.get("note"),
            ]
            comment = "; ".join(str(part) for part in comment_parts if part)

            row = [
                date_obj.strftime("%d.%m.%Y"),
                weekday,
                pair_counter,
                time_slot,
                pair.get("subject", "-"),
                teacher,
                auditorium,
                groups_str,
                comment,
            ]
            ws.append(row)

    ws.freeze_panes = "A5"
    _auto_fit_columns(ws, max_width=45)
    return wb


def _auto_fit_columns(ws, max_width: int = 40) -> None:
    for column_cells in ws.columns:
        letter = get_column_letter(column_cells[0].column)
        max_length = 0
        for cell in column_cells:
            value = cell.value or ""
            max_length = max(max_length, len(str(value)))
        ws.column_dimensions[letter].width = min(max_width, max_length + 2)


def _sanitize_sheet_name(value: str) -> str:
    invalid = set('[]:*?/\\')
    cleaned = "".join("_" if ch in invalid else ch for ch in value)
    if len(cleaned) > 31:
        cleaned = cleaned[:31]
    return cleaned or "Sheet1"


def save_workbook(wb: Workbook, output_dir: Path, filename: Optional[str]) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    if filename:
        target = output_dir / filename
    else:
        target = output_dir / f"{dt.datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    wb.save(target)
    return target


async def send_via_telegram(token: str, chat_id: str, file_path: Path, caption: str) -> None:
    if Bot is None:
        raise RuntimeError("Модуль python-telegram-bot недоступен. Установите зависимость.")
    bot = Bot(token=token)
    async with bot:
        try:
            with file_path.open("rb") as fh:
                await bot.send_document(chat_id=chat_id, document=fh, filename=file_path.name, caption=caption)
            logger.info("📤 Файл отправлен в Telegram (chat_id=%s)", chat_id)
        except TelegramError as exc:  # pragma: no cover
            logger.error("Не удалось отправить файл: %s", exc)


async def main_async() -> None:
    args = parse_args()
    if args.silent:
        logging.getLogger().setLevel(logging.WARNING)

    start_date, end_date, semester_label = resolve_semester_bounds(args.semester, args.year, args.start, args.end)
    entity_type = API_TYPE_GROUP if args.mode == "student" else API_TYPE_TEACHER

    timetable = await fetch_semester_schedule(args.query, entity_type, start_date, end_date)
    if not timetable:
        logger.warning("⚠️ За указанный период не найдено расписания.")
        return

    workbook = build_excel_workbook(args.query, args.mode, semester_label, timetable)
    output_dir = Path(args.output)
    filename = args.filename or f"{_sanitize_sheet_name(args.query)}_{semester_label.replace(' ', '_')}.xlsx"
    file_path = save_workbook(workbook, output_dir, filename)
    logger.info("💾 Файл сохранён: %s", file_path)

    if args.send:
        token = args.bot_token or CONFIG_BOT_TOKEN
        chat_id = args.chat_id or CONFIG_CHAT_ID
        if not token or not chat_id:
            logger.error("Не удалось отправить файл: не указан бот-токен или chat_id.")
            return
        await send_via_telegram(str(token), str(chat_id), file_path, f"Экспорт расписания: {args.query}")


def main() -> None:
    asyncio.run(main_async())


if __name__ == "__main__":
    main()

