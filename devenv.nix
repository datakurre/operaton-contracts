{ pkgs, ... }:
let
  python = pkgs.python312.withPackages (ps: with ps; [
    black
    hatchling
    jsonschema
    mkdocs-material
    mypy
    pydantic
    pytest
    pytest-cov
    robotframework
    types-jsonschema
  ]);
in
{
  packages = [
    python
    pkgs.uv
  ];
  env.PYTHONPATH = "src";
}
