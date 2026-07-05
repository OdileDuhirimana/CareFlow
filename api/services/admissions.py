"""Admission lifecycle business rules: creation, transfer, discharge, update
validation, and the bed-state transitions that accompany each.

Moved out of `api/views.py` — see `api/services/triage.py`'s module
docstring for the shared ARC-01 rationale. `AdmissionViewSet` is now a thin
orchestrator: it parses/validates the request via serializers, delegates
the actual admit/transfer/discharge state-machine rules to this module, and
records the audit trail entry — it no longer owns the business rules
itself.

Why these functions raise `rest_framework.exceptions.ValidationError`
directly instead of a parallel domain-exception hierarchy: this project is
DRF-first end to end (see `api/exceptions.py`), and `ValidationError` is
already the vocabulary the whole call chain (serializers, permissions,
views) uses for "this input/state is invalid, tell the client why".
Introducing a separate exception type that views would then have to catch
and translate back into DRF's `ValidationError` would add a layer of
indirection with no real benefit at this project's size (YAGNI). One
concrete improvement falls out of this for free: the previous view-layer
code returned some of these errors as a raw `Response({'detail': ...})`
that bypassed `careflow_exception_handler` entirely, so those specific
error paths (`transfer`/`discharge`) did not carry the `errors` key the
rest of the API's error envelope guarantees (see README "Error Response
Shape"). Raising `ValidationError` here routes them through the same
exception handler as everything else, closing that inconsistency.
"""
from __future__ import annotations

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from api.models import Admission, Bed, Patient
from api.services.workflow_engine import emit_domain_event


def set_bed_available(bed: Bed | None) -> None:
    if not bed:
        return
    bed.status = Bed.STATUS_AVAILABLE
    bed.current_patient = None
    bed.save(update_fields=['status', 'current_patient', 'updated_at'])


def assign_bed_to_patient(bed: Bed, patient: Patient) -> None:
    bed.status = Bed.STATUS_OCCUPIED
    bed.current_patient = patient
    bed.save(update_fields=['status', 'current_patient', 'updated_at'])


@transaction.atomic
def admit_patient(serializer, admitted_by) -> Admission:
    """Validate business rules and persist a new admission via `serializer`.

    `serializer` must already be schema-valid (`.is_valid()` already
    called by the view/generic create flow) — this only enforces
    cross-field domain rules that a per-field serializer cannot: no
    duplicate active admission per patient, and bed availability.
    """
    patient = serializer.validated_data['patient']
    bed = serializer.validated_data.get('bed')

    has_active_admission = Admission.objects.filter(
        patient=patient,
        status=Admission.STATUS_ADMITTED,
    ).exists()
    if has_active_admission:
        raise ValidationError({'patient': 'Patient already has an active admission.'})

    if bed:
        bed.refresh_from_db()
        if bed.status != Bed.STATUS_AVAILABLE:
            raise ValidationError({'bed': 'Selected bed is not available.'})

    admission = serializer.save(admitted_by=admitted_by)

    if bed:
        assign_bed_to_patient(bed, patient)

    emit_domain_event(
        event_type='admission.created',
        source='admissions.perform_create',
        payload={
            'admission_id': admission.id,
            'patient_id': patient.id,
            'patient_age': patient.age,
            'bed_id': bed.id if bed else None,
            'ward_code': bed.ward.code if bed else '',
            'reason': admission.reason,
            'status': admission.status,
        },
    )
    return admission


def validate_admission_update(instance: Admission, validated_data: dict) -> None:
    """Reject generic PATCH/PUT attempts to change bed or terminal status.

    Bed changes and discharge/transfer must go through the dedicated
    `transfer`/`discharge` actions below, which carry the bed-availability
    and bed-release side effects a bare field update would silently skip.
    """
    next_bed = validated_data.get('bed', instance.bed)
    next_status = validated_data.get('status', instance.status)
    if next_bed != instance.bed:
        raise ValidationError({'bed': 'Use the transfer endpoint to change bed assignments.'})
    if next_status != instance.status and next_status in [Admission.STATUS_DISCHARGED, Admission.STATUS_TRANSFERRED]:
        raise ValidationError({'status': 'Use dedicated admission actions for discharge/transfer.'})


@transaction.atomic
def release_admission_bed_if_active(instance: Admission) -> None:
    """Free the bed if a still-active admission is being deleted directly."""
    if instance.status == Admission.STATUS_ADMITTED and instance.bed_id:
        set_bed_available(instance.bed)


@transaction.atomic
def transfer_admission(admission: Admission, new_bed: Bed, reason: str = '') -> Admission:
    if admission.status != Admission.STATUS_ADMITTED:
        raise ValidationError({'detail': 'Only active admissions can be transferred.'})

    if new_bed.id == admission.bed_id:
        raise ValidationError({'detail': 'Admission is already assigned to this bed.'})

    new_bed.refresh_from_db()
    if new_bed.status != Bed.STATUS_AVAILABLE:
        raise ValidationError({'detail': 'Target bed is not available.'})

    old_bed = admission.bed
    assign_bed_to_patient(new_bed, admission.patient)
    set_bed_available(old_bed)

    admission.bed = new_bed
    if reason:
        suffix = f"\nTransfer note: {reason}"
        admission.discharge_summary = f"{admission.discharge_summary}{suffix}".strip()
    admission.save(update_fields=['bed', 'discharge_summary'])

    emit_domain_event(
        event_type='admission.transferred',
        source='admissions.transfer',
        payload={
            'admission_id': admission.id,
            'patient_id': admission.patient_id,
            'patient_age': admission.patient.age,
            'from_bed_id': old_bed.id if old_bed else None,
            'to_bed_id': new_bed.id,
            'to_ward_code': new_bed.ward.code,
            'reason': reason,
        },
    )
    return admission


@transaction.atomic
def discharge_admission(admission: Admission, discharge_summary: str = '') -> Admission:
    if admission.status != Admission.STATUS_ADMITTED:
        raise ValidationError({'detail': 'Admission is not active.'})

    admission.status = Admission.STATUS_DISCHARGED
    admission.discharge_at = timezone.now()
    if discharge_summary:
        admission.discharge_summary = discharge_summary
    admission.save(update_fields=['status', 'discharge_at', 'discharge_summary'])

    set_bed_available(admission.bed)

    emit_domain_event(
        event_type='admission.discharged',
        source='admissions.discharge',
        payload={
            'admission_id': admission.id,
            'patient_id': admission.patient_id,
            'patient_age': admission.patient.age,
            'bed_id': admission.bed_id,
            'summary': admission.discharge_summary,
            'status': admission.status,
        },
    )
    return admission
