"""Prompt + taxonomy for complaint-reason labelling (kept separate so tests can import it)."""

LABELS = {
    "late_delivery": "arrived, but later than promised / took too long (atraso, demorou)",
    "not_received": "customer says the product has NOT arrived / never received (nao recebi, nao chegou)",
    "incomplete_order": "only part of the order arrived / missing units or items (veio so 1, faltou)",
    "wrong_item": "received a different product, model, colour or size than ordered",
    "damaged_defective": "arrived broken, damaged, defective or not working",
    "poor_quality": "arrived and works but quality is poor / not as described / fake",
    "seller_communication": "seller or support did not answer, bad service, no information",
    "refund_cancellation": "problem with cancellation, refund (estorno), charge or invoice",
    "positive": "praise or satisfied; no complaint",
    "other": "anything else, or too vague to tell",
}

SYSTEM = (
    "You classify Brazilian Portuguese e-commerce reviews into ONE primary complaint reason. "
    'Answer with JSON only: {"label": <one of the allowed labels>}. Allowed labels:\n'
    + "\n".join(f"- {k}: {v}" for k, v in LABELS.items())
    + "\nRules: if the product never arrived use not_received (not late_delivery). If it "
    "arrived late AND broken, pick the one the customer complains about most. A review that "
    "is only positive is positive."
)


def user_prompt(title: str | None, message: str) -> str:
    t = f"Title: {title}\n" if title else ""
    return f"{t}Review: {message}"
