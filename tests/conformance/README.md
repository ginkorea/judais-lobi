# The conformance kit

**Copy these two files, edit `READS`, set the `PIN`.**

That is the whole of it. `conftest.py` and `test_conformance.py` go into your
own test directory unchanged except for the one dict at the top of the second
one — `CONFORMANCE`, whose `reads` key is the `READS` table this file's title
means and whose `pin` key is the pin.

```
cp <judais-lobi>/tests/conformance/conftest.py         yourrepo/tests/
cp <judais-lobi>/tests/conformance/test_conformance.py yourrepo/tests/
```

Then, in `test_conformance.py` and nowhere else:

1. **`pin`** — the release you integrated against, as `pip` reports it
   (`"1.0.0"`). Read it out of whatever one file already holds your pin rather
   than typing the version a second time. `None` means "not pinned yet", and
   the check says nothing.
2. **`schema_version`** — `contract.SCHEMA_VERSION` at that release. The
   load-bearing line: the harness bumps it exactly when a consumer has to
   change.
3. **`reads`** — every event your bridge has a branch for, and every field it
   takes off one. **Make it shorter than the copy you started from.** The
   shipped table names all ten events and every field because judais-lobi's own
   suite runs this kit against itself and a template that had fallen behind the
   contract would be worse than none. Yours should name what you actually
   index; an event you have no branch for does not belong in it.
4. **`flags`** and **`env`** — what your spawn line passes and exports. Mission
   mode is a closed surface; everything else in `--help` is a person's surface
   and may move between releases.
5. **`outcomes`** and **`exit_clauses`** — the words you branch on, and the
   promises about the process you build behaviour on.
6. **`spawn`** — how you start the harness, and **one recorded run** to replay.
   Any run directory you have archived will do: a replay needs no model, no
   server and no credential, so this step runs on a hosted CI runner. Leave
   `run_id` as `None` and that half skips and says so.

## What it costs to run

Nothing. No model, no API key, no MCP server, no GPU, no network. Add it to
your CI on the same trigger as everything else.

## What it does not do

It does not test *your* platform. It tests the boundary: that the harness still
declares everything you read, and that a real stream is the shape the table
claims. Whether your pane renders a `gate_requested` correctly is your test to
write.

## When it goes red

* **`schema_version`** — the harness made a breaking change on purpose. Read
  `CONTRACT.md`'s "Compatibility" and "1.0 — the freeze" sections and change
  your bridge, then move both this number and the pin.
* **a field** — the dangerous one. A field you read that the harness no longer
  declares reaches your bridge as `None`, and the turn renders with the content
  simply gone. Nothing else catches it.
* **an unknown event** — the harmless one. The harness grew a record type you
  have no branch for; dropping it is correct and is what the compatibility rule
  expects. Widen `reads`, or leave the branch out and widen it anyway, so that
  "no opinion" stays a decision somebody made.
* **the pin** — the environment is not the release you tested against.

`PLATFORMS.md` §10 is the long version, and §11 is the versioning rule this
kit enforces.
