import json
def test_probe(client, fx, typed):
    import sys
    sys.path.insert(0, ".")
    from test_object_sets import group
    r = group(client, fx, {"object_type_id": typed, "filters": []}, property="seen")
    print("GROUPS", json.dumps(r.json()["groups"]))
