from django.contrib.auth.models import Group, Permission
from django.core.management.base import BaseCommand

from api.roles import ROLE_ADMIN, ROLE_CLINICIAN, ROLE_OUTREACH


class Command(BaseCommand):
    help = 'Create CareFlow role groups and assign model permissions.'

    def handle(self, *args, **options):
        admin_group, _ = Group.objects.get_or_create(name=ROLE_ADMIN)
        clinician_group, _ = Group.objects.get_or_create(name=ROLE_CLINICIAN)
        outreach_group, _ = Group.objects.get_or_create(name=ROLE_OUTREACH)

        api_permissions = Permission.objects.filter(content_type__app_label='api')
        admin_group.permissions.set(api_permissions)

        clinician_codenames = [
            'view_patient', 'add_patient', 'change_patient',
            'view_appointment', 'add_appointment', 'change_appointment',
            'view_hospitalward',
            'view_bed',
            'view_admission', 'add_admission', 'change_admission',
            'view_medicationorder', 'add_medicationorder', 'change_medicationorder',
            'view_laborder', 'add_laborder', 'change_laborder',
            'view_riskassessment', 'add_riskassessment', 'change_riskassessment',
            'view_clinicalalert', 'change_clinicalalert',
            'view_patientcheckin', 'add_patientcheckin',
            'view_communityresource',
            'view_resourcereferral', 'add_resourcereferral', 'change_resourcereferral',
            'view_workflowrule',
            'view_domainevent',
        ]
        clinician_group.permissions.set(Permission.objects.filter(codename__in=clinician_codenames))

        outreach_codenames = [
            'view_patient',
            'view_hospitalward',
            'view_bed',
            'view_admission',
            'view_medicationorder',
            'view_laborder',
            'view_riskassessment',
            'view_clinicalalert',
            'view_patientcheckin', 'add_patientcheckin',
            'view_communityresource',
            'view_resourcereferral', 'add_resourcereferral', 'change_resourcereferral',
            'view_workflowrule',
        ]
        outreach_group.permissions.set(Permission.objects.filter(codename__in=outreach_codenames))

        self.stdout.write(self.style.SUCCESS('CareFlow roles configured: admin, clinician, outreach'))
