"""What kind of flake a failure looks like (the environment: infrastructure, network, concurrency, timing; or the test's code:
resource leak, async wait, time, randomness, floating point, shared state, io, ordering), so people know where
to look. Measured against labelled causes in bench/accuracy/flaky/kinds.py."""
import re

# Checked in this order.
KINDS = (
    # The runner, a cache or artifact store, or a service the job starts on its own machine.
    ("infrastructure", re.compile(r"(?i)(ServerBusy|No space left on device|runner has received a shutdown signal|"
                                  r"lost communication with the server|Cannot connect to the Docker daemon|"
                                  r"failed to connect to the docker API|hosted runner encountered an error|out of memory|"
                                  r"OOMKilled|exit code 137|Cannot allocate memory|heap out of memory|FinalizeArtifact|"
                                  r"upload of artifact|artifact (upload|download) failed|"
                                  r"(127\.0\.0\.1|localhost)\S{0,8}.{0,60}connection refused)")),
    # ENOTFOUND matched case-sensitively: "FileNotFoundError" holds it in any case.
    ("network", re.compile(r"(?i)((?-i:\bENOTFOUND\b)|EAI_AGAIN|ECONNRESET|ECONNREFUSED|ETIMEDOUT|socket hang up|Could not resolve host|"
                           r"Temporary failure in name resolution|Name or service not known|Failed to fetch|"
                           r"Failed to download(?! and build)|\b50[234] (Service Unavailable|Bad Gateway|Gateway Time-?out)|"
                           r"HTTP (error )?5\d\d|status code 5\d\d|returned HTTP 5\d\d|TLS handshake timeout|i/o timeout|"
                           r"Connection (timed out|reset|refused)|Unable to make request|toomanyrequests|Too Many Requests|"
                           r"rate limit|quota exceeded|Service Unavailable|net/http: request canceled|Client\.Timeout exceeded|"
                           r"Error response from daemon|download has timed out)")),
    ("concurrency", re.compile(r"(?i)(DATA RACE|data race|deadlock|ConcurrentModificationException|race condition|"
                               r"concurrent map (writes|read and map write)|already borrowed)")),
    ("timing", re.compile(r"(?i)(timed? ?out (after|in|waiting)|timeout of \d+ ?ms exceeded|exceeded (the )?timeout|"
                          r"test timed out|deadline exceeded|TimeoutError|Timeout - Async callback|waiting for .{0,80} timed out|"
                          r"Expected condition failed: waiting for|Matcher did not succeed in time|"
                          r"exceeded the maximum execution time|has timed out)")),
    # Causes in the test's own code (Datadog's categories), checked after the environment's.
    ("resource leak", re.compile(r"(?i)(Too many open files|EMFILE|ResourceWarning|unclosed (file|socket|transport)|"
                                 r"address already in use|EADDRINUSE|port \d+ is already (in use|allocated)|leaked? (handle|connection))")),
    ("async wait", re.compile(r"(?i)(not wrapped in act\(|Unable to find (an )?element|StaleElementReference|"
                              r"ElementNotInteractable|detached from (the )?DOM|element is not attached|waitFor(Element)? .{0,40}failed|"
                              r"Promise rejection was handled asynchronously|unhandled promise rejection)")),
    ("time", re.compile(r"(?i)(time ?zone|\bDST\b|daylight saving|leap (year|second)|ZoneInfo|ZonedDateTime|"
                        r"datetime\.(now|utcnow)|LocalDate|Clock skew|month end|end of (the )?month)")),
    ("randomness", re.compile(r"(?i)(Falsifying example|random seed|seed[=: ]+\d+|Math\.random|randomly ordered|"
                              r"--randomly-seed|--seed=\d+)")),
    ("floating point", re.compile(r"(?i)(\d\.\d{12,}|not almost equal|assertAlmostEqual|approx\(|ULP|"
                                  r"floating[- ]point|toBeCloseTo|within tolerance|rel_tol|abs_tol)")),
    ("shared state", re.compile(r"(?i)(already registered|already exists|duplicate key|UNIQUE constraint failed|"
                                r"IntegrityError|state from (a |another )?(previous|other) test|test pollution|singleton)")),
    ("io", re.compile(r"(?i)(FileNotFoundError|ENOENT|No such file or directory|Permission denied|EACCES|"
                      r"Directory not empty|ENOTEMPTY|file is being used by another process|EBUSY)")),
    ("ordering", re.compile(r"(?i)(Items in the (first|second) (set|list)|Element counts were not equal|in any order|"
                            r"Lists differ|expected order|unordered|sort(ed)? order)")),
)


def kind_of(text: str | None) -> str | None:
    """The first kind whose signs the text shows, checked in order; None when it shows none."""
    return next((name for name, rx in KINDS if rx.search(text or "")), None)
