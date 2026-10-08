"""Background job scanning payments by created_at."""

REPORT_SQL = """
SELECT id, amount, created_at
FROM payments
WHERE created_at >= NOW() - INTERVAL '7 days'
ORDER BY created_at DESC
"""


def run():
    return REPORT_SQL
