from main import main


def test_the_default_name_is_world():
    assert main([]) == "hello, world"


def test_a_named_greeting():
    assert main(["--name", "ada"]) == "hello, ada"
