"""Medication-order lifecycle business rules.

Moved out of `api/views.py` (previously inline in
`MedicationOrderViewSet.mark_status`) — see `api/services/triage.py`'s
module docstring for the shared ARC-01 rationale.
"""
from __future__ import annotations

from django.utils import timezone

from api.models import MedicationOrder


def mark_medication_order_status(order: MedicationOrder, new_status: str, notes: str = '') -> MedicationOrder:
    """Apply a status transition to a medication order.

    Deliberately has no ownership/role check of its own — that is the
    concern of `MedicationOrderPermission` (`api/permissions.py`), which
    intentionally exempts this action from its prescriber-ownership
    restriction so any admin/clinician can update order status (see that
    permission class's docstring for the full rationale).
    """
    order.status = new_status
    if new_status in [MedicationOrder.STATUS_COMPLETED, MedicationOrder.STATUS_STOPPED] and not order.end_at:
        order.end_at = timezone.now()
    if notes:
        order.instructions = f"{order.instructions}\nStatus note: {notes}".strip()
    order.save(update_fields=['status', 'end_at', 'instructions'])
    return order
