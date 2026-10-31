"""Container base images (OSV-Scanner's image scan needs Docker; this needs none): the operating system under each
Dockerfile image, by version or codename, judged against endoflife.date like the runtimes."""
from stackvitals.deps.runtimes import detect, judge

DOCKERFILE = """FROM python:3.9-slim-buster AS build
FROM debian:bookworm-slim
FROM --platform=linux/amd64 ubuntu:20.04
FROM alpine:3.16
"""


def test_base_operating_systems_are_found_and_judged():
    found = {(f["runtime"], f["version"]) for f in detect({"Dockerfile": DOCKERFILE})}
    assert {("python", "3.9"), ("debian", "10"), ("debian", "12"), ("ubuntu", "20.04"), ("alpine", "3.16")} <= found
    cycles = {"debian": [{"cycle": "10", "eol": "2024-06-30", "latest": "10.13"}, {"cycle": "12", "eol": "2028-06-10", "latest": "12.7"}],
              "alpine-linux": [{"cycle": "3.16", "eol": "2024-05-23", "latest": "3.16.9"}]}
    got = {(j["runtime"], j["version"]): j["status"] for j in judge([f for f in detect({"Dockerfile": DOCKERFILE})
                                                                   if f["runtime"] in ("debian", "alpine")], cycles, "2026-10-29")}
    assert got == {("debian", "10"): "end of life", ("debian", "12"): "supported", ("alpine", "3.16"): "end of life"}
