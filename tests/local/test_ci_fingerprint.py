"""Failure fingerprints in Sentry's order: the root cause's type and innermost in-app frames when a stack exists, the
normalised message only when it does not. Framework and standard-library frames never count."""
from stackvitals.ci.fingerprint import analyse, normalise

JAVA_WRAPPED = """java.util.concurrent.ExecutionException: java.net.UnknownHostException: Failed to resolve 'a.netty.io' [A(1)]
\tat io.netty.util.concurrent.DefaultPromise.get(DefaultPromise.java:340)
\tat io.netty.resolver.dns.DnsNameResolverTest.testFollow(DnsNameResolverTest.java:1714)
\tat java.base/java.lang.reflect.Method.invoke(Method.java:565)
\tat org.junit.platform.commons.util.ReflectionUtils.invokeMethod(ReflectionUtils.java:786)
Caused by: java.net.UnknownHostException: Failed to resolve 'a.netty.io' [A(1)]
\tat io.netty.resolver.dns.DnsResolveContext.finishResolve(DnsResolveContext.java:1138)
\tat io.netty.resolver.dns.DnsResolveContext.tryToFinishResolve(DnsResolveContext.java:1085)
\tat io.netty.resolver.dns.DnsResolveContext.lambda$query$0(DnsResolveContext.java:509)
\t... 21 more
"""
JAVA_OTHER_WRAPPER = JAVA_WRAPPED.replace("java.util.concurrent.ExecutionException", "java.util.concurrent.CompletionException") \
    .replace("a.netty.io", "b.example.com").replace("testFollow", "testOther").replace(":1138)", ":1140)")
JAVA_ASSERT = """org.opentest4j.AssertionFailedError: expected: <true> but was: <false>
\tat org.junit.jupiter.api@5.14.3/org.junit.jupiter.api.AssertionFailureBuilder.build(AssertionFailureBuilder.java:151)
\tat org.junit.jupiter.api@5.14.3/org.junit.jupiter.api.AssertTrue.failNotTrue(AssertTrue.java:63)
\tat io.netty.handler.ssl.ocsp.OCSPTest.testValidate(OCSPTest.java:88)
"""
PYTEST = """self = <pkg.tests.test_oecd.TestOECD object at 0x0000019E08E43890>

    def test_get_un_den(self):
>       df = web.DataReader("TUD", "oecd")

pkg\\tests\\test_oecd.py:14:
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
pkg\\compat\\__init__.py:85: in wrapper
    return func(*args, **kwargs)
C:\\hostedtoolcache\\Python\\3.14\\lib\\site-packages\\requests\\api.py:73: in get
    return request("get", url)
pkg\\io\\sdmx.py:47: in read_jsdmx
    raise ValueError("Unsupported SDMX-JSON payload structure")
E   ValueError: Unsupported SDMX-JSON payload structure

pkg\\io\\sdmx.py:47: ValueError
"""
PY_TRACEBACK = """Traceback (most recent call last):
  File "/home/runner/work/app/app/tests/test_x.py", line 10, in test_x
    run()
  File "/home/runner/work/app/app/.venv/lib/python3.12/site-packages/lib/core.py", line 5, in run
    raise KeyError(key)
  File "/home/runner/work/app/app/src/app/store.py", line 33, in load
    return cache[key]
KeyError: 'user-81723'
"""
JS = """TypeError: Cannot read properties of undefined (reading 'id')
    at getUser (/home/runner/work/web/web/src/users.ts:42:17)
    at Object.<anonymous> (/home/runner/work/web/web/src/__tests__/users.test.ts:12:5)
    at Promise.then.completed (/home/runner/work/web/web/node_modules/jest-circus/build/utils.js:298:28)
    at node:internal/process/task_queues:105:5
"""
VITEST = """AssertionError: expected 'abc' to contain 'TS2322'
 ❯ vi.waitFor.timeout packages/cli/src/__tests__/runtime.test.ts:88:20
 ❯ node_modules/.pnpm/vitest@3.2.4/node_modules/vitest/dist/index.js:12:3
"""
GO = """    store_test.go:42: expected 3 rows, got 2
"""
GO_PANIC = """panic: runtime error: index out of range [5] with length 3 [recovered]

goroutine 7 [running]:
testing.tRunner.func1.2({0x5f2a40, 0xc0000a2018})
\t/opt/hostedtoolcache/go/1.22.0/x64/src/testing/testing.go:1631 +0x24a
github.com/acme/app/store.(*Table).Row(...)
\t/home/runner/work/app/app/store/table.go:57 +0x1d
github.com/acme/app/store.TestRows(0xc000007ba0)
\t/home/runner/work/app/app/store/table_test.go:21 +0x3b
"""
RUST = """thread 'parser::tests::reads_header' panicked at src/parser.rs:118:9:
assertion `left == right` failed
  left: 3
 right: 4
"""
CSHARP = """System.InvalidOperationException : Sequence contains no elements
   at System.Linq.ThrowHelper.ThrowNoElementsException()
   at Acme.Orders.OrderService.Latest() in /home/runner/work/orders/src/OrderService.cs:line 77
   at Acme.Orders.Tests.OrderServiceTests.LatestWorks() in /home/runner/work/orders/tests/OrderServiceTests.cs:line 19
"""


