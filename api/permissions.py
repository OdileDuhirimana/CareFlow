from rest_framework.permissions import BasePermission, SAFE_METHODS

from .roles import CAREFLOW_ROLES, ROLE_ADMIN, ROLE_CLINICIAN, ROLE_OUTREACH


def has_any_role(user, allowed_roles):
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    return user.groups.filter(name__in=allowed_roles).exists()


class HasCareflowRole(BasePermission):
    def has_permission(self, request, view):
        return has_any_role(request.user, CAREFLOW_ROLES)


class ClinicalWritePermission(BasePermission):
    """Read allowed to all care roles, write restricted to admin/clinician."""

    def has_permission(self, request, view):
        if not has_any_role(request.user, CAREFLOW_ROLES):
            return False
        if request.method in SAFE_METHODS:
            return True
        return has_any_role(request.user, [ROLE_ADMIN, ROLE_CLINICIAN])


class MedicationOrderPermission(BasePermission):
    """Medication orders: read for care roles, write for admin/clinician,
    object-level edit/delete restricted to the prescribing clinician (or admin)
    — but *only* for the prescription-editing endpoints (standard update/
    partial_update/destroy). Non-prescription-editing actions, most
    importantly `mark-status`, are intentionally exempt from the ownership
    check below.

    Why a dedicated class instead of reusing `ClinicalWritePermission`:
    medication orders are the highest-risk resource in the schema to allow
    blanket cross-clinician editing on — a clinician should not be able to
    silently alter another clinician's prescription (dosage, route,
    frequency) without at least an ownership signal. Admins retain full
    override access for legitimate corrections/audits. This mirrors the
    same admin-override pattern used by `CommunityWorkflowPermission` for
    `ResourceReferral`.

    Why `mark-status` is excluded from the ownership check: marking an order
    active/completed/stopped is an operational status update any admin or
    clinician on the care team needs to be able to perform (e.g. a covering
    clinician completing a course started by someone else on a prior shift)
    — it does not change dosage, route, or frequency. Scoping the check to
    `OWNERSHIP_SCOPED_ACTIONS` (rather than to `request.method`) is what
    fixed a real regression: a blanket method-based check on PATCH/PUT/DELETE
    would also 403 `mark-status`, since that action is a `POST` but DRF still
    routes it through `get_object()` -> `check_object_permissions()` just
    like a normal detail action.
    """

    # Only these standard ModelViewSet actions actually change prescription
    # fields (dosage/route/frequency/etc.) via the generic update mechanism.
    # `mark_status` is a distinct custom action and must not inherit this
    # restriction — see class docstring.
    OWNERSHIP_SCOPED_ACTIONS = frozenset({'update', 'partial_update', 'destroy'})

    def has_permission(self, request, view):
        if not has_any_role(request.user, CAREFLOW_ROLES):
            return False
        if request.method in SAFE_METHODS:
            return True
        return has_any_role(request.user, [ROLE_ADMIN, ROLE_CLINICIAN])

    def has_object_permission(self, request, view, obj):
        if request.method in SAFE_METHODS:
            return True
        if getattr(view, 'action', None) not in self.OWNERSHIP_SCOPED_ACTIONS:
            # Non-scoped actions (e.g. `mark_status`) were already gated by
            # `has_permission` above (admin/clinician only); no further
            # per-record ownership restriction applies to them.
            return True
        if has_any_role(request.user, [ROLE_ADMIN]):
            return True
        return getattr(obj, 'prescribed_by_id', None) == request.user.id


class AlertPermission(BasePermission):
    """Read for all roles, update for admin/clinician only."""

    def has_permission(self, request, view):
        if not has_any_role(request.user, CAREFLOW_ROLES):
            return False
        if request.method in SAFE_METHODS:
            return True
        return has_any_role(request.user, [ROLE_ADMIN, ROLE_CLINICIAN])


class ClinicianAdminOnly(BasePermission):
    def has_permission(self, request, view):
        return has_any_role(request.user, [ROLE_ADMIN, ROLE_CLINICIAN])


