from django.contrib.auth import authenticate, get_user_model, login, logout, update_session_auth_hash
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.tokens import default_token_generator
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.middleware.csrf import get_token
from django.utils.decorators import method_decorator
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode
from django.views.decorators.csrf import ensure_csrf_cookie
from rest_framework import permissions, serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from . import serializers as s
from .models import Membership, UserPreference
from .permissions import CanManageTeam, IsMember, _membership, workspace_for

User = get_user_model()
OPEN = [permissions.AllowAny]


class CsrfView(APIView):
    permission_classes = OPEN

    @method_decorator(ensure_csrf_cookie)
    def get(self, request):
        get_token(request)
        return Response(status=status.HTTP_204_NO_CONTENT)


class LoginView(APIView):
    permission_classes = OPEN

    def post(self, request):
        data = s.LoginSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        email = data.validated_data["email"].strip()
        candidate = User.objects.filter(email__iexact=email).first()
        user = None
        if candidate is not None:
            user = authenticate(request, username=candidate.get_username(), password=data.validated_data["password"])
        membership = Membership.objects.select_related("workspace").filter(user=user).first() if user else None
        if user is None or membership is None:
            return Response({"detail": "Wrong email or password."}, status=status.HTTP_400_BAD_REQUEST)
        login(request, user)
        return Response(s.me_payload(user, membership))


class LogoutView(APIView):
    permission_classes = OPEN

    def post(self, request):
        logout(request)
        return Response(status=status.HTTP_204_NO_CONTENT)


class SetPasswordView(APIView):
    """Consumes the one-time link from an invite: uid + token + new password."""

    permission_classes = OPEN
    authentication_classes: list = []

    def post(self, request):
        data = s.SetPasswordSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        invalid = Response({"detail": "This link is invalid or has expired."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            user = User.objects.get(pk=force_str(urlsafe_base64_decode(data.validated_data["uid"])))
        except (User.DoesNotExist, ValueError, TypeError, OverflowError, UnicodeDecodeError):
            return invalid
        if not default_token_generator.check_token(user, data.validated_data["token"]):
            return invalid
        try:
            validate_password(data.validated_data["new_password"], user)
        except DjangoValidationError as exc:
            return Response({"new_password": list(exc.messages)}, status=status.HTTP_400_BAD_REQUEST)
        user.set_password(data.validated_data["new_password"])
        user.save(update_fields=["password"])
        return Response(status=status.HTTP_204_NO_CONTENT)


class MeView(APIView):
    def get(self, request):
        return Response(s.me_payload(request.user, _membership(request)))

    def patch(self, request):
        data = s.MeUpdateSerializer(data=request.data, partial=True)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        user = request.user
        pref, _ = UserPreference.objects.get_or_create(user=user)
        with transaction.atomic():
            if "name" in v:
                user.first_name, user.last_name = v["name"], ""
                user.save(update_fields=["first_name", "last_name"])
            if "phone" in v:
                pref.phone = v["phone"]
            for key, value in v.get("preferences", {}).items():
                setattr(pref, key, value)
            pref.save()
        return Response(s.me_payload(user, _membership(request)))


class MePasswordView(APIView):
    def post(self, request):
        data = s.PasswordChangeSerializer(data=request.data, context={"user": request.user})
        data.is_valid(raise_exception=True)
        request.user.set_password(data.validated_data["new_password"])
        request.user.save(update_fields=["password"])
        update_session_auth_hash(request, request.user)
        return Response(status=status.HTTP_204_NO_CONTENT)


def _set_password_url(user):
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    return f"/set-password/{uid}/{default_token_generator.make_token(user)}"


class TeamView(APIView):
    def get_permissions(self):
        return [IsMember(), CanManageTeam()] if self.request.method == "POST" else [IsMember()]

    def get(self, request):
        qs = Membership.objects.filter(workspace=workspace_for(request)).select_related("user").order_by("user__id")
        return Response(s.TeamMemberSerializer(qs, many=True).data)

    def post(self, request):
        data = s.InviteSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        with transaction.atomic():
            user = User(username=v["email"], email=v["email"], first_name=v["name"])
            user.set_unusable_password()
            user.save()
            Membership.objects.create(user=user, workspace=workspace_for(request), role=v["role"])
            UserPreference.objects.get_or_create(user=user)
        return Response({"set_password_url": _set_password_url(user)}, status=status.HTTP_201_CREATED)


class TeamMemberView(APIView):
    permission_classes = [IsMember, CanManageTeam]

    def patch(self, request, pk):
        ws = workspace_for(request)
        try:
            membership = Membership.objects.select_related("user").get(workspace=ws, user_id=pk)
        except Membership.DoesNotExist:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        data = s.RoleSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        role = data.validated_data["role"]
        with transaction.atomic():
            owners = Membership.objects.select_for_update().filter(workspace=ws, role=Membership.OWNER)
            owner_ids = list(owners.values_list("pk", flat=True))
            if membership.role == Membership.OWNER and role != Membership.OWNER and owner_ids == [membership.pk]:
                raise serializers.ValidationError({"role": "A workspace must keep at least one owner."})
            membership.role = role
            membership.save(update_fields=["role"])
        return Response(s.TeamMemberSerializer(membership).data)
