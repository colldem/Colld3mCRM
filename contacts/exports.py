"""What a CSV export of records may hold, and what the audit keeps of it.

Every export of contacts or companies goes through here: the contact and
company lists (the selection, or else the filtered list) and the analytics
lists. A user without ``can_export_unlimited`` gets at most
``SystemSettings.export_row_limit`` rows and never the whole base unfiltered.
The audit row says where the export came from, by which filter, which columns
and how many rows — but never a personal code typed into the search.

The file is streamed in chunks, so a few hundred thousand rows do not sit in
memory at once; each chunk reads its child rows (phones, tags …) in one query
per table.
"""
import csv
import re

from django.http import StreamingHttpResponse
from django.utils.translation import gettext as _

from .audit import log as audit_log
from .models import AuditLog, SystemSettings
from .permissions import has_capability
from .sanitizers import csv_safe

CHUNK = 2000
_CODE = re.compile(r"\d{11}")


def in_chunks(queryset, build):
    """Yield the rows `build(records)` makes, reading CHUNK records at a time."""
    chunk = []
    for record in queryset.iterator(chunk_size=CHUNK):
        chunk.append(record)
        if len(chunk) == CHUNK:
            yield from build(chunk)
            chunk = []
    if chunk:
        yield from build(chunk)


def grouped(queryset, key, value):
    """{key: [value, …]} from one query — what prefetch_related would build one queryset per record for."""
    values = {}
    for owner, item in queryset.values_list(key, value):
        values.setdefault(owner, []).append(item)
    return values


def row_limit(user):
    """The most rows `user` may export, or None for no limit."""
    if has_capability(user, "can_export_unlimited"):
        return None
    return SystemSettings.load().export_row_limit


def refusal(user, rows, *, whole_base=False):
    """Why `user` may not export `rows` rows, or None when they may."""
    limit = row_limit(user)
    if limit is None:
        return None
    if whole_base:
        return _("Visą bazę be filtro eksportuoti gali tik turintys teisę „Eksportuoti be eilučių ribos“. "
                 "Pasirinkite filtrą arba pažymėkite eilutes.")
    if rows > limit:
        return _("Rezultate %(rows)s eilučių, jūsų riba — %(limit)s. Susiaurinkite filtrą arba kreipkitės "
                 "į administratorių dėl teisės eksportuoti be ribos.") % {
            "rows": f"{rows:,}".replace(",", " "), "limit": f"{limit:,}".replace(",", " ")}
    return None


def audited_filters(values):
    """The filter as the audit keeps it: set values only, never an 11-digit code."""
    kept = {}
    for key, value in values.items():
        if not value:
            continue
        if isinstance(value, str) and _CODE.search(value):
            continue
        kept[key] = value
    return kept


def stream(request, *, filename, header, rows, total, source, label, filters, selected=False):
    """Audit the export and return it as a streamed UTF-8 CSV.

    `rows` yields the cell values of one record at a time; `total` is the row
    count the limit was checked against.
    """
    audit_log(AuditLog.EXPORT, request=request, target_type="export", target_label=label, new=str(total),
              detail={"source": source, "filters": audited_filters(filters), "columns": list(header),
                      "rows": total, "selected": selected})

    class Echo:
        def write(self, value):
            return value

    def lines():
        writer = csv.writer(Echo())
        yield "﻿" + writer.writerow(header)
        for values in rows:
            yield writer.writerow([csv_safe(value) for value in values])

    response = StreamingHttpResponse(lines(), content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response
