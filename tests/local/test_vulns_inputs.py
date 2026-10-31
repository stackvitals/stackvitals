"""What the dependency check hands OSV-Scanner: .NET project files (an RCE advisory was missed without them, found in
the OSV-Scanner side-by-side) and SBOM files, beside the lockfiles."""
from stackvitals.deps.vulns import scannable


def test_dotnet_projects_and_sboms_are_scanned():
    for path in ("src/App/App.csproj", "Lib.fsproj", "packages.config", "Directory.Packages.props",
                 "sbom.spdx.json", "app.cdx.json", "bom.json", "uv.lock"):
        assert scannable(path), path
    for path in ("vendor/x/App.csproj", "README.md", "src/app.cs"):
        assert not scannable(path), path
