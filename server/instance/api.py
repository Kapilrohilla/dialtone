from rest_framework import permissions
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import InstanceSettings
from .serializers import InstanceSerializer


class IsSuperuserToWrite(permissions.BasePermission):
    """Anyone may read; only a superuser may write. Anonymous writes get 403 too: session auth sends
    no WWW-Authenticate header, so DRF answers NotAuthenticated with 403."""

    message = "Only a super admin can change instance settings."

    def has_permission(self, request, view):
        if request.method in permissions.SAFE_METHODS:
            return True
        return bool(request.user and request.user.is_authenticated and request.user.is_superuser)


class InstanceView(APIView):
    """GET (public): {"project_name": "..."}. PATCH (super admins): {"project_name": "..."}."""

    permission_classes = [IsSuperuserToWrite]
    serializer_class = InstanceSerializer

    def get(self, request):
        return Response(InstanceSerializer(InstanceSettings.load()).data)

    def patch(self, request):
        data = InstanceSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        obj = InstanceSettings.load()
        obj.project_name = data.validated_data["project_name"]
        obj.updated_by = request.user
        obj.save()
        return Response(InstanceSerializer(obj).data)
