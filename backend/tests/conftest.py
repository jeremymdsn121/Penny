"""Test bootstrap.

``app.config`` instantiates ``Settings()`` at import time and requires the
Supabase env vars to be present, and several service modules read
``settings.SUPABASE_URL`` while building their base URLs. Tests never make real
network calls (the Supabase/Rentcast/Twilio clients are monkeypatched), so we
seed harmless dummy values here — before any ``app.*`` module is imported — so
collection doesn't blow up in a clean environment (e.g. CI, where there is no
``.env``).

``setdefault`` keeps any real environment a developer already has, and env vars
take precedence over a ``.env`` file in pydantic-settings, so this stays
deterministic regardless of a local ``.env``.
"""

import os

os.environ.setdefault("SUPABASE_URL", "http://supabase.test")
os.environ.setdefault("SUPABASE_ANON_KEY", "test-anon-key")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-service-role-key")
