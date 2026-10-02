# Applications

Every concrete sudofx application lives in its own package directory under this folder.

Allowed shape:

```text
applications/
  conversation/
    __init__.py
    application.py
    runtime.py
    provider.py
    README.md
```

Do not place application implementations directly in `applications/*.py`.

The only exception is an optional package-level `applications/__init__.py`, which must not contain application behavior.

Why this exists:

- ownership stays obvious;
- application-specific runtime/provider/UI code stays together;
- removal is clean;
- domain behavior does not leak into the sudofx kernel;
- future applications can evolve independently without turning this folder into a pile of unrelated modules.

A complete domain system is an **application**. Shared authority/runtime primitives belong in `src/sudofx/`, not here.
