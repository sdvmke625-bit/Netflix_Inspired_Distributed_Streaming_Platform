from rest_framework.permissions import SAFE_METHODS, BasePermission


class IsCatalogWriterOrReadOnly(BasePermission):
    """Allow public reads and writes from staff users authenticated by JWT."""

    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            return True
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.is_staff
        )
