"""Moving a transform into a repository, on the screen (§275; B.1).

§274 built adoption on the server and `test_transform_publish.py` holds what it
does. What needs a browser is what the Models screen *offers* — and that is the
half that was wrong:

**`ModelOut` has carried `source_repo_id` since §94 and the shared `Model` type
did not**, so no screen could read it, and this page showed an editable body
and a Save button for every model including the ones `services/models.py`
refuses. §214's shape — a control that looks like it works — kept alive by a
field that was on the wire and absent from the type.

The rules are in `apps/web/src/lib/model-authoring.test.ts`. What needs a
browser is that the page acts on them.
"""
from __future__ import annotations

import uuid

from playwright.sync_api import expect

from api import Module


def project(api, name: str) -> Module:
    """A project to hang models off. `Module` is the cheapest handle the suite
    has for one — its constructor creates a project and nothing else."""
    return Module(api, name)


def make_model(mod: Module, *, name: str, code: str = "SELECT 1", language: str = "sql") -> dict:
    return mod.api.call(
        "POST", f"{mod.base}/models",
        {"name": name, "language": language, "code": code, "inputs": []},
    )


def make_repository(mod: Module, name: str) -> dict:
    return mod.api.call("POST", f"{mod.base}/repositories", {"name": name})


def models_screen(page, mod: Module) -> None:
    page.goto(f"http://localhost:3100/{mod.workspace_slug}/{mod.project_slug}/models")
    # The row for a model this test made is what everything here reads, so the
    # wait is for the table to hold something rather than for the page to have
    # navigated (§271: a one-shot read of a collection that starts empty).
    # `.table`, not `.data-grid`: this screen's list is the former and the
    # history dialog is the latter, so the wrong one waits forever on a table
    # that is not on the page yet.
    expect(page.locator(".table tbody tr").first).to_be_visible(timeout=30000)


def row(page, name: str):
    return page.locator(".table tbody tr").filter(has_text=name)


def test_a_directly_authored_transform_is_offered_a_repository(page, api) -> None:
    """The button exists, and after it is used the offer is gone.

    Adoption is one-way — B.1 removes direct editing, so there is nothing to
    hand a model back to — which makes "offered exactly once" a property rather
    than a detail.
    """
    mod = project(api, "Adopt offer")
    name = f"adoptme_{uuid.uuid4().hex[:6]}"
    make_model(mod, name=name)
    repo = make_repository(mod, f"Transforms {mod.tag}")

    models_screen(page, mod)
    line = row(page, name)
    expect(line.get_by_test_id("model-adopt")).to_be_visible()
    expect(line.get_by_test_id("model-authored-in")).to_have_count(0)

    line.get_by_test_id("model-adopt").click()
    # Waited for, not assumed: the picker is empty until the repositories
    # request resolves, and `select_option` does not retry for options.
    picker = page.get_by_test_id("adopt-repository")
    expect(picker.locator("option")).to_have_count(2)
    picker.select_option(repo["id"])
    page.get_by_test_id("adopt-confirm").click()

    # The row now says where it lives, and does not offer to move it again.
    line = row(page, name)
    expect(line.get_by_test_id("model-authored-in")).to_contain_text(f"{name}.sql")
    expect(line.get_by_test_id("model-adopt")).to_have_count(0)


def test_an_adopted_transform_is_not_offered_an_edit_the_server_refuses(
    page, api
) -> None:
    """**The defect this unit exists for.**

    Before §275 the dialog showed an editable body and an enabled Save for a
    repository-authored transform, and the server answered with a refusal. The
    reason names the file, because the reader's next move is to open it — a
    message that only said "read-only" would read as a permission problem and
    send them to an administrator.
    """
    mod = project(api, "Adopt lock")
    name = f"locked_{uuid.uuid4().hex[:6]}"
    model = make_model(mod, name=name)
    repo = make_repository(mod, f"Transforms {mod.tag}")
    mod.api.call(
        "POST", f"{mod.base}/models/{model['id']}/adopt",
        {"repository_id": repo["id"], "branch": "main"},
    )

    models_screen(page, mod)
    row(page, name).get_by_role("button", name="Edit").click()

    body = page.get_by_test_id("model-code")
    expect(body).to_be_visible()
    expect(body).to_have_attribute("readonly", "")
    # The reason, naming the file and saying what to do instead.
    expect(page.get_by_text(f"src/{name}.sql", exact=False).first).to_be_visible()
    expect(page.get_by_role("button", name="Save changes")).to_be_disabled()


