# ruff: noqa: F405
"""Репозиторий kit с полным набором для test_outside_tree.py и test_outside_cancel.py (metis-0732, 0873): правки домена, M.FULL_TESTS, K1."""
from _outside_common import *  # noqa: F403

KIT = os.path.join(HOME, "projects", "kit")
os.makedirs(KIT)
git(KIT, "init", "-q", "-b", "main")
git(KIT, "remote", "add", "origin", "git@github.com:latark/kit.git")
os.makedirs(os.path.join(CACHE, "metis-k", "tmp"))
P.write_json(os.path.join(STATE, "domains.json"),
             {"domains": {"athena-x": ["~/projects/app"], "metis-y": ["~/projects/other"], "metis-k": ["~/projects/kit"]}})
M = P.merge_mod()
M.FULL_TESTS["kit"] = "heavy python3 t.py"   # полный набор этого репозитория для теста (у agent-kit — run-tests.py)
K1 = commit(KIT, {"t.py": GREEN, ".pantheon-verify": "heavy python3 t.py\n"}, "k1")
qkit = os.path.join(CACHE, "metis-k", "outside")


def kit_request():
    one_request.n += 1
    rid = f"20261103-1{one_request.n:05d}-c0c0c0"
    os.makedirs(qkit, exist_ok=True)
    with open(os.path.join(qkit, rid + ".req.json"), "w") as fh:
        json.dump({"v": 1, "id": rid, "kind": "test", "dir": KIT, "time": time.strftime("%Y-%m-%dT%H:%M:%S%z")}, fh)
    run_pass()
    return O.load_result(qkit, rid) or {}


__all__ = ["KIT", "M", "K1", "qkit", "kit_request"]
