# apps/fbr/invoice_numbers.py
import re


def get_fbr_category(product_name):
    """Map products to the categories shown on FBR invoices."""
    product_upper = product_name.upper() if product_name else ''

    if 'CO2' in product_upper or 'CARBON DIOXIDE' in product_upper:
        return 'CO2'
    if 'LPG' in product_upper:
        return 'LPG'
    if any(term in product_upper for term in (
        'OXYGEN', 'NITROGEN', 'N2', 'DA', 'SPECIAL ARGON', 'ARGON', 'O2',
    )):
        return 'OXYGEN LIQUID'
    if any(term in product_upper for term in (
        'VACUUM', 'PUMP', 'SERVICE', 'RENTAL', 'REPAIR', 'EQUIPMENT', 'FITTING',
    )):
        return None
    return 'OXYGEN LIQUID'


def parse_invoice_number(value):
    """Parse an invoice number into prefix, number, suffix, and width."""
    trimmed = (value or '').strip()
    match = re.match(r'^(.*?)(\d+)([^\d]*)$', trimmed)
    if not match:
        return {'prefix': '', 'number': None, 'suffix': trimmed, 'width': 0, 'original': trimmed}
    return {
        'prefix': match.group(1),
        'number': int(match.group(2)),
        'suffix': match.group(3),
        'width': len(match.group(2)),
        'original': trimmed,
    }


def format_invoice_number(parsed, number):
    """Format a number using the parsed invoice number pattern."""
    if not parsed or parsed['number'] is None:
        return str(number)
    num_str = str(number)
    if parsed['width'] > 0:
        num_str = num_str.zfill(parsed['width'])
    return parsed['prefix'] + num_str + parsed['suffix']


def apply_invoice_numbers_to_rows(rows, start_invoice_number=None, row_overrides=None):
    """
    Apply invoice numbers to a list of rows.
    
    Args:
        rows: List of dictionaries with 'row_key' and 'invoice_no' keys.
        start_invoice_number: Optional starting invoice number.
        row_overrides: Dictionary of row_key -> invoice_no overrides.
    """
    if not rows:
        return
    
    row_overrides = row_overrides or {}
    
    # First, apply any row overrides
    for row in rows:
        row_key = row.get('row_key')
        if row_key and row_key in row_overrides:
            row['invoice_no'] = row_overrides[row_key]
    
    # If a start_invoice_number is provided, apply it to the first row
    if start_invoice_number:
        first_row = rows[0]
        first_row['invoice_no'] = start_invoice_number
        parsed = parse_invoice_number(start_invoice_number)
        if parsed['number'] is not None:
            # Cascade to subsequent rows
            for index, row in enumerate(rows):
                if index > 0:
                    row['invoice_no'] = format_invoice_number(parsed, parsed['number'] + index)