import sys

if "--splash-only" in sys.argv:
    from palworld_admin.splash import run_standalone

    run_standalone()
    raise SystemExit(0)

if getattr(sys, "frozen", False):
    from palworld_admin.splash import start_splash_process

    start_splash_process()

from palworld_admin.__main__ import main

if __name__ == "__main__":
    try:
        raise SystemExit(main())
    finally:
        from palworld_admin.splash import close_splash

        close_splash()
