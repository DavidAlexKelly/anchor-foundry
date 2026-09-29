"""p.38's Repository node colouring on the pipeline graph (§677;
`data-lineage` p.38).

> "Repository: Colors the nodes based on the code repository used to create
> them. You can either color the nodes by the name of the repository, or by
> its type (e.g. Code Repository, Code Workbook)." (p.38)

The upload, two models, and their outputs from `test_pipeline_colouring.py`'s
fixture, with model A marked as written in a repository: A and the dataset it
writes take the repository's colour and name it in the legend, and the rest
say they came from no repository. How colours are assigned is
`node-colouring.test.ts`; that the graph carries the name is `test_pipeline.py`.
"""
from __future__ import annotations

import psycopg
from playwright.sync_api import expect

from conftest import ADMIN_DSN
from test_pipeline_colouring import coloured, open_graph  # noqa: F401


def test_the_repository_a_model_was_written_in_colours_it_and_its_output(page, api, coloured) -> None:
    tag = coloured["tag"]
    workspace = api.call("GET", "/workspaces")[0]
    project = next(p for p in api.call("GET", f"/workspaces/{workspace['id']}/projects")
                   if p["slug"] == coloured["project_slug"])
    base = f"/workspaces/{workspace['id']}/projects/{project['id']}"
    repo = api.call("POST", f"{base}/repositories", {"name": f"Transforms {tag}"})
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        conn.execute("UPDATE models SET source_repo_id = %s, source_path = 'src/a.sql'"
                     " WHERE project_id = %s AND name = %s", (repo["id"], project["id"], f"A {tag}"))

    open_graph(page, coloured)
    page.get_by_test_id("graph-colouring").select_option("repository")
    named = page.get_by_test_id(f"legend-repo:Transforms {tag}")
    expect(named).to_have_attribute("data-count", "2")
    expect(named).to_contain_text(f"Transforms {tag}")
    expect(page.get_by_test_id("legend-none")).to_contain_text("Not from a repository")
    expect(page.get_by_test_id("legend-none")).to_have_attribute("data-count", "3")
    keys = [row.get_attribute("data-testid") for row in page.locator("[data-testid^='legend-']").all()]
    assert keys == [f"legend-repo:Transforms {tag}", "legend-none"], keys
