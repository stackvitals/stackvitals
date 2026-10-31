from mergescout.owners import owner_logins


def test_owner_logins_reads_codeowners_and_maintainers():
    text = "* @org/core @alice\n/docs/ @Bob # docs\nMaintainers:\n- Carol (@carol-x)\nemail: dave@example.com"
    assert owner_logins(text) == {"alice", "bob", "carol-x"}


def test_owner_logins_reads_kubernetes_owners_yaml():
    text = "approvers:\n  - Alice\n  - bob # lead\nreviewers:\n- carol\nlabels:\n- sig/node\n"
    assert owner_logins(text) == {"alice", "bob", "carol"}