def test_a_project_with_no_repository_says_so_rather_than_offering_nothing(
    page, api
) -> None:
    """An empty picker reads as broken, and what to do about it is on another
    screen. Worth a browser test because it is a *rendering* decision: the
    server has no opinion about a project with no repositories, it simply
    returns an empty list."""
    mod = project(api, "Adopt empty")
    name = f"norepo_{uuid.uuid4().hex[:6]}"
    make_model(mod, name=name)

    models_screen(page, mod)
    row(page, name).get_by_test_id("model-adopt").click()

    expect(page.get_by_test_id("adopt-no-repositories")).to_be_visible()
    expect(page.get_by_test_id("adopt-repository")).to_have_count(0)
    expect(page.get_by_test_id("adopt-confirm")).to_be_disabled()


def require_review(mod: Module, on: bool = True) -> None:
    mod.api.call("PUT", f"{mod.base}/code/review-policy", {"require_code_review": on})


def test_a_review_required_project_points_a_local_transform_at_a_repository(
    page, api
) -> None:
    """§277: **the state that would have stranded somebody.**

    `models.update` refuses a direct edit when `require_code_review` is set, and
    the answer used to be "open a proposal" — true while the Code pillar page
    existed to open one on, and that is the page B.1 deletes. For a transform
    that is not yet a file there is now exactly one path, and the screen has to
    say which.
    """
    mod = project(api, "Adopt gated")
    name = f"gated_{uuid.uuid4().hex[:6]}"
    make_model(mod, name=name)
    make_repository(mod, f"Transforms {mod.tag}")
    require_review(mod)

    models_screen(page, mod)
    row(page, name).get_by_role("button", name="Edit").click()

    body = page.get_by_test_id("model-code")
    expect(body).to_have_attribute("readonly", "")
    expect(page.get_by_text("requires code review", exact=False).first).to_be_visible()
    expect(page.get_by_text("Move it into a repository", exact=False).first).to_be_visible()
    expect(page.get_by_role("button", name="Save changes")).to_be_disabled()

    # **And the move is still offered**, because adoption copies the code
    # through unchanged and so is not what the gate is about. A gate that also
    # blocked it would leave the transform with no editable path at all - the
    # exact state B.1 exists to remove.
    page.get_by_role("button", name="Cancel").click()
    expect(row(page, name).get_by_test_id("model-adopt")).to_be_visible()


def test_the_two_read_only_reasons_are_not_the_same_sentence(page, api) -> None:
    """A repository-authored transform in a review-required project is still
    "go to the file". Saying "your project requires review" there would send
    somebody to propose a change to a definition they cannot edit anyway."""
    mod = project(api, "Adopt gated adopted")
    name = f"both_{uuid.uuid4().hex[:6]}"
    model = make_model(mod, name=name)
    repo = make_repository(mod, f"Transforms {mod.tag}")
    mod.api.call(
        "POST", f"{mod.base}/models/{model['id']}/adopt",
        {"repository_id": repo["id"], "branch": "main"},
    )
    require_review(mod)

    models_screen(page, mod)
    row(page, name).get_by_role("button", name="Edit").click()
    expect(page.get_by_text(f"src/{name}.sql", exact=False).first).to_be_visible()
    expect(page.get_by_text("requires code review", exact=False)).to_have_count(0)


# ---- the project's transform history (§280) ----------------------------------
def test_the_projects_change_history_is_not_the_page_b1_deletes(page, api) -> None:
    """§278 found `codeApi.history` living only on the Code pillar page.

    **Three different histories, and this is the one nothing else shows.** A
    model's own History dialog is `model_versions` for that model; the
    repository application's History tab is commits in one repository; this is
    every transform in the project, with the change sets that group them —
    decision 0001's "one genuinely new concept".
    """
    mod = project(api, "History project")
    first = f"one_{uuid.uuid4().hex[:6]}"
    second = f"two_{uuid.uuid4().hex[:6]}"
    make_model(mod, name=first)
    make_model(mod, name=second)

    models_screen(page, mod)
    page.get_by_test_id("project-history").click()

    entries = page.get_by_test_id("project-history-list")
    expect(entries).to_be_visible()
    # Both transforms' creations are in it, as ungrouped versions — a single
    # save is still an edit and belongs in the log.
    expect(entries).to_contain_text(first)
    expect(entries).to_contain_text(second)
    expect(entries).to_contain_text("v1")


