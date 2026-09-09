# 0017 — How a script declares

**Status:** decided
**Roadmap:** phase 3, B.1 (models into repositories), which it blocks
**Extends** `0004-running-customer-code.md`, whose §272 addition is the other
half of this.

---

## The question

B.1 is "one editor, one repository model": delete `code/page.tsx`, and let a
transform be a file. That needs every existing model to be expressible as a
repository file, because a model that cannot live in a repository is a model
whose only editor is the one being deleted — and in a project that requires
review it would have no editable path at all (`README.md` records this as the
blocker that reorders the plan).

For SQL, adoption is a prepend:

```sql
-- output: daily_orders
-- input: orders = raw_orders
SELECT * FROM orders WHERE total > 0
```

For Python it is nothing. A directly-authored Python model is a **script** —
inputs arrive as module-level names, the result is assigned to `output` — and
the only Python declaration form is a decorated function:

```python
@transform(output="daily_orders", inputs={"orders": "raw_orders"})
def build(orders): ...
```

A script has no function to decorate. `read()` returns `None` for it, which
means "this is a helper, not a transform" — so publishing a repository
containing it says *"nothing at this commit declares a transform"*.

## The options

**Wrap the script into a function at adoption time.** Indent the body, add the
decorator, append `return output`. It is a *code transformation applied to
customer code*, and the failure modes are quiet: `global` statements change
meaning, a module-level `import` inside a function is legal but no longer
shared, and anything reading `__name__` or module scope moves. Worse, the file
in the repository would no longer be the code the author wrote, so the first
thing they see after adoption is a diff they did not make.

**Refuse, and make the author rewrite.** Honest, and it fails the goal: the
models that cannot be adopted are exactly the ones that then have no editor.

**Let a script declare in a leading comment, the way SQL already does.**

```python
# output: daily_orders
# input: orders = raw_orders

output = orders[orders.total > 0]
```

## The decision

**The third.** A Python file may declare either way — a `@transform`-decorated
function, or a leading comment block — and one file still declares exactly one
transform, so a file carrying both is refused like any other double
declaration (§272).

Three reasons, in the order they matter:

1. **It is the shape the module already claims to have.**
   `transform_declarations.py` opens by saying both languages answer "the same
   question" in "the same answer shape, so a reader does not have to know which
   language a repository is written in". That was true of SQL and of decorated
   Python and false of everything else; this is the sentence becoming true
   rather than a new idea.

2. **Adoption becomes one operation with one property to check.** Prepend a
   header, then *parse the result back* and require it to say what the model
   said. Not a formality, and this was measured rather than assumed: the reader
   takes the leading comment block only, so a model whose code already begins
   with comments produces a longer block than the header alone. A `-- output:`
   in it is refused as a second declaration — loud, fine. **A `-- input: x = y`
   in it is not.** The parse succeeds and the transform silently gains an input
   the model never had. So the round trip has to be checked as *exact
   equality*, not as "the header survived", and it catches that identically in
   both languages because it is the same reader.

3. **Nothing is lost at the parity end.** Foundry has no script-shaped
   transform; its transforms are decorated functions, and that form stays
   exactly as decision 0004 documents it. This adds a declaration form for a
   shape that is *this platform's own* — every model authored before
   repositories existed — rather than replacing Foundry's.

### What it is not

- **Not a second runtime contract.** §272 settled how a file runs: a
  module-level `output` wins, otherwise the declared function is called. A
  comment-declared file has no function, so it runs as the script it is. The
  declaration says what the file *produces*; it never says how it runs.
- **Not a way to declare a decorated transform.** A file with a comment header
  and a decorated function declares twice and is refused, naming both — same
  rule, same message shape as two decorators.
- **Not read by importing.** The comment form is parsed with the same regexes
  SQL uses, over the leading comment block. `ast` is not involved and nothing
  is executed, which is decision 0004's whole point.

## The two asymmetries worth stating

**The prefix.** SQL's is `--` and Python's is `#`, so the two are not the same
bytes. Everything else is: the same two keys, the same order-free leading
block, the same refusals, one parameterised pattern rather than two
hand-written pairs — because two copies is precisely how the claim above stops
being true, which §272 found had already happened once in the other reader.

**Orphan inputs are an error in SQL and a comment in Python** — but only beside
a decorator. "This file declares inputs but no output" exists because a
mistyped output line otherwise leaves a file that silently builds nothing, and
in SQL there is no other way to have declared. In Python there is. So a stray
`# input:` line above a `@transform` function is a comment, and raising there
would answer a question the author did not ask about a file that declares
perfectly well. With no decorator the refusal stands, because then it is the
typo it looks like.

## Consequences

- **A `.py` file whose leading comments contain `# output: something` becomes a
  declaration where it previously was not.** This is the real cost, and it is
  bounded: the line must be in the *leading* comment block, must match the
  strict form, and the file must be in a repository. The publish plan shows
  exactly what it read before anything is written.
- **A module docstring ends the leading block, and a shebang does not.** That
  follows from "leading *comment* block" — a docstring is a statement, so it
  closes the block exactly as the first `SELECT` does, while `#!/usr/bin/env
  python` is a comment and does not. It is the surprising half of the rule: it
  is about comments, not about "before the code starts". Both are tested,
  because a reader who assumed either would be wrong about a real file.
- **"One file, one transform" now has three ways to be violated rather than
  two**: two decorators, two `output:` lines, or one of each. The third refusal
  names the *forms* rather than lines, because the fix is to delete one of them.

## Proof

`apps/api/tests/test_transform_declarations.py`: a comment-declared script is a
transform; the same file declaring both ways is refused naming both forms; a
stray `# input:` beside a decorator is a comment while the same line alone is
still the SQL refusal; `# output:` after the first statement is not a
declaration and neither is one after a docstring, while a shebang leaves the
block open; and `test_the_two_languages_answer_identically_apart_from_the_prefix`
asserts the module docstring's claim directly rather than leaving it a sentence.

`apps/worker/tests/test_python_sandbox.py` and
`apps/api/tests/test_transform_publish.py` hold the two ends of the seam — the
form runs, and the form publishes. Added the same day as the reader's tests on
purpose: §272 was two halves each thorough about itself and never tested
against each other.