def test_java_uses_the_root_cause_and_its_in_app_frames_so_wrappers_group_together():
    a = analyse("java.util.concurrent.ExecutionException", "", JAVA_WRAPPED)
    b = analyse("java.util.concurrent.CompletionException", "", JAVA_OTHER_WRAPPER)
    assert a.type == "java.net.UnknownHostException" and a.frames[0] == "io.netty.resolver.dns.DnsResolveContext.finishResolve"
    assert a.cause == b.cause  # same failure, different wrapper, host and line
    assert analyse(None, "", JAVA_ASSERT).frames == ["io.netty.handler.ssl.ocsp.OCSPTest.testValidate"]


def test_python_pytest_and_plain_tracebacks_find_the_innermost_frame_of_the_project():
    p = analyse(None, "ValueError: Unsupported SDMX-JSON payload structure", PYTEST)
    assert p.type == "ValueError" and p.frames[0] == "pkg/io/sdmx.py:read_jsdmx"
    assert "site-packages" not in " ".join(p.frames)
    t = analyse(None, "", PY_TRACEBACK)
    assert t.type == "KeyError" and t.frames[0] == "src/app/store.py:load" and t.frames[-1] == "tests/test_x.py:test_x"


def test_javascript_go_rust_and_csharp_frames():
    j = analyse("TypeError", "", JS)
    assert j.type == "TypeError" and j.frames == ["src/users.ts:getUser", "src/__tests__/users.test.ts:Object.<anonymous>"]
    assert analyse("AssertionError", "", VITEST).frames == ["packages/cli/src/__tests__/runtime.test.ts"]
    assert analyse(None, "", GO).frames == ["store_test.go"]
    g = analyse(None, "", GO_PANIC)
    assert g.type == "panic" and g.frames[0] == "github.com/acme/app/store.(*Table).Row"
    r = analyse(None, "", RUST)
    assert r.type == "panic" and r.frames == ["src/parser.rs"]
    c = analyse(None, "", CSHARP)
    assert c.type == "System.InvalidOperationException" and c.frames[0] == "Acme.Orders.OrderService.Latest"


def test_without_frames_the_normalised_message_decides():
    a = analyse("TimeoutException", "testSslEcho timed out after 30000 milliseconds at 2026-10-20T10:11:12Z", "")
    b = analyse("TimeoutException", "testSslEcho timed out after 45000 milliseconds at 2026-10-21T00:00:01Z", "")
    c = analyse("TimeoutException", "connect timed out after 30000 milliseconds", "")
    assert a.frames == [] and a.cause == b.cause != c.cause
    assert normalise("object at 0x7fd5582b0e10 id 3f2a9c1e-1b2c-4d5e-8f90-123456789abc in /tmp/x/y.txt took 3.5s") == \
        "object at # id # in # took #"
    assert normalise("#x1B[0m#x1B[91m- users[2,]#x1B[39;49;00m") == "- users[#,]"


def test_the_per_test_fingerprint_keeps_tests_and_distinct_assertions_apart():
    one = analyse(None, "expected: not <null>", JAVA_ASSERT.replace("expected: <true> but was: <false>", "expected: not <null>"))
    two = analyse(None, "", JAVA_ASSERT)
    assert one.cause == two.cause  # same place in the same test
    assert one.key("io.netty.OCSPTest::testValidate") != two.key("io.netty.OCSPTest::testValidate")  # different assertion
    assert two.key("a::t1") != two.key("a::t2") and len(two.key("a::t1")) == 12
    assert two.where == "io.netty.handler.ssl.ocsp.OCSPTest.testValidate"


def test_pytest_failures_in_the_test_body_keep_their_only_location():
    # Real finding (Context-Engine, 2026-10-20): the closing "path:line: Error" line is the only frame then.
    text = """self = <test_toon_encoder.TestTabularEncoding object at 0x7fd560d28fd0>

    def test_encode_tabular_basic(self):
        lines = encode_tabular("users", arr)
>       assert lines[0] == "users[2,]{id,name}:"
E       AssertionError: assert 'users[2]{id,name}:' == 'users[2,]{id,name}:'

tests/test_toon_encoder.py:45: AssertionError
"""
    f = analyse(None, "AssertionError: assert 'users[2]{id,name}:' == 'users[2,]{id,name}:'\n  - users[2,]", text)
    assert f.type == "AssertionError" and f.frames == ["tests/test_toon_encoder.py:test_encode_tabular_basic"]
    # And when deeper frames exist, the closing line is the innermost one (pandas-datareader's jsdmx.py).
    deep = PYTEST.replace("pkg\\io\\sdmx.py:47: in read_jsdmx\n    raise ValueError(\"Unsupported SDMX-JSON payload structure\")\n", "")
    assert analyse(None, "ValueError: x", deep.replace("pkg\\io\\sdmx.py:47: ValueError",
                                                        "    def read_jsdmx(x):\n>       raise ValueError(x)\n\npkg\\io\\sdmx.py:47: ValueError")).frames[0] == "pkg/io/sdmx.py:read_jsdmx"


def test_checkout_folders_of_other_ci_systems_are_dropped_too():
    from stackvitals.ci.fingerprint import _rel
    assert _rel("/builds/acme/web/src/login.js") == "src/login.js"  # GitLab
    assert _rel("/var/jenkins_home/workspace/web-main/src/login.js") == "src/login.js"  # Jenkins
    assert _rel("/home/circleci/project/src/login.js") == "src/login.js"  # CircleCI
    assert _rel("/var/lib/buildkite-agent/builds/agent-1/acme/web/src/login.js") == "src/login.js"  # Buildkite
    assert _rel(r"D:\a\web\web\src\login.js") == "src/login.js" and _rel("src/login.js") == "src/login.js"
