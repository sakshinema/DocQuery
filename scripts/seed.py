from __future__ import annotations

from hashlib import sha256
from pathlib import Path

from lib.db import create_document, init_db, insert_chunks, mark_document_ready
from lib.extract import heuristic_extract


SEED_DOCS = [
    (
        "northstar_invoice.txt",
        "Acme Northstar Invoice\nInvoice number: INV-1048\nCustomer: Northstar Retail\nTotal: INR 125,000\nDue date: 30/09/2026\nfinance@northstar.example",
    ),
    (
        "partner_agreement.txt",
        "Partner Agreement\nCompany: Northstar Retail\nEffective date: 01/08/2026\nExpiry date: 31/07/2027\nTermination requires 30 days notice.\nLegal contact: legal@northstar.example",
    ),
    (
        "quarterly_report.txt",
        "Q3 Operations Report\nRevenue increased 14% quarter over quarter.\nNorthstar Retail represented INR 125,000 of billed activity in the period.\nThe largest open risk is contract renewal timing.",
    ),
]


def main() -> None:
    init_db()
    for filename, content in SEED_DOCS:
        digest = sha256(content.encode()).hexdigest()
        doc_id, created = create_document(filename, "text/plain", len(content.encode()), digest)
        if not created:
            continue
        insert_chunks(doc_id, [{"page": 1, "section": None, "content": content}])
        mark_document_ready(doc_id, heuristic_extract(filename, content), {})
    print("Demo data seeded.")


if __name__ == "__main__":
    main()