def test_an_empty_history_tells_the_two_empties_apart(page, api) -> None:
    """A project whose transforms have never been saved has no history; so does
    a project with no transforms. Only the second is a reason to go somewhere
    else, and the reader is the one who knows which they are looking at."""
    mod = project(api, "History empty")
    # No models at all. `models_screen` waits for a row, so go straight there.
    page.goto(f"http://localhost:3100/{mod.workspace_slug}/{mod.project_slug}/models")
    page.get_by_test_id("project-history").click()

    expect(page.get_by_test_id("project-history-empty")).to_contain_text(
        "No transforms in this project"
    )


# ---- moving several at once (§289) -------------------------------------------
# **What a change set becomes.** Decision 0001 called the change set "the one
# genuinely new concept" — "these three transforms changed together, for one
# reason" — and B.1 deletes the only screen that can make one. A commit says the
# same about a repository's files, so the successor is to adopt them together
# and commit together. That is only a successor if adopting *is* together: six
# adoptions are six commits and six unrelated moves in the history.
def pick(page, name: str) -> None:
    """Tick the checkbox for this transform, **by its label rather than by its
    row**.

    `row()` filters with `has_text`, which Playwright matches
    case-insensitively - so `daily_orders_x` selects the row for
    `Daily_Orders_x` as well, and the two names that differ only in case are
    exactly the pair the collision test needs. The checkbox's `aria-label`
    carries the name verbatim and matches exactly.
    """
    page.get_by_role(
        "checkbox", name=f"Move {name} into a repository", exact=True
    ).check()


def test_several_transforms_move_together_as_one_commit(page, api) -> None:
    """The whole unit: choose three, name a repository, one commit."""
    mod = project(api, "Move together")
    names = [f"together{n}_{uuid.uuid4().hex[:6]}" for n in range(3)]
    for name in names:
        make_model(mod, name=name)
    repo = make_repository(mod, f"Transforms {mod.tag}")

    models_screen(page, mod)
    for name in names:
        pick(page, name)

    bar = page.get_by_test_id("move-together")
    expect(bar).to_be_visible()
    expect(page.get_by_test_id("move-confirm")).to_contain_text("Move 3 transforms")
    page.get_by_test_id("move-repository").select_option(value=repo["id"])
    page.get_by_test_id("move-confirm").click()

    # Every one of them is now authored in the repository, and they share a
    # commit - which is what says they moved together.
    for name in names:
        expect(row(page, name).get_by_test_id("model-authored-in")).to_be_visible(
            timeout=30000
        )
    commits = mod.api.call("GET", f"{mod.base}/repositories/{repo['id']}/commits")
    assert len(commits) == 1, commits
    tree = mod.api.call("GET", f"{mod.base}/repositories/{repo['id']}/tree")["files"]
    assert len(tree) == 3, sorted(tree)


def test_a_transform_already_in_a_repository_offers_no_checkbox(page, api) -> None:
    """**Empty rather than disabled.** A greyed checkbox invites the question
    "why not"; nothing there says the row is not part of this, and the row
    already says why."""
    mod = project(api, "Move already")
    name = f"already_{uuid.uuid4().hex[:6]}"
    model = make_model(mod, name=name)
    repo = make_repository(mod, f"Transforms {mod.tag}")
    mod.api.call("POST", f"{mod.base}/models/{model['id']}/adopt",
                 {"repository_id": repo["id"], "branch": "main"})

    models_screen(page, mod)
    expect(row(page, name).get_by_test_id("model-pick")).to_have_count(0)


