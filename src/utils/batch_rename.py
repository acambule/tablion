from __future__ import annotations

import re
from pathlib import Path

from localization import app_tr

_PADDED_NUMBER_PATTERN = re.compile(r"\{(0*)n\}")
_MONTH_NAME_DE_PATTERN = re.compile(r"\{month_name_de:g(\d+)\}")

_MONTH_NAMES_DE = {
    "1": "Januar",
    "01": "Januar",
    "2": "Februar",
    "02": "Februar",
    "3": "Maerz",
    "03": "Maerz",
    "4": "April",
    "04": "April",
    "5": "Mai",
    "05": "Mai",
    "6": "Juni",
    "06": "Juni",
    "7": "Juli",
    "07": "Juli",
    "8": "August",
    "08": "August",
    "9": "September",
    "09": "September",
    "10": "Oktober",
    "11": "November",
    "12": "Dezember",
}


def batch_rename_help_text() -> str:
    return app_tr(
        "BatchRenameDialog",
        """
<div style="padding:4px;">
  <div style="font-weight:600; margin-bottom:6px;">Normaler Modus</div>
  <table cellspacing="0" cellpadding="0" style="margin-bottom:8px;">
    <tr><td style="padding-right:12px;"><code>{stem}</code></td><td>Dateiname ohne Endung</td></tr>
    <tr><td style="padding-right:12px;"><code>{name}</code></td><td>Voller Dateiname</td></tr>
    <tr><td style="padding-right:12px;"><code>{ext}</code></td><td>Endung inklusive Punkt</td></tr>
    <tr><td style="padding-right:12px;"><code>{n}</code></td><td>Laufende Nummer: 1, 2, 3</td></tr>
    <tr><td style="padding-right:12px;"><code>{0n}</code></td><td>Mit führender Null: 01, 02, 03</td></tr>
    <tr><td style="padding-right:12px;"><code>{00n}</code></td><td>Mit zwei führenden Nullen: 001, 002, 003</td></tr>
  </table>
  <div style="margin-bottom:10px;">Ohne Platzhalter wird der Text als gemeinsamer Basisname verwendet.</div>

  <div style="font-weight:600; margin-bottom:6px;">Regex-Modus</div>
  <table cellspacing="0" cellpadding="0" style="margin-bottom:8px;">
    <tr><td style="padding-right:12px;"><code>{g1}</code></td><td>Erste Regex-Gruppe</td></tr>
    <tr><td style="padding-right:12px;"><code>{g2}</code></td><td>Zweite Regex-Gruppe</td></tr>
    <tr><td style="padding-right:12px;"><code>{month_name_de:g2}</code></td><td>Wandelt z. B. 07 in Juli um</td></tr>
  </table>

  <div style="margin-bottom:4px;"><code>links =&gt; rechts</code></div>
  <div style="margin-bottom:4px;">Links steht das Suchmuster, rechts der neue Name.</div>
  <div style="background-color:#111111; color:#f5f5f5; padding:4px; border-radius:3px;">
    <code>(.*) (\\d{2}) (\\d{4}) =&gt; {g1} {g3} {g2} {month_name_de:g2}{ext}</code>
  </div>
</div>
""",
    )


def render_batch_rename_name(source_path: str, rule_text: str, number: int, regex_mode: bool = False) -> str:
    source = Path(source_path)
    file_name = source.name
    stem = source.stem
    ext = source.suffix
    text = str(rule_text or "").strip()

    if not text:
        return file_name

    if regex_mode:
        return _render_regex_rule(file_name, stem, ext, text, number)

    if "{" not in text:
        return f"{text} {number}{ext}" if number > 1 else f"{text}{ext}"

    prepared = _apply_number_tokens(text, number)
    try:
        rendered = prepared.format(name=file_name, stem=stem, ext=ext, n=number)
    except (IndexError, KeyError, ValueError) as error:
        raise ValueError(app_tr("PaneController", "Ungueltige Umbenennungsregel")) from error

    rendered = str(rendered).strip()
    if not rendered:
        raise ValueError(app_tr("PaneController", "Der neue Name darf nicht leer sein"))
    return rendered


def _render_regex_rule(file_name: str, stem: str, ext: str, regex_rule: str, number: int) -> str:
    pattern_text, separator, replacement = regex_rule.partition("=>")
    pattern_text = pattern_text.strip()
    replacement = replacement.strip()
    if not separator or not pattern_text or not replacement:
        raise ValueError(app_tr("PaneController", "Ungueltige Regex-Regel"))

    try:
        pattern = re.compile(pattern_text)
    except re.error as error:
        raise ValueError(app_tr("PaneController", "Ungueltige Regex-Regel")) from error

    match = pattern.fullmatch(stem)
    if match is None:
        raise ValueError(app_tr("PaneController", "Dateiname passt nicht zur Regex-Regel"))

    prepared = _apply_number_tokens(replacement, number)
    prepared = _apply_month_tokens(prepared, match)

    values = {
        "name": file_name,
        "stem": stem,
        "ext": ext,
        "n": number,
    }
    for group_index, group_value in enumerate(match.groups(), start=1):
        values[f"g{group_index}"] = group_value or ""

    try:
        rendered = prepared.format(**values)
    except (IndexError, KeyError, ValueError) as error:
        raise ValueError(app_tr("PaneController", "Ungueltige Regex-Regel")) from error

    rendered = str(rendered).strip()
    if not rendered:
        raise ValueError(app_tr("PaneController", "Der neue Name darf nicht leer sein"))
    return rendered


def _apply_number_tokens(text: str, number: int) -> str:
    def replace(match: re.Match[str]) -> str:
        zero_prefix = match.group(1)
        if not zero_prefix:
            return str(number)
        width = len(zero_prefix) + 1
        return str(number).zfill(width)

    return _PADDED_NUMBER_PATTERN.sub(replace, text)


def _apply_month_tokens(text: str, match: re.Match[str]) -> str:
    def replace(token_match: re.Match[str]) -> str:
        group_index = int(token_match.group(1))
        try:
            group_value = match.group(group_index)
        except IndexError as error:
            raise ValueError(app_tr("PaneController", "Ungueltige Regex-Regel")) from error
        if group_value is None:
            raise ValueError(app_tr("PaneController", "Ungueltige Regex-Regel"))
        month_name = _MONTH_NAMES_DE.get(str(group_value).strip())
        if month_name is None:
            raise ValueError(app_tr("PaneController", "Monat konnte nicht erkannt werden"))
        return month_name

    return _MONTH_NAME_DE_PATTERN.sub(replace, text)
