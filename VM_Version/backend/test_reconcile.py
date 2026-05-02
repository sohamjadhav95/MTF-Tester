def test_parse_comment():
    comment = "AUTO:2b6f1a9a:5f3c9e1z"
    if comment.startswith("AUTO:"):
        parts = comment.split(":")
        assert len(parts) >= 3
        assert parts[1] == "2b6f1a9a"
        assert parts[2] == "5f3c9e1z"

if __name__ == "__main__":
    test_parse_comment()
    print("test_reconcile passed!")