class CommunityCatalogPermission(BasePermission):
    """Resource catalog editable by admins, readable by all roles."""

    def has_permission(self, request, view):
        if not has_any_role(request.user, CAREFLOW_ROLES):
            return False
        if request.method in SAFE_METHODS:
            return True
        return has_any_role(request.user, [ROLE_ADMIN])


class _OwnedByFieldPermission(BasePermission):
    """Shared object-ownership check for resources that record who created
    them via a single FK field (e.g. `referred_by`, `submitted_by`).

    Why a mixin instead of one permission class shared across models: a
    prior remediation pass hardcoded `referred_by_id` inside a single
    `CommunityWorkflowPermission` class and then reused that same class for
    `PatientCheckInViewSet`, whose ownership field is actually
    `submitted_by`, not `referred_by`. Because `getattr(obj, 'referred_by_id',
    None)` silently returns `None` for a `PatientCheckIn` (it has no such
    field) and `None` never equals `request.user.id`, every outreach worker
    was incorrectly denied edit access to their *own* check-ins. Declaring
    `ownership_field` per subclass makes the correct field explicit and
    prevents that class of bug from recurring when a third resource needs
    the same pattern.
    """

    #: Subclasses must set this to the `<fk_field>_id` attribute name that
    #: identifies the creating user on the model this permission guards.
    ownership_field: str = ''

    def has_object_permission(self, request, view, obj):
        if request.method in SAFE_METHODS:
            return True
        if has_any_role(request.user, [ROLE_ADMIN, ROLE_CLINICIAN]):
            return True
        assert self.ownership_field, f'{type(self).__name__} must define ownership_field'
        return getattr(obj, self.ownership_field, None) == request.user.id


class CommunityWorkflowPermission(_OwnedByFieldPermission):
    """Community workflows (resource referrals) writable by
    admin/clinician/outreach.

    Object-level check: outreach workers may only modify/delete referrals
    they personally created (`referral.referred_by == request.user`).
    Without this, any outreach-role user could edit or cancel a referral
    created by a completely different outreach worker for a patient they
    have no assigned relationship with — a real ownership gap the code
    review flagged (`api/permissions.py` previously had zero
    `has_object_permission` overrides anywhere).

    Admins and clinicians are exempt from the ownership restriction: they
    are the supervising care team and are expected to be able to correct or
    reassign any referral, matching how `has_permission` already treats
    them as elevated roles relative to outreach.
    """

    ownership_field = 'referred_by_id'

    def has_permission(self, request, view):
        return has_any_role(request.user, [ROLE_ADMIN, ROLE_CLINICIAN, ROLE_OUTREACH])


class PatientCheckInPermission(_OwnedByFieldPermission):
    """Remote-monitoring check-ins writable by admin/clinician/outreach.

    Object-level check: outreach workers may only modify/delete check-ins
    they personally submitted (`checkin.submitted_by == request.user`) —
    the check-in equivalent of `CommunityWorkflowPermission`'s referral
    ownership rule. This is a *separate* class from
    `CommunityWorkflowPermission` (rather than reusing it) specifically
    because the two models track ownership through different FK fields
    (`submitted_by` vs `referred_by`); see `_OwnedByFieldPermission` for why
    that distinction matters.
    """

    ownership_field = 'submitted_by_id'

    def has_permission(self, request, view):
        return has_any_role(request.user, [ROLE_ADMIN, ROLE_CLINICIAN, ROLE_OUTREACH])


class InfrastructureCatalogPermission(BasePermission):
    """Wards/beds readable by care roles, writable by admins."""

    def has_permission(self, request, view):
        if not has_any_role(request.user, CAREFLOW_ROLES):
            return False
        if request.method in SAFE_METHODS:
            return True
        return has_any_role(request.user, [ROLE_ADMIN])


class WorkflowRulePermission(BasePermission):
    """Workflow rules readable by care roles, writable by admins."""

    def has_permission(self, request, view):
        if not has_any_role(request.user, CAREFLOW_ROLES):
            return False
        if request.method in SAFE_METHODS:
            return True
        return has_any_role(request.user, [ROLE_ADMIN])


class WorkflowEventPermission(BasePermission):
    """Domain events visible and processable by admin/clinician roles."""

    def has_permission(self, request, view):
        return has_any_role(request.user, [ROLE_ADMIN, ROLE_CLINICIAN])
