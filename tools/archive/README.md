# Archived AML importer

`migrate_aml.py` is the historical one-shot importer for Ty’s AML vault. R4 Q6
archives it; it is not a product write law, has no shipped CLI command and is
outside the Python/npm package paths. This directory is never copied into the
plugin or product payload.

The source was moved byte-for-byte from `trajecta_identity/migrate_aml.py`.
Its package-relative import is deliberately preserved. The historical regression
and AML fixture builder moved explicitly from `tests/test_identity.py` into
`tests/test_archived_aml.py`, which loads these bytes with the original package
context. No test was silently deleted or retired. Run it only on synthetic stores:

```sh
python -m pytest tests/test_archived_aml.py
```

R4 S2 permits exactly the oracle-source path re-key in five corpus MANIFESTs.
The corpus audit proves the source bytes and digest did not change.
