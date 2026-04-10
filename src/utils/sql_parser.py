import re

_JOIN_PATTERN = re.compile(
    r'\b(INNER\s+JOIN|LEFT\s+(?:OUTER\s+)?JOIN|RIGHT\s+(?:OUTER\s+)?JOIN|'
    r'FULL\s+(?:OUTER\s+)?JOIN|CROSS\s+JOIN|JOIN)\b',
    re.IGNORECASE,
)
_FROM_TABLE_PATTERN = re.compile(r'\bFROM\s+`?([a-zA-Z_][a-zA-Z0-9_]*)`?', re.IGNORECASE)
_JOIN_TABLE_PATTERN = re.compile(r'\bJOIN\s+`?([a-zA-Z_][a-zA-Z0-9_]*)`?', re.IGNORECASE)


def count_joins(sql: str) -> int:
    if not sql:
        return 0
    cleaned = re.sub(r'--[^\n]*', '', sql)
    return len(_JOIN_PATTERN.findall(cleaned))


def extract_table_names(sql: str) -> list[str]:
    if not sql:
        return []
    cleaned = re.sub(r'--[^\n]*', '', sql)
    tables = set()
    for m in _FROM_TABLE_PATTERN.finditer(cleaned):
        tables.add(m.group(1).lower())
    for m in _JOIN_TABLE_PATTERN.finditer(cleaned):
        tables.add(m.group(1).lower())
    return sorted(tables)
