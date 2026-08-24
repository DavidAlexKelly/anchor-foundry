from test_clipboard import module_with, tree_rows, select_section
from conftest import open_builder, settled

def test_probe(page, api) -> None:
    mod = module_with(api, "Clip probe")
    open_builder(page, mod)
    settled(page)
    print("BEFORE:", tree_rows(page).count())
    for i in range(tree_rows(page).count()):
        print("  ROW:", tree_rows(page).nth(i).inner_text().replace("\n", " | ")[:70])
    select_section(page)
    page.get_by_test_id("clip-copy").click()
    page.get_by_test_id("clip-paste-same").click()
    page.wait_for_timeout(3000)
    print("AFTER:", tree_rows(page).count())
    for i in range(tree_rows(page).count()):
        print("  ROW:", tree_rows(page).nth(i).inner_text().replace("\n", " | ")[:70])
