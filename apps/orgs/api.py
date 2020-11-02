# -*- coding: utf-8 -*-
#

from django.utils.translation import ugettext as _
from django.db.models import Q
from rest_framework import status
from rest_framework.views import Response
from rest_framework_bulk import BulkModelViewSet

from common.permissions import IsSuperUserOrAppUser
from common.drf.api import JMSBulkRelationModelViewSet, JMSModelViewSet
from .models import Organization, ROLE
from .serializers import (
    OrgSerializer, OrgReadSerializer,
    OrgRetrieveSerializer, OrgMemberSerializer
)
from users.models import User, UserGroup
from assets.models import Asset, Domain, AdminUser, SystemUser, Label
from perms.models import AssetPermission
from orgs.utils import current_org
from common.utils import get_logger
from .filters import OrgMemberRelationFilterSet
from .models import OrganizationMember


logger = get_logger(__file__)


class OrgViewSet(BulkModelViewSet):
    filter_fields = ('name',)
    search_fields = ('name', 'comment')
    queryset = Organization.objects.all()
    serializer_class = OrgSerializer
    permission_classes = (IsSuperUserOrAppUser,)
    org = None

    def get_serializer_class(self):
        mapper = {
            'list': OrgReadSerializer,
            'retrieve': OrgRetrieveSerializer
        }
        return mapper.get(self.action, super().get_serializer_class())

    def get_data_from_model(self, model):
        if model == User:
            data = model.objects.filter(orgs__id=self.org.id, m2m_org_members__role=ROLE.USER)
        else:
            data = model.objects.filter(org_id=self.org.id)
        return data

    def destroy(self, request, *args, **kwargs):
        self.org = self.get_object()
        models = [
            User, UserGroup,
            Asset, Domain, AdminUser, SystemUser, Label,
            AssetPermission,
        ]
        for model in models:
            data = self.get_data_from_model(model)
            if data:
                msg = _('Organization contains undeleted resources')
                return Response(data={'error': msg}, status=status.HTTP_403_FORBIDDEN)
        else:
            if str(current_org) == str(self.org):
                msg = _('The current organization cannot be deleted')
                return Response(data={'error': msg}, status=status.HTTP_403_FORBIDDEN)
            self.org.delete()
            return Response({'msg': True}, status=status.HTTP_200_OK)


class OrgMemberRelationBulkViewSet(JMSBulkRelationModelViewSet):
    permission_classes = (IsSuperUserOrAppUser,)
    m2m_field = Organization.members.field
    serializer_class = OrgMemberSerializer
    filterset_class = OrgMemberRelationFilterSet

    def get_queryset(self):
        queryset = super().get_queryset()
        search = self.request.query_params.get('search')
        if search:
            users_id = User.objects.filter(
                Q(name__icontains=search) |
                Q(username__icontains=search) |
                Q(id__icontains=search)
            ).values_list('id', flat=True)

            orgs_id = Organization.objects.filter(
                Q(name__icontains=search) |
                Q(id__icontains=search)
            ).values_list('id', flat=True)

            queryset = queryset.filter(
                Q(user_id__in=users_id) |
                Q(org_id__in=orgs_id)
            )
        return queryset

    def perform_bulk_create(self, serializer):
        data = serializer.validated_data
        relations = [OrganizationMember(**i) for i in data]
        OrganizationMember.objects.bulk_create(relations, ignore_conflicts=True)

    def perform_bulk_destroy(self, queryset):
        objs = list(queryset.all().prefetch_related('user', 'org'))
        queryset.delete()
        self.send_m2m_changed_signal(objs, action='post_remove')