def test_the_commit_message_can_be_given_and_is_otherwise_derived(page, api) -> None:
    """Prefilled as a placeholder rather than as a value: leaving it alone
    sends nothing and the server writes the sentence, so the browser is not a
    second implementation of the rule."""
    mod = project(api, "Move message")
    names = [f"msg{n}_{uuid.uuid4().hex[:6]}" for n in range(2)]
    for name in names:
        make_model(mod, name=name)
    repo = make_repository(mod, f"Transforms {mod.tag}")

    models_screen(page, mod)
    for name in names:
        pick(page, name)
    # The suggestion is visible before anybody types, so what will be recorded
    # is readable rather than a surprise in the log.
    expect(page.get_by_test_id("move-message")).to_have_attribute(
        "placeholder", f"Move {names[0]}, {names[1]} into this repository"
    )

    page.get_by_test_id("move-repository").select_option(value=repo["id"])
    page.get_by_test_id("move-message").fill("Ahead of the Q3 rebuild")
    page.get_by_test_id("move-confirm").click()

    expect(row(page, names[0]).get_by_test_id("model-authored-in")).to_be_visible(
        timeout=30000
    )
    commits = mod.api.call("GET", f"{mod.base}/repositories/{repo['id']}/commits")
    assert commits[0]["message"] == "Ahead of the Q3 rebuild", commits[0]


def test_a_project_with_no_repositories_says_there_is_nowhere_to_go(page, api) -> None:
    """The one absence that is a reason to go and do something else."""
    mod = project(api, "Move nowhere")
    name = f"nowhere_{uuid.uuid4().hex[:6]}"
    make_model(mod, name=name)

    models_screen(page, mod)
    pick(page, name)
    expect(page.get_by_test_id("move-no-repositories")).to_be_visible()
    expect(page.get_by_test_id("move-confirm")).to_be_disabled()


def test_a_refused_batch_moves_none_of_them_and_says_why(page, api) -> None:
    """**All of them or none**, and the refusal names the transform it is
    about - in a batch the whole point of the message is which one."""
    mod = project(api, "Move refused")
    tag = uuid.uuid4().hex[:6]
    # Two names that slugify the same way: one file, two models.
    first, second = f"daily_orders_{tag}", f"Daily_Orders_{tag}"
    make_model(mod, name=first)
    make_model(mod, name=second)
    repo = make_repository(mod, f"Transforms {mod.tag}")

    models_screen(page, mod)
    pick(page, first)
    pick(page, second)
    page.get_by_test_id("move-repository").select_option(value=repo["id"])
    page.get_by_test_id("move-confirm").click()

    error = page.get_by_test_id("move-error")
    expect(error).to_be_visible(timeout=20000)
    expect(error).to_contain_text("would both be written to")
    # And neither moved: the repository is still empty.
    commits = mod.api.call("GET", f"{mod.base}/repositories/{repo['id']}/commits")
    assert commits == [], commits


# ---- what a version changed (§291) -------------------------------------------
def test_a_versions_diff_survived_the_deletion_of_the_code_page(page, api) -> None:
    """**The last row of §278's table, and the one §280 half-moved.**

    That table listed `changeSet` + `diff` together; §280 moved the change-set
    contents onto this screen and left the *diffs* on the page B.1 deletes. So
    the history dialog could show what a version **is** and not what it
    **changed** - which is the question a history is usually opened to answer.
    Deleting the page without this would have taken it away from every
    transform outside a repository, silently, which is the exact failure §278
    stopped.
    """
    mod = project(api, "Version diff")
    name = f"diffme_{uuid.uuid4().hex[:6]}"
    made = make_model(mod, name=name, code="SELECT 1 AS id")
    mod.api.call("PATCH", f"{mod.base}/models/{made['id']}",
                 {"code": "SELECT 1 AS id, 2 AS total"})

    models_screen(page, mod)
    row(page, name).get_by_role("button", name="History").click()

    # v1 has nothing before it, so it is not offered a diff: a diff of
    # everything against nothing is the file, which the Code button shows.
    expect(page.get_by_test_id("version-1-changes")).to_have_count(0)

    page.get_by_test_id("version-2-changes").click()
    shown = page.get_by_test_id("version-2-diff")
    expect(shown).to_be_visible(timeout=30000)
    # The added column, as an addition rather than as the whole file - which is
    # what separates this from the Code button next to it.
    expect(shown).to_contain_text("+SELECT 1 AS id, 2 AS total")
    expect(shown).to_contain_text("-SELECT 1 AS id")
