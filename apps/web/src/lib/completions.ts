/**
 * Completions over the platform's own names (§434; `code-repositories` p.2).
 *
 * > "Every repository type includes integrated features to aid with the code
 * > authoring experience, including IntelliSense, code linting and error
 * > checking, and rich help dialogs."
 *
 * **Monaco already completes the language; what it cannot know is the
 * platform.** SQL keywords, Python builtins and the words already in the file
 * come free with the editor, and nothing in this repository needed to be built
 * for them. What no editor can guess is that this project has a dataset called
 * `raw_orders`, that this file declared it as `raw`, and that it has a column
 * called `total` — and those are the three things somebody writing a transform
 * types wrong.
 *
 * So the completions here are over three vocabularies, each offered only where
 * it is the answer:
 *
 *   `-- input: raw = ` …  the project's datasets
 *   `FROM ` / `JOIN ` …   the aliases *this file* declared
 *   `raw.` …              that input's columns
 *
 * **Not everything everywhere.** A list that offered dataset names, aliases and
 * columns at every keystroke would be a list nobody reads, and would bury
 * Monaco's own suggestions under three hundred rows of the project's tables.
 * Where a vocabulary is not the answer, this returns nothing and Monaco's own
 * suggestions stand — which is why `completionsFor` can return an empty list
 * and that is a result rather than a failure.
 *
 * ---
 *
 * **The declaration syntax is not re-implemented here, it is matched.** Its one
 * writer is `transform_declarations.py` (§272), which also reads it, and a
 * second parser in the browser would be a second answer to "what is declared"
 * — the failure `api.ts`'s `render` comment names. What this file does is
 * narrower and cannot drift into that: it asks where the *cursor* is, which is
 * a question about a half-typed line the reader is still writing and that no
 * server has been asked about.
 */

export type CompletionKind = "dataset" | "alias" | "column";

export interface Completion {
  /** What the list shows. */
  label: string;
  /** What is typed when it is chosen.
   *
   * **Separate from the label since §444**, which is p.115's sentence in one
   * field: *"the editor will present the dataset name over the RID"*. A
   * repository that prefers ids gets a list of names and a file full of ids,
   * which is the whole point — an id is unreadable and a name does not
   * survive a rename, so the screen shows one and the file holds the other. */
  insert: string;
  kind: CompletionKind;
  /** Shown beside the label: a dataset's row count, a column's type, the
   *  dataset an alias points at. A list of bare names makes somebody pick the
   *  wrong one and find out at run time. */
  detail: string;
}

/** What this file has declared, and what the project holds. */
export interface Vocabulary {
  /** Every dataset in the project, with something to say about each. */
  datasets: { id: string; name: string; columns: { name: string; type: string }[] }[];
}

/** `-- input: alias = name`, in either language's comment prefix. The same
 *  shape `transform_declarations.py` reads, matched rather than re-derived. */
