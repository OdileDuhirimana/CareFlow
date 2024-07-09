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


class CommunityWorkflowPermission(BasePermission):
    """Community workflows writable by admin/clinician/outreach."""

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
