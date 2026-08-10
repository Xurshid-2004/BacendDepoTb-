#!/usr/bin/env python
"""Django boshqaruv buyruqlari."""
import os
import sys


def main():
    # Windows konsoli standart holda cp1252 ishlatadi va oʻzbekcha
    # belgilarni (ʻ, ʼ) chiqara olmay xato beradi. UTF-8 ga oʻtkazamiz.
    for oqim in (sys.stdout, sys.stderr):
        if hasattr(oqim, "reconfigure"):
            try:
                oqim.reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass

    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Django import qilinmadi. Oʻrnatilganmi va virtual muhit "
            "faollashtirilganmi? Oʻrnatish: pip install -r requirements.txt"
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == '__main__':
    main()
