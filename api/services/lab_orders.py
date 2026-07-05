"""Lab-order lifecycle business rules.

Moved out of `api/views.py` (previously inline in
`LabOrderViewSet.start`/`.complete`) — see `api/services/triage.py`'s
module docstring for the shared ARC-01 rationale, including why these
raise `rest_framework.exceptions.ValidationError` rather than returning a
raw `Response` (the previous view code bypassed the normalized error
envelope for these two error paths; raising here fixes that).
"""
from __future__ import annotations

from django.utils import timezone
from rest_framework.exceptions import ValidationError

from api.models import LabOrder
from api.services.workflow_engine import emit_domain_event


def start_lab_order(order: LabOrder) -> LabOrder:
    if order.status not in [LabOrder.STATUS_ORDERED, LabOrder.STATUS_IN_PROGRESS]:
        raise ValidationError({'detail': 'Only ordered lab requests can be started.'})

    if not order.sample_collected_at:
        order.sample_collected_at = timezone.now()
    order.status = LabOrder.STATUS_IN_PROGRESS
    order.save(update_fields=['status', 'sample_collected_at'])
    return order


def complete_lab_order(order: LabOrder, result_value: str = '', result_summary: str = '') -> LabOrder:
    if order.status == LabOrder.STATUS_CANCELLED:
        raise ValidationError({'detail': 'Cancelled lab requests cannot be completed.'})

    order.status = LabOrder.STATUS_COMPLETED
    order.completed_at = timezone.now()
    order.result_value = result_value or order.result_value
    order.result_summary = result_summary or order.result_summary
    if not order.sample_collected_at:
        order.sample_collected_at = timezone.now()
    order.save(
        update_fields=[
            'status',
            'completed_at',
            'result_value',
            'result_summary',
            'sample_collected_at',
        ]
    )

    emit_domain_event(
        event_type='lab_order.completed',
        source='lab_orders.complete',
        payload={
            'lab_order_id': order.id,
            'patient_id': order.patient_id,
            'patient_age': order.patient.age,
            'priority': order.priority,
            'result_value': order.result_value,
            'result_summary': order.result_summary,
            'status': order.status,
        },
    )
    return order
