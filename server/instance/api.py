import secrets

from django.http import HttpResponse, HttpResponseNotFound
from drf_spectacular.utils import extend_schema
from rest_framework import permissions
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from .logo import MAX_LOGO_BYTES, LogoError, check_logo
from .models import InstanceSettings
from .serializers import InstanceSerializer, LogoUploadSerializer


class IsSuperuserToWrite(permissions.BasePermission):
    """Anyone may read; only a superuser may write. Anonymous writes get 403 too: session auth sends
    no WWW-Authenticate header, so DRF answers NotAuthenticated with 403."""

    message = "Only a super admin can change instance settings."

    def has_permission(self, request, view):
        if request.method in permissions.SAFE_METHODS:
            return True
        return bool(request.user and request.user.is_authenticated and request.user.is_superuser)


class InstanceView(APIView):
    """GET (public): {"project_name", "theme", "logo_url"}. PATCH (super admins): project_name and/or theme."""

    permission_classes = [IsSuperuserToWrite]
    serializer_class = InstanceSerializer

    def get(self, request):
        return Response(InstanceSerializer(InstanceSettings.load()).data)

    def patch(self, request):
        data = InstanceSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        obj = InstanceSettings.load()
        for field, value in data.validated_data.items():
            setattr(obj, field, value)
        obj.updated_by = request.user
        obj.save(update_fields=[*data.validated_data, "updated_by", "updated_at"])
        return Response(InstanceSerializer(obj).data)


# An SVG opened directly (not through <img>) must not run anything, even if the sanitizer missed something.
_LOGO_CSP = "default-src 'none'; style-src 'unsafe-inline'; img-src data:; sandbox"


class InstanceLogoView(APIView):
    """GET (public): the logo file, 404 if there is none. POST (super admins): multipart `file`, PNG, SVG or JPG,
    square, up to 1 MB; SVGs are sanitized. DELETE (super admins): back to the initials tile."""

    permission_classes = [IsSuperuserToWrite]
    parser_classes = [MultiPartParser, FormParser]

    @extend_schema(responses={(200, "image/*"): bytes, 404: None})
    def get(self, request):
        obj = InstanceSettings.load(with_logo=True)
        if not obj.logo:
            return HttpResponseNotFound()
        res = HttpResponse(bytes(obj.logo), content_type=obj.logo_content_type)
        res["X-Content-Type-Options"] = "nosniff"
        res["Content-Security-Policy"] = _LOGO_CSP
        # The URL carries the version, so a cached copy is never stale for long.
        res["Cache-Control"] = "public, max-age=86400" if request.GET.get("v") == obj.logo_version else "no-cache"
        return res

    @extend_schema(request={"multipart/form-data": LogoUploadSerializer}, responses=InstanceSerializer)
    def post(self, request):
        f = request.FILES.get("file")
        if f is None:
            return Response({"file": ["Attach an image in the 'file' field."]}, status=400)
        if f.size > MAX_LOGO_BYTES:
            return Response({"file": ["The logo is too large; the limit is 1 MB."]}, status=400)
        try:
            data, content_type = check_logo(f.read())
        except LogoError as e:
            return Response({"file": [str(e)]}, status=400)
        obj = InstanceSettings.load()
        obj.logo, obj.logo_content_type, obj.logo_version = data, content_type, secrets.token_hex(6)
        obj.updated_by = request.user
        obj.save(update_fields=["logo", "logo_content_type", "logo_version", "updated_by", "updated_at"])
        return Response(InstanceSerializer(obj).data)

    @extend_schema(request=None, responses=InstanceSerializer)
    def delete(self, request):
        obj = InstanceSettings.load()
        obj.logo, obj.logo_content_type, obj.logo_version = None, "", ""
        obj.updated_by = request.user
        obj.save(update_fields=["logo", "logo_content_type", "logo_version", "updated_by", "updated_at"])
        return Response(InstanceSerializer(obj).data)