const INPUT_LINE = /^\s*(?:--|#)\s*input\s*:\s*([A-Za-z0-9_]+)\s*=\s*([A-Za-z0-9_.-]+)\s*$/i;

/** The same line while it is still being typed: everything up to the `=`. */
const INPUT_HALF = /^\s*(?:--|#)\s*input\s*:\s*[A-Za-z0-9_]+\s*=\s*([A-Za-z0-9_.-]*)$/i;

/** `FROM x` / `JOIN x`, where `x` is what is being typed. */
const FROM_HALF = /\b(?:from|join)\s+([A-Za-z0-9_]*)$/i;

/** `alias.` or `alias.col`, where the part after the dot is being typed. */
const DOTTED = /\b([A-Za-z0-9_]+)\.([A-Za-z0-9_]*)$/;

/** The same dotted shape, but immediately after `FROM` or `JOIN` — where it is
 *  a schema qualifier rather than a column. `FROM_HALF` cannot answer this: it
 *  requires the name to run to the cursor, and the dot ends it. */
const FROM_DOTTED = /\b(?:from|join)\s+[A-Za-z0-9_]+\.[A-Za-z0-9_]*$/i;

/**
 * The aliases this file declares, in the order they appear.
 *
 * **Read from the whole file, not from the lines above the cursor.** Somebody
 * writing the body of a query and then adding an input at the top is the
 * ordinary way this goes, and a reader that only looked upwards would stop
 * offering an alias the moment they scrolled.
 */
export function declaredInputs(text: string): { alias: string; dataset: string }[] {
  const found: { alias: string; dataset: string }[] = [];
  for (const line of text.split("\n")) {
    const match = INPUT_LINE.exec(line);
    if (match) found.push({ alias: match[1]!, dataset: match[2]! });
  }
  return found;
}

/**
 * What kind of thing belongs where the cursor is, or `null` for "not our
 * question".
 *
 * `before` is the text from the start of the line to the cursor — which is all
 * that can be known about a line somebody is still typing, and is what Monaco
 * hands a completion provider.
 */
export function contextAt(before: string): {
  kind: CompletionKind;
  prefix: string;
  alias?: string;
} | null {
  const input = INPUT_HALF.exec(before);
  if (input) return { kind: "dataset", prefix: input[1]! };

  // **Before `FROM`**, because `raw.` inside a `FROM` clause is a schema
  // qualifier rather than a column and offering columns there would be wrong
  // in the one place somebody is naming a table.
  const dotted = DOTTED.exec(before);
  if (dotted && !FROM_DOTTED.test(before)) {
    return { kind: "column", prefix: dotted[2]!, alias: dotted[1]! };
  }

  const from = FROM_HALF.exec(before);
  if (from) return { kind: "alias", prefix: from[1]! };

  return null;
}

/**
 * The completions to offer, best first.
 *
 * **Matched anywhere in the name, and case-insensitively.** A list that ignored
 * what has already been typed would put the right answer at row forty; one
 * that matched only the *start* would answer "orders" with nothing while
 * `raw_orders` sat in the project, which is the ordinary way somebody refers
 * to a table. Names keep the order they arrived in: re-sorting as the
 * vocabulary grows moves the answer under somebody's finger between one
 * keystroke and the next.
 */
export function completionsFor(
  before: string, text: string, vocabulary: Vocabulary,
  { preferIds = false }: { preferIds?: boolean } = {},
): Completion[] {
  const where = contextAt(before);
  if (where === null) return [];
  const prefix = where.prefix.toLowerCase();
  const keep = (label: string) => label.toLowerCase().includes(prefix);

  if (where.kind === "dataset") {
    return vocabulary.datasets
      .filter((d) => keep(d.name))
      .map((d) => ({
        label: d.name,
        // p.115's setting, and the only place it has any effect: what the
        // editor types for you. A file that already names a dataset by either
        // form goes on working whichever way this is set.
        insert: preferIds ? d.id : d.name,
        kind: "dataset" as const,
        detail: columnSummary(d.columns),
      }));
  }

  const inputs = declaredInputs(text);

  if (where.kind === "alias") {
    return inputs
      .filter((i) => keep(i.alias))
      .map((i) => ({
        label: i.alias,
        insert: i.alias,
        kind: "alias" as const,
        // **What the alias points at, named.** A file that declares its input
        // by id would otherwise offer `raw — aabbccdd-…`, which tells nobody
        // which table they are about to write a column of.
        detail: datasetOf(vocabulary, i.dataset)?.name ?? i.dataset,
      }));
  }

  // A column, of the dataset the alias points at. **An alias this file has not
  // declared offers nothing**, rather than every column in the project: the
  // reader typed a name, and answering a different question than the one they
  // asked is worse than answering none.
  const declared = inputs.find((i) => i.alias === where.alias);
  if (!declared) return [];
  const dataset = datasetOf(vocabulary, declared.dataset);
  if (!dataset) return [];
  return dataset.columns
    .filter((c) => keep(c.name))
    .map((c) => ({ label: c.name, insert: c.name, kind: "column" as const, detail: c.type }));
}

/** The dataset a declaration's right-hand side means, by either form.
 *
 * **Id first, then name**, which is `transform_publish._input_row`'s rule and
 * has to be: a file that names its inputs by id would otherwise get no column
 * completions at all, and p.115 recommends exactly that file. */
function datasetOf(
  vocabulary: Vocabulary, reference: string,
): Vocabulary["datasets"][number] | undefined {
  return vocabulary.datasets.find((d) => d.id === reference)
    ?? vocabulary.datasets.find((d) => d.name === reference);
}

/** What a dataset row says about itself. Columns rather than a row count: the
 *  question being answered is "is this the table I mean", and the column names
 *  answer it where a number does not. */
export function columnSummary(columns: { name: string }[]): string {
  if (columns.length === 0) return "no columns yet";
  const named = columns.slice(0, 4).map((c) => c.name).join(", ");
  const rest = columns.length - 4;
  return rest > 0 ? `${named} and ${rest} more` : named;
}
