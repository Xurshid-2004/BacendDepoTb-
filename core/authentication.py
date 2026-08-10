"""
=====================================================================
DRF autentifikatsiya sinfi — "Authorization: Bearer <access>".

Har soʻrovda token tekshiriladi va ishchi bazadan olinadi. Ishchi
oʻchirilgan yoki faolsizlantirilgan boʻlsa — token yaroqli boʻlsa ham
kirish rad etiladi (ishdan boʻshagan xodim darhol kira olmaydi).
=====================================================================
"""

from __future__ import annotations

from rest_framework import authentication, exceptions

from core.models import Worker
from core.tokens import read_access


class JWTAuthentication(authentication.BaseAuthentication):
    keyword = "Bearer"

    def authenticate(self, request):
        header = authentication.get_authorization_header(request).decode("latin-1")
        if not header:
            return None

        parts = header.split()
        if len(parts) != 2 or parts[0].lower() != self.keyword.lower():
            return None

        claims = read_access(parts[1])
        if not claims or not claims.get("sub"):
            raise exceptions.AuthenticationFailed("Token yaroqsiz yoki muddati oʻtgan")

        worker = (
            Worker.objects.filter(id=claims["sub"], deleted=False, faol=True)
            .select_related("position", "depo")
            .first()
        )
        if not worker:
            raise exceptions.AuthenticationFailed("Foydalanuvchi topilmadi yoki faolsiz")

        return (worker, parts[1])

    def authenticate_header(self, request):
        return self.keyword
