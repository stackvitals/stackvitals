"""Runtime quarantine for more runners (Trunk's and Datadog's): Playwright, Maven Surefire and .NET leave the listed
tests out by name; anything else uses `stackvitals ci quarantine -- <command>`."""
from stackvitals.ci.quarantine_runtime import runtime_args

IDS = {"src/test/java/com/acme/CartTest.java::com.acme.CartTest::addsItem", "tests/e2e/login.spec.ts::login::signs in"}


def test_playwright_maven_and_dotnet_arguments():
    pw = runtime_args({"tests/e2e/login.spec.ts::login::signs in"}, "playwright")
    assert pw == ["--grep-invert", "(?:signs\ in)$"]
    mvn = runtime_args({"src/test/java/com/acme/CartTest.java::com.acme.CartTest::addsItem"}, "maven")
    assert mvn == ["-Dtest=!CartTest#addsItem", "-Dsurefire.failIfNoSpecifiedTests=false"]
    net = runtime_args({"Acme.Tests.CartTests::AddsItem", "Acme.Tests.CartTests::RemovesItem"}, "dotnet")
    assert net == ["--filter", "FullyQualifiedName!=Acme.Tests.CartTests.AddsItem&FullyQualifiedName!=Acme.Tests.CartTests.RemovesItem"]
    assert runtime_args(set(), "maven") == []
