import io
import pandas as pd
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter


def parse_contacts_excel(file_stream):
    """
    Parse an Excel file and return (headers, rows).
    headers: list of str
    rows: list of dict {header: value}
    """
    df = pd.read_excel(file_stream, dtype=str)
    df = df.where(pd.notna(df), None)
    headers = list(df.columns)
    rows = df.to_dict(orient='records')
    return headers, rows


def export_contacts_to_excel(contacts, fields):
    """
    Build an Excel workbook from contacts and field definitions.
    Returns a BytesIO buffer ready to send as file download.
    """
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = 'Contactos'

    header_font = Font(bold=True, color='FFFFFF', size=11)
    header_fill = PatternFill(start_color='4361EE', end_color='4361EE', fill_type='solid')
    header_align = Alignment(horizontal='center', vertical='center', wrap_text=True)
    cell_align = Alignment(vertical='center', wrap_text=True)

    thin = Side(style='thin', color='DEE2E6')
    border = Border(left=thin, right=thin, top=thin, bottom=thin)

    for col_idx, field in enumerate(fields, start=1):
        cell = ws.cell(row=1, column=col_idx, value=field.display_name)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = header_align
        cell.border = border
        ws.column_dimensions[get_column_letter(col_idx)].width = 22

    ws.row_dimensions[1].height = 30

    for row_idx, contact in enumerate(contacts, start=2):
        for col_idx, field in enumerate(fields, start=1):
            value = contact.get_value(field.id)
            cell = ws.cell(row=row_idx, column=col_idx, value=value)
            cell.alignment = cell_align
            cell.border = border
            if row_idx % 2 == 0:
                cell.fill = PatternFill(start_color='F8F9FA', end_color='F8F9FA', fill_type='solid')

    ws.freeze_panes = 'A2'

    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    return buffer
